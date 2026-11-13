'use strict';
const $=id=>document.getElementById(id);
const states={pending:'Pendente',reviewed:'Revisada',approved:'Aprovada',rejected:'Rejeitada'};
let config={},filter='all',page=1,total=0,items=[],selected=new Set(),current=null,boxes=[],chosen=-1,loadedImage=null,drag=null,watched=null,uploading=false;
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
function say(text,error=false){$('message').textContent=text;$('message').className='message'+(error?' error':'');$('message').hidden=false;}
async function api(url,data,method='POST'){
  const response=await fetch(url,{method,cache:'no-store',headers:{'Content-Type':'application/json','X-VigiaAI':'1'},...(method==='GET'?{}:{body:JSON.stringify(data||{})})});
  const result=await response.json();if(!response.ok||result.ok===false)throw new Error(result.error||result.mensagem||'Não foi possível completar a ação.');return result;
}
const get=url=>api(url,null,'GET');
function option(select,value,text){const o=node('option',text);o.value=value;select.append(o);}
function action(button,fn){button.addEventListener('click',async()=>{button.disabled=true;try{await fn();}catch(e){say(e.message,true);}finally{button.disabled=false;}});}
function preserveSelect(el,fill){const value=el.value;el.replaceChildren();fill();if([...el.options].some(o=>o.value===value))el.value=value;}

async function refreshConfig(){
  config=await get('/api/banco/config');$('storagePath').textContent=config.storage;
  preserveSelect($('initialModel'),()=>{for(const m of config.models.filter(m=>m.kind==='epi'))option($('initialModel'),m.id,m.name+(m.approved?' · aprovado':' · candidato'));});
  preserveSelect($('trainDataset'),()=>{for(const d of config.datasets.filter(d=>d.kind==='detector'))option($('trainDataset'),d.id,d.name);});
  $('datasets').replaceChildren();
  for(const d of config.datasets){const summary=JSON.parse(d.summary),row=node('div',undefined,'row'),detail=node('div',undefined,'details');detail.append(node('strong',d.name),node('small',`${d.kind} · ${summary.groups} grupos · ${Object.entries(summary.counts).map(([k,v])=>k+': '+(v.images??Object.values(v).reduce((a,b)=>a+b,0))).join(' | ')}`));row.append(detail);$('datasets').append(row);}
  renderModels();
}
async function refreshGallery(){
  const q=new URLSearchParams({state:filter,q:$('search').value,session:$('sessionFilter').value,page});
  const data=await get('/api/banco/images?'+q);items=data.items;total=data.total;
  $('countTotal').textContent=Object.values(data.counts).reduce((a,b)=>a+b,0);$('countPending').textContent=data.counts.pending||0;$('countReady').textContent=data.ready;
  preserveSelect($('sessionFilter'),()=>{option($('sessionFilter'),'','Todas as sessões');for(const s of data.sessions)option($('sessionFilter'),s.id,s.name);});
  const area=$('gallery');area.replaceChildren();
  if(!items.length)area.append(node('div','Nenhuma imagem neste filtro. Importe suas fotos para começar.','empty'));
  for(const image of items){
    const card=node('article',undefined,'image-card'),check=node('input');check.type='checkbox';check.checked=selected.has(image.id);check.setAttribute('aria-label','Selecionar '+image.name);
    check.addEventListener('change',()=>{check.checked?selected.add(image.id):selected.delete(image.id);selectionCount();});
    const img=node('img');img.src=`/api/banco/images/${image.id}/thumb`;img.alt=image.name;img.loading='lazy';img.tabIndex=0;
    img.addEventListener('click',()=>openImage(image.id).catch(e=>say(e.message,true)));img.addEventListener('keydown',e=>{if(e.key==='Enter')openImage(image.id).catch(e=>say(e.message,true));});
    const info=node('div',undefined,'info');info.append(node('h3',image.name),node('p',`${image.width} × ${image.height} · ${image.session_name}`),node('span',states[image.state],'badge '+image.state));
    const issues=JSON.parse(image.issues);if(issues.length)info.append(node('p','⚠ '+issues.join('; ')));
    card.append(check,img,info);area.append(card);
  }
  $('pageLabel').textContent=`Página ${page} de ${Math.max(1,Math.ceil(total/60))} · ${total} imagens`;
  $('previous').disabled=page<=1;$('next').disabled=page*60>=total;selectionCount();
}
function selectionCount(){$('selectedCount').textContent=`${selected.size} selecionadas`;$('selectPage').checked=items.length>0&&items.every(i=>selected.has(i.id));}
async function refreshAll(){await Promise.all([refreshGallery(),refreshConfig(),refreshJobs()]);}

