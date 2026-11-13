import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import preparar_instalacao as setup
from iniciar3 import default_base


class InstallationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);base=self.root/'performance';base.mkdir()
        for rel in ('main.py','epi_inferencia.py','epi_monitoramento.py','queda_temporal.py','runtime_ia.py',
                    'performance_runtime.py','presentation_mode.py','requirements.txt','requirements-cpu.txt','requirements-cuda.txt'):
            (base/rel).write_text('fixture',encoding='utf-8')
        self.content=b'fixture model bytes, not a trained model'
        self.models=[dict(path='weights/test.pt',bytes=len(self.content),sha256=hashlib.sha256(self.content).hexdigest())]
    def tearDown(self):self.temp.cleanup()

    def test_automatic_download_without_any_archive_picker(self):
        requests=[]
        def opener(req,timeout):requests.append(req.full_url);return contextlib.closing(io.BytesIO(self.content))
        with patch.object(setup,'MODELS',self.models):r=setup.prepare(self.root,opener=opener)
        self.assertEqual(r['versions'],['Performance','3.0']);self.assertEqual(len(requests),1)
        self.assertEqual((self.root/'performance/weights/test.pt').read_bytes(),self.content)
        self.assertTrue((self.root/'performance/performance/ISOLATED_COPY').is_file())

    def test_existing_models_not_downloaded_or_changed(self):
        target=self.root/'performance/weights/test.pt';target.parent.mkdir();target.write_bytes(self.content)
        with patch.object(setup,'MODELS',self.models):
            result=setup.prepare(self.root,opener=lambda *_a,**_kw:self.fail('Não deveria baixar'))
        self.assertEqual(result['models'][0]['status'],'existing');self.assertEqual(target.read_bytes(),self.content)

    def test_different_trained_weight_is_never_overwritten(self):
        target=self.root/'performance/weights/test.pt';target.parent.mkdir();target.write_bytes(b'local training')
        with patch.object(setup,'MODELS',self.models):
            with self.assertRaises(ValueError):setup.prepare(self.root)
        self.assertEqual(target.read_bytes(),b'local training')

    def test_network_or_hash_failure_does_not_install_bad_model(self):
        with patch.object(setup,'MODELS',self.models):
            with self.assertRaises(RuntimeError):setup.prepare(self.root,opener=lambda *_a,**_kw:contextlib.closing(io.BytesIO(b'wrong bytes')))
        self.assertFalse((self.root/'performance/weights/test.pt').exists())

    def test_legacy_base_is_copied_read_only(self):
        legacy=self.root/'.performance-base/weights/test.pt';legacy.parent.mkdir(parents=True);legacy.write_bytes(self.content)
        with patch.object(setup,'MODELS',self.models):result=setup.prepare(self.root,download=False)
        self.assertEqual(result['models'][0]['status'],'copied');self.assertEqual(legacy.read_bytes(),self.content)

    def test_repository_contains_both_complete_entry_points(self):
        root=Path(__file__).resolve().parents[1]
        self.assertTrue((root/'performance/main.py').is_file())
        self.assertTrue((root/'iniciar3.py').is_file());self.assertTrue((root/'iniciar_performance.py').is_file())
        installer=(root/'Instalar-VigiaAI3.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('OpenFileDialog',installer)
        self.assertIn('preparar_instalacao.py',installer)
        self.assertEqual(default_base(),root/'performance')

    def test_all_three_real_original_models_preserved(self):
        root=Path(__file__).resolve().parents[1]
        result=setup.prepare(root,download=False)
        self.assertEqual(len(result['models']),3)

    def test_launcher_performance_is_separate_from_bank_version(self):
        # App factory, no webcam, no server and no notification.
        from iniciar_performance import create
        app=create(data_root=self.root/'data')
        self.assertNotIn('vigia3_store',app.extensions)
        self.assertFalse(hasattr(app.extensions['monitor'],'crowd'))
        with app.test_client() as client:self.assertEqual(client.get('/').status_code,200)
