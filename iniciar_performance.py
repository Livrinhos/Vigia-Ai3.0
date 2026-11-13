"""Versão Performance preservada, usando o mesmo ambiente instalado do VigiaAI 3.0."""
import argparse
import os
import sys
from pathlib import Path


def create(base=None,data_root=None):
    from iniciar3 import default_base
    from vigia3.store import Store
    from vigia3.privacy import local_only
    base=Path(base or default_base()).resolve()
    store=Store(data_root);folder=store.root/'performance-monitor';folder.mkdir(exist_ok=True)
    config=store.root/'trabalhos/ultralytics';config.mkdir(parents=True,exist_ok=True)
    os.environ.update(VIGIAAI_TESTE='1',NOTIFICACOES_ATIVAS='0',SALVAR_IMAGEM_OCORRENCIA='0',YOLO_AUTOINSTALL='false',
        YOLO_CONFIG_DIR=str(config),VIGIAAI_MEDIA_DIR=str(folder/'media'),VIGIAAI_FP16='0')
    local_only()
    sys.path.insert(0,str(base))
    import main
    monitor=main.Monitor(base=folder)
    # Não instala os hooks de multidão ou treinamento; esta é a versão Performance preservada.
    return main.criar_app(monitor)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=5011);p.add_argument('--data',type=Path)
    args=p.parse_args()
    if not 1024<=args.port<=65535 or args.port==5001:raise ValueError('Use uma porta separada, como 5011.')
    from vigia3.store import Store
    from vigia3.lease import DataLease
    root=Store(args.data).root
    with DataLease(root/'servidor.lock'):
        app=create(data_root=root)
        print(f'VigiaAI Performance: http://127.0.0.1:{args.port} · para usar o 3.0, encerre esta versão primeiro.',flush=True)
        app.run(host='127.0.0.1',port=args.port,debug=False,threaded=True,load_dotenv=False)