async function importFiles(files){
  if(uploading)return;
  if(!$('sessionName').value.trim())throw new Error('Informe o nome do conjunto/sessão.');
  if(!$('authorized').checked)throw new Error('Confirme autorização para usar as imagens.');
  const all=[...files],images=all.filter(f=>/\.(jpe?g|png|webp|zip)$/i.test(f.name));
  if(!images.length)throw new Error('Não foram encontradas imagens ou ZIP compatíveis.');
  const byPath=new Map(all.map(f=>[f.webkitRelativePath||f.name,f]));
  const session=await api('/api/banco/sessions',{name:$('sessionName').value,group:$('groupName').value,authorized:true});
  uploading=true;$('uploadProgress').hidden=false;
  let done=0,duplicates=0,errors=[];
  try{
    for(const file of images){
      const name=file.webkitRelativePath||file.name,stem=name.replace(/\.[^.]+$/,''),extras={};
      const txt=byPath.get(stem+'.txt')||byPath.get((stem+'.txt').replace(/(^|\/)images\//,'$1labels/'));
      const meta=byPath.get(stem+'.json');
      if(txt){if(txt.size>1024*1024)throw new Error('Anotação muito grande: '+txt.name);extras.yolo=await txt.text();}
      if(meta){if(meta.size>1024*1024)throw new Error('JSON muito grande: '+meta.name);extras.metadata=JSON.parse(await meta.text());}
      const u=await api('/api/banco/uploads',{session:session.id,name,size:file.size,extras});
      for(let offset=0;offset<file.size;){
        const chunk=file.slice(offset,offset+4*1024*1024);
        const r=await fetch(`/api/banco/uploads/${u.id}/chunk?offset=${offset}`,{method:'PUT',headers:{'X-VigiaAI':'1','Content-Type':'application/octet-stream'},body:chunk});
        const body=await r.json();if(!r.ok)throw new Error(body.error||'Falha ao enviar bloco; o arquivo original permanece intacto.');offset=body.offset;
        $('uploadProgress').value=(done+offset/file.size)/images.length*100;
        $('uploadStatus').textContent=`Enviando ${done+1}/${images.length}: ${file.name} · ${Math.round(offset/file.size*100)}%`;
      }
      const j=await api(`/api/banco/uploads/${u.id}/finish`,{});
      const result=await waitJob(j.job,job=>{$('uploadStatus').textContent=`Validando ${file.name} · ${job.progress?.done??0}/${job.progress?.total??'…'} imagens`;});
      duplicates+=result?.duplicates||0;if(result?.errors?.length)errors.push(...result.errors);done++;
      $('uploadProgress').value=done/images.length*100;
    }
    say(`Importação concluída: ${done} arquivo(s) processado(s), ${duplicates} duplicata(s) reconhecida(s), ${errors.length} erro(s). Nenhuma imagem foi aprovada automaticamente.`,errors.length>0);
    $('uploadStatus').textContent=errors.length?JSON.stringify(errors.slice(0,20),null,2):'Originais e metadados preservados no banco local.';
  }finally{uploading=false;await refreshAll();}
}
async function waitJob(id,update=()=>{}){
  for(;;){const job=await get('/api/banco/jobs/'+id);update(job);if(job.state==='succeeded'&&!job.process_running)return job.result;if(['failed','cancelled','interrupted'].includes(job.state))throw new Error(job.error||'Trabalho cancelado.');await new Promise(r=>setTimeout(r,500));}
}

function labelOptions(){
  const scope=$('scope').value,values=scope==='epi'?(config.classes||['capacete','colete','oculos','luvas','mascara']):scope==='pessoa'?['pessoa']:['com_capacete','sem_capacete','inconclusivo'];
  $('label').replaceChildren();for(const v of values)option($('label'),v,v.replaceAll('_',' '));
}
async function openImage(id){
  current=await get('/api/banco/images/'+id);boxes=structuredClone(current.annotation.boxes);chosen=-1;
  $('imageName').textContent=current.name;$('negative').checked=current.annotation.negative;$('notes').value=current.annotation.notes;
  $('reviewState').value=current.state;$('humanReview').checked=false;$('ackIssues').checked=false;
  $('downloadOriginal').href=`/api/banco/images/${id}/file?download=1`;
  $('imageMeta').textContent=JSON.stringify({dimensoes:`${current.width}×${current.height}`,importada_em:new Date(current.created*1000).toLocaleString(),sessao:current.session_name,origem:current.source,todas_as_origens:current.sources,similares_para_revisar:current.related,grupo:current.group_key,avisos:current.issues,metadados:current.metadata},null,2);
  loadedImage=new Image();loadedImage.onload=()=>{const c=$('canvas');c.width=loadedImage.naturalWidth;c.height=loadedImage.naturalHeight;draw();};loadedImage.src=`/api/banco/images/${id}/file`;
  labelOptions();renderBoxes();$('editor').showModal();
}
function draw(){
  if(!loadedImage||!loadedImage.complete)return;
  const c=$('canvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(loadedImage,0,0);
  const scale=Math.max(1,c.width/800);ctx.lineWidth=2*scale;ctx.font=`${13*scale}px system-ui`;
  boxes.forEach((b,i)=>{const [x1,y1,x2,y2]=b.xyxy.map((v,j)=>v*(j%2?c.height:c.width));ctx.strokeStyle=i===chosen?'#fff':b.scope==='cabeca'?'#ffbf58':'#54dbb9';ctx.strokeRect(x1,y1,x2-x1,y2-y1);ctx.fillStyle=ctx.strokeStyle;ctx.fillText(`${i+1} ${b.label}`,x1+3*scale,Math.max(15*scale,y1-5*scale));});
  if(drag){ctx.strokeStyle='#6cbfff';ctx.strokeRect(drag.x*c.width,drag.y*c.height,(drag.endX-drag.x)*c.width,(drag.endY-drag.y)*c.height);}
}
function point(e){const r=$('canvas').getBoundingClientRect();return{x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};}
$('canvas').addEventListener('pointerdown',e=>{const p=point(e);drag={...p,endX:p.x,endY:p.y};$('canvas').setPointerCapture(e.pointerId);});
$('canvas').addEventListener('pointermove',e=>{if(drag){const p=point(e);drag.endX=p.x;drag.endY=p.y;draw();}});
$('canvas').addEventListener('pointerup',e=>{
  if(!drag)return;const p=point(e),start=drag;drag=null;
  if(Math.abs(p.x-start.x)<.008||Math.abs(p.y-start.y)<.008){chosen=boxes.findLastIndex(b=>b.xyxy[0]<=p.x&&p.x<=b.xyxy[2]&&b.xyxy[1]<=p.y&&p.y<=b.xyxy[3]);}
  else{boxes.push({scope:$('scope').value,label:$('label').value,xyxy:[Math.min(start.x,p.x),Math.min(start.y,p.y),Math.max(start.x,p.x),Math.max(start.y,p.y)],origin:'manual'});chosen=boxes.length-1;}
  renderBoxes();draw();
});
function renderBoxes(){
  $('boxList').replaceChildren();boxes.forEach((b,i)=>{const row=node('div',`${i+1} · ${b.scope}: ${b.label.replaceAll('_',' ')}${b.origin==='sugestao_ia'?' · sugestão não revisada':''}`,'row'+(chosen===i?' chosen':''));row.tabIndex=0;row.addEventListener('click',()=>{chosen=i;$('scope').value=b.scope;labelOptions();$('label').value=b.label;renderBoxes();draw();});$('boxList').append(row);});
}
async function saveReview(){
  if(!current)return;
  current=await api(`/api/banco/images/${current.id}/review`,{revision:current.revision,state:$('reviewState').value,
    annotation:{boxes,negative:$('negative').checked,notes:$('notes').value},human_reviewed:$('humanReview').checked,issues_acknowledged:$('ackIssues').checked},'PUT');
  say('Revisão salva. O original não foi alterado.');$('editor').close();await refreshGallery();
}

async function refreshJobs(){
  const data=await get('/api/banco/jobs');$('countJobs').textContent=data.items.filter(j=>j.kind==='train').length;$('jobs').replaceChildren();
  for(const j of data.items){const row=node('div',undefined,'row'),detail=node('div',undefined,'details');detail.append(node('strong',`${j.kind} · ${j.state}`),node('small',`${new Date(j.created*1000).toLocaleString()}${j.error?' · '+j.error:''}`));const b=node('button','Ver logs e resultado');action(b,()=>watchJob(j.id));row.append(detail,b);$('jobs').append(row);}
}
async function watchJob(id){watched=id;$('jobDetail').hidden=false;await pollWatched();}
async function pollWatched(){
  if(!watched)return;
  const j=await get('/api/banco/jobs/'+watched);$('jobTitle').textContent=`${j.kind} · ${j.state}`;$('jobLogs').textContent=j.log||j.error||'Aguardando saída do processo…';$('jobResult').textContent=j.result?JSON.stringify(j.result,null,2):'';
  const p=j.progress||{};$('jobProgress').value=p.epochs?p.epoch/p.epochs*100:p.total?p.done/p.total*100:0;$('cancelJob').disabled=!['queued','running','cancelling'].includes(j.state);
  if(['queued','running','cancelling'].includes(j.state))setTimeout(()=>pollWatched().catch(e=>say(e.message,true)),800);
  else await Promise.all([refreshJobs(),refreshGallery(),refreshConfig()]);
}
function renderModels(){
  $('models').replaceChildren();
  const original=config.models.find(m=>m.kind==='epi'&&m.origin==='original');
  for(const m of config.models){const row=node('div',undefined,'row'),detail=node('div',undefined,'details');detail.append(node('strong',m.name),node('small',`${m.kind} · ${m.origin} · ${m.approved?'aprovado':'não aprovado'} · SHA-256 ${m.sha256.slice(0,16)}…`));row.append(detail);
    if(m.kind==='epi'){
      if(m.origin!=='original'){const compare=node('button','Comparar com original');action(compare,async()=>{if(!original||!$('trainDataset').value)throw new Error('Selecione um dataset preparado e mantenha o modelo original disponível.');const r=await api('/api/banco/evaluate',{model:m.id,baseline:original.id,dataset:$('trainDataset').value,device:$('device').value});await watchJob(r.job);});row.append(compare);
        const approve=node('button','Aprovar para monitoramento');action(approve,async()=>{if(!confirm('Confirmo que revisei o resultado da comparação e os vídeos independentes. Aprovar este modelo?'))return;await api(`/api/banco/models/${m.id}/approve`,{confirmation:'APROVAR '+m.id});await refreshConfig();});row.append(approve);}
      if(m.approved){const select=node('button','Selecionar no monitoramento');action(select,async()=>{if(!confirm('Selecionar este modelo aprovado? O monitoramento precisa estar encerrado.'))return;await api(`/api/banco/models/${m.id}/select`,{confirmation:'SELECIONAR'});say('Modelo selecionado. Pode iniciar a demonstração.');});row.append(select);}
    }$('models').append(row);
  }
}

$('files').addEventListener('change',e=>importFiles(e.target.files).catch(e=>say(e.message,true)));$('folder').addEventListener('change',e=>importFiles(e.target.files).catch(e=>say(e.message,true)));
for(const button of $('filters').querySelectorAll('button'))action(button,async()=>{filter=button.dataset.state;page=1;for(const b of $('filters').querySelectorAll('button'))b.classList.toggle('selected',b===button);await refreshGallery();});
let searchTimer;$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;refreshGallery().catch(e=>say(e.message,true));},250);});$('sessionFilter').addEventListener('change',()=>{page=1;refreshGallery().catch(e=>say(e.message,true));});
$('selectPage').addEventListener('change',e=>{for(const i of items)e.target.checked?selected.add(i.id):selected.delete(i.id);refreshGallery().catch(e=>say(e.message,true));});
action($('refresh'),refreshAll);action($('previous'),async()=>{page--;await refreshGallery();});action($('next'),async()=>{page++;await refreshGallery();});
for(const [id,state] of [['bulkReject','rejected'],['bulkPending','pending']])action($(id),async()=>{await api('/api/banco/images/bulk-review',{ids:[...selected],state});selected.clear();await refreshGallery();});
action($('trash'),async()=>{if(!selected.size)throw new Error('Selecione imagens.');if(!confirm(`Mover ${selected.size} imagem(ns) para a lixeira recuperável? Os arquivos serão preservados.`))return;await api('/api/banco/images/trash',{ids:[...selected],confirmation:'CONFIRMAR'});selected.clear();await refreshGallery();});
action($('trashOpen'),async()=>{const d=await get('/api/banco/trash');$('trashList').replaceChildren();for(const image of d.items){const row=node('div',undefined,'row'),b=node('button','Restaurar');row.append(node('span',image.name),b);action(b,async()=>{await api('/api/banco/images/restore',{ids:[image.id],confirmation:'CONFIRMAR'});row.remove();await refreshGallery();});$('trashList').append(row);}$('trashDialog').showModal();});
$('closeTrash').addEventListener('click',()=>$('trashDialog').close());$('closeEditor').addEventListener('click',()=>$('editor').close());$('scope').addEventListener('change',labelOptions);
action($('changeLabel'),async()=>{if(chosen<0)throw new Error('Selecione uma caixa.');boxes[chosen].scope=$('scope').value;boxes[chosen].label=$('label').value;boxes[chosen].origin='manual';renderBoxes();draw();});
action($('removeBox'),async()=>{if(chosen<0)throw new Error('Selecione uma caixa.');boxes.splice(chosen,1);chosen=-1;renderBoxes();draw();});action($('saveReview'),saveReview);
action($('suggest'),async()=>{if(!current)throw new Error('Abra uma imagem.');if(!confirm('Executar o modelo local para sugerir caixas? Elas precisarão de revisão humana.'))return;const j=await api(`/api/banco/images/${current.id}/suggest`,{model:$('initialModel').value,device:$('device').value});const result=await waitJob(j.job);if(result.image!==current?.id||result.revision!==current.revision)throw new Error('Imagem mudou; descarte a sugestão e recarregue.');boxes.push(...result.boxes);$('humanReview').checked=false;renderBoxes();draw();say('Sugestões inseridas para correção. Nenhuma aprovação automática.');});
action($('export'),async()=>{if(!selected.size)throw new Error('Selecione imagens aprovadas.');const q=new URLSearchParams();for(const id of selected)q.append('id',id);const response=await fetch('/api/banco/export/yolo?'+q);if(!response.ok){const e=await response.json();throw new Error(e.error);}const url=URL.createObjectURL(await response.blob()),a=node('a');a.href=url;a.download='anotacoes-yolo.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
action($('prepare'),async()=>{const r=await api('/api/banco/datasets',{name:$('datasetName').value,kind:$('datasetKind').value,test_independent:$('testIndependent').checked});await watchJob(r.job);say('Preparação iniciada. Consulte os erros e a auditoria antes de treinar.');});
action($('train'),async()=>{if(!confirm('Iniciar um treinamento real, em processo separado, com os parâmetros selecionados? Nenhum modelo original será substituído.'))return;const r=await api('/api/banco/train',{model:$('initialModel').value,dataset:$('trainDataset').value,epochs:Number($('epochs').value),imgsz:Number($('imgsz').value),batch:Number($('batch').value),device:$('device').value,name:$('experiment').value,pilot:$('pilot').checked});await watchJob(r.job);});
action($('cancelJob'),async()=>{if(!watched)return;if(!confirm('Cancelar este trabalho? Checkpoints já gravados serão preservados.'))return;await api('/api/banco/jobs/'+watched+'/cancel',{});say('Cancelamento solicitado; o processo encerrará de forma cooperativa ou após o prazo de segurança.');});
action($('restoreModel'),async()=>{if(!confirm('Retornar ao modelo original preservado?'))return;await api('/api/banco/models/restore',{confirmation:'RESTAURAR'});say('Modelo original restaurado para o próximo início do monitoramento.');});
action($('backup'),async()=>{const r=await api('/api/banco/backup',{});say('Catálogo salvo em backups/'+r.file+'. Faça também backup externo de toda a pasta de dados.');});
refreshAll().catch(e=>say(e.message,true));
