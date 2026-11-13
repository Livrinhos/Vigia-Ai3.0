"""Registro de pesos por hash. Promoção explícita e reversível, sem sobrescrever pesos."""
import json
from pathlib import Path
from .store import file_hash, ident


class Models:
    def __init__(self,store,base):
        self.store,self.base=store,Path(base).resolve()
        for rel,kind in (('epi.pt','epi'),('yolov8n.pt','pessoas'),('runs/detect/treinamento_epi-2/weights/best.pt','auxiliar')):
            p=self.base/rel
            if p.is_file():self.register(p,kind,'original',rel,approved=True)

    def register(self,path,kind,origin,name,approved=False):
        p=Path(path).resolve()
        if not p.is_file() or p.suffix!='.pt' or not (p.is_relative_to(self.base) or p.is_relative_to(self.store.root/'modelos')):
            raise ValueError('Peso precisa ser uma cópia confiável dentro da base ou de modelos persistentes.')
        sha=file_hash(p)
        with self.store.db() as db:
            if origin=='original':
                same=db.execute("SELECT id FROM models WHERE origin='original' AND kind=? AND sha256=?",(kind,sha)).fetchone()
                if same:
                    db.execute('UPDATE models SET path=? WHERE id=?',(str(p),same['id']))
                    return same['id']
            r=db.execute('SELECT id FROM models WHERE path=? AND sha256=?',(str(p),sha)).fetchone()
            if r:return r['id']
            mid=ident();db.execute('INSERT INTO models(id,name,path,sha256,kind,origin,approved) VALUES(?,?,?,?,?,?,?)',(mid,name,str(p),sha,kind,origin,int(approved)))
        return mid

    def get(self,mid):
        with self.store.db() as db:r=db.execute('SELECT * FROM models WHERE id=?',(mid,)).fetchone()
        if not r:raise ValueError('Modelo não registrado.')
        r=dict(r);p=Path(r['path']).resolve()
        if not p.is_file() or file_hash(p)!=r['sha256']:raise ValueError('Integridade do modelo falhou. Peso não será usado.')
        if not (p.is_relative_to(self.base) or p.is_relative_to(self.store.root/'modelos')):raise ValueError('Modelo fora das raízes autorizadas.')
        return r

    def list(self):
        with self.store.db() as db:rows=[dict(r) for r in db.execute('SELECT id,name,sha256,kind,origin,approved,evaluation FROM models')]
        return rows

    def approve(self,mid,confirmation):
        m=self.get(mid)
        if confirmation!='APROVAR '+mid:raise ValueError('Aprovação explícita do modelo é obrigatória.')
        if m['origin']!='original':
            evaluation=json.loads(m['evaluation'] or '{}')
            if not evaluation.get('compatible') or not evaluation.get('independent_test'):
                raise ValueError('Compare o candidato com o original no teste independente antes de aprovar.')
            if not evaluation.get('non_regression'):
                raise ValueError('Comparação indicou regressão; candidato não pode ser promovido.')
        if m['kind']!='epi':raise ValueError('Somente detector de EPI compatível pode substituir o detector de capacetes.')
        with self.store.db() as db:db.execute('UPDATE models SET approved=1 WHERE id=?',(mid,))
        self.store.log('approve_model',dict(id=mid))

    def select(self,mid,monitor,confirmation):
        if confirmation!='SELECIONAR':raise ValueError('Confirme a seleção do modelo.')
        with monitor.lock:
            if monitor.thread and monitor.thread.is_alive():raise ValueError('Encerre o monitoramento antes de trocar o modelo.')
            m=self.get(mid)
            if not m['approved'] or m['kind']!='epi':raise ValueError('Modelo não aprovado ou incompatível.')
            monitor.modelo_epi=Path(m['path'])
            monitor.status.update(modelo_epi=m['name'],modelo_epi_disponivel=True,modelo_aprovado_id=mid)
            monitor.status['modelo_selecao_erro']=None
            p=self.store.root/'modelo-ativo.json';tmp=p.with_suffix('.tmp')
            tmp.write_text(json.dumps(dict(id=mid,sha256=m['sha256'])),encoding='utf-8');tmp.replace(p)
        self.store.log('select_model',dict(id=mid))

    def restore(self,monitor):
        original=next((m for m in self.list() if m['origin']=='original' and m['kind']=='epi'),None)
        if not original:raise ValueError('Modelo original ausente; copie o peso preservado para a base.')
        self.select(original['id'],monitor,'SELECIONAR')
