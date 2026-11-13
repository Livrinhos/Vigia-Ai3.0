"""Mede vídeos autorizados com a base ou os hooks 3.0. Não cria pessoas/vídeos fictícios."""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,default=Path(__file__).parent/'performance')
    p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',choices=['cpu','0'],default='0');p.add_argument('--baseline',action='store_true')
    p.add_argument('--people-declared',type=int,choices=[1,5,10,15,20,25],required=True)
    a=p.parse_args();base=a.base.resolve()
    if not a.video.is_file():raise ValueError('Vídeo autorizado indisponível; nenhum resultado será fabricado.')
    os.environ.update(VIGIAAI_TESTE='1',NOTIFICACOES_ATIVAS='0',SALVAR_IMAGEM_OCORRENCIA='0',YOLO_AUTOINSTALL='false',
        YOLO_CONFIG_DIR=str(a.output.resolve()/'ultralytics'))
    sys.path.insert(0,str(base))
    import main as original
    if not a.baseline:
        from vigia3.crowd import install
        old=original.Monitor
        class Monitor(old):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);install(original,self)
        original.Monitor=Monitor
    import performance_benchmark
    args=argparse.Namespace(root=base,video=a.video,output=a.output,device=a.device,profile='qualidade',
        epis=['capacete'],absence='observacao',warmup=10)
    performance_benchmark.run(args)
    frames=[];states=Counter();ids=set()
    with (a.output/'readings.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line);frames.append(len(row['pessoas']))
            for person in row['pessoas']:
                ids.add(person['id']);states[person.get('epis',{}).get('capacete','não avaliado')]+=1
    result=dict(version='Performance base' if a.baseline else '3.0',people_declared_by_user=a.people_declared,
        frames=len(frames),min_people=min(frames,default=0),max_people=max(frames,default=0),
        mean_people=sum(frames)/len(frames) if frames else None,temporary_ids_created=len(ids),helmet_readings=dict(states),
        identity_switches=None,false_alerts=None,missed_alerts=None,
        limitations='Quantidade declarada não é ground truth por quadro. Trocas de identidade, recall e falsos alertas exigem anotações independentes. Sem vídeos adequados não há medição real.')
    (a.output/'coletivo.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
