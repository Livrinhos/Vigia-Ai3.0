"""Worker local isolado. Executa somente trabalhos solicitados; nunca promove automaticamente."""
import json
import os
import sys
import time
import traceback
from pathlib import Path
from .store import Store, file_hash
from .datasets import DatasetBuilder
from .imports import Importer
from .models import Models


def execute(payload,store,folder,progress,cancel):
    base=Path(payload['base']).resolve();sys.path.insert(0,str(base))
    req=payload['request'];kind=payload['kind']
    if kind=='import':return Importer(store).finish(req['upload'],progress,cancel)
    if kind=='dataset':return DatasetBuilder(store,base).prepare(req.get('name','Dataset'),req.get('sessions'),req.get('kind','detector'),progress,cancel,req.get('test_independent',False))
    from ultralytics import YOLO
    from ultralytics import settings
    private_settings={k:False for k in ('sync','hub','wandb','mlflow','clearml','neptune','comet','dvc','raytune','tensorboard') if k in settings}
    if private_settings:settings.update(private_settings)
    import torch
    models=Models(store,base)
    model=models.get(req['model'])
    before=file_hash(model['path'])
    device=req.get('device','cpu')
    if device=='0' and not torch.cuda.is_available():raise ValueError('CUDA 0 solicitada, mas indisponível. Execute o diagnóstico e confira o driver/torch.')
    torch.set_num_threads(max(1,min(6,(os.cpu_count() or 4)//2)))
    def checkpoint():
        if cancel():raise InterruptedError('Cancelado pelo usuário; arquivos anteriores preservados.')
    if kind=='suggest':
        image=store.image(req['image']);checkpoint()
        im=store.root/image['relative_path']
        if file_hash(im)!=image['sha256']:raise ValueError('Imagem alterada após importação.')
        detector=YOLO(model['path'])
        result=detector(str(im),imgsz=640,device=device,quantize='fp32',conf=.25,verbose=False)[0]
        from .store import CLASSES
        boxes=[];raw=result.boxes.cpu()
        aliases={'helmet':'capacete','vest':'colete','goggles':'oculos','gloves':'luvas','mask':'mascara'}
        for xy,cls,confidence in zip(raw.xyxy.tolist(),raw.cls.tolist(),raw.conf.tolist()):
            label=result.names[int(cls)];label=aliases.get(label,label)
            if label not in CLASSES:continue
            boxes.append(dict(scope='epi',label=label,xyxy=[max(0,min(1,v/(image['width'] if i%2==0 else image['height']))) for i,v in enumerate(xy)],origin='sugestao_ia',confidence=confidence))
        if file_hash(model['path'])!=before:raise RuntimeError('Peso original alterado.')
        return dict(image=req['image'],revision=image['revision'],boxes=boxes,review_required=True)
    dataset=DatasetBuilder(store,base).validate(req['dataset'])
    if dataset['kind']!='detector':raise ValueError('Treinamento deste worker exige dataset de objetos, não classificador de cabeças.')
    data=Path(dataset['path'])/'data.yaml'
    from dataset_ia import auditar_dataset
    audit=auditar_dataset(data)
    if audit['erros'] or not audit['grupos_verificados']:raise ValueError('Auditoria rejeitou os dados antes da inferência/treino.')
    checkpoint()
    if kind=='train':
        # Fonte distribuída com matplotlib; evita downloads auxiliares de fonte durante o treino.
        import shutil
        import matplotlib.font_manager as fonts
        config=Path(os.environ['YOLO_CONFIG_DIR']);config.mkdir(parents=True,exist_ok=True)
        for name in ('Arial.ttf','Arial.Unicode.ttf'):
            if not (config/name).exists():shutil.copyfile(fonts.findfont('DejaVu Sans'),config/name)
        from .jobs import training_request
        req=training_request(store,models,req)
        detector=YOLO(model['path'])
        def epoch(trainer):
            progress(epoch=int(getattr(trainer,'epoch',0))+1,epochs=req['epochs'],metrics={k:float(v) for k,v in getattr(trainer,'metrics',{}).items() if isinstance(v,(int,float))})
            if cancel():trainer.stop=True
        def batch(trainer):
            if cancel():trainer.stop=True
        detector.add_callback('on_train_epoch_end',epoch)
        detector.add_callback('on_train_batch_end',batch)
        # Diretório UUID novo, FP32, sem auto-batch ou substituição do modelo ativo.
        detector.train(data=str(data),epochs=req['epochs'],imgsz=req['imgsz'],batch=req['batch'],device=req['device'],
            workers=0,amp=False,cache=False,save=True,save_period=1,project=str(store.root/'modelos'),
            name=payload['id'],exist_ok=False,seed=42,deterministic=True,plots=True)
        if file_hash(model['path'])!=before:raise RuntimeError('Integridade do modelo inicial falhou.')
        checkpoint()
        best=store.root/'modelos'/payload['id']/'weights/best.pt'
        if not best.is_file():raise ValueError('Treinamento terminou sem best.pt; consulte logs.')
        mid=models.register(best,'epi','candidate',req['name'],approved=False)
        manifest=json.loads((Path(dataset['path'])/'manifesto.json').read_text(encoding='utf-8'))
        history=json.loads(model.get('training_history') or '[]')
        history.append(dict(dataset=dataset['id'],train=[dict(sha256=r['sha256'],groups=[g for g in r['grupos'] if g.startswith('origem:')]) for r in manifest if r['split']=='train']))
        with store.db() as db:db.execute('UPDATE models SET training_history=? WHERE id=?',(json.dumps(history),mid))
        return dict(model=mid,path=str(best),approved=False,initial_sha256=before,dataset=dataset['id'],pilot=req['pilot'])
    if kind=='evaluate':
        baseline=models.get(req['baseline'])
        if not dataset['summary'].get('test_independence_declared'):
            raise ValueError('Confirme na preparação que os grupos de teste são novos e não foram usados em treinos anteriores. A divisão por sessão sozinha não comprova isso.')
        manifest=json.loads((Path(dataset['path'])/'manifesto.json').read_text(encoding='utf-8'))
        test=[r for r in manifest if r['split']=='test']
        for m in (model,baseline):
            for previous in json.loads(m.get('training_history') or '[]'):
                for trained in previous['train']:
                    if any(r['sha256']==trained['sha256'] or set(r['grupos'])&set(trained['groups']) for r in test):
                        raise ValueError('O teste contém imagem ou grupo já utilizado no histórico de treino do modelo.')
        from treinar_epi import metricas_dict
        values={};names={}
        for label,m in (('original',baseline),('candidate',model)):
            checkpoint();detector=YOLO(m['path'])
            names[label]=list(detector.names.values())
            result=detector.val(data=str(data),split='test',imgsz=req.get('imgsz',640),batch=1,device=device,
                workers=0,plots=False,project=str(folder),name=label,exist_ok=False,verbose=False)
            values[label]=metricas_dict(result)
            if file_hash(m['path'])!=m['sha256']:raise RuntimeError('Peso alterado durante avaliação.')
        from .store import CLASSES
        compatible=names['original']==names['candidate']==CLASSES
        all_classes=all(dataset['summary']['counts']['test'].get(c,0)>0 for c in CLASSES)
        a,b=values['original'],values['candidate']
        non_regression=all_classes and b['mAP50_95']>=a['mAP50_95'] and b['recall']>=a['recall']
        for c in CLASSES:
            x,y=a['por_classe'].get(c),b['por_classe'].get(c)
            non_regression=non_regression and bool(x and y and y['recall']>=x['recall'] and y['mAP50_95']>=x['mAP50_95'])
        evaluation=dict(compatible=compatible,independent_test=True,non_regression=bool(non_regression),
            full_class_coverage=all_classes,dataset=dataset['id'],dataset_hash=dataset['manifest_hash'],
            baseline_sha256=baseline['sha256'],candidate_sha256=model['sha256'],values=values,
            limits='Teste por grupos e independência declarados pelo usuário; histórico de pré-treino original não está integralmente disponível. Revisar vídeos/falsos alertas. Repetir ajustes no teste causa viés.')
        with store.db() as db:db.execute('UPDATE models SET evaluation=? WHERE id=?',(json.dumps(evaluation),model['id']))
        (folder/'comparacao.json').write_text(json.dumps(evaluation,indent=2),encoding='utf-8')
        return evaluation
    raise ValueError('Trabalho não reconhecido.')


def main():
    jobfile=Path(sys.argv[1]).resolve();payload=json.loads(jobfile.read_text(encoding='utf-8'))
    store=Store(payload['data_root']);folder=store.root/'trabalhos'/payload['id']
    if jobfile!=folder/'request.json':raise ValueError('Caminho de trabalho inválido.')
    def progress(**data):
        p=folder/'progress.json';t=folder/'progress.tmp';t.write_text(json.dumps(data),encoding='utf-8');t.replace(p)
    cancel=lambda:(folder/'cancel.request').exists()
    with store.db() as db:db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),payload['id']))
    try:
        if cancel():raise InterruptedError('Cancelado antes de iniciar.')
        result=execute(payload,store,folder,progress,cancel)
        state='cancelled' if cancel() else 'succeeded';error=None
    except InterruptedError as e:state,result,error='cancelled',None,str(e)
    except Exception as e:
        traceback.print_exc();state,result,error='failed',None,str(e)
    with store.db() as db:db.execute('UPDATE jobs SET state=?,updated=?,result=?,error=? WHERE id=?',(state,time.time(),json.dumps(result) if result is not None else None,error,payload['id']))
    print(json.dumps(dict(state=state,error=error)),flush=True)
    return 0 if state in ('succeeded','cancelled') else 1


if __name__=='__main__':raise SystemExit(main())
