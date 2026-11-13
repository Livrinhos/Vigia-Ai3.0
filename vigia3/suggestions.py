"""Sugestões em lote separadas das anotações humanas e do dataset."""
import json
import time
from pathlib import Path
from .store import CLASSES, file_hash, validate_annotations

MAX_BATCH = 5000


def batch_request(store, models, data):
    ids = data.get('ids')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_BATCH
            or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids)):
        raise ValueError('Selecione de 1 a 5.000 imagens diferentes.')
    model = models.get(data.get('model'))
    if model['kind'] != 'epi':
        raise ValueError('Sugestões em lote exigem o detector de EPIs.')
    device = data.get('device', 'cpu')
    if device not in ('cpu', '0'):
        raise ValueError('Dispositivo inválido.')
    # Congela a revisão solicitada. Edições posteriores nunca são sobrescritas.
    images = []
    for iid in ids:
        r = store.image(iid)
        images.append(dict(id=iid, revision=r['revision']))
    return dict(images=images, model=model['id'], device=device)


def predict_boxes(detector, image, path, device):
    result = detector(str(path), imgsz=640, device=device, quantize='fp32', conf=.25, verbose=False)[0]
    raw = result.boxes.cpu()
    aliases = {'helmet':'capacete', 'vest':'colete', 'goggles':'oculos', 'gloves':'luvas', 'mask':'mascara'}
    boxes = []
    for xy, cls in zip(raw.xyxy.tolist(), raw.cls.tolist()):
        label = aliases.get(result.names[int(cls)], result.names[int(cls)])
        if label not in CLASSES:
            continue
        xy = [max(0, min(1, v/(image['width'] if i % 2 == 0 else image['height']))) for i, v in enumerate(xy)]
        if xy[0] >= xy[2] or xy[1] >= xy[3]:
            continue
        boxes.append(dict(scope='epi', label=label, xyxy=xy, origin='sugestao_ia'))
    return validate_annotations(dict(boxes=boxes))['boxes']


def run_batch(store, model, req, job_id, detector, progress, cancel):
    """Uma instância, uma imagem por inferência: VRAM limitada, resultados incrementais."""
    before = file_hash(model['path'])
    if before != model['sha256']:
        raise ValueError('Peso inicial não corresponde ao registro preservado.')
    counts = dict(done=0, total=len(req['images']), suggested=0, empty=0, skipped=0, failed=0)
    errors = []
    try:
        for entry in req['images']:
            if cancel():
                raise InterruptedError('Lote cancelado; sugestões já concluídas permanecem disponíveis.')
            iid = entry['id']
            try:
                r = store.image(iid)
                if (r['revision'] != entry['revision'] or r['state'] != 'pending'
                        or r['annotation']['boxes'] or r['annotation']['negative']):
                    counts['skipped'] += 1
                else:
                    path = store.root / r['relative_path']
                    if file_hash(path) != r['sha256']:
                        raise ValueError('Imagem alterada após importação.')
                    boxes = predict_boxes(detector, r, path, req['device'])
                    if cancel():
                        raise InterruptedError('Lote cancelado; sugestões anteriores preservadas.')
                    with store.lock, store.db() as db:
                        # O lock SQLite também protege contra outro processo de revisão.
                        db.execute('BEGIN IMMEDIATE')
                        row = db.execute('SELECT revision,state,deleted,annotation FROM images WHERE id=?', (iid,)).fetchone()
                        ann = json.loads(row['annotation']) if row else {}
                        if (not row or row['deleted'] or row['revision'] != entry['revision']
                                or row['state'] != 'pending' or ann.get('boxes') or ann.get('negative')):
                            counts['skipped'] += 1
                        else:
                            db.execute('INSERT INTO image_suggestions VALUES(?,?,?,?,?,?,?)',
                                (iid, job_id, entry['revision'], model['sha256'], json.dumps(boxes), time.time(), 'pending'))
                            counts['suggested'] += 1
                            counts['empty'] += int(not boxes)
            except InterruptedError:
                raise
            except (ValueError, OSError) as e:
                counts['failed'] += 1
                errors.append(dict(image=iid, error=str(e)))
            counts['done'] += 1
            progress(**counts)
    finally:
        if file_hash(model['path']) != before:
            raise RuntimeError('Integridade do peso inicial falhou.')
    return dict(**counts, errors=errors, review_required=True,
        note='Sugestões não alteram anotações, não aprovam imagens e não confirmam ausência de capacete.')
