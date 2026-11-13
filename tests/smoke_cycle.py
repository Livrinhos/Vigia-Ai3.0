"""Ciclo REAL opcional sobre a saída sintética de smoke_training.py; sem promoção."""
import argparse
import json
import time
from pathlib import Path
from vigia3.store import Store,file_hash
from vigia3.models import Models
from vigia3.jobs import Jobs,training_request


def run(root,base):
    store=Store(root);models=Models(store,base);jobs=Jobs(store,base)
    with store.db() as db:
        original=db.execute("SELECT id FROM models WHERE kind='epi' AND origin='original'").fetchone()['id']
        candidate=db.execute("SELECT id FROM models WHERE origin='candidate'").fetchone()['id']
        dataset=db.execute('SELECT id FROM datasets ORDER BY created LIMIT 1').fetchone()['id']
        image=db.execute('SELECT id,revision,annotation FROM images ORDER BY created LIMIT 1').fetchone()
    hashes={str(p):file_hash(p) for p in base.rglob('*.pt')}
    def wait(jid,limit=180):
        until=time.monotonic()+limit
        while time.monotonic()<until:
            j=jobs.get(jid)
            if j['state'] not in ('queued','running','cancelling') and not j['process_running']:return j
            time.sleep(.1)
        jobs.cancel(jid);raise RuntimeError('Trabalho excedeu o prazo do smoke test.')
    suggestion=wait(jobs.start('suggest',dict(model=original,image=image['id'],device='cpu')))
    if suggestion['state']!='succeeded':raise RuntimeError(str(suggestion))
    now=store.image(image['id'])
    assert now['revision']==image['revision'] and json.dumps(now['annotation'])==image['annotation']
    evaluation=wait(jobs.start('evaluate',dict(model=candidate,baseline=original,dataset=dataset,device='cpu',imgsz=320)))
    if evaluation['state']!='succeeded':raise RuntimeError(str(evaluation))
    request=training_request(store,models,dict(model=original,dataset=dataset,device='cpu',epochs=50,imgsz=320,batch=1,name='smoke-cancelamento-real',pilot=True))
    jid=jobs.start('train',request);deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        job=jobs.get(jid)
        if job.get('progress',{}).get('epoch',0)>=1:break
        if job['state'] not in ('queued','running'):raise RuntimeError(str(job))
        time.sleep(.1)
    jobs.cancel(jid);cancelled=wait(jid)
    assert cancelled['state']=='cancelled',cancelled
    assert hashes=={str(p):file_hash(p) for p in base.rglob('*.pt')}
    result=dict(suggestion_succeeded=True,suggestion_did_not_change_review=True,evaluation_succeeded=True,
        candidate_auto_promoted=False,real_training_cancelled=True,checkpoints_preserved=[p.name for p in (store.root/'modelos'/jid).rglob('*.pt')],
        original_hashes_unchanged=True,synthetic_engine_test=True,recognition_accuracy_validated=False)
    (root/'relatorios/smoke-ciclo.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--base',type=Path,default=Path(__file__).resolve().parents[1]/'.performance-base')
    a=p.parse_args();run(a.data.resolve(),a.base.resolve())
