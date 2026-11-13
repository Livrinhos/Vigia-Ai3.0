import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace

from main import Monitor, criar_app
from presentation_mode import request_mode, apply_pending, posture_detail


class TestPresentation(unittest.TestCase):
    def test_real_pipeline_suspends_auxiliary_and_face_then_restores(self):
        from test_central import video_teste, PoseTeste, FaceTeste, ModeloTeste
        with tempfile.TemporaryDirectory() as temp:
            video_teste(temp,quadros=3)
            m=Monitor(base=temp,fonte_video=Path(temp)/'teste.avi')
            m.epi_obrigatorio=['capacete','oculos']
            face=Mock(wraps=FaceTeste())
            mp=SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **_:PoseTeste()),face_detection=SimpleNamespace(FaceDetection=lambda **_:face)))
            request_mode(m,True);ModeloTeste.chamadas=[]
            with patch.dict('sys.modules',{'mediapipe':mp,'ultralytics':SimpleNamespace(YOLO=ModeloTeste)}),patch('runtime_ia.opcoes_inferencia',return_value={'device':'cpu'}):
                # FaceTeste é um context manager real; Mock não implementa métodos especiais.
                with patch.object(mp.solutions.face_detection,'FaceDetection',return_value=FaceTeste()):
                    m.executar()
                    self.assertEqual(m.status['estado'],'parado',m.status['mensagem'])
                    self.assertFalse(any(name=='best.pt' for name,_ in ModeloTeste.chamadas))
                    self.assertTrue(all(opts['classes']==[0] for name,opts in ModeloTeste.chamadas if name=='epi.pt'))
                    self.assertEqual(list(m.status['deteccoes'][0]['epis']),['capacete'])
                    self.assertIn('postura_apresentacao',m.status['deteccoes'][0])
                    request_mode(m,False);ModeloTeste.chamadas=[]
                    m.executar()
                    self.assertTrue(any(name=='best.pt' for name,_ in ModeloTeste.chamadas))
                    self.assertEqual(m.epi_obrigatorio,['capacete','oculos'])

    def test_toggle_restores_exact_policy_and_preserves_disk_and_temporal(self):
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'config_epi.json'
            config.write_text(json.dumps(dict(obrigatorios=['oculos','luvas'],modo_ausencia='explicita',confirmacao_segundos=7,extra='preservar')))
            before=config.read_bytes();m=Monitor(base=temp)
            temporal=object();m.motor.temporais[1]=temporal
            request_mode(m,True)
            self.assertEqual(m.epi_obrigatorio,['capacete'])
            self.assertTrue(m.presentation_active)
            self.assertEqual(m.motor.modo_ausencia,'explicita')
            self.assertEqual(m.confirmacao_epi,7)
            with self.assertRaises(ValueError):m.configurar_epi(['colete'])
            request_mode(m,True)  # Idempotência não perde a política normal.
            request_mode(m,False)
            self.assertEqual(m.epi_obrigatorio,['oculos','luvas'])
            self.assertEqual(config.read_bytes(),before)
            self.assertIs(m.motor.temporais[1],temporal)

    def test_running_switch_waits_for_frame_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            m=Monitor(base=temp);m.epi_obrigatorio=['oculos'];m.thread=Mock()
            m.thread.is_alive.return_value=True
            m.motor.confirmador.observacoes[(1,'epi','capacete')]='old'
            request_mode(m,True)
            self.assertFalse(m.presentation_active)
            self.assertEqual(m.epi_obrigatorio,['oculos'])
            apply_pending(m)
            self.assertTrue(m.presentation_active)
            self.assertFalse(m.motor.confirmador.observacoes)

    def test_api_validation_and_return_to_normal(self):
        with tempfile.TemporaryDirectory() as temp:
            m=Monitor(base=temp);c=criar_app(m).test_client();h={'X-VigiaAI':'1'}
            self.assertEqual(c.post('/api/performance/apresentacao',json={'ativo':True}).status_code,403)
            for invalid in ('1',1,None):
                self.assertEqual(c.post('/api/performance/apresentacao',json={'ativo':invalid},headers=h).status_code,400)
            self.assertEqual(c.post('/api/performance/apresentacao',json={'ativo':True},headers=h).status_code,200)
            self.assertTrue(c.get('/api/performance').json['modo_apresentacao'])
            c.post('/api/performance/apresentacao',json={'ativo':False},headers=h)
            self.assertFalse(m.presentation_active)

    def test_posture_detail_is_conservative_without_visible_legs(self):
        self.assertIn('inconclusivas',posture_detail({},(0,0,200,400),'Em pe'))
        self.assertEqual(posture_detail({},(0,0,200,400),'Deitada'),'Deitada')
        self.assertEqual(posture_detail({},(0,0,200,400),None),'Postura inconclusiva')

    def test_standing_and_deep_squat_synthetic_geometry(self):
        standing={23:(.4,.3,1),24:(.6,.3,1),25:(.4,.6,1),26:(.6,.6,1),27:(.4,.95,1),28:(.6,.95,1)}
        self.assertEqual(posture_detail(standing,(0,0,200,400),'Em pe'),'Em pé')
        squat={23:(.1,.7,1),24:(.2,.7,1),25:(.9,.5,1),26:(1,.5,1),27:(.9,.95,1),28:(1,.95,1)}
        self.assertEqual(posture_detail(squat,(0,0,200,400),'Em pe'),'Agachada (estimativa)')
