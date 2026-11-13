"""Importação em blocos e ZIP sem extração de caminhos controlados pelo arquivo."""
import json
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath
from .store import MAX_IMAGE, ident, safe_name, yolo_parse

MAX_UPLOAD=512*1024*1024
MAX_EXPANDED=1024*1024*1024
IMAGE_EXT={'.jpg','.jpeg','.png','.webp'}


class Importer:
    def __init__(self,store):self.store=store

    def start(self,session,name,size,extras=None):
        self.store.get_session(session);name=safe_name(name)
        if type(size) is not int or not 0<size<=MAX_UPLOAD:raise ValueError('Arquivo vazio ou maior que 512 MB.')
        ext=PurePosixPath(name).suffix.lower()
        if ext not in IMAGE_EXT|{'.zip'}:raise ValueError('Importe imagem ou ZIP com imagens e anotações.')
        if ext!='.zip' and size>MAX_IMAGE:raise ValueError('Imagem individual maior que 20 MB.')
        if shutil.disk_usage(self.store.root).free<size*2+100*1024*1024:raise ValueError('Espaço livre insuficiente.')
        uid=ident()
        if extras is not None and (not isinstance(extras,dict) or len(json.dumps(extras))>1024*1024):raise ValueError('Metadados de importação excessivos.')
        with self.store.db() as db:db.execute('INSERT INTO uploads(id,session_id,name,size,created,extras) VALUES(?,?,?,?,?,?)',(uid,session,name,size,time.time(),json.dumps(extras or {})))
        (self.store.root/'importacoes'/f'{uid}.part').touch(exist_ok=False)
        return uid

    def get(self,uid):
        with self.store.db() as db:r=db.execute('SELECT * FROM uploads WHERE id=?',(uid,)).fetchone()
        if not r:raise ValueError('Upload não encontrado.')
        return dict(r)

    def chunk(self,uid,offset,data):
        if not data or len(data)>4*1024*1024:raise ValueError('Bloco vazio ou maior que 4 MB.')
        with self.store.lock,self.store.db() as db:
            r=self.get(uid)
            if r['state']!='uploading' or offset!=r['offset'] or offset+len(data)>r['size']:
                raise ValueError('Posição de upload divergente; consulte o progresso e retome o bloco correto.')
            p=self.store.root/'importacoes'/f'{uid}.part'
            if p.stat().st_size!=offset:raise ValueError('Upload interrompido antes de confirmar o último bloco; inicie uma nova importação.')
            with p.open('ab') as f:f.write(data);f.flush()
            db.execute('UPDATE uploads SET offset=? WHERE id=?',(offset+len(data),uid))
        return offset+len(data)

    def seal(self,uid):
        with self.store.lock,self.store.db() as db:
            r=self.get(uid)
            if r['offset']!=r['size'] or r['state']!='uploading':raise ValueError('Upload incompleto ou já finalizado.')
            db.execute("UPDATE uploads SET state='queued' WHERE id=?",(uid,))
        return r

    def finish(self,uid,progress=lambda **_:None,cancel=lambda:False):
        r=self.get(uid)
        if r['offset']!=r['size'] or r['state'] not in ('queued','running'):raise ValueError('Upload não está pronto.')
        p=self.store.root/'importacoes'/f'{uid}.part'
        report=dict(imported=0,duplicates=0,errors=[],unsupported=[],total=0,cancelled=False)
        def add(name,data,annotation=None,metadata=None):
            try:
                result=self.store.import_image(r['session_id'],name,data,annotation,metadata)
                report['duplicates' if result['duplicate'] else 'imported']+=1
            except (ValueError,OSError) as e:report['errors'].append(dict(file=name,error=str(e)))
        try:
            if PurePosixPath(r['name']).suffix.lower()!='.zip':
                extra=json.loads(r['extras'] or '{}');annotation=yolo_parse(extra['yolo']) if 'yolo' in extra else None
                metadata=extra.get('metadata')
                if annotation is None and isinstance(metadata,dict) and isinstance(metadata.get('annotation'),dict):
                    from .store import validate_annotations
                    annotation=validate_annotations(metadata['annotation'])
                report['total']=1;add(r['name'],p.read_bytes(),annotation,metadata)
            else:
                with zipfile.ZipFile(p) as archive:
                    infos=archive.infolist()
                    if len(infos)>10000:raise ValueError('ZIP possui mais de 10.000 entradas.')
                    total=0;entries={}
                    # Preflight de TODO o ZIP antes de gravar uma imagem.
                    for entry in infos:
                        name=safe_name(entry.filename.rstrip('/'))
                        if stat.S_ISLNK(entry.external_attr>>16) or entry.flag_bits&1:raise ValueError('ZIP com links ou criptografia não é aceito.')
                        if entry.is_dir():continue
                        if name in entries:raise ValueError('ZIP com nomes duplicados é ambíguo.')
                        ext=PurePosixPath(name).suffix.lower()
                        if ext in ('.zip','.7z','.rar','.exe','.dll','.bat','.cmd','.ps1'):raise ValueError('ZIP contém arquivo executável ou arquivo compactado aninhado.')
                        if entry.file_size>MAX_IMAGE or entry.file_size/max(entry.compress_size,1)>150:
                            raise ValueError('ZIP excede limite de entrada ou taxa de descompressão.')
                        if ext in ('.txt','.json','.yaml','.yml') and entry.file_size>1024*1024:raise ValueError('Metadado no ZIP excede 1 MB.')
                        total+=entry.file_size
                        if total>MAX_EXPANDED:raise ValueError('ZIP excede 1 GB descompactado.')
                        entries[name]=entry
                    # Um YAML fornecido só pode descrever as classes atuais; nunca é executado.
                    for name,entry in entries.items():
                        if PurePosixPath(name).name in ('data.yaml','dataset.yaml'):
                            import yaml
                            content=yaml.safe_load(archive.read(entry))
                            from .store import CLASSES
                            names=content.get('names') if isinstance(content,dict) else None
                            if isinstance(names,dict):names=[names.get(i,names.get(str(i))) for i in range(len(names))]
                            if names!=CLASSES:raise ValueError('Classes do ZIP não correspondem aos IDs 0–4 originais. Remapeie e revise antes de importar.')
                    images=[n for n in entries if PurePosixPath(n).suffix.lower() in IMAGE_EXT]
                    if len(images)>5000:raise ValueError('Importe no máximo 5.000 imagens por ZIP.')
                    if not images:raise ValueError('ZIP não contém imagens compatíveis.')
                    report['total']=len(images)
                    for index,name in enumerate(images):
                        if cancel():report['cancelled']=True;break
                        label=str(PurePosixPath(name).with_suffix('.txt'))
                        # Compatibilidade com images/train/a.jpg + labels/train/a.txt.
                        alternate='/'.join('labels' if part=='images' else part for part in PurePosixPath(label).parts)
                        label=label if label in entries else alternate
                        sidecar=str(PurePosixPath(name).with_suffix('.json'))
                        try:
                            annotation=yolo_parse(archive.read(entries[label]).decode('utf-8-sig')) if label in entries else None
                            metadata=json.loads(archive.read(entries[sidecar])) if sidecar in entries else None
                            if metadata is not None and not isinstance(metadata,(dict,list)):raise ValueError('Metadados JSON inválidos.')
                            add(name,archive.read(entries[name]),annotation,metadata)
                        except (ValueError,UnicodeError,zipfile.BadZipFile) as e:report['errors'].append(dict(file=name,error=str(e)))
                        progress(done=index+1,total=len(images))
                    report['unsupported']=[n for n in entries if PurePosixPath(n).suffix.lower() not in IMAGE_EXT|{'.txt','.json','.yaml','.yml'}][:100]
            with self.store.db() as db:db.execute('UPDATE uploads SET state=? WHERE id=?',('cancelled' if report['cancelled'] else 'done',uid))
        except Exception:
            with self.store.db() as db:db.execute("UPDATE uploads SET state='failed' WHERE id=?",(uid,))
            raise
        self.store.log('import',dict(upload=uid,report=report))
        return report
