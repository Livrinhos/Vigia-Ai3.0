"""Métricas da interface separadas do FPS da inteligência artificial."""
import math
import time
from flask import jsonify, request


def register_performance(app, monitor):
    @app.get('/api/performance')
    def performance():
        with monitor.lock:
            display = getattr(monitor, '_display_sample', {})
            fresh = time.monotonic() - display.get('received', -1e9) < 3
            return jsonify(perfil=monitor.performance_profile,
                modo_apresentacao=monitor.presentation_active,alteracao_pendente=monitor.presentation_pending is not None,
                pessoas_imgsz=monitor.performance_config['pessoas'], epi_imgsz=monitor.performance_config['epi'],
                fps_processamento=monitor.status['fps'],
                fps_exibido=display.get('fps') if fresh else None,
                latencia_captura_ack_ms=display.get('latency') if fresh else None,
                metricas=monitor.status.get('performance'),
                limite='FPS exibido estima imagens decodificadas no navegador. ACK inclui rede; não mede sensor/tela física.')

    @app.post('/api/performance/apresentacao')
    def presentation():
        if request.headers.get('X-VigiaAI') != '1':
            return jsonify(ok=False), 403
        data=request.get_json(silent=True)
        try:
            from presentation_mode import request_mode
            request_mode(monitor,data.get('ativo') if isinstance(data,dict) else None)
        except ValueError as error:
            return jsonify(ok=False,mensagem=str(error)),400
        return jsonify(ok=True,ativo=monitor.presentation_active,pendente=monitor.presentation_pending is not None)

    @app.post('/api/performance/display')
    def display():
        if request.headers.get('X-VigiaAI') != '1':
            return jsonify(ok=False), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(ok=False), 400
        fps, sequence = data.get('fps'), data.get('frame')
        if (isinstance(fps, bool) or not isinstance(fps, (int,float)) or not math.isfinite(fps)
                or not 0 <= fps <= 1000 or type(sequence) is not int):
            return jsonify(ok=False), 400
        with monitor.lock:
            capture = monitor.frame_history.get(sequence)
            if capture is None:
                return jsonify(ok=False), 409
            now = time.monotonic()
            monitor._display_sample = dict(fps=fps, received=now, latency=max(0, now-capture)*1000)
        return jsonify(ok=True)
