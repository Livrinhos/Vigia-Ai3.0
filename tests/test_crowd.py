import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from iniciar3 import create
from vigia3 import crowd
from vigia3.crowd import FairQueue,Controller

BASE=Path(__file__).resolve().parents[1]/'.performance-base'


def scene(n):
    boxes=[(20+i*60,100,70+i*60,420) for i in range(n)]
    frame=np.random.default_rng(77).integers(40,220,(480,60*n+40,3),dtype=np.uint8)
    return frame,boxes


def face_fixture(frame,boxes):
    h,w=frame.shape[:2];faces=[]
    for x1,y1,x2,y2 in boxes:
        bb=SimpleNamespace(xmin=(x1+10)/w,ymin=(y1+20)/h,width=30/w,height=35/h)
        kps=[SimpleNamespace(x=(x1+x)/w,y=(y1+y)/h) for x,y in ((18,31),(32,31),(25,40))]
        faces.append(SimpleNamespace(score=[.95],location_data=SimpleNamespace(relative_bounding_box=bb,relative_keypoints=kps)))
    return SimpleNamespace(process=lambda _:SimpleNamespace(detections=faces),close=lambda:None)


class EmptyDetector:
    names={0:'capacete'}
    def __init__(self):self.calls=0
    def __call__(self,*a,**kw):
        self.calls+=1
        return [SimpleNamespace(names=self.names,boxes=SimpleNamespace(xyxy=np.empty((0,4)),cls=np.array([]),conf=np.array([]))) ]


class CrowdTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create(BASE,Path(self.temp.name)/'data');self.monitor=self.app.extensions['monitor'];self.ctrl=self.monitor.crowd
        self.monitor.epi_obrigatorio=['capacete'];self.monitor.status.update(epi_ativo=True,epis_suportados=['capacete'])
    def tearDown(self):
        self.ctrl.close();crowd._local.controller=None;self.temp.cleanup()

    def test_fair_queue_no_starvation_1_5_10_15_20_25_and_reordering(self):
        for n in (1,5,10,15,20,25):
            q=FairQueue();seen=set();keys=['p'+str(i) for i in range(n)]
            for frame in range(math.ceil(n/4)):
                order=keys[frame:]+keys[:frame]
                seen.update(order[i] for i in q.choose(order,4))
            self.assertEqual(seen,set(keys),n)

    def test_one_helmet_is_never_shared_by_group(self):
        import epi_monitoramento as epi
        for n in (1,5,10,15,20,25):
            frame,boxes=scene(n);points=[{} for _ in boxes];self.ctrl.face=face_fixture(frame,boxes);self.ctrl.head_regions(frame,boxes,points)
            persons=[dict(id=i,caixa=b,pontos=p) for i,(b,p) in enumerate(zip(boxes,points))]
            helmet=dict(classe='capacete',caixa=(27,100,63,120),confianca=.95)
            present,ambiguous=epi.associar_epis(persons,[helmet])
            self.assertEqual([pid for pid,items in present.items() if 'capacete' in items],[0],n)
            self.assertFalse(any('capacete' in v for v in ambiguous.values()))

    def test_missing_helmet_revisits_confirm_only_actual_observations(self):
        frame,boxes=scene(20);detector=EmptyDetector();seen_possible=set()
        helmet=dict(classe='capacete',caixa=(27,100,63,120),confianca=.95)
        import main
        crowd._local.controller=self.ctrl
        for tick in range(50):
            self.ctrl.begin(boxes);self.ctrl.face=face_fixture(frame,boxes);points=[{'_imagem_adequada':True} for _ in boxes]
            new,report=self.ctrl.reanalyze(lambda *a,**k:([],dict(concluidas=0,pendentes=0,erros=[])),detector,frame,boxes,points,['capacete'],[helmet],opcoes_inferencia={'device':'cpu'})
            people,alerts=self.monitor.processar_deteccoes(frame,boxes,points,[helmet]+new,now=tick*.3)
            self.assertEqual(len(people),20)
            self.assertEqual(sum(p['epis']['capacete']=='presente' for p in people),1)
            seen_possible.update(p['id'] for p in people if p['epis']['capacete']=='possivel_ausencia')
            self.assertTrue(all(a['confirmacao']=='verificacao_humana_pendente' for a in alerts))
        self.assertEqual(len(seen_possible),19)
        self.assertGreater(detector.calls,0)

    def test_ambiguous_crossing_and_tiny_heads_stay_inconclusive(self):
        import epi_monitoramento as epi
        boxes=[(100,100,180,400),(102,100,182,400)]
        persons=[dict(id=i,caixa=b,pontos={}) for i,b in enumerate(boxes)]
        present,amb=epi.associar_epis(persons,[dict(classe='capacete',caixa=(120,105,160,130),confianca=.95)])
        self.assertFalse(any(present.values()));self.assertTrue(all('capacete' in a for a in amb.values()))
        frame,boxes=scene(1);points=[{}];self.ctrl.face=SimpleNamespace(process=lambda _:SimpleNamespace(detections=[]),close=lambda:None)
        self.ctrl.head_regions(frame,boxes,points)
        self.assertFalse(epi.regiao_verificavel('capacete',boxes[0],points[0],frame.shape))

    def test_pending_does_not_increment_confirmation_and_expired_samples_reset(self):
        import epi_monitoramento as epi
        c=epi.ConfirmadorAlertas();key=(1,'epi','capacete')
        self.ctrl.pending_ids={1};crowd._local.controller=self.ctrl
        c.observar(key,True,0,3);self.assertEqual(c.observacoes[key].quadros,1)
        self.assertFalse(c.observar(key,False,.5,3));self.assertEqual(c.observacoes[key].quadros,1)
        c.observar(key,False,3.1,3);self.assertNotIn(key,c.observacoes)

    def test_pose_budget_does_not_limit_total_people(self):
        frame,boxes=scene(25);self.ctrl.begin(boxes)
        self.assertEqual(self.ctrl.stats['detectadas'],25)
        self.assertEqual(len(self.ctrl.pose_selected),8)
        self.assertEqual(self.ctrl.stats['poses_pendentes'],17)

    def test_visible_helmet_does_not_require_face_for_positive_presence(self):
        frame,boxes=scene(1);points=[{'_imagem_adequada':True}]
        self.monitor.presentation_active=True
        self.ctrl.face=SimpleNamespace(process=lambda _:SimpleNamespace(detections=[]),close=lambda:None)
        self.ctrl.head_regions(frame,boxes,points)
        self.assertTrue(points[0]['_imagem_adequada'])
        people,_=self.monitor.processar_deteccoes(frame,boxes,points,[dict(classe='capacete',caixa=(27,100,63,120),confianca=.95)],now=0)
        self.assertEqual(people[0]['epis']['capacete'],'presente')
