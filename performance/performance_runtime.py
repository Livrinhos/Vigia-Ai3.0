"""Instrumentação sem alterar a sequência dos quadros ou a política de alertas."""
import os
import time
from collections import defaultdict, deque
from contextlib import contextmanager


PROFILES = {
    'qualidade': dict(pessoas=640, epi=640, jpeg=85),
    'equilibrado': dict(pessoas=640, epi=640, jpeg=80),
    'desempenho': dict(pessoas=512, epi=640, jpeg=75),
}


def profile():
    name = os.getenv('VIGIAAI_PERFIL', 'qualidade').lower()
    if name not in PROFILES:
        raise ValueError('Perfil deve ser qualidade, equilibrado ou desempenho.')
    if name == 'desempenho' and os.getenv('VIGIAAI_PERMITIR_EXPERIMENTAL') != '1':
        raise ValueError('Desempenho requer validação visual e VIGIAAI_PERMITIR_EXPERIMENTAL=1.')
    config = dict(PROFILES[name])
    if os.getenv('VIGIAAI_IMGSZ'):
        size = int(os.environ['VIGIAAI_IMGSZ'])
        if size < 320 or size % 32:
            raise ValueError('VIGIAAI_IMGSZ deve ser múltiplo de 32, a partir de 320.')
        config.update(pessoas=size,epi=size)
    return name, config


def cpu_boxes(boxes):
    """Uma cópia CPU por conjunto de caixas; também aceita doubles dos testes."""
    return boxes.cpu() if callable(getattr(boxes, 'cpu', None)) else boxes


def person_boxes(result):
    coords = cpu_boxes(result.boxes).xyxy
    return coords.tolist() if callable(getattr(coords, 'tolist', None)) else [x.tolist() for x in coords]


class Timings:
    def __init__(self):
        self.rows = deque(maxlen=600)
        self.reset()

    def reset(self):
        self.started = time.perf_counter()
        self.stages = defaultdict(float)
        for name in ('captura_ms','yolo_pessoas_ms','yolo_epi_ms','yolo_auxiliar_ms','reanalises_ms',
                     'mediapipe_pose_ms','mediapipe_rosto_ms','rastreamento_temporal_ms',
                     'preparacao_ms','renderizacao_ms','jpeg_publicacao_ms'):
            self.stages[name] = 0.

    @contextmanager
    def stage(self, name):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] += (time.perf_counter() - start) * 1000

    def call(self, name, function, *args, **kwargs):
        with self.stage(name):
            return function(*args, **kwargs)

    def finish(self, captured, **extra):
        now = time.monotonic()
        total = (time.perf_counter() - self.started) * 1000
        row = dict(self.stages, total_ms=total, fps_processamento=1000 / max(total, .001),
                   latencia_captura_publicacao_ms=(now - captured) * 1000, **extra)
        self.rows.append(row)
        return row


class DetectorTimed:
    """Materializa resultados na CPU antes de encerrar o timer CUDA assíncrono."""
    def __init__(self, model, timings, stage):
        self.model, self.timings, self.name = model, timings, stage

    @property
    def names(self):
        return self.model.names

    def __call__(self, *args, **kwargs):
        with self.timings.stage(self.name):
            results = list(self.model(*args, **kwargs))
            for result in results:
                result.boxes = cpu_boxes(result.boxes)
            return results
