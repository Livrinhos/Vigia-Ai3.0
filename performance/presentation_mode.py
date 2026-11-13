"""Política temporária da apresentação e estimativas visuais sem mudar alertas de queda."""
import math


def request_mode(monitor, enabled):
    if type(enabled) is not bool:
        raise ValueError('ativo deve ser booleano.')
    with monitor.lock:
        monitor.presentation_pending = enabled
        if not monitor.thread or not monitor.thread.is_alive():
            apply_pending(monitor)


def apply_pending(monitor):
    with monitor.lock:
        enabled = monitor.presentation_pending
        if enabled is None:
            return
        monitor.presentation_pending = None
        if enabled == monitor.presentation_active:
            return
        if enabled:
            monitor.presentation_saved_epis = list(monitor.epi_obrigatorio)
            monitor.epi_obrigatorio = ['capacete']
        else:
            monitor.epi_obrigatorio = list(monitor.presentation_saved_epis)
        monitor.presentation_active = enabled
        # Nada de confirmar uma política nova usando observações da anterior.
        c = monitor.motor.confirmador
        c.observacoes = {k:v for k,v in c.observacoes.items() if k[1]!='epi'}
        c.alertados = {k:v for k,v in c.alertados.items() if k[1]!='epi'}
        c.avisados_continuos = {k for k in c.avisados_continuos if k[1]!='epi'}
        monitor.status.update(modo_apresentacao=enabled,epi_obrigatorio=list(monitor.epi_obrigatorio))


def posture_detail(points, box, base_posture):
    """Exibição experimental: nunca alimenta a decisão temporal de queda.

    Sem pernas visíveis, a verticalidade do tronco não distingue sentar/agachar.
    Valores em pixels evitam distorcer ângulos pela proporção do recorte.
    """
    if base_posture == 'Deitada':
        return 'Deitada'
    if base_posture != 'Em pe':
        return 'Postura inconclusiva'
    w,h=box[2]-box[0],box[3]-box[1]
    if w<=0 or h<=0:return 'Postura inconclusiva'
    def pixel(i):
        p=points.get(i)
        if (not p or len(p)<3 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in p[:3])
                or p[2]<.7 or not all(-.1<=x<=1.1 for x in p[:2])):
            return None
        return p[0]*w,p[1]*h
    votes=[]
    for hip,knee,ankle in ((23,25,27),(24,26,28)):
        a,b,c=map(pixel,(hip,knee,ankle))
        if not all((a,b,c)):continue
        u,v=(a[0]-b[0],a[1]-b[1]),(c[0]-b[0],c[1]-b[1])
        nu,nv=math.hypot(*u),math.hypot(*v)
        if min(nu,nv)<max(12,h*.07):continue
        angle=math.degrees(math.acos(max(-1,min(1,(u[0]*v[0]+u[1]*v[1])/(nu*nv)))))
        if angle>=155 and c[1]>a[1]+h*.25:
            votes.append('Em pé')
        elif 35<=angle<=135 and c[1]>b[1]+h*.08:
            if a[1]>b[1]+nv*.2:
                votes.append('Agachada (estimativa)')
            elif abs(a[1]-b[1])<nu*.15 and abs(a[0]-b[0])>nu*.85 and 75<=angle<=115:
                votes.append('Sentada ou agachada (ambígua)')
            else:votes.append('Sentada/agachada (inconclusiva)')
    if len(votes)==2 and votes[0]==votes[1]:return votes[0]
    return 'Pernas/posição inconclusivas'
