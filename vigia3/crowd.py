"""Escalonamento justo e evidência de cabeça por pessoa, sobre o pipeline Performance.

Não reutiliza coordenadas antigas como pose atual; não fabrica classes de ausência.
"""
import math
import os
import threading
import time
from types import SimpleNamespace

_local=threading.local()


def overlap(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    return x*y/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-x*y)


class FairQueue:
    def __init__(self):self.last={};self.clock=0
    def choose(self,keys,budget):
        self.clock+=1
        chosen=sorted(range(len(keys)),key=lambda i:(self.last.get(keys[i],-1),str(keys[i])))[:budget or len(keys)]
        for i in chosen:self.last[keys[i]]=self.clock
        if len(self.last)>2000:self.last={k:v for k,v in self.last.items() if self.clock-v<100}
        return set(chosen)


class Controller:
    def __init__(self,monitor):
        self.monitor=monitor;self.pose_queue=FairQueue();self.head_queue=FairQueue();self.face=None
        self.pose_budget=max(0,int(os.getenv('VIGIAAI_POSES_POR_QUADRO','8')))
        self.head_budget=max(1,int(os.getenv('VIGIAAI_CABECAS_POR_QUADRO','4')))
        self.keys=[];self.pose_selected=set();self.pose_skipped=set();self.pending_indices=set();self.pending_ids=set();self.actual_ids=[]
        self.ambiguous_indices=set()
        self.stats={};self.pose_index=0;self.points=[]

    def begin(self,boxes):
        old=self.monitor.motor.rastreador.pessoas
        keys=[]
        for index,box in enumerate(boxes):
            scores=sorted(((overlap(box,p.caixa),pid) for pid,p in old.items()),reverse=True)
            if scores and scores[0][0]>.2 and (len(scores)==1 or scores[0][0]-scores[1][0]>.15):key='id:'+str(scores[0][1])
            else:key='new:'+str(tuple(round(x/8) for x in box))+':'+str(index)
            keys.append(key)
        self.keys=keys;self.pose_index=0;self.pose_skipped=set();self.pending_indices=set();self.pending_ids=set()
        self.ambiguous_indices=set()
        self.pose_selected=self.pose_queue.choose(keys,self.pose_budget)
        self.stats=dict(detectadas=len(boxes),poses_programadas=len(self.pose_selected),poses_pendentes=len(boxes)-len(self.pose_selected),
                        limite_pose=self.pose_budget,limite_cabecas=self.head_budget)

    def head_regions(self,frame,boxes,points):
        import cv2
        heads={};reasons={i:'Cabeça sem detalhe/visibilidade suficiente para avaliar ausência.' for i in range(len(boxes))}
        # Pose atual pode dar uma referência; nunca usa marcos da rodada anterior.
        for i,(b,p) in enumerate(zip(boxes,points)):
            eyes=[p.get(k) for k in (2,5,0)]
            if all(x and len(x)>=3 and x[2]>=.7 and all(math.isfinite(v) for v in x[:3]) for x in eyes):
                ex=[(b[0]+x[0]*(b[2]-b[0]),b[1]+x[1]*(b[3]-b[1])) for x in eyes]
                dist=math.dist(ex[0],ex[1]);cx=(ex[0][0]+ex[1][0])/2;cy=(ex[0][1]+ex[1][1])/2
                region=(cx-dist*1.4,cy-dist*1.6,cx+dist*1.4,cy+dist*1.8)
                if dist>=12 and abs(ex[2][0]-cx)<=dist*.65 and abs(ex[0][1]-ex[1][1])<=dist*.7:
                    heads[i]=dict(box=region,eyes=dist,source='pose atual')
        started=time.perf_counter()
        try:
            if self.face is None:
                import mediapipe as mp
                self.face=mp.solutions.face_detection.FaceDetection(model_selection=1,min_detection_confidence=.75)
            faces=self.face.process(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).detections or []
            for face in faces:
                bb=face.location_data.relative_bounding_box;kp=face.location_data.relative_keypoints
                h,w=frame.shape[:2];x,y,bw,bh=bb.xmin*w,bb.ymin*h,bb.width*w,bb.height*h
                cx,cy=x+bw/2,y+bh/2
                candidates=[]
                for i,b in enumerate(boxes):
                    if b[0]<=cx<=b[2] and b[1]-.05*(b[3]-b[1])<=cy<=b[1]+.45*(b[3]-b[1]):
                        score=math.hypot((cx-(b[0]+b[2])/2)/max(1,b[2]-b[0]),(cy-(b[1]+.14*(b[3]-b[1])))/max(1,b[3]-b[1]))
                        candidates.append((score,i))
                candidates.sort()
                if not candidates:continue
                if len(candidates)>1 and candidates[1][0]-candidates[0][0]<.12:
                    for _,i in candidates[:2]:heads.pop(i,None);reasons[i]='Cabeça entre pessoas próximas; associação ambígua.'
                    continue
                i=candidates[0][1];ex=[(k.x*w,k.y*h) for k in kp[:3]]
                dist=math.dist(ex[0],ex[1]);ecx=(ex[0][0]+ex[1][0])/2
                if (float(face.score[0])>=.75 and min(bw,bh)>=24 and dist>=12 and abs(ex[2][0]-ecx)<=dist*.65
                        and abs(ex[0][1]-ex[1][1])<=dist*.7):
                    heads[i]=dict(box=(x-.12*bw,y-.65*bh,x+1.12*bw,y+1.1*bh),eyes=dist,source='rosto global atual')
        except (ImportError,AttributeError,RuntimeError):
            self.stats['rosto_global_indisponivel']=True
        self.stats['rosto_global_ms']=(time.perf_counter()-started)*1000
        for i,p in enumerate(points):
            head=heads.get(i);valid=False
            if head:
                x1,y1,x2,y2=head['box'];h,w=frame.shape[:2]
                if 2<x1<x2<w-2 and 2<y1<y2<h-2:
                    crop=frame[int(y1):int(y2),int(x1):int(x2)]
                    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
                    valid=float(gray.mean())>=35 and float(gray.std())>=8
                    if not valid:reasons[i]='Cabeça com pouca luz ou contraste.'
                else:reasons[i]='Região da cabeça cortada pela borda da imagem.'
            p['_head_v3']=dict(head or {},verifiable=valid,reason='Cabeça visível; aguardando reanálise.' if valid else reasons[i])
            if self.monitor.presentation_active and valid:p['_imagem_adequada']=True
        return heads

    def reanalyze(self,original_function,model,frame,boxes,points,required,detections,**kwargs):
        from epi_monitoramento import associar_epis,identificar_epi,identificar_ausencia
        from epi_inferencia import extrair_deteccoes_epi
        others=[x for x in required if x!='capacete']
        new,report=(original_function(model,frame,boxes,points,others,detections,**kwargs) if others else ([],dict(concluidas=0,pendentes=0,erros=[])))
        if 'capacete' not in required:return new,report
        self.head_regions(frame,boxes,points)
        persons=[dict(id=i,caixa=b,pontos=p) for i,(b,p) in enumerate(zip(boxes,points))]
        positive,ambiguous=associar_epis(persons,detections)
        self.ambiguous_indices={i for i,v in ambiguous.items() if 'capacete' in v}
        candidates=[i for i in range(len(boxes)) if 'capacete' not in positive[i]]
        keys=[self.keys[i] if i<len(self.keys) else 'index:'+str(i) for i in candidates]
        selected={candidates[i] for i in self.head_queue.choose(keys,self.head_budget)}
        complete=0;errors=set(report['erros']);pending=0
        for i,(box,p) in enumerate(zip(boxes,points)):
            needed=set(p.get('_epi_local_necessarios',()));evaluated=set(p.get('_epi_local_avaliados',()))
            if i not in candidates:continue
            needed.add('capacete')
            if i not in selected:
                self.pending_indices.add(i);pending+=1
                p['_head_v3']['reason']='Reanálise em fila; outra pessoa está sendo atendida nesta rodada.'
            elif model is not None:
                head=p['_head_v3'];h,w=frame.shape[:2]
                roi=head.get('box',(box[0]-.05*(box[2]-box[0]),box[1]-.08*(box[3]-box[1]),box[2]+.05*(box[2]-box[0]),box[1]+.4*(box[3]-box[1])))
                x1,y1,x2,y2=(max(0,int(roi[0])),max(0,int(roi[1])),min(w,int(roi[2])),min(h,int(roi[3])))
                try:
                    if min(x2-x1,y2-y1)<16:raise ValueError('Cabeça pequena demais para reanálise.')
                    classes=[ci for ci,n in model.names.items() if (identificar_epi(n) or identificar_ausencia(n))=='capacete']
                    if not classes:raise ValueError('Modelo sem classe de capacete.')
                    options={k:v for k,v in (kwargs.get('opcoes_inferencia') or {}).items() if k in ('device','quantize','imgsz')}
                    options.setdefault('imgsz',640)
                    output=model(frame[y1:y2,x1:x2],classes=classes,conf=.25,verbose=False,**options)
                    found=extrair_deteccoes_epi(output,origem=(x1,y1),itens={'capacete'},piso_outros=.25)
                    for d in found:
                        cx=(d['caixa'][0]+d['caixa'][2])/2;cy=(d['caixa'][1]+d['caixa'][3])/2
                        if box[0]-.05*(box[2]-box[0])<=cx<=box[2]+.05*(box[2]-box[0]) and y1<=cy<=y2:d['local']=True;new.append(d)
                    evaluated.add('capacete');complete+=1
                    p['_head_v3']['reason']='Reanálise realizada; ausência é apenas possibilidade e depende de confirmação temporal.' if head['verifiable'] else head['reason']
                except Exception as error:errors.add(type(error).__name__);pending+=1;p['_head_v3']['reason']='Falha de reanálise; resultado inconclusivo.'
            else:pending+=1;p['_head_v3']['reason']='Modelo de capacete indisponível.'
            p['_epi_local_necessarios']=tuple(sorted(needed));p['_epi_local_avaliados']=tuple(sorted(evaluated))
        self.stats.update(cabecas_em_fila=pending,cabecas_reanalisadas=complete)
        return new,dict(concluidas=report['concluidas']+complete,pendentes=report['pendentes']+pending,erros=sorted(errors))

    def close(self):
        if self.face and callable(getattr(self.face,'close',None)):self.face.close()
        self.face=None


