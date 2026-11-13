"""Inicializa o VigiaAI 3.0 usando a base Performance existente, sem reescrevê-la."""
import argparse
import json
import os
import sys
from pathlib import Path


def default_base():
    if os.getenv('VIGIAAI_PERFORMANCE_BASE'):return Path(os.environ['VIGIAAI_PERFORMANCE_BASE']).resolve()
    root=Path(__file__).resolve().parent
    return root/'performance' if (root/'performance/main.py').is_file() else root/'.performance-base'


def create(base=None,data_root=None):
    base=Path(base or default_base()).resolve()
    if not (base/'performance/ISOLATED_COPY').is_file():raise ValueError('Integre uma cópia Performance separada. Nunca aponte para a instalação original da apresentação.')
    from vigia3.store import Store
    storage=Store(data_root)
    os.environ.update(VIGIAAI_TESTE='1',NOTIFICACOES_ATIVAS='0',SALVAR_IMAGEM_OCORRENCIA='0',YOLO_AUTOINSTALL='false',
        YOLO_CONFIG_DIR=str(storage.root/'trabalhos/ultralytics'),VIGIAAI_MEDIA_DIR=str(storage.root/'monitoramento/media'))
    sys.path.insert(0,str(base))
    import main
    monitor_root=storage.root/'monitoramento';monitor_root.mkdir(exist_ok=True)
    monitor=main.Monitor(base=monitor_root)
    app=main.criar_app(monitor)
    from vigia3.web import register
    store,models,jobs=register(app,monitor,base,storage.root)
    from vigia3.crowd import install
    install(main,monitor)
    active=store.root/'modelo-ativo.json'
    if active.is_file():
        try:models.select(json.loads(active.read_text())['id'],monitor,'SELECIONAR')
        except (ValueError,KeyError,OSError) as e:monitor.status['modelo_selecao_erro']=str(e)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path);parser.add_argument('--data',type=Path);parser.add_argument('--port',type=int,default=5013)
    a=parser.parse_args()
    if not 1024<=a.port<=65535 or a.port==5001:raise ValueError('Use uma porta separada, como 5013.')
    from vigia3.store import Store
    from vigia3.lease import DataLease
    root=Store(a.data).root
    with DataLease(root/'servidor.lock'):
        app=create(a.base,root)
        print(f'VigiaAI 3.0 em http://127.0.0.1:{a.port} · Banco de Imagens: /banco · SMTP desativado',flush=True)
        app.run(host='127.0.0.1',port=a.port,debug=False,threaded=True,load_dotenv=False)
