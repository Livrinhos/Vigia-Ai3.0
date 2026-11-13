import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.handlers={};this.attributes={};this.value='';this.checked=false;this.disabled=false;this.dataset={};this.className='';this.style={};this.textContent='';this.files=[];
    this.classList={toggle:(name,on)=>{const classes=new Set(this.className.split(' '));on?classes.add(name):classes.delete(name);this.className=[...classes].join(' ');}};}
  append(...v){this.children.push(...v);if(this.tag==='select'&&!this.value&&v[0])this.value=v[0].value;}
  replaceChildren(...v){this.children=[];this.append(...v);}
  get options(){return this.children;}
  addEventListener(k,f){this.handlers[k]=f;}
  setAttribute(k,v){this.attributes[k]=v;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  querySelectorAll(tag){return this.children.filter(e=>e.tag===tag);}
  getContext(){return {clearRect(){},drawImage(){},strokeRect(){},fillText(){}};}
  click(){return this.handlers.click?.({target:this});}
}

test('galeria e revisão usam JavaScript real e rotas Flask reais',async t=>{
  const python=process.env.VIGIAAI_PYTHON;if(!python)throw Error('Defina VIGIAAI_PYTHON.');
  const child=spawn(python,[fileURLToPath(new URL('api_bridge.py',import.meta.url))],{stdio:['pipe','pipe','inherit'],windowsHide:true});
  t.after(()=>child.stdin.end());
  const pending=new Map();let sequence=0;
  createInterface({input:child.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);pending.delete(r.id);p.resolve(new Response([204,304].includes(r.status)?null:Buffer.from(r.body,'base64'),{status:r.status,headers:r.headers}));});
  child.on('error',e=>{for(const p of pending.values())p.reject(e);});
  child.on('exit',()=>{for(const p of pending.values())p.reject(Error('Ponte de testes encerrada.'));});
  const fetch=async(url,options={})=>{const message={id:++sequence,url,method:options.method||'GET',headers:options.headers||{}};
    if(options.body instanceof Blob)message.binary=Buffer.from(await options.body.arrayBuffer()).toString('base64');else if(options.body)message.body=options.body;
    return new Promise((resolve,reject)=>{pending.set(message.id,{resolve,reject});child.stdin.write(JSON.stringify(message)+'\n');});};
  const html=await readFile(new URL('../web/banco.html',import.meta.url),'utf8');const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  for(const id of ['initialModel','trainDataset','sessionFilter','scope','label','reviewState','datasetKind','device','batch','imgsz'])elements.get(id).tag='select';
  for(const [id,value] of [['scope','epi'],['reviewState','pending'],['datasetKind','detector'],['device','cpu']])elements.get(id).value=value;
  for(const state of ['all','pending','approved']){const b=new Element('button');b.dataset.state=state;elements.get('filters').append(b);}
  class ImageFixture {constructor(){this.complete=true;this.naturalWidth=96;this.naturalHeight=96;}set src(v){this.url=v;queueMicrotask(()=>this.onload?.());}}
  const context=vm.createContext({document:{getElementById:id=>elements.get(id),createElement:tag=>new Element(tag)},fetch,console,URL,URLSearchParams,Image:ImageFixture,structuredClone,Blob,confirm:()=>true,setTimeout:()=>1,clearTimeout(){},queueMicrotask});
  vm.runInContext(await readFile(new URL('../web/banco.js',import.meta.url),'utf8'),context);
  await vm.runInContext('refreshAll()',context);
  assert.equal(elements.get('countTotal').textContent,0);
  const sid=await (await fetch('/api/banco/sessions',{method:'POST',headers:{'Content-Type':'application/json','X-VigiaAI':'1'},body:JSON.stringify({name:'fixture',group:'fixture',authorized:true})})).json();
  // PNG sintético explícito, gerado por PIL na fixture Python de dados, sem pessoas reais.
  const fixture=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
  const upload=await (await fetch('/api/banco/uploads',{method:'POST',headers:{'Content-Type':'application/json','X-VigiaAI':'1'},body:JSON.stringify({session:sid.id,name:'fixture.png',size:fixture.length})})).json();
  await fetch(`/api/banco/uploads/${upload.id}/chunk?offset=0`,{method:'PUT',headers:{'X-VigiaAI':'1','Content-Type':'application/octet-stream'},body:new Blob([fixture])});
  const job=await (await fetch(`/api/banco/uploads/${upload.id}/finish`,{method:'POST',headers:{'Content-Type':'application/json','X-VigiaAI':'1'},body:'{}'})).json();
  const deadline=Date.now()+15000;let status;
  do{status=await(await fetch('/api/banco/jobs/'+job.job)).json();if(!['queued','running'].includes(status.state))break;await new Promise(r=>globalThis.setTimeout(r,50));}while(Date.now()<deadline);
  assert.equal(status.state,'succeeded',JSON.stringify(status));
  await vm.runInContext('refreshGallery()',context);assert.equal(elements.get('countTotal').textContent,1);
  const id=vm.runInContext('items[0].id',context);context.imageId=id;
  await vm.runInContext('openImage(imageId)',context);assert.equal(elements.get('editor').open,true);
  vm.runInContext("boxes=[{scope:'epi',label:'capacete',xyxy:[.1,.1,.5,.5],origin:'manual'}]",context);
  elements.get('reviewState').value='approved';elements.get('humanReview').checked=true;elements.get('ackIssues').checked=true;
  await vm.runInContext('saveReview()',context);assert.equal(elements.get('countReady').textContent,1);
  assert.equal(elements.get('editor').open,false);
  const original=await(await fetch('/api/banco/images/'+id)).json();assert.equal(original.annotation.boxes[0].label,'capacete');
});
