"""Iniciador isolado: sem SMTP ou capturas automáticas, porta própria."""
import argparse
import os
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=5011)
    p.add_argument('--profile',choices=['qualidade','equilibrado','desempenho'],default='qualidade')
    p.add_argument('--device',choices=['auto','cpu','0'],default='auto')
    a=p.parse_args()
    if not 1024<=a.port<=65535 or a.port==5001:
        raise ValueError('Escolha outra porta, entre 1024 e 65535; padrão separado: 5011.')
    base=Path(__file__).resolve().parent
    os.chdir(base)
    for name in ('yolov8n.pt','epi.pt','runs/detect/treinamento_epi-2/weights/best.pt'):
        if not (base/name).is_file(): raise FileNotFoundError('Peso preservado ausente: '+name)
    for key in ('EPI_MODEL_PATH','OCULOS_MODEL_PATH'):
        if os.getenv(key) and not (base/os.environ[key]).resolve().is_relative_to(base):
            raise ValueError(key+' precisa apontar para uma cópia dentro desta instalação.')
    os.environ.update(VIGIAAI_TESTE='1',NOTIFICACOES_ATIVAS='0',SALVAR_IMAGEM_OCORRENCIA='0',
        VIGIAAI_PERFIL=a.profile,VIGIAAI_DEVICE=a.device,VIGIAAI_FP16='0',
        YOLO_AUTOINSTALL='false',YOLO_CONFIG_DIR=str(base/'diagnosticos/ultralytics'),
        VIGIAAI_MEDIA_DIR=str(base/'media_privada'))
    from main import app
    monitor=app.extensions['monitor']
    for weight in (monitor.modelo_epi,monitor.modelo_oculos):
        if weight and not weight.resolve().is_relative_to(base):
            raise ValueError('Copie os modelos para a instalação separada antes de apontar a configuração.')
    print(f'VigiaAI Performance: http://127.0.0.1:{a.port} · notificações externas desativadas')
    app.run(host='127.0.0.1',port=a.port,debug=False,threaded=True,load_dotenv=False)


if __name__=='__main__': main()
