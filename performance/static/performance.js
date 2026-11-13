'use strict';
(() => {
  const img = document.getElementById('quadroProcessado');
  const label = document.getElementById('performanceStatus');
  const button = document.getElementById('modoApresentacao');
  const modeLabel = document.getElementById('modoApresentacaoStatus');
  let active = false;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const r = await fetch('/api/performance/apresentacao',{method:'POST',
        headers:{'Content-Type':'application/json','X-VigiaAI':'1'},body:JSON.stringify({ativo:!active})});
      if (!r.ok) throw new Error('Não foi possível trocar o modo.');
      modeLabel.textContent = 'Aplicando na próxima fronteira de quadro…';
    } catch (error) { modeLabel.textContent = error.message; button.disabled = false; }
  });
  let ticks = [], lastAck = 0, frame = null;
  img.addEventListener('load', () => requestAnimationFrame(() => {
    const now = performance.now();
    if (frame === img.dataset.frame || !img.dataset.frame) return;
    frame = img.dataset.frame;
    ticks.push(now); ticks = ticks.filter(t => now-t <= 3000);
    if (now-lastAck < 1000 || ticks.length < 2) return;
    lastAck = now;
    const fps = (ticks.length-1)*1000/(now-ticks[0]);
    fetch('/api/performance/display', {method:'POST',headers:{'Content-Type':'application/json','X-VigiaAI':'1'},
      body:JSON.stringify({frame:Number(frame),fps})}).catch(() => {});
  }));
  async function update() {
    try {
      const r = await fetch('/api/performance', {cache:'no-store'});
      if (!r.ok) throw new Error();
      const p = await r.json();
      active = p.modo_apresentacao;
      button.setAttribute('aria-pressed',String(active));
      button.textContent = active ? 'Voltar ao modo normal' : 'Modo Apresentação — Capacete e Postura';
      button.disabled = p.alteracao_pendente;
      modeLabel.textContent = p.alteracao_pendente ? 'Alteração aguardando próximo quadro' :
        active ? 'Capacete e postura · demais EPIs temporariamente suspensos · posturas estimadas' : 'Modo normal · política salva preservada';
      label.textContent = `Perfil ${p.perfil} · pessoas ${p.pessoas_imgsz}px · EPIs ${p.epi_imgsz}px · `+
        `${Number(p.fps_processamento).toFixed(1)} FPS IA · `+
        (p.fps_exibido == null ? 'FPS exibido: aguardando' : `${p.fps_exibido.toFixed(1)} FPS exibidos (estimativa)`)+
        (p.latencia_captura_ack_ms == null ? '' : ` · captura→navegador ${p.latencia_captura_ack_ms.toFixed(0)} ms`);
    } catch (_) { label.textContent = 'Métricas indisponíveis.'; }
    setTimeout(update,1000);
  }
  update();
})();
