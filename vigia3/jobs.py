"""Trabalhos em processos próprios: logs persistentes e cancelamento do próprio filho."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from .store import ident


class Jobs:
    def __init__(self,store,base,monitor=None,command=None):
        self.store,self.base,self.monitor=store,Path(base).resolve(),monitor
        self.command=command or [sys.executable,'-u','-m','vigia3.worker']
        self.lock=threading.RLock();self.processes={}
        with self.store.db() as db:previous=[r['id'] for r in db.execute("SELECT id FROM jobs WHERE state IN ('queued','running','cancelling')")]
        for jid in previous:
            if not self._alive(jid):
                with self.store.db() as db:db.execute("UPDATE jobs SET state='interrupted',error='Processo não está mais ativo; arquivos e checkpoints foram preservados.' WHERE id=?",(jid,))

    def _alive(self,jid):
        if jid in self.processes:return self.processes[jid].poll() is None
        try:import psutil
        except ImportError:return False
        try:
            record=json.loads((self.store.root/'trabalhos'/jid/'process.json').read_text())
            p=psutil.Process(record['pid'])
            return abs(p.create_time()-record['created'])<1 and p.is_running()
        except (OSError,ValueError,KeyError,psutil.Error):return False

    def active(self):
        with self.lock:
            if any(p.poll() is None for p in self.processes.values()):return True
            with self.store.db() as db:rows=[r['id'] for r in db.execute("SELECT id FROM jobs WHERE state IN ('queued','running','cancelling')")]
            return any(self._alive(jid) for jid in rows)

    def start(self,kind,request):
        if kind not in ('import','dataset','suggest','suggest_batch','train','evaluate'):raise ValueError('Trabalho inválido.')
        with self.lock:
            if self.active():raise ValueError('Aguarde ou cancele o trabalho atual antes de iniciar outro.')
            if kind in ('suggest','suggest_batch','train','evaluate') and self.monitor:
                with self.monitor.lock:
                    if self.monitor.thread and self.monitor.thread.is_alive():
                        raise ValueError('Encerre o monitoramento para evitar disputa de GPU/CPU.')
            jid=ident();folder=self.store.root/'trabalhos'/jid;folder.mkdir(exist_ok=False)
            payload=dict(id=jid,kind=kind,request=request,data_root=str(self.store.root),base=str(self.base))
            jobfile=folder/'request.json';jobfile.write_text(json.dumps(payload),encoding='utf-8')
            with self.store.db() as db:db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',(jid,kind,'queued',time.time(),time.time(),json.dumps(request),None,None))
            env=dict(os.environ,YOLO_AUTOINSTALL='false',VIGIAAI_TESTE='1',NOTIFICACOES_ATIVAS='0',SALVAR_IMAGEM_OCORRENCIA='0',
                YOLO_CONFIG_DIR=str(self.store.root/'trabalhos'/'ultralytics'))
            Path(env['YOLO_CONFIG_DIR']).mkdir(parents=True,exist_ok=True)
            env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(self.base)
            try:
                log=(folder/'worker.log').open('ab',buffering=0)
                process=subprocess.Popen(self.command+[str(jobfile)],cwd=Path(__file__).resolve().parents[1],env=env,
                    stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                log.close();self.processes[jid]=process
                import psutil
                try:(folder/'process.json').write_text(json.dumps(dict(pid=process.pid,created=psutil.Process(process.pid).create_time())),encoding='utf-8')
                except psutil.NoSuchProcess:pass
            except Exception as e:
                with self.store.db() as db:db.execute("UPDATE jobs SET state='failed',error=? WHERE id=?",(str(e),jid))
                raise
            threading.Thread(target=self._watch,args=(jid,process),daemon=True).start()
            return jid

    def _watch(self,jid,process):
        code=process.wait()
        folder=self.store.root/'trabalhos'/jid
        with self.store.db() as db:
            row=db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()
            if row and row['state'] in ('queued','running','cancelling'):
                cancelled=(folder/'cancel.request').exists()
                db.execute('UPDATE jobs SET state=?,updated=?,error=? WHERE id=?',('cancelled' if cancelled else 'failed',time.time(),
                    'Processo encerrado; logs e checkpoints preservados. Código '+str(code),jid))

    def get(self,jid):
        with self.store.db() as db:r=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not r:raise ValueError('Trabalho não encontrado.')
        r=dict(r);folder=self.store.root/'trabalhos'/jid
        r['process_running']=self._alive(jid)
        log=folder/'worker.log'
        if log.exists():
            with log.open('rb') as f:f.seek(max(0,log.stat().st_size-30000));r['log']=f.read().decode('utf-8',errors='replace')
        if (folder/'progress.json').is_file():
            try:r['progress']=json.loads((folder/'progress.json').read_text(encoding='utf-8'))
            except (ValueError,OSError):pass
        r['result']=json.loads(r['result']) if r['result'] else None
        return r

    def cancel(self,jid):
        with self.lock:
            p=self.processes.get(jid)
            if p is None:
                if not self._alive(jid):raise ValueError('Este servidor não possui um processo ativo com esse ID.')
                (self.store.root/'trabalhos'/jid/'cancel.request').touch(exist_ok=True)
                return
            if p.poll() is not None:raise ValueError('Este servidor não possui um processo ativo com esse ID.')
            (self.store.root/'trabalhos'/jid/'cancel.request').touch(exist_ok=True)
            with self.store.db() as db:db.execute("UPDATE jobs SET state='cancelling' WHERE id=?",(jid,))
            def timeout():
                try:p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    if p.poll() is None:p.terminate()  # Somente o filho criado por esta instância.
            threading.Thread(target=timeout,daemon=True).start()


def training_request(store,models,data):
    from .datasets import DatasetBuilder
    model=models.get(data.get('model'))
    if model['kind']!='epi':raise ValueError('Use um modelo de EPI compatível, não o detector de pessoas ou um classificador.')
    dataset=DatasetBuilder(store).validate(data.get('dataset'))
    if dataset['kind']!='detector':raise ValueError('Recortes de cabeça são destinados a classificador separado; não treinar como objetos no_helmet.')
    epochs,res,batch=data.get('epochs'),data.get('imgsz'),data.get('batch')
    if type(epochs)is not int or not 1<=epochs<=300:raise ValueError('Épocas: 1 a 300.')
    if type(res)is not int or not 320<=res<=1280 or res%32:raise ValueError('Resolução: múltiplo de 32 entre 320 e 1280.')
    if type(batch)is not int or not 1<=batch<=4:raise ValueError('Batch: 1 a 4 nesta configuração de 4 GB.')
    if data.get('device') not in ('cpu','0'):raise ValueError('Escolha CPU ou CUDA 0.')
    name=str(data.get('name','')).strip()
    if not re.fullmatch(r'[\w -]{1,70}',name):raise ValueError('Nome de experimento inválido.')
    pilot=data.get('pilot') is True
    counts=dataset['summary']['counts']
    minima={'train':8,'val':2,'test':2} if pilot else {'train':100,'val':30,'test':30}
    if any(counts[s].get('images',0)<n for s,n in minima.items()):raise ValueError('Dados insuficientes: treino/validação/teste exigem '+str(minima)+'. Piloto deve ser escolhido explicitamente.')
    if not pilot and any(counts['train'].get(c,0)==0 for c in ('capacete','colete','oculos','luvas','mascara')):
        raise ValueError('Treino completo exige exemplos das cinco classes para preservar funcionalidades. Estudo somente de capacetes deve ser piloto e não é promovido automaticamente.')
    return dict(model=model['id'],dataset=dataset['id'],epochs=epochs,imgsz=res,batch=batch,device=data['device'],name=name,pilot=pilot)
