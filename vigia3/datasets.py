"""Snapshots revisados e divisão por grupos; nunca escreve sobre imagens importadas."""
import hashlib
import json
import random
import shutil
import time
from collections import Counter
from pathlib import Path
from PIL import Image
import yaml
from .store import CLASSES, ident, file_hash, validate_annotations, yolo_text


class DatasetBuilder:
    def __init__(self,store,base=None):self.store,self.base=store,Path(base) if base else None

    def prepare(self,name,session_ids=None,kind='detector',progress=lambda **_:None,cancel=lambda:False,test_independent=False):
        if kind not in ('detector','cabecas'):raise ValueError('Tipo de dataset inválido.')
        with self.store.db() as db:
            rows=[dict(r) for r in db.execute("SELECT i.*,s.group_key,s.authorized FROM images i JOIN sessions s ON i.session_id=s.id WHERE i.deleted=0 AND i.state='approved'")]
            source_groups={}
            for r in db.execute('SELECT src.image_id,s.group_key FROM image_sources src JOIN sessions s ON s.id=src.session_id'):
                source_groups.setdefault(r['image_id'],set()).add(r['group_key'])
        if session_ids:rows=[r for r in rows if r['session_id'] in session_ids]
        if len(rows)<12:raise ValueError('São necessárias pelo menos 12 imagens aprovadas para preparar um piloto, distribuídas em três grupos independentes.')
        if len(rows)>5000:raise ValueError('Prepare até 5.000 imagens por snapshot, selecionando conjuntos na requisição.')
        parents=list(range(len(rows)))
        def find(x):
            while parents[x]!=x:parents[x]=parents[parents[x]];x=parents[x]
            return x
        def union(a,b):parents[find(b)]=find(a)
        for i,a in enumerate(rows):
            if i%32==0 and cancel():raise ValueError('Preparação cancelada durante a análise de grupos.')
            for j in range(i):
                b=rows[j]
                if (source_groups.get(a['id'],{a['group_key']}) & source_groups.get(b['id'],{b['group_key']}) or a['pixel_hash']==b['pixel_hash']
                        or (int(a['dhash'],16)^int(b['dhash'],16)).bit_count()<=4):union(i,j)
        groups={}
        for i,row in enumerate(rows):groups.setdefault(find(i),[]).append(row)
        if len(groups)<3:raise ValueError('Há menos de três grupos independentes após unir sessões e imagens semelhantes. Informe a mesma origem/pessoas no grupo e adicione novas sequências independentes.')
        ordered=sorted(groups.values(),key=lambda rs:hashlib.sha256('|'.join(sorted(r['id'] for r in rs)).encode()).hexdigest())
        n=len(ordered);nval=max(1,round(n*.15));ntest=max(1,round(n*.15))
        if nval+ntest>=n:nval=ntest=1
        assignments={}
        for idx,group in enumerate(ordered):
            split='test' if idx<ntest else 'val' if idx<ntest+nval else 'train'
            for r in group:assignments[r['id']]=(split,'componente-'+str(idx))
        did=ident();folder=self.store.root/'datasets'/did;folder.mkdir(exist_ok=False)
        records=[];stats={s:Counter() for s in ('train','val','test')}
        for index,row in enumerate(rows):
            if cancel():raise ValueError('Preparação cancelada; snapshot parcial preservado e não liberado para treino.')
            source=self.store.root/row['relative_path']
            if file_hash(source)!=row['sha256']:raise ValueError('Imagem original foi alterada fora do banco: '+row['name'])
            annotation=validate_annotations(json.loads(row['annotation']))
            if not row['authorized']:raise ValueError('Imagem sem autorização registrada.')
            split,group=assignments[row['id']]
            if kind=='detector':
                epis=[b for b in annotation['boxes'] if b['scope']=='epi']
                if not epis and not annotation['negative']:raise ValueError('Negativo precisa ser revisado explicitamente: '+row['name'])
                rel=f"images/{split}/{row['id']}{source.suffix}"
                target=folder/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                label=folder/'labels'/split/(row['id']+'.txt');label.parent.mkdir(parents=True,exist_ok=True);label.write_text(yolo_text(annotation),encoding='utf-8')
                stats[split].update(b['label'] for b in epis);stats[split]['images']+=1
                if not epis:stats[split]['negative']+=1
                records.append(dict(imagem=rel,split=split,grupos=[group]+['origem:'+g for g in sorted(source_groups.get(row['id'],{row['group_key']}))],revisada=True,autorizada=True,licenca='autorização de uso declarada na sessão',
                    image_id=row['id'],revision=row['revision'],sha256=row['sha256'],label_sha256=file_hash(label),source=row['source']))
            else:
                with Image.open(source) as im:
                    for bi,box in enumerate(annotation['boxes']):
                        if box['scope']!='cabeca' or box['label']=='inconclusivo':continue
                        xy=[round(v*(im.width if k%2==0 else im.height)) for k,v in enumerate(box['xyxy'])]
                        if min(xy[2]-xy[0],xy[3]-xy[1])<24:raise ValueError('Cabeça anotada pequena demais para classificador.')
                        rel=f"{split}/{box['label']}/{row['id']}-{bi}.jpg";target=folder/rel;target.parent.mkdir(parents=True,exist_ok=True)
                        im.crop(tuple(xy)).convert('RGB').save(target,quality=95)
                        stats[split][box['label']]+=1
                        records.append(dict(imagem=rel,split=split,grupos=[group,'origem:'+row['group_key']],image_id=row['id'],revision=row['revision'],sha256=file_hash(target),revisada=True,autorizada=True))
            progress(done=index+1,total=len(rows))
        for split in stats:
            if kind=='detector' and (stats[split]['images']<2 or not stats[split]['capacete']):
                raise ValueError('Cada divisão precisa de pelo menos duas imagens e capacetes anotados. Revise os grupos sem separar sequências semelhantes.')
            if kind=='cabecas' and any(stats[split][c]<2 for c in ('com_capacete','sem_capacete')):
                raise ValueError('Cada divisão do classificador precisa de ao menos duas cabeças com e duas sem capacete, revisadas em grupos independentes.')
        (folder/'manifesto.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        config=dict(path=str(folder),train='images/train',val='images/val',test='images/test',names=CLASSES,nc=5,manifesto='manifesto.json')
        if kind=='detector':
            (folder/'data.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
            audit=dict(erros=[],avisos=['Piloto pequeno; não comprova precisão industrial.'],grupos_verificados=True)
            if self.base:
                import importlib.util
                spec=importlib.util.spec_from_file_location('vigia_base_audit',self.base/'dataset_ia.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                audit=module.auditar_dataset(folder/'data.yaml')
                if audit['erros'] or not audit['grupos_verificados']:raise ValueError('Auditoria da base rejeitou o dataset: '+'; '.join(audit['erros'][:8]))
        else:audit=dict(erros=[],avisos=['Exportação de recortes para classificador separado; não é no_helmet YOLO. Treino de classificador não habilitado sem modelo inicial compatível.'])
        frozen=[]
        for p in folder.rglob('*'):
            if p.is_file():frozen.append(dict(path=p.relative_to(folder).as_posix(),sha256=file_hash(p)))
        seal=json.dumps(frozen,sort_keys=True).encode();fingerprint=hashlib.sha256(seal).hexdigest()
        (folder/'integridade.json').write_bytes(seal)
        summary=dict(counts={s:dict(c) for s,c in stats.items()},groups=len(groups),audit=audit,kind=kind,
                     test_independence_declared=test_independent is True,
                     limits='Independência depende dos grupos de origem/pessoas informados; não identifica pessoas automaticamente.')
        with self.store.db() as db:db.execute('INSERT INTO datasets VALUES(?,?,?,?,?,?,?)',(did,str(name)[:100],kind,time.time(),str(folder),fingerprint,json.dumps(summary)))
        self.store.log('dataset',dict(id=did,summary=summary))
        return dict(id=did,**summary)

    def validate(self,did):
        with self.store.db() as db:r=db.execute('SELECT * FROM datasets WHERE id=?',(did,)).fetchone()
        if not r:raise ValueError('Dataset não preparado ou rejeitado.')
        r=dict(r);folder=Path(r['path']).resolve()
        if not folder.is_relative_to(self.store.root/'datasets'):raise ValueError('Caminho de dataset inválido.')
        seal=(folder/'integridade.json').read_bytes()
        if hashlib.sha256(seal).hexdigest()!=r['manifest_hash']:raise ValueError('Manifesto de integridade alterado.')
        for file in json.loads(seal):
            p=(folder/file['path']).resolve()
            if not p.is_relative_to(folder) or not p.is_file() or file_hash(p)!=file['sha256']:raise ValueError('Dataset alterado após preparação.')
        with self.store.db() as db:
            current={r['id']:dict(r) for r in db.execute('SELECT id,revision,state,deleted FROM images')}
            groups={}
            for source in db.execute('SELECT src.image_id,s.group_key FROM image_sources src JOIN sessions s ON s.id=src.session_id'):
                groups.setdefault(source['image_id'],set()).add('origem:'+source['group_key'])
        for record in json.loads((folder/'manifesto.json').read_text(encoding='utf-8')):
            source=current.get(record['image_id'])
            if not source or source['deleted'] or source['state']!='approved' or source['revision']!=record['revision']:
                raise ValueError('Revisão de origem mudou após o snapshot. Prepare um novo dataset; o anterior permanece preservado.')
            if r['kind']=='detector' and set(g for g in record['grupos'] if g.startswith('origem:'))!=groups.get(record['image_id'],set()):
                raise ValueError('Novas origens/duplicatas mudaram os grupos; prepare outro dataset para evitar vazamento.')
        r['summary']=json.loads(r['summary']);return r
