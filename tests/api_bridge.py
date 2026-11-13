"""Ponte de testes JS→Flask, sem servidor exposto, webcam ou modelos fictícios exibidos como reais."""
import base64
import json
import sys
import tempfile
from pathlib import Path
from iniciar3 import create

with tempfile.TemporaryDirectory() as temp:
    app=create(Path(__file__).resolve().parents[1]/'.performance-base',Path(temp)/'data');client=app.test_client()
    for line in sys.stdin:
        message=json.loads(line)
        body=base64.b64decode(message['binary']) if 'binary' in message else message.get('body')
        with client.open(message['url'],method=message.get('method','GET'),data=body,headers=message.get('headers',{})) as response:
            print(json.dumps(dict(id=message['id'],status=response.status_code,headers=dict(response.headers),body=base64.b64encode(response.get_data()).decode())),flush=True)
