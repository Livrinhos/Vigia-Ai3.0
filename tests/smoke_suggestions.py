"""Inferência real CPU em imagens sintéticas. Não treina nem mede precisão de EPIs."""
import json
import sys
import time
from pathlib import Path
from test_bank import picture, BASE
from vigia3.store import Store, file_hash
from vigia3.models import Models
from vigia3.jobs import Jobs
from vigia3.suggestions import batch_request


def main():
    folder = Path(sys.argv[1]).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    store = Store(folder)
    sid = store.session('Fixture sintética: não representa trabalhadores', 'synthetic-only', True)
    ids = [store.import_image(sid, f'synthetic-{i}.png', picture(i))['id'] for i in range(3)]
    before = {i:store.image(i) for i in ids}
    models = Models(store, BASE)
    original = next(m for m in models.list() if m['kind']=='epi' and m['origin']=='original')
    sha = file_hash(models.get(original['id'])['path'])
    jobs = Jobs(store, BASE)
    jid = jobs.start('suggest_batch', batch_request(store,models,dict(ids=ids,model=original['id'],device='cpu')))
    deadline = time.monotonic()+90
    try:
        while jobs.active() and time.monotonic()<deadline:time.sleep(.2)
        result = jobs.get(jid)
        assert result['state']=='succeeded', json.dumps(result,ensure_ascii=False)
        assert result['result']['suggested']==3
        for iid in ids:
            r = store.image(iid)
            assert (r['annotation'],r['revision'],r['state'])==(before[iid]['annotation'],0,'pending')
            assert file_hash(store.root/r['relative_path'])==before[iid]['sha256']
            assert store.suggestion(iid) is not None
        assert file_hash(models.get(original['id'])['path'])==sha
        print(json.dumps(dict(state=result['state'],suggested=3,original_sha256=sha,
            training_executed=False,accuracy_measured=False,fixture='synthetic'),indent=2))
    finally:
        if jobs.active():jobs.cancel(jid);jobs.processes[jid].wait(timeout=35)


if __name__=='__main__':main()
