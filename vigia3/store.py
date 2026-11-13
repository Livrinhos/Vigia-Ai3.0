"""Banco local de imagens: originais imutáveis, revisão versionada e lixeira recuperável."""
import hashlib
import io
import json
import math
import os
import sqlite3
import threading
import time
import uuid
import warnings
from contextlib import contextmanager, closing
from pathlib import Path, PurePosixPath
from PIL import Image, ImageOps, ImageStat

CLASSES = ['capacete', 'colete', 'oculos', 'luvas', 'mascara']
FORMATS = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp'}
MAX_IMAGE = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000


def ident(): return uuid.uuid4().hex
def digest(data): return hashlib.sha256(data).hexdigest()
def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def documents():
    if os.name=='nt':
        import ctypes
        buf=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None,5,None,0,buf)==0:return Path(buf.value)
    return Path.home()/'Documents'


def safe_name(name):
    name=str(name).replace('\\','/')
    p=PurePosixPath(name)
    if (not name or name.startswith('/') or ':' in name or any(s in ('..','') for s in name.split('/'))
            or len(name)>500 or any(ord(c)<32 for c in name)):
        raise ValueError('Nome/caminho de arquivo inválido.')
    return p.as_posix()


def decode_image(data):
    if not data or len(data)>MAX_IMAGE:raise ValueError('Imagem vazia ou maior que 20 MB.')
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as im:
                fmt=im.format
                if fmt not in FORMATS or im.width*im.height>MAX_PIXELS:raise ValueError('Formato ou tamanho de imagem não permitido.')
                if getattr(im,'n_frames',1)!=1:raise ValueError('Imagens animadas não são aceitas.')
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                # Coordenadas preservam os pixels originais; EXIF não rotaciona silenciosamente labels antigas.
                rgb=im.convert('RGB');rgb.load()
                orientation=im.getexif().get(274,1)
        except (OSError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning) as e:
            raise ValueError('Conteúdo de imagem inválido ou descompressão excessiva.') from e
    tiny=rgb.resize((9,8)).convert('L');px=list(tiny.getdata())
    bits=sum((px[y*9+x]>px[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
    stat=ImageStat.Stat(rgb.convert('L'));issues=[]
    if min(rgb.size)<64:issues.append('resolução muito pequena')
    if stat.mean[0]<25 or stat.mean[0]>240:issues.append('iluminação extrema')
    if stat.stddev[0]<8:issues.append('baixo contraste')
    if orientation!=1:issues.append('EXIF orientado: conferir alinhamento das caixas nos pixels originais')
    return rgb,fmt,f'{bits:016x}',issues


def validate_annotations(data):
    if not isinstance(data,dict):raise ValueError('Anotações devem ser um objeto.')
    boxes=data.get('boxes',[])
    if not isinstance(boxes,list) or len(boxes)>1000:raise ValueError('Lista de caixas inválida.')
    clean=[]
    for b in boxes:
        if not isinstance(b,dict):raise ValueError('Caixa inválida.')
        scope=b.get('scope','epi');label=b.get('label')
        if scope=='epi' and label not in CLASSES:raise ValueError('Classe de EPI inválida; índices 0 a 4 são preservados.')
        if scope=='pessoa' and label!='pessoa':raise ValueError('Região de pessoa inválida.')
        if scope=='cabeca' and label not in ('com_capacete','sem_capacete','inconclusivo'):
            raise ValueError('Rótulo de cabeça inválido.')
        if scope not in ('epi','pessoa','cabeca'):raise ValueError('Tipo de região inválido.')
        xy=b.get('xyxy')
        if (not isinstance(xy,list) or len(xy)!=4 or not all(type(v) in (int,float) and math.isfinite(v) for v in xy)
                or not 0<=xy[0]<xy[2]<=1 or not 0<=xy[1]<xy[3]<=1):
            raise ValueError('Caixa precisa estar dentro da imagem e ter área positiva.')
        clean.append(dict(scope=scope,label=label,xyxy=xy,origin=str(b.get('origin','manual'))[:30]))
    negative=data.get('negative',False)
    if type(negative) is not bool:raise ValueError('Confirmação de negativo inválida.')
    if negative and any(b['scope']=='epi' for b in clean):raise ValueError('Imagem com EPI anotado não pode ter rótulo YOLO vazio.')
    return dict(boxes=clean,negative=negative,notes=str(data.get('notes',''))[:2000])


def yolo_parse(text):
    boxes=[]
    for line in text.splitlines():
        if not line.strip():continue
        v=list(map(float,line.split()))
        if len(v)!=5 or not all(math.isfinite(x) for x in v):raise ValueError('Linha YOLO inválida.')
        c,x,y,w,h=v
        if c!=int(c) or int(c) not in range(5):raise ValueError('IDs de classe incompatíveis com os cinco EPIs originais.')
        boxes.append(dict(scope='epi',label=CLASSES[int(c)],xyxy=[x-w/2,y-h/2,x+w/2,y+h/2],origin='importada'))
    return validate_annotations(dict(boxes=boxes,negative=not boxes))


def yolo_text(annotation):
    lines=[]
    for b in annotation['boxes']:
        if b['scope']!='epi':continue
        x1,y1,x2,y2=b['xyxy']
        lines.append(f"{CLASSES.index(b['label'])} {(x1+x2)/2:.8f} {(y1+y2)/2:.8f} {x2-x1:.8f} {y2-y1:.8f}")
    return '\n'.join(lines)+('\n' if lines else '')


class Store:
    def __init__(self,root=None):
        self.root=Path(root or os.getenv('VIGIAAI_DATA_DIR') or documents()/'VigiaAI-Dados').resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        for name in ('imagens/originais','imagens/miniaturas','imagens/visualizacao','anotacoes','datasets','modelos','relatorios','backups','importacoes','trabalhos'):
            (self.root/name).mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,name TEXT NOT NULL,group_key TEXT NOT NULL,authorized INTEGER NOT NULL,created REAL);
            CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,session_id TEXT,sha256 TEXT UNIQUE,pixel_hash TEXT,dhash TEXT,name TEXT,source TEXT,width INTEGER,height INTEGER,bytes INTEGER,format TEXT,relative_path TEXT,created REAL,state TEXT DEFAULT 'pending',annotation TEXT,revision INTEGER DEFAULT 0,issues TEXT,deleted INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,session_id TEXT,name TEXT,size INTEGER,offset INTEGER DEFAULT 0,state TEXT DEFAULT 'uploading',created REAL);
            CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,name TEXT,kind TEXT,created REAL,path TEXT,manifest_hash TEXT,summary TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT,state TEXT,created REAL,updated REAL,request TEXT,result TEXT,error TEXT);
            CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY,name TEXT,path TEXT,sha256 TEXT,kind TEXT,origin TEXT,approved INTEGER DEFAULT 0,evaluation TEXT);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,created REAL,action TEXT,details TEXT);
            CREATE TABLE IF NOT EXISTS image_sources(image_id TEXT,session_id TEXT,source TEXT,created REAL,PRIMARY KEY(image_id,session_id,source));
            CREATE TABLE IF NOT EXISTS image_suggestions(image_id TEXT,job_id TEXT,revision INTEGER,model_sha256 TEXT,boxes TEXT,created REAL,state TEXT,PRIMARY KEY(image_id,job_id));
            ''')
            if 'extras' not in {r[1] for r in db.execute('PRAGMA table_info(uploads)')}:
                db.execute('ALTER TABLE uploads ADD COLUMN extras TEXT')
            db.execute('INSERT OR IGNORE INTO image_sources SELECT id,session_id,source,created FROM images')
            if 'training_history' not in {r[1] for r in db.execute('PRAGMA table_info(models)')}:
                db.execute('ALTER TABLE models ADD COLUMN training_history TEXT')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.root/'banco.sqlite3',timeout=30)
        db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:yield db
        finally:db.close()

    def log(self,action,details):
        with self.db() as db:db.execute('INSERT INTO audit(created,action,details) VALUES(?,?,?)',(time.time(),action,json.dumps(details)))

    def session(self,name,group,authorized):
        if authorized is not True:raise ValueError('Confirme autorização de uso das imagens antes de importar.')
        if not str(name).strip() or len(str(name))>150:raise ValueError('Informe o nome da sessão.')
        sid=ident();group=str(group).strip() or sid
        if len(group)>200:raise ValueError('Grupo de origem muito longo.')
        with self.db() as db:db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(sid,str(name).strip(),group,1,time.time()))
        return sid

    def get_session(self,sid):
        with self.db() as db:r=db.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
        if not r:raise ValueError('Sessão inexistente.')
        return dict(r)

    def import_image(self,sid,name,data,annotation=None,metadata=None):
        self.get_session(sid);name=safe_name(name)
        rgb,fmt,phash,issues=decode_image(data)
        sha=digest(data);pixels=digest(str(rgb.size).encode()+rgb.tobytes())
        with self.lock,self.db() as db:
            same=db.execute('SELECT id,deleted FROM images WHERE sha256=? OR pixel_hash=? LIMIT 1',(sha,pixels)).fetchone()
            if same:
                db.execute('INSERT OR IGNORE INTO image_sources VALUES(?,?,?,?)',(same['id'],sid,name,time.time()))
                if annotation is not None or metadata is not None:
                    extra=dict(annotation=annotation,metadata=metadata,source=name)
                    (self.root/'anotacoes'/f'{same["id"]}-{sid}-duplicata.json').write_text(json.dumps(extra,ensure_ascii=False),encoding='utf-8')
                return dict(duplicate=True,id=same['id'],in_trash=bool(same['deleted']))
            iid=ident();rel='imagens/originais/'+iid+FORMATS[fmt]
            (self.root/rel).write_bytes(data)
            rgb.save(self.root/'imagens/visualizacao'/f'{iid}.jpg',quality=95)
            thumb=rgb.copy();thumb.thumbnail((360,240));thumb.save(self.root/'imagens/miniaturas'/f'{iid}.jpg',quality=80)
            ann=validate_annotations(annotation or {})
            db.execute('INSERT INTO images(id,session_id,sha256,pixel_hash,dhash,name,source,width,height,bytes,format,relative_path,created,annotation,issues) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (iid,sid,sha,pixels,phash,PurePosixPath(name).name,name,*rgb.size,len(data),fmt,rel,time.time(),json.dumps(ann),json.dumps(issues)))
            db.execute('INSERT INTO image_sources VALUES(?,?,?,?)',(iid,sid,name,time.time()))
            if metadata is not None:
                (self.root/'anotacoes'/f'{iid}-origem.json').write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
            if ann['boxes'] or ann['negative']:
                (self.root/'anotacoes'/f'{iid}-importada.json').write_text(json.dumps(ann),encoding='utf-8')
        return dict(duplicate=False,id=iid,issues=issues)

    def image(self,iid,include_deleted=False):
        with self.db() as db:r=db.execute('SELECT i.*,s.name session_name,s.group_key,s.authorized FROM images i JOIN sessions s ON s.id=i.session_id WHERE i.id=?',(iid,)).fetchone()
        if not r or (r['deleted'] and not include_deleted):raise ValueError('Imagem não encontrada.')
        r=dict(r);r['annotation']=json.loads(r['annotation']);r['issues']=json.loads(r['issues'])
        with self.db() as db:r['sources']=[dict(x) for x in db.execute('SELECT src.source,s.name session_name,s.group_key FROM image_sources src JOIN sessions s ON s.id=src.session_id WHERE src.image_id=?',(iid,))]
        return r

    def list_images(self,state='all',q='',session='',page=1):
        where=['i.deleted=0'];args=[]
        if state=='ready':where.append("i.state='approved'")
        elif state!='all':
            if state not in ('pending','reviewed','approved','rejected'):raise ValueError('Filtro inválido.')
            where.append('i.state=?');args.append(state)
        if q:where.append('(i.name LIKE ? OR s.name LIKE ? OR i.source LIKE ?)');args += ['%'+q[:150]+'%']*3
        if session:where.append('i.session_id=?');args.append(session)
        sql=' FROM images i JOIN sessions s ON i.session_id=s.id WHERE '+' AND '.join(where)
        with self.db() as db:
            total=db.execute('SELECT COUNT(*)'+sql,args).fetchone()[0]
            rows=db.execute('SELECT i.id,i.name,i.width,i.height,i.state,i.issues,i.revision,s.name session_name'+sql+' ORDER BY i.created DESC LIMIT 60 OFFSET ?',args+[(max(1,int(page))-1)*60]).fetchall()
            counts={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM images WHERE deleted=0 GROUP BY state')}
            sessions=[dict(r) for r in db.execute('SELECT * FROM sessions ORDER BY created DESC')]
        return dict(items=[dict(r) for r in rows],total=total,page=int(page),counts=counts,ready=counts.get('approved',0),sessions=sessions)

    def image_ids(self,state='all',q='',session=''):
        from .suggestions import MAX_BATCH
        where=['i.deleted=0'];args=[]
        if state=='ready':state='approved'
        if state!='all':
            if state not in ('pending','reviewed','approved','rejected'):raise ValueError('Filtro inválido.')
            where.append('i.state=?');args.append(state)
        if q:where.append('(i.name LIKE ? OR s.name LIKE ? OR i.source LIKE ?)');args += ['%'+q[:150]+'%']*3
        if session:where.append('i.session_id=?');args.append(session)
        with self.db() as db:
            rows=db.execute('SELECT i.id FROM images i JOIN sessions s ON i.session_id=s.id WHERE '+' AND '.join(where)+' ORDER BY i.created DESC LIMIT ?',args+[MAX_BATCH+1]).fetchall()
        if len(rows)>MAX_BATCH:raise ValueError('O filtro excede 5.000 imagens. Restrinja por sessão ou pesquisa.')
        return [r['id'] for r in rows]

    def suggestion(self,iid):
        image=self.image(iid)
        with self.db() as db:
            r=db.execute("SELECT * FROM image_suggestions WHERE image_id=? AND revision=? AND state='pending' ORDER BY created DESC LIMIT 1",(iid,image['revision'])).fetchone()
        if not r:return None
        r=dict(r);r['boxes']=json.loads(r['boxes']);r['review_required']=True
        return r

    def review(self,iid,data,expected_revision):
        ann=validate_annotations(data.get('annotation',{}));state=data.get('state')
        if state not in ('pending','reviewed','approved','rejected'):raise ValueError('Estado de revisão inválido.')
        if state in ('reviewed','approved') and data.get('human_reviewed') is not True:
            raise ValueError('Revisão humana explícita obrigatória.')
        if state=='approved' and not any(b['scope']=='epi' for b in ann['boxes']) and not ann['negative']:
            raise ValueError('Anote EPIs visíveis ou confirme o rótulo YOLO vazio como negativo revisado.')
        if type(expected_revision) is not int:raise ValueError('Revisão de concorrência obrigatória.')
        with self.lock,self.db() as db:
            row=self.image(iid)
            if row['revision']!=expected_revision:raise ValueError('A imagem foi alterada em outra tela. Recarregue antes de salvar.')
            if state=='approved' and row['issues'] and data.get('issues_acknowledged') is not True:
                raise ValueError('Confirme que revisou os avisos de qualidade da imagem.')
            newrev=expected_revision+1
            (self.root/'anotacoes'/f'{iid}-r{newrev}.json').write_text(json.dumps(dict(annotation=ann,state=state,reviewed_at=time.time()),ensure_ascii=False),encoding='utf-8')
            db.execute('UPDATE images SET state=?,annotation=?,revision=? WHERE id=?',(state,json.dumps(ann),newrev,iid))
        self.log('review',dict(id=iid,state=state,revision=newrev));return self.image(iid)

    def trash(self,ids,confirmed,restore=False):
        if confirmed!='CONFIRMAR':raise ValueError('Confirmação obrigatória para alterar a lixeira.')
        if not isinstance(ids,list) or not 1<=len(ids)<=1000 or not all(isinstance(x,str) for x in ids):raise ValueError('Seleção inválida.')
        with self.db() as db:
            for iid in ids:db.execute('UPDATE images SET deleted=? WHERE id=?',(0 if restore else 1,iid))
        self.log('restore' if restore else 'trash',ids)
        return len(ids)

    def backup(self):
        name='banco-'+time.strftime('%Y%m%d-%H%M%S')+'-'+ident()[:8]+'.sqlite3'
        with self.db() as source,closing(sqlite3.connect(self.root/'backups'/name)) as dest:source.backup(dest)
        return name
