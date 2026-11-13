"""Somente fixture de ciclo de processo/cancelamento; não é treinamento nem gera pesos."""
import json
import sys
import time
from pathlib import Path
from vigia3.store import Store

payload=json.loads(Path(sys.argv[1]).read_text());store=Store(payload['data_root']);folder=store.root/'trabalhos'/payload['id']
with store.db() as db:db.execute("UPDATE jobs SET state='running' WHERE id=?",(payload['id'],))
for i in range(100):
    if (folder/'cancel.request').exists():
        with store.db() as db:db.execute("UPDATE jobs SET state='cancelled' WHERE id=?",(payload['id'],))
        print('Cancelamento cooperativo da fixture; nenhum modelo treinado.',flush=True);break
    print('fixture step',i,flush=True);time.sleep(.05)
else:
    with store.db() as db:db.execute("UPDATE jobs SET state='succeeded',result='{}' WHERE id=?",(payload['id'],))
