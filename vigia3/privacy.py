"""Execução local: desativa telemetria e integrações de envio automático do Ultralytics."""
import os


def local_only():
    os.environ['YOLO_OFFLINE']='true'
    os.environ['YOLO_AUTOINSTALL']='false'
    import ultralytics
    if not getattr(ultralytics,'__version__',None):return  # Apenas doubles explícitos de testes.
    from ultralytics import settings
    from ultralytics.utils import callbacks
    disabled={k:False for k in ('sync','hub','wandb','mlflow','clearml','neptune','comet','dvc','raytune','tensorboard') if k in settings}
    if disabled:settings.update(disabled)
    # A API de callbacks é reutilizada somente para progresso/cancelamento locais.
    # Evita ativações automáticas de SDKs de plataforma que possam estar instalados.
    callbacks.add_integration_callbacks=lambda instance:None
