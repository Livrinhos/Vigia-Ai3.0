"""Sem câmera, treinamento ou inferência real: regressões do fluxo em lote."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_bank import picture, annotation, BASE
from vigia3.store import Store, file_hash
from vigia3.models import Models
from vigia3.suggestions import batch_request, run_batch


class BatchSuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'data')
        self.sid = self.store.session('Sessão', 'gravação-1', True)
        weight = self.store.root/'modelos'/'fixture.pt'
        weight.write_bytes(b'explicit synthetic test fixture; not a usable model')
        self.model = dict(id='fixture', kind='epi', path=str(weight), sha256=file_hash(weight))
        self.models = SimpleNamespace(get=lambda mid: self.model)
        self.ids = [self.store.import_image(self.sid, f'f{i}.png', picture(i))['id'] for i in range(3)]

    def req(self, ids=None):
        return batch_request(self.store, self.models, dict(ids=ids or self.ids, model='fixture', device='cpu'))

    def run_batch(self, req=None, predict=None, cancel=lambda:False, jid='test-job'):
        with patch('vigia3.suggestions.predict_boxes', predict or Mock(return_value=annotation()['boxes'])):
            return run_batch(self.store, self.model, req or self.req(), jid, object(), lambda **p:None, cancel)

    def test_persist_suggestions_without_modifying_human_annotations_or_sources(self):
        before = [self.store.image(i) for i in self.ids]
        r = self.run_batch()
        self.assertEqual(r['suggested'], 3)
        reopened = Store(self.store.root)
        for previous in before:
            image = reopened.image(previous['id'])
            self.assertEqual(image['annotation'], previous['annotation'])
            self.assertEqual((image['revision'], image['state']), (0, 'pending'))
            self.assertEqual(file_hash(self.store.root/image['relative_path']), previous['sha256'])
            self.assertEqual(reopened.suggestion(image['id'])['boxes'][0]['label'], 'capacete')
        self.assertEqual(file_hash(self.model['path']), self.model['sha256'])
        self.assertEqual(reopened.list_images()['ready'], 0)

    def test_manual_reviewed_and_stale_images_are_not_overwritten(self):
        req = self.req()
        self.store.review(self.ids[0], dict(state='approved', annotation=annotation(), human_reviewed=True, issues_acknowledged=True), 0)
        self.store.review(self.ids[1], dict(state='pending', annotation=annotation()), 0)
        r = self.run_batch(req)
        self.assertEqual((r['skipped'], r['suggested']), (2, 1))
        self.assertIsNone(self.store.suggestion(self.ids[0]))
        self.assertEqual(self.store.image(self.ids[0])['state'], 'approved')

    def test_edit_during_inference_discards_stale_suggestion(self):
        def predict(detector, image, path, device):
            self.store.review(image['id'], dict(state='pending', annotation=annotation()), 0)
            return annotation()['boxes']
        r = self.run_batch(predict=predict)
        self.assertEqual((r['skipped'], r['suggested']), (3, 0))
        self.assertTrue(all(self.store.suggestion(i) is None for i in self.ids))

    def test_empty_inference_never_confirms_negative_and_human_save_expires_suggestion(self):
        self.run_batch(predict=Mock(return_value=[]))
        image = self.store.image(self.ids[0])
        self.assertFalse(image['annotation']['negative'])
        self.assertEqual(self.store.suggestion(self.ids[0])['boxes'], [])
        with self.assertRaises(ValueError):
            self.store.review(self.ids[0], dict(state='approved', annotation=image['annotation'], human_reviewed=True, issues_acknowledged=True), 0)
        self.store.review(self.ids[0], dict(state='approved', annotation=annotation(), human_reviewed=True, issues_acknowledged=True), 0)
        self.assertIsNone(self.store.suggestion(self.ids[0]))

    def test_cancel_keeps_completed_suggestions(self):
        stopped = False
        def cancel():return stopped
        def progress(**data):
            nonlocal stopped
            stopped = data['done'] == 1
        with patch('vigia3.suggestions.predict_boxes', return_value=annotation()['boxes']):
            with self.assertRaises(InterruptedError):
                run_batch(self.store, self.model, self.req(), 'cancel-test', object(), progress, cancel)
        self.assertIsNotNone(self.store.suggestion(self.ids[0]))
        self.assertIsNone(self.store.suggestion(self.ids[1]))

    def test_filter_selects_all_pages_and_rejects_invalid_or_duplicate_ids(self):
        for i in range(3,65):self.store.import_image(self.sid, f'f{i}.png', picture(i))
        self.assertEqual(len(self.store.list_images()['items']), 60)
        self.assertEqual(len(self.store.image_ids(session=self.sid)), 65)
        self.assertEqual(len(self.store.image_ids(q='f64.png')), 1)
        for ids in ([], [self.ids[0]]*2, [None], ['missing'], self.ids*2000):
            with self.assertRaises(ValueError):batch_request(self.store, self.models, dict(ids=ids, model='fixture'))
        with self.assertRaises(ValueError):self.store.image_ids(state='invented')

    def test_route_creates_one_job_and_rejects_cross_site_or_monitor_conflict(self):
        from iniciar3 import create
        app = create(BASE, self.store.root)
        client = app.test_client()
        models = app.extensions['vigia3_models']
        # Registra fixture explicitamente; o teste não carrega o peso como modelo.
        mid = models.register(self.model['path'], 'epi', 'candidate', 'fixture')
        jobs = app.extensions['vigia3_jobs']
        headers = {'X-VigiaAI':'1'}
        d = dict(ids=self.ids, model=mid, device='cpu')
        with patch.object(jobs, 'start', return_value='test-job') as start:
            response = client.post('/api/banco/images/suggest-batch', json=d, headers=headers)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(start.call_args.args[0], 'suggest_batch')
            self.assertEqual(len(start.call_args.args[1]['images']), 3)
        self.assertEqual(client.post('/api/banco/images/suggest-batch', json=d).status_code, 403)
        self.assertEqual(client.post('/api/banco/images/suggest-batch', json=d, headers={**headers,'Origin':'https://other.example'}).status_code, 403)
        self.assertEqual(client.post('/api/banco/images/suggest-batch', json={**d,'ids':[]}, headers=headers).status_code, 400)
        self.assertEqual(len(client.get('/api/banco/images/selection?state=pending').json['ids']), 3)
        jobs.monitor.thread = SimpleNamespace(is_alive=lambda:True)
        response = client.post('/api/banco/images/suggest-batch', json=d, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('monitoramento', response.json['error'])

    def test_model_loading_reused_and_errors_reported_per_image(self):
        # O mesmo detector é entregue a todas as imagens; erro individual não oculta o restante.
        detector = object()
        calls = []
        def predict(value, image, path, device):
            calls.append(value)
            if image['id'] == self.ids[1]:raise ValueError('fixture invalid image')
            return annotation()['boxes']
        with patch('vigia3.suggestions.predict_boxes', side_effect=predict):
            r = run_batch(self.store, self.model, self.req(), 'errors', detector, lambda **p:None, lambda:False)
        self.assertEqual((r['suggested'], r['failed'], r['done']), (2, 1, 3))
        self.assertTrue(all(value is detector for value in calls))
        self.assertEqual(r['errors'][0]['image'], self.ids[1])
