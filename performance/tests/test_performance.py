import json
import os
import tempfile
import time
import unittest
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from performance_preserve import inventory, copy_verified, verify, sha256
from performance_runtime import Timings, DetectorTimed, person_boxes, profile
from performance_benchmark import summary
from performance_benchmark import run
from main import Monitor, criar_app


class TestPreservation(unittest.TestCase):
    def test_backup_all_private_and_model_files_and_restore_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source';source.mkdir()
            for name in ('best.pt','last.pt','.env','dataset/labels/a.txt','capturas/a.jpg','config_epi.json'):
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            manifest=inventory(source)
            self.assertEqual(len(manifest['files']),6)
            backup=copy_verified(source,root/'backup',manifest)
            self.assertFalse(verify(backup,manifest))
            restored=copy_verified(backup,root/'restore',manifest)
            self.assertFalse(verify(restored,manifest))
            with self.assertRaises(ValueError):copy_verified(source,backup,manifest)
            with self.assertRaises(ValueError):copy_verified(source,source/'inside',manifest)
            self.assertFalse(verify(source,manifest))

    def test_tampering_and_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'best.pt').write_bytes(b'weights')
            manifest=inventory(root);(root/'best.pt').write_bytes(b'changed')
            self.assertEqual(verify(root,manifest),['best.pt'])
            self.assertEqual(verify(root,{'files':[dict(path='../escape',sha256='0')]}),['../escape'])

    def test_origin_models_are_byte_identical(self):
        base=Path(__file__).resolve().parents[1]
        for item in json.loads((base/'performance/models-origin.json').read_text(encoding='utf-8-sig')):
            self.assertEqual(sha256(base/item['path']),item['sha256'])


class TestRuntime(unittest.TestCase):
    def test_benchmark_harness_real_video_with_explicit_model_fixtures(self):
        from test_central import video_teste,PoseTeste,FaceTeste,ModeloTeste
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);video_teste(root,quadros=4)
            mp=SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **_:PoseTeste()),
                face_detection=SimpleNamespace(FaceDetection=lambda **_:FaceTeste())))
            args=SimpleNamespace(root=Path(__file__).resolve().parents[1],video=root/'teste.avi',output=root/'results',
                device='cpu',profile='qualidade',epis=['capacete','oculos'],absence='observacao',warmup=1)
            with patch.dict('sys.modules',{'mediapipe':mp,'ultralytics':SimpleNamespace(YOLO=ModeloTeste)}),\
                    patch('runtime_ia.opcoes_inferencia',return_value={'device':'cpu'}),\
                    patch('performance_benchmark.Resources.run'),contextlib.redirect_stdout(io.StringIO()):
                run(args)
            data=json.loads((args.output/'result.json').read_text())
            self.assertEqual(data['cold_summary']['frames'],4)
            self.assertEqual(data['summary']['frames'],3)
            self.assertIsNone(data['fps_exibido'])
            self.assertEqual(len((args.output/'readings.jsonl').read_text().splitlines()),4)

    def test_bulk_cpu_transfer_preserves_boxes(self):
        data=SimpleNamespace(xyxy=np.array([[1.,2.,3.,4.]]))
        boxes=SimpleNamespace(cpu=Mock(return_value=data))
        timings=Timings();result=SimpleNamespace(boxes=boxes)
        detector=DetectorTimed(lambda *_a,**_kw:[result],timings,'yolo_pessoas_ms')
        self.assertEqual(person_boxes(detector(None)[0]),[[1.,2.,3.,4.]])
        boxes.cpu.assert_called_once()
        self.assertGreaterEqual(timings.stages['yolo_pessoas_ms'],0)

    def test_profiles_preserve_epi_and_gate_reduced_resolution(self):
        with patch.dict(os.environ,{'VIGIAAI_PERFIL':'equilibrado'},clear=True):
            self.assertEqual(profile()[1]['epi'],640)
            self.assertEqual(profile()[1]['pessoas'],640)
        with patch.dict(os.environ,{'VIGIAAI_PERFIL':'desempenho'},clear=True):
            with self.assertRaises(ValueError):profile()

    def test_explicit_cuda_and_fp16_fail_closed(self):
        from runtime_ia import opcoes_inferencia
        torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False))
        with patch.dict('sys.modules',{'torch':torch}),patch.dict(os.environ,{'VIGIAAI_DEVICE':'0'},clear=True):
            with self.assertRaises(RuntimeError):opcoes_inferencia()
        with patch.dict('sys.modules',{'torch':torch}),patch.dict(os.environ,{'VIGIAAI_DEVICE':'cpu','VIGIAAI_FP16':'1'},clear=True):
            with self.assertRaises(ValueError):opcoes_inferencia()

    def test_fps_is_total_time_not_average_instantaneous_fps(self):
        s=summary([dict(total_ms=100),dict(total_ms=300)])
        self.assertEqual(s['fps_processamento'],5)

    def test_display_api_distinguishes_unknown_from_measured(self):
        with tempfile.TemporaryDirectory() as temp:
            m=Monitor(base=temp); c=criar_app(m).test_client()
            self.assertIsNone(c.get('/api/performance').json['fps_exibido'])
            self.assertEqual(c.post('/api/performance/display',json={}).status_code,403)
            h={'X-VigiaAI':'1'}
            self.assertEqual(c.post('/api/performance/display',json={'frame':1,'fps':False},headers=h).status_code,400)
            m.frame_history[1]=time.monotonic()-.1
            self.assertEqual(c.post('/api/performance/display',json={'frame':1,'fps':12},headers=h).status_code,200)
            self.assertEqual(c.get('/api/performance').json['fps_exibido'],12)
            self.assertGreaterEqual(c.get('/api/performance').json['latencia_captura_ack_ms'],100)
