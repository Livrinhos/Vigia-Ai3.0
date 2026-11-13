import tempfile
import time
import sys
import threading
import unittest
from pathlib import Path
from vigia3.store import Store
from vigia3.jobs import Jobs


class TestJobs(unittest.TestCase):
    def test_data_lease_blocks_second_server_and_releases(self):
        from vigia3.lease import DataLease
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'server.lock'
            with DataLease(path):
                with self.assertRaises(RuntimeError):
                    with DataLease(path):pass
            with DataLease(path):pass
    def test_separate_process_mutual_exclusion_and_cooperative_cancel(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);jobs=Jobs(store,Path(__file__).parents[1]/'.performance-base',command=[sys.executable,'-u',str(Path(__file__).parent/'fixture_worker.py')])
            jid=jobs.start('train',{})
            try:
                with self.assertRaises(ValueError):jobs.start('suggest',{})
                deadline=time.monotonic()+10
                while time.monotonic()<deadline and jobs.get(jid)['state']=='queued':time.sleep(.05)
                jobs.cancel(jid)
                while time.monotonic()<deadline and jobs.active():time.sleep(.05)
                self.assertFalse(jobs.active());self.assertEqual(jobs.get(jid)['state'],'cancelled')
                self.assertTrue((store.root/'trabalhos'/jid/'request.json').is_file())
                with self.assertRaises(ValueError):jobs.cancel('nao-e-nosso-processo')
            finally:
                if jobs.active():jobs.cancel(jid);jobs.processes[jid].wait(timeout=5)
