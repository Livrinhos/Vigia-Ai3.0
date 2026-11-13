"""Smoke test REAL de uma época CPU, usando somente fixtures sintéticas explícitas.

Não valida reconhecimento de capacetes. Não promove nem seleciona o candidato.
Executar apenas manualmente com --output novo; não faz parte dos testes automáticos.
"""
import argparse
import io
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from vigia3.store import Store,file_hash
from vigia3.datasets import DatasetBuilder
from vigia3.models import Models
from vigia3.jobs import Jobs,training_request


def run(base,output):
    if output.exists():raise ValueError('Saída precisa ser uma pasta nova.')
    store=Store(output);models=Models(store,base)
    original={str(p):file_hash(p) for p in base.rglob('*.pt')}
    for g in range(6):
        sid=store.session('FIXTURE SINTÉTICA '+str(g),'fixture-grupo-'+str(g),True)
        for i in range(6):
            array=np.random.default_rng(g*100+i).integers(0,255,(96,96,3),dtype=np.uint8)
            image=Image.fromarray(array);draw=ImageDraw.Draw(image);draw.ellipse((20,15,70,50),fill='#f6bf35')
            buf=io.BytesIO();image.save(buf,format='PNG')
            iid=store.import_image(sid,f'fixture-{g}-{i}.png',buf.getvalue())['id']
            ann=dict(boxes=[dict(scope='epi',label='capacete',xyxy=[20/96,15/96,70/96,50/96],origin='fixture-sintetica')],negative=False,notes='Fixture programática de engenharia; não usar para avaliar precisão real.')
            store.review(iid,dict(state='approved',annotation=ann,human_reviewed=True,issues_acknowledged=True),0)
    dataset=DatasetBuilder(store,base).prepare('SMOKE SINTÉTICO — não é avaliação de reconhecimento',test_independent=True)
    mid=next(m['id'] for m in models.list() if m['kind']=='epi' and m['origin']=='original')
    request=training_request(store,models,dict(model=mid,dataset=dataset['id'],epochs=1,imgsz=320,batch=1,device='cpu',name='smoke-sintetico-cpu',pilot=True))
    jobs=Jobs(store,base);jid=jobs.start('train',request)
    while True:
        job=jobs.get(jid)
        if job['state'] not in ('queued','running') and not job['process_running']:break
        time.sleep(.5)
    if job['state']!='succeeded':raise RuntimeError(json.dumps(job,ensure_ascii=False))
    if original!={str(p):file_hash(p) for p in base.rglob('*.pt')}:raise RuntimeError('Modelo original mudou!')
    result=dict(state=job['state'],job=jid,result=job['result'],original_hashes_unchanged=True,
                real_training=True,device='cpu',epochs=1,synthetic_engine_test=True,recognition_accuracy_validated=False,model_promoted=False)
    (store.root/'relatorios'/'smoke-engenharia.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--base',type=Path,default=Path(__file__).resolve().parents[1]/'performance')
    a=p.parse_args();run(a.base.resolve(),a.output.resolve())
