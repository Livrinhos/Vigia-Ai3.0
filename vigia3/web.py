"""Rotas locais da Central de Imagens. Nenhum caminho arbitrário vem do navegador."""
import io
import json
import time
import zipfile
from pathlib import Path
from flask import Blueprint, Response, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from .store import Store, yolo_text
from .imports import Importer
from .datasets import DatasetBuilder
from .models import Models
from .jobs import Jobs, training_request


def register(app,monitor,base,data_root=None):
    store=Store(data_root);models=Models(store,base);jobs=Jobs(store,base,monitor);importer=Importer(store)
    root=Path(__file__).resolve().parents[1]/'web'
    bp=Blueprint('vigia3',__name__)
    app.extensions.update(vigia3_store=store,vigia3_models=models,vigia3_jobs=jobs)

    @bp.before_request
    def protect():
        if request.path.startswith('/api/banco/') and request.method!='GET':
            if request.headers.get('X-VigiaAI')!='1':return jsonify(ok=False,error='Requisição local sem cabeçalho de confirmação.'),403
            origin=request.headers.get('Origin')
            if request.headers.get('Sec-Fetch-Site')=='cross-site' or (origin and origin.rstrip('/')!=request.host_url.rstrip('/')):
                return jsonify(ok=False,error='Origem não permitida.'),403

    @bp.errorhandler(ValueError)
    def invalid(e):return jsonify(ok=False,error=str(e)),400
    @bp.errorhandler(OSError)
    def io_error(e):return jsonify(ok=False,error='Não foi possível ler/gravar os dados locais; consulte espaço livre e permissões.'),500

    def data():
        d=request.get_json(silent=True)
        if not isinstance(d,dict):raise ValueError('Envie um objeto JSON.')
        return d

    @bp.get('/banco')
    def bank():return Response((root/'banco.html').read_text(encoding='utf-8'),mimetype='text/html')
    @bp.get('/vigia3-assets/<name>')
    def asset(name):
        if name not in ('banco.js','banco.css','coletivo.js'):return Response(status=404)
        return send_file(root/name)

    @app.after_request
    def navigation(response):
        if request.path=='/' and response.mimetype=='text/html':
            text=response.get_data(as_text=True)
            link='<a class="rail-link" style="font-size:10px;line-height:1.3;text-align:center" href="/banco" title="Banco de Imagens e Treinamento">Banco de<br>Imagens</a>'
            text=text.replace('</aside>',link+'</aside>',1)
            text=text.replace('</body>','<script src="/vigia3-assets/coletivo.js" defer></script></body>')
            response.set_data(text)
        if request.path.startswith(('/api/banco','/banco')):response.headers['Cache-Control']='no-store'
        return response

    @bp.get('/api/banco/config')
    def config():
        from .store import CLASSES
        with store.db() as db:datasets=[dict(r) for r in db.execute('SELECT id,name,kind,summary FROM datasets ORDER BY created DESC')]
        return jsonify(classes=CLASSES,storage=str(store.root),models=models.list(),datasets=datasets,job_active=jobs.active(),
            limits=dict(image_mb=20,zip_mb=512,chunk_mb=4),head_schema=['com_capacete','sem_capacete','inconclusivo'])

    @bp.post('/api/banco/sessions')
    def session():
        d=data();return jsonify(id=store.session(d.get('name'),d.get('group',''),d.get('authorized'))),201

    @bp.get('/api/banco/images')
    def images():return jsonify(store.list_images(request.args.get('state','all'),request.args.get('q',''),request.args.get('session',''),int(request.args.get('page',1))))
    @bp.get('/api/banco/images/<iid>')
    def image(iid):
        row=store.image(iid);p=store.root/'anotacoes'/f'{iid}-origem.json'
        row['metadata']=json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None
        with store.db() as db:
            row['related']=[dict(id=r['id'],name=r['name'],distance=(int(r['dhash'],16)^int(row['dhash'],16)).bit_count())
                for r in db.execute('SELECT id,name,dhash FROM images WHERE deleted=0 AND id!=?',(iid,))
                if (int(r['dhash'],16)^int(row['dhash'],16)).bit_count()<=4][:30]
        row['duplicate_annotations']=[json.loads(p.read_text(encoding='utf-8')) for p in (store.root/'anotacoes').glob(f'{iid}-*-duplicata.json')][:30]
        return jsonify(row)
    @bp.get('/api/banco/images/<iid>/file')
    def image_file(iid):
        r=store.image(iid)
        if request.args.get('download')=='1':return send_file(store.root/r['relative_path'],as_attachment=True,download_name=r['name'])
        return send_file(store.root/'imagens/visualizacao'/f'{r["id"]}.jpg',mimetype='image/jpeg')
    @bp.get('/api/banco/images/<iid>/thumb')
    def thumb(iid):
        r=store.image(iid);return send_file(store.root/'imagens/miniaturas'/f'{r["id"]}.jpg',mimetype='image/jpeg')
    @bp.put('/api/banco/images/<iid>/review')
    def review(iid):
        d=data();return jsonify(store.review(iid,d,d.get('revision')))
    @bp.post('/api/banco/images/bulk-review')
    def bulk():
        d=data();ids=d.get('ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=500:raise ValueError('Seleção inválida.')
        # Ação em lote não aprova caixas sem abrir e revisar cada imagem.
        if d.get('state') not in ('pending','rejected'):raise ValueError('Aprovação requer revisão individual das anotações.')
        count=0
        for iid in ids:
            r=store.image(iid);store.review(iid,dict(annotation=r['annotation'],state=d['state']),r['revision']);count+=1
        return jsonify(updated=count)
    @bp.post('/api/banco/images/trash')
    def trash():
        d=data();return jsonify(updated=store.trash(d.get('ids'),d.get('confirmation')))
    @bp.post('/api/banco/images/restore')
    def restore():
        d=data();return jsonify(updated=store.trash(d.get('ids'),d.get('confirmation'),restore=True))
    @bp.get('/api/banco/trash')
    def trash_list():
        with store.db() as db:rows=[dict(r) for r in db.execute('SELECT id,name,state FROM images WHERE deleted=1 ORDER BY created DESC LIMIT 500')]
        return jsonify(items=rows)

    @bp.post('/api/banco/uploads')
    def upload():
        d=data();return jsonify(id=importer.start(d.get('session'),d.get('name'),d.get('size'),d.get('extras'))),201
    @bp.get('/api/banco/uploads/<uid>')
    def upload_state(uid):return jsonify(importer.get(uid))
    @bp.put('/api/banco/uploads/<uid>/chunk')
    def chunk(uid):
        if request.content_length is None or request.content_length>4*1024*1024:raise ValueError('Bloco excede 4 MB.')
        offset=int(request.args.get('offset','-1'))
        return jsonify(offset=importer.chunk(uid,offset,request.get_data(cache=False)))
    @bp.post('/api/banco/uploads/<uid>/finish')
    def finish(uid):
        if jobs.active():raise ValueError('Há outro trabalho em andamento; o arquivo permanece salvo para retomar.')
        importer.seal(uid)
        try:jid=jobs.start('import',dict(upload=uid))
        except Exception:
            with store.db() as db:db.execute("UPDATE uploads SET state='uploading' WHERE id=?",(uid,))
            raise
        return jsonify(job=jid),202

    @bp.post('/api/banco/images/<iid>/suggest')
    def suggest(iid):
        r=store.image(iid);d=data();m=models.get(d.get('model'))
        if d.get('device','cpu') not in ('cpu','0'):raise ValueError('Dispositivo inválido.')
        return jsonify(job=jobs.start('suggest',dict(image=iid,model=m['id'],device=d.get('device','cpu')))),202
    @bp.post('/api/banco/datasets')
    def dataset():
        d=data();return jsonify(job=jobs.start('dataset',dict(name=d.get('name','Dataset'),sessions=d.get('sessions'),kind=d.get('kind','detector'),test_independent=d.get('test_independent',False)))),202
    @bp.post('/api/banco/train')
    def train():
        d=training_request(store,models,data());return jsonify(job=jobs.start('train',d)),202
    @bp.post('/api/banco/evaluate')
    def evaluate():
        d=data();m=models.get(d.get('model'));b=models.get(d.get('baseline'));DatasetBuilder(store).validate(d.get('dataset'))
        if m['kind']!='epi' or b['kind']!='epi' or b['origin']!='original':raise ValueError('Compare um candidato EPI com o modelo EPI original.')
        if d.get('device') not in ('cpu','0'):raise ValueError('Dispositivo inválido.')
        return jsonify(job=jobs.start('evaluate',dict(model=m['id'],baseline=b['id'],dataset=d['dataset'],device=d['device'],imgsz=640))),202
    @bp.get('/api/banco/jobs')
    def list_jobs():
        with store.db() as db:rows=[dict(r) for r in db.execute('SELECT id,kind,state,created,error FROM jobs ORDER BY created DESC LIMIT 50')]
        return jsonify(items=rows)
    @bp.get('/api/banco/jobs/<jid>')
    def job(jid):return jsonify(jobs.get(jid))
    @bp.post('/api/banco/jobs/<jid>/cancel')
    def cancel(jid):jobs.cancel(jid);return jsonify(ok=True)
    @bp.post('/api/banco/models/<mid>/approve')
    def approve(mid):models.approve(mid,data().get('confirmation'));return jsonify(ok=True)
    @bp.post('/api/banco/models/<mid>/select')
    def select(mid):
        if jobs.active():raise ValueError('Aguarde o trabalho atual.')
        models.select(mid,monitor,data().get('confirmation'));return jsonify(ok=True)
    @bp.post('/api/banco/models/restore')
    def restore_model():
        if data().get('confirmation')!='RESTAURAR':raise ValueError('Confirmação obrigatória.')
        models.restore(monitor);return jsonify(ok=True)
    @bp.post('/api/banco/backup')
    def backup():
        data();return jsonify(file=store.backup(),note='Snapshot do catálogo; originais e checkpoints permanecem em suas pastas e devem ser incluídos no backup externo.')

    @bp.get('/api/banco/export/yolo')
    def export():
        ids=request.args.getlist('id')
        if not 1<=len(ids)<=500:raise ValueError('Selecione até 500 imagens para exportar.')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            from .store import CLASSES
            archive.writestr('classes.json',json.dumps(CLASSES))
            for iid in ids:
                r=store.image(iid)
                if r['state']!='approved':raise ValueError('Exporte apenas anotações aprovadas.')
                archive.writestr('labels/'+iid+'.txt',yolo_text(r['annotation']))
                archive.writestr('metadata/'+iid+'.json',json.dumps(dict(name=r['name'],source=r['source'],sha256=r['sha256'],annotation=r['annotation'])))
        output.seek(0);return send_file(output,mimetype='application/zip',as_attachment=True,download_name='anotacoes-yolo.zip')

    # Serializa o início do monitoramento contra trabalhos com modelos.
    start=monitor.iniciar
    def guarded_start(*args,**kwargs):
        with jobs.lock:
            if monitor.status.get('modelo_selecao_erro'):return False,'Restaure ou selecione um modelo íntegro antes de iniciar.'
            if jobs.active():return False,'Aguarde ou cancele o trabalho de imagens/treinamento antes de iniciar o monitoramento.'
            return start(*args,**kwargs)
    monitor.iniciar=guarded_start
    app.register_blueprint(bp)
    return store,models,jobs
