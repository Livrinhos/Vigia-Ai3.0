'use strict';
(() => {
  const main=document.querySelector('main');if(!main)return;
  const section=document.createElement('section');section.style.cssText='margin:16px 0;padding:18px;border:1px solid #2b4765;border-radius:12px;background:#102236;color:#cfe4f8';
  const title=document.createElement('strong');title.textContent='Monitoramento coletivo · leituras atuais';
  const stats=document.createElement('p'),note=document.createElement('small'),model=document.createElement('select'),select=document.createElement('button'),restore=document.createElement('button'),bank=document.createElement('a');
  bank.href='/banco';bank.textContent='Banco de Imagens e Treinamento';bank.style.marginLeft='15px';select.textContent='Selecionar modelo aprovado';restore.textContent='Voltar ao original';
  section.append(title,stats,note,document.createElement('br'),model,select,restore,bank);main.insertBefore(section,main.firstChild);
  const tell=e=>{note.textContent=e.message;};
  async function post(url,data){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-VigiaAI':'1'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw new Error(d.error||d.mensagem);}
  select.onclick=async()=>{try{if(!confirm('Selecionar o modelo aprovado? Encerre o monitoramento antes.'))return;await post(`/api/banco/models/${model.value}/select`,{confirmation:'SELECIONAR'});note.textContent='Modelo selecionado para o próximo início.';}catch(e){tell(e);}};
  restore.onclick=async()=>{try{if(!confirm('Restaurar o modelo original?'))return;await post('/api/banco/models/restore',{confirmation:'RESTAURAR'});note.textContent='Modelo original restaurado.';}catch(e){tell(e);}};
  async function loop(){
    try{const r=await fetch('/status',{cache:'no-store'});const s=await r.json(),c=s.coletivo;
      stats.textContent=c?`${c.pessoas} pessoas · ${c.com_capacete} com capacete · ${c.possivel_ausencia} possível ausência · ${c.inconclusivas} inconclusivas/observando · ${c.possiveis_quedas} possíveis quedas · ${Number(s.fps||0).toFixed(1)} FPS IA`:'Aguardando quadros reais. Nenhuma contagem simulada.';
      note.textContent=c?`${c.poses_pendentes||0} poses aguardando; ${c.cabecas_em_fila||0} reanálises de cabeça em fila. Pessoas sem pose atual ficam inconclusivas para quedas; ausência de detecção não é infração confirmada.`:'Use o Modo Apresentação — Capacete e Postura. Modelos só são trocados com o monitoramento encerrado.';
      const area=document.getElementById('pessoasCentral');if(area&&s.deteccoes){for(let i=0;i<s.deteccoes.length;i++){const card=area.children[i];if(!card)continue;let reason=card.querySelector('.cabeca-v3');if(!reason){reason=document.createElement('p');reason.className='person-reason cabeca-v3';card.append(reason);}reason.textContent=s.deteccoes[i].cabeca_motivo||'';}}
    }catch(_){stats.textContent='Métricas coletivas indisponíveis.';}setTimeout(loop,700);
  }
  fetch('/api/banco/config').then(r=>r.json()).then(c=>{for(const m of c.models.filter(m=>m.kind==='epi'&&m.approved)){const o=document.createElement('option');o.value=m.id;o.textContent=m.name;model.append(o);}}).catch(tell);
  loop();
})();
