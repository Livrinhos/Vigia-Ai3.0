import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import numpy as np

from vigia3.store import Store,validate_annotations,yolo_parse,file_hash
from vigia3.imports import Importer
from vigia3.datasets import DatasetBuilder
from vigia3.models import Models
from vigia3.jobs import Jobs,training_request
from iniciar3 import create

BASE=Path(__file__).resolve().parents[1]/'.performance-base'


def picture(seed=0,size=(96,96)):
    arr=np.random.default_rng(seed).integers(30,230,(size[1],size[0],3),dtype=np.uint8)
    out=io.BytesIO();Image.fromarray(arr).save(out,format='PNG');return out.getvalue()


def annotation(label='capacete'):
    return dict(boxes=[dict(scope='epi',label=label,xyxy=[.1,.1,.6,.5])],negative=False)


class BankTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root/'data');self.importer=Importer(self.store)
        self.sid=self.store.session('Fotos antigas','camera-01',True)
    def tearDown(self):self.temp.cleanup()
    def import_bytes(self,name,content,extras=None):
        uid=self.importer.start(self.sid,name,len(content),extras)
        for offset in range(0,len(content),1024):self.importer.chunk(uid,offset,content[offset:offset+1024])
        self.importer.seal(uid);return self.importer.finish(uid)

    def test_image_persistent_duplicate_and_original_immutable(self):
        data=picture();r=self.import_bytes('pendentes/foto.png',data)
        row=self.store.image(next(iter(self.store.list_images()['items']))['id'])
        self.assertEqual((self.store.root/row['relative_path']).read_bytes(),data)
        self.assertEqual(row['source'],'pendentes/foto.png')
        self.assertEqual(self.import_bytes('outra.png',data)['duplicates'],1)
        reopened=Store(self.store.root);self.assertEqual(reopened.list_images()['total'],1)
        self.assertEqual(row['state'],'pending');self.assertEqual(r['imported'],1)

    def test_content_not_extension_and_invalid_files(self):
        self.assertEqual(self.import_bytes('falsa.jpg',b'<script>no</script>')['imported'],0)
        with self.assertRaises(ValueError):self.importer.start(self.sid,'bad.exe',10)
        with self.assertRaises(ValueError):self.store.import_image(self.sid,'../escape.png',picture())
        with self.assertRaises(ValueError):self.store.session('Sem direitos','',False)

    def test_200_image_zip_with_annotations_and_metadata(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_STORED) as z:
            for i in range(200):
                z.writestr(f'images/train/f{i}.png',picture(i));z.writestr(f'labels/train/f{i}.txt','0 .35 .3 .5 .4\n')
            z.writestr('images/train/f0.json',json.dumps({'camera':'antiga','observacao':'preservar'}))
        result=self.import_bytes('cem-fotos.zip',data.getvalue())
        self.assertEqual(result['imported'],200);self.assertFalse(result['errors'])
        self.assertEqual(self.store.list_images()['ready'],0)
        row=self.store.image(self.store.list_images(q='f0.png')['items'][0]['id'])
        self.assertEqual(row['annotation']['boxes'][0]['label'],'capacete')
        self.assertTrue((self.store.root/'anotacoes'/f'{row["id"]}-origem.json').exists())

    def test_zip_path_traversal_symlink_bomb_and_wrong_classes(self):
        for name,payload,mode in [('../escape.png',picture(),None),('a.zip',b'xx',None),('bomb.txt',b'0'*100000,None),('link.png',b'not-image',0o120777)]:
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('ok.png',picture())
                if mode:
                    info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=mode<<16;z.writestr(info,payload)
                else:z.writestr(name,payload)
            with self.assertRaises(ValueError):self.import_bytes('malicioso.zip',data.getvalue())
        self.assertEqual(self.store.list_images()['total'],0)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:z.writestr('a.png',picture());z.writestr('data.yaml','names: [person, no_helmet]')
        with self.assertRaises(ValueError):self.import_bytes('classes.zip',data.getvalue())

    def test_folder_sidecar_and_safe_resume(self):
        uid=self.importer.start(self.sid,'antigo/amostras/a.png',len(picture()),{'yolo':'0 .35 .3 .5 .4','metadata':{'origem':'captura'}})
        with self.assertRaises(ValueError):self.importer.chunk(uid,5,b'bad')
        data=picture();self.importer.chunk(uid,0,data)
        with self.assertRaises(ValueError):self.importer.chunk(uid,0,b'bad')
        self.importer.seal(uid);self.importer.finish(uid)
        row=self.store.image(self.store.list_images()['items'][0]['id'])
        self.assertTrue(row['annotation']['boxes'])

    def test_review_requires_human_no_fake_nohelmet_and_revision(self):
        iid=self.store.import_image(self.sid,'a.png',picture())['id']
        with self.assertRaises(ValueError):self.store.review(iid,{'state':'approved','annotation':annotation()},0)
        row=self.store.review(iid,{'state':'approved','annotation':annotation(),'human_reviewed':True},0)
        self.assertEqual(row['state'],'approved')
        with self.assertRaises(ValueError):self.store.review(iid,{'state':'pending'},0)
        with self.assertRaises(ValueError):validate_annotations({'boxes':[{'scope':'epi','label':'no_helmet','xyxy':[.1,.1,.3,.3]}]})
        heads=validate_annotations({'boxes':[{'scope':'cabeca','label':'sem_capacete','xyxy':[.1,.1,.3,.3]}],'negative':True})
        self.assertEqual(heads['boxes'][0]['label'],'sem_capacete')

    def test_trash_and_restore_do_not_remove_any_bytes(self):
        iid=self.store.import_image(self.sid,'a.png',picture())['id'];r=self.store.image(iid)
        with self.assertRaises(ValueError):self.store.trash([iid],False)
        self.store.trash([iid],'CONFIRMAR');self.assertEqual(self.store.list_images()['total'],0)
        self.assertTrue((self.store.root/r['relative_path']).is_file())
        self.store.trash([iid],'CONFIRMAR',restore=True);self.assertEqual(self.store.list_images()['total'],1)
        name=self.store.backup();self.assertTrue((self.store.root/'backups'/name).is_file())

    def prepared(self):
        for group in range(6):
            sid=self.store.session('sessao'+str(group),'origem'+str(group),True)
            for n in range(6):
                iid=self.store.import_image(sid,f'f{group}-{n}.png',picture(100+group*10+n))['id']
                self.store.review(iid,dict(state='approved',annotation=annotation(),human_reviewed=True),0)
        return DatasetBuilder(self.store,BASE).prepare('piloto')

    def test_dataset_group_independence_audit_frozen_and_unreviewed_excluded(self):
        self.store.import_image(self.sid,'pendente.png',picture(9999))
        d=self.prepared();record=DatasetBuilder(self.store,BASE).validate(d['id'])
        manifest=json.loads((Path(record['path'])/'manifesto.json').read_text())
        splits={}
        for r in manifest:
            for g in r['grupos']:
                self.assertIn(splits.get(g,r['split']),[r['split']]);splits[g]=r['split']
        self.assertEqual(len(manifest),36);self.assertTrue(record['summary']['audit']['grupos_verificados'])
        target=next((Path(record['path'])/'labels').rglob('*.txt'));target.write_text('alterado')
        with self.assertRaises(ValueError):DatasetBuilder(self.store).validate(d['id'])

    def test_insufficient_data_and_near_duplicates_block_dataset(self):
        with self.assertRaises(ValueError):DatasetBuilder(self.store).prepare('vazio')
        for i in range(12):
            iid=self.store.import_image(self.sid,f'a{i}.png',picture(i+100))['id'];self.store.review(iid,dict(state='approved',annotation=annotation(),human_reviewed=True),0)
        with self.assertRaises(ValueError):DatasetBuilder(self.store).prepare('mesma origem')

    def test_revision_change_invalidates_snapshot_without_deleting_it(self):
        d=self.prepared();record=DatasetBuilder(self.store).validate(d['id'])
        row=self.store.image(self.store.list_images()['items'][0]['id'])
        self.store.review(row['id'],dict(state='rejected',annotation=row['annotation']),row['revision'])
        with self.assertRaises(ValueError):DatasetBuilder(self.store).validate(d['id'])
        self.assertTrue((Path(record['path'])/'manifesto.json').exists())

    def test_model_hash_approval_selection_and_restore(self):
        models=Models(self.store,BASE)
        class Monitor:
            def __init__(self):
                import threading
                self.lock=threading.RLock();self.thread=None;self.status={}
        monitor=Monitor();models.restore(monitor);original=monitor.modelo_epi
        candidate=self.store.root/'modelos'/'candidate.pt';candidate.write_bytes(b'fixture-only-not-real-weights')
        mid=models.register(candidate,'epi','candidate','teste')
        with self.assertRaises(ValueError):models.select(mid,monitor,'SELECIONAR')
        with self.assertRaises(ValueError):models.approve(mid,'APROVAR '+mid)
        with self.store.db() as db:db.execute('UPDATE models SET evaluation=? WHERE id=?',(json.dumps(dict(compatible=True,independent_test=True,non_regression=True)),mid))
        models.approve(mid,'APROVAR '+mid);models.select(mid,monitor,'SELECIONAR');self.assertEqual(monitor.modelo_epi,candidate)
        models.restore(monitor);self.assertEqual(monitor.modelo_epi,original)
        candidate.write_bytes(b'changed')
        with self.assertRaises(ValueError):models.get(mid)

    def test_training_validation_blocks_unprepared_and_small_unflagged(self):
        models=Models(self.store,BASE);mid=next(m['id'] for m in models.list() if m['kind']=='epi')
        d=self.prepared();req=dict(model=mid,dataset=d['id'],epochs=1,imgsz=640,batch=1,device='cpu',name='piloto',pilot=True)
        self.assertTrue(training_request(self.store,models,req)['pilot'])
        with self.assertRaises(ValueError):training_request(self.store,models,dict(req,pilot=False))
        with self.assertRaises(ValueError):training_request(self.store,models,dict(req,batch=16))


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create(BASE,Path(self.temp.name)/'data');self.client=self.app.test_client();self.h={'X-VigiaAI':'1'}
    def tearDown(self):self.temp.cleanup()
    def test_page_navigation_mutation_guards_and_empty_truth(self):
        self.assertIn('Banco de Imagens'.encode(),self.client.get('/').data)
        self.assertEqual(self.client.get('/banco').status_code,200)
        self.assertEqual(self.client.get('/api/banco/images').json['total'],0)
        self.assertEqual(self.client.post('/api/banco/sessions',json={'name':'x'}).status_code,403)
        self.assertEqual(self.client.post('/api/banco/sessions',json={'name':'x'},headers=self.h|{'Origin':'https://evil.test'}).status_code,403)
        self.assertIn('Banco de Imagens e Treinamento'.encode(),self.client.get('/banco').data)
    def test_upload_worker_real_process_import_and_review(self):
        sid=self.client.post('/api/banco/sessions',json=dict(name='teste',group='teste',authorized=True),headers=self.h).json['id']
        content=picture();uid=self.client.post('/api/banco/uploads',json=dict(session=sid,name='a.png',size=len(content)),headers=self.h).json['id']
        r=self.client.put(f'/api/banco/uploads/{uid}/chunk?offset=0',data=content,headers=self.h|{'Content-Type':'application/octet-stream'});self.assertEqual(r.status_code,200)
        j=self.client.post(f'/api/banco/uploads/{uid}/finish',json={},headers=self.h);self.assertEqual(j.status_code,202)
        jid=j.json['job'];end=time.monotonic()+15
        while time.monotonic()<end:
            job=self.client.get('/api/banco/jobs/'+jid).json
            if job['state'] not in ('queued','running'):break
            time.sleep(.05)
        self.assertEqual(job['state'],'succeeded',job)
        iid=self.client.get('/api/banco/images').json['items'][0]['id']
        with self.client.get(f'/api/banco/images/{iid}/file') as response:self.assertEqual(response.status_code,200)
        review=dict(revision=0,state='approved',annotation=annotation(),human_reviewed=True)
        self.assertEqual(self.client.put(f'/api/banco/images/{iid}/review',json=review,headers=self.h).status_code,200)
        self.assertEqual(self.client.get('/api/banco/export/yolo?id='+iid).status_code,200)
        self.assertEqual(self.client.get('/api/banco/images').json['ready'],1)
