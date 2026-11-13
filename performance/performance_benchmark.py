"""Benchmark sequencial de vídeo no pipeline real; suporta a cópia intocada da origem."""
import argparse
import contextlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path

from performance_preserve import sha256


class Resources:
    def __init__(self):
        self.rows, self.stop = [], threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            import psutil
            process = psutil.Process()
            process.cpu_percent()
        except ImportError:
            process = None
        while not self.stop.is_set():
            row = dict(time=time.monotonic())
            if process:
                row.update(ram_bytes=process.memory_info().rss, process_cpu_percent=process.cpu_percent())
            try:
                r = subprocess.run(['nvidia-smi','--query-gpu=name,utilization.gpu,memory.used,memory.total',
                                    '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,
                                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if r.returncode == 0:
                    row['gpu_system_samples'] = r.stdout.strip().splitlines()
            except (OSError,subprocess.TimeoutExpired):
                pass
            self.rows.append(row)
            self.stop.wait(2)


def summary(rows):
    values = defaultdict(list)
    for row in rows:
        for name, value in row.items():
            if name.endswith('_ms') and isinstance(value,(int,float)):
                values[name].append(value)
    result = {key:dict(mean=statistics.mean(v),p50=statistics.median(v),p95=sorted(v)[min(len(v)-1,int(len(v)*.95))])
              for key,v in values.items()}
    total = sum(v.get('total_ms',0) for v in rows)
    return dict(frames=len(rows),fps_processamento=1000*len(rows)/total if total else None,stages=result)


def run(args):
    root, video = args.root.resolve(), args.video.resolve()
    if not video.is_file() or not (root/'main.py').is_file():
        raise ValueError('Vídeo ou projeto não encontrado.')
    if not (root/'performance/ISOLATED_COPY').is_file() or (root/'.env').exists():
        raise ValueError('Benchmark requer cópia isolada marcada, sem .env; nunca execute na instalação original.')
    if args.warmup < 0:
        raise ValueError('Aquecimento deve ser não negativo.')
    if args.output.exists():
        raise FileExistsError('Use um diretório novo para cada execução.')
    args.output.mkdir(parents=True)
    # Ambiente temporário e sem notificações; .env da base não sobrescreve estas variáveis.
    os.environ.update(VIGIAAI_TESTE='1',NOTIFICACOES_ATIVAS='0',SALVAR_IMAGEM_OCORRENCIA='0',
                      YOLO_AUTOINSTALL='false', VIGIAAI_DEVICE=args.device, VIGIAAI_PERFIL=args.profile,
                      VIGIAAI_FP16='0')
    sys.path.insert(0,str(root))
    import cv2
    from performance_runtime import Timings
    import ultralytics
    import mediapipe as mp
    timings, rows, events = Timings(), [], []
    original_yolo = ultralytics.YOLO
    original_capture = cv2.VideoCapture
    original_pose = mp.solutions.pose.Pose
    original_face = mp.solutions.face_detection.FaceDetection

    def measured(name,function,*a,**kw):
        with timings.stage(name):
            result = function(*a,**kw)
            # Timer inclui a conclusão dos kernels; sem mudar os resultados da origem.
            if name.startswith('yolo') and args.device != 'cpu':
                import torch
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
            return result

    class Model:
        def __init__(self,file,*a,**kw):
            self.model = original_yolo(file,*a,**kw)
            self.stage = 'yolo_pessoas_ms' if Path(file).name=='yolov8n.pt' else ('yolo_epi_ms' if Path(file).name=='epi.pt' else 'yolo_auxiliar_ms')
        @property
        def names(self): return self.model.names
        def __call__(self,*a,**kw): return measured(self.stage,self.model,*a,**kw)

    class Capture:
        def __init__(self,*a,**kw): self.cap=original_capture(*a,**kw)
        def __getattr__(self,name): return getattr(self.cap,name)
        def read(self):
            timings.reset()
            return timings.call('captura_ms',self.cap.read)

    class Body:
        def __init__(self,factory,name,*a,**kw): self.obj,self.name=factory(*a,**kw),name
        def __enter__(self): self.obj.__enter__(); return self
        def __exit__(self,*a): return self.obj.__exit__(*a)
        def process(self,*a): return timings.call(self.name,self.obj.process,*a)

    ultralytics.YOLO = Model
    cv2.VideoCapture = Capture
    mp.solutions.pose.Pose = lambda *a,**kw: Body(original_pose,'mediapipe_pose_ms',*a,**kw)
    mp.solutions.face_detection.FaceDetection = lambda *a,**kw: Body(original_face,'mediapipe_rosto_ms',*a,**kw)
    os.environ['YOLO_CONFIG_DIR'] = str(args.output/'ultralytics')
    before = {p.relative_to(root).as_posix():sha256(p) for p in root.rglob('*.pt')}
    resources = Resources()
    resources.thread.start()
    main_module = None
    original_reanalysis = None
    try:
        import main
        main_module = main
        with tempfile.TemporaryDirectory(prefix='vigiaai-bench-') as temp:
            monitor = main.Monitor(base=temp,fonte_video=video)
            monitor.epi_obrigatorio = args.epis
            monitor.demonstracao = True
            # Mesma política em todas as execuções, sem configuração privada implícita.
            monitor.modo_ausencia = monitor.motor.modo_ausencia = args.absence
            monitor.status.update(executando=True,estado='iniciando')
            process = monitor.processar_deteccoes
            local = main.reanalisar_epi_por_pessoa
            original_reanalysis = local
            main.reanalisar_epi_por_pessoa = lambda *a,**kw: timings.call('reanalises_ms',local,*a,**kw)
            monitor.processar_deteccoes = lambda *a,**kw: timings.call('rastreamento_temporal_ms',process,*a,**kw)
            publish = monitor._publicar_frame
            with (args.output/'readings.jsonl').open('w',encoding='utf-8') as readings, (args.output/'frames.jsonl').open('w',encoding='utf-8') as frames:
                def publishing(original,annotated,people,fps):
                    timings.call('jpeg_publicacao_ms',publish,original,annotated,people,fps)
                    row=timings.finish(monitor.frame_capturado_em,frame=len(rows)+1,tempo_fonte=monitor.video_tempo)
                    rows.append(row)
                    frames.write(json.dumps(row)+'\n')
                    readings.write(json.dumps(dict(tempo=monitor.video_tempo,pessoas=people))+'\n')
                def alert(_frame,event,now):
                    events.append(dict(tempo=now,pessoa_id=event['pessoa_id'],tipo=event['tipo'],
                                       epis=event.get('epis',[]),classificacao=event.get('classificacao')))
                    monitor.motor.confirmador.marcar_alerta(event['chaves'],now)
                monitor._publicar_frame,monitor.alerta=publishing,alert
                started=time.perf_counter()
                monitor.executar()
                elapsed=time.perf_counter()-started
            if monitor.status['estado']=='erro':
                raise RuntimeError(monitor.status['mensagem'])
            cap=original_capture(str(video))
            count,fps=cap.get(cv2.CAP_PROP_FRAME_COUNT),cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            if len(rows)!=int(count): raise RuntimeError('Vídeo incompleto. Resultado rejeitado.')
            after={p.relative_to(root).as_posix():sha256(p) for p in root.rglob('*.pt')}
            if before!=after: raise RuntimeError('Integridade dos modelos falhou.')
            data=dict(video_id=sha256(video),duracao_segundos=count/fps,eventos=events,
                      summary=summary(rows[min(args.warmup,len(rows)):]),cold_summary=summary(rows),
                      warmup_frames=args.warmup,wall_seconds_including_load=elapsed,device=args.device,
                      profile=args.profile,policy=args.epis,absence=args.absence,models=before,
                      resources=resources.rows,fps_exibido=None,root=str(root),
                      limitation='Offline, sem webcam/tela. Rastreamento+temporal agregados; etapas YOLO incluem recortes e reanalises são inclusivas. Não somar tempos aninhados. Renderização fina na versão otimizada via /api/performance. CPU do processo pode exceder 100%; GPU/VRAM são do sistema. Qualidade requer anotação independente.')
            (args.output/'result.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
            print(json.dumps(data['summary'],indent=2))
    finally:
        resources.stop.set(); resources.thread.join(timeout=3)
        ultralytics.YOLO=original_yolo; cv2.VideoCapture=original_capture
        mp.solutions.pose.Pose=original_pose; mp.solutions.face_detection.FaceDetection=original_face
        if main_module and original_reanalysis:
            main_module.reanalisar_epi_por_pessoa=original_reanalysis


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).parent)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',choices=['cpu','0'],default='0')
    p.add_argument('--profile',choices=['qualidade','equilibrado','desempenho'],default='qualidade')
    p.add_argument('--epis',nargs='+',choices=['capacete','oculos','colete','luvas','mascara'],default=['capacete','oculos'])
    p.add_argument('--absence',choices=['observacao','explicita'],default='observacao')
    p.add_argument('--warmup',type=int,default=10)
    run(p.parse_args())