def install(main,monitor):
    """Hooks locais sobre pontos de extensão existentes; não edita os arquivos da base."""
    import epi_monitoramento as epi
    import epi_inferencia as inference
    import performance_runtime as runtime
    ctrl=Controller(monitor);monitor.crowd=ctrl
    if not getattr(main,'_vigia3_crowd_installed',False):
        original_detector=runtime.DetectorTimed.__call__
        def detector(self,*args,**kwargs):
            result=original_detector(self,*args,**kwargs);c=getattr(_local,'controller',None)
            if c and self.name=='yolo_pessoas_ms':
                boxes=[]
                for r in result:boxes.extend(runtime.person_boxes(r))
                c.begin(boxes)
            return result
        runtime.DetectorTimed.__call__=detector
        original_region=epi.regiao_verificavel
        def region(item,box,points,shape):
            if item=='capacete' and '_head_v3' in points:
                if item in points.get('_epi_local_necessarios',()) and item not in points.get('_epi_local_avaliados',()):return False
                return points['_head_v3']['verifiable']
            return original_region(item,box,points,shape)
        epi.regiao_verificavel=region
        original_association=epi.associar_epis
        def associate(persons,detections,ausencia=False):
            identify=epi.identificar_ausencia if ausencia else epi.identificar_epi
            helmets=[d for d in detections if identify(d['classe'])=='capacete']
            result,ambiguous=original_association(persons,[d for d in detections if identify(d['classe'])!='capacete'],ausencia)
            for d in helmets:
                confidence=d.get('confianca',1)
                if not isinstance(confidence,(int,float)) or not math.isfinite(confidence):continue
                minimum=.25 if d.get('local') and not ausencia else .5
                x1,y1,x2,y2=d['caixa'];cx,cy=(x1+x2)/2,(y1+y2)/2;candidates=[]
                for person in persons:
                    b=person['caixa'];bw,bh=b[2]-b[0],b[3]-b[1]
                    head=person.get('pontos',{}).get('_head_v3',{}).get('box',(b[0]-.05*bw,b[1]-.1*bh,b[2]+.05*bw,b[1]+.32*bh))
                    if head[0]<=cx<=head[2] and head[1]<=cy<=head[3] and x2-x1<=bw*1.3:
                        score=math.hypot((cx-(head[0]+head[2])/2)/max(1,head[2]-head[0]),(cy-(head[1]+head[3])/2)/max(1,head[3]-head[1]))
                        candidates.append((score,person['id']))
                candidates.sort()
                if not candidates:continue
                if confidence<minimum:
                    for _,pid in candidates:ambiguous[pid].add('capacete')
                elif len(candidates)>1 and candidates[1][0]-candidates[0][0]<.2:
                    for _,pid in candidates[:2]:ambiguous[pid].add('capacete')
                else:result[candidates[0][1]].add('capacete')
            return result,ambiguous
        epi.associar_epis=inference.associar_epis=associate
        original_tracking=epi.RastreadorPessoas.atualizar
        def tracking(self,boxes,now):
            ids=original_tracking(self,boxes,now);c=getattr(_local,'controller',None)
            if c:
                c.actual_ids=ids;c.pending_ids={ids[i] for i in c.pending_indices if i<len(ids) and i<len(c.points)
                    and i not in c.ambiguous_indices and c.points[i].get('_head_v3',{}).get('verifiable') and not self.pessoas[ids[i]].ambiguo}
            return ids
        epi.RastreadorPessoas.atualizar=tracking
        original_observe=epi.ConfirmadorAlertas.observar
        def observe(self,key,signal,now,duration):
            c=getattr(_local,'controller',None)
            if c and not signal and key[1:]==('epi','capacete') and key[0] in c.pending_ids:
                previous=self.observacoes.get(key)
                if previous and 0<=now-previous.ultima<=2.0:return False  # Não incrementa, confirma ou gera alerta em quadro pendente.
            return original_observe(self,key,signal,now,duration)
        epi.ConfirmadorAlertas.observar=observe
        original_reanalysis=main.reanalisar_epi_por_pessoa
        def reanalysis(model,frame,boxes,points,required,detections,**kwargs):
            c=getattr(_local,'controller',None)
            if c:return c.reanalyze(original_reanalysis,model,frame,boxes,points,required,detections,**kwargs)
            return original_reanalysis(model,frame,boxes,points,required,detections,**kwargs)
        main.reanalisar_epi_por_pessoa=reanalysis
        main._vigia3_crowd_installed=True
    execute=monitor.executar;process=monitor.processar_deteccoes
    def process_detections(frame,boxes,points,detections,now=None,**kwargs):
        ctrl.points=points
        # Falta de pose atual fica explicitamente inconclusiva. O motor original interrompe
        # a trajetória quando não há pontos: não interpreta a espera como imobilidade.
        people,alerts=process(frame,boxes,points,detections,now,**kwargs)
        for index,person in enumerate(people):
            info=points[index].get('_head_v3',{}) if index<len(points) else {}
            person.update(cabeca_motivo=info.get('reason','Não houve reanálise de cabeça nesta rodada.'),
                cabeca_visivel=info.get('verifiable',False),pose_pendente=index in ctrl.pose_skipped)
            if person['pose_pendente']:person['postura_motivo']='Pose aguardando processamento; sem evidência temporal suficiente nesta rodada.'
        counts=dict(pessoas=len(people),com_capacete=sum(p.get('epis',{}).get('capacete')=='presente' for p in people),
            possivel_ausencia=sum(p.get('epis',{}).get('capacete')=='possivel_ausencia' for p in people),
            inconclusivas=sum(p.get('epis',{}).get('capacete') not in ('presente','possivel_ausencia') for p in people),
            possiveis_quedas=sum(bool(p.get('emergencia')) for p in people),**ctrl.stats)
        with monitor.lock:monitor.status['coletivo']=counts
        return people,alerts
    def executing():
        _local.controller=ctrl
        try:
            try:
                import mediapipe as mp
                original_pose=mp.solutions.pose.Pose
                class Pose:
                    def __init__(self,*a,**kw):self.obj=original_pose(*a,**kw)
                    def __enter__(self):self.obj.__enter__();return self
                    def __exit__(self,*a):return self.obj.__exit__(*a)
                    def process(self,rgb):
                        index=ctrl.pose_index;ctrl.pose_index+=1
                        if index not in ctrl.pose_selected:
                            ctrl.pose_skipped.add(index);return SimpleNamespace(pose_landmarks=None)
                        return self.obj.process(rgb)
                mp.solutions.pose.Pose=Pose
            except ImportError:mp=None;original_pose=None
            return execute()
        finally:
            if mp is not None and original_pose is not None:mp.solutions.pose.Pose=original_pose
            ctrl.close();_local.controller=None
    monitor.processar_deteccoes=process_detections;monitor.executar=executing
    return ctrl
