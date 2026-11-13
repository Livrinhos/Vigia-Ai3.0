import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

test('botão de apresentação alterna e restaura; FPS exibido exige quadros novos',async()=>{
  const timers=[];
  class Element {constructor(){this.handlers={};this.dataset={};this.attributes={};}addEventListener(k,f){this.handlers[k]=f;}setAttribute(k,v){this.attributes[k]=v;}}
  const elements=new Map(['quadroProcessado','performanceStatus','modoApresentacao','modoApresentacaoStatus'].map(id=>[id,new Element()]));
  let state={modo_apresentacao:false,alteracao_pendente:false,perfil:'qualidade',pessoas_imgsz:640,epi_imgsz:640,fps_processamento:0,fps_exibido:null,latencia_captura_ack_ms:null};
  const calls=[];
  const context=vm.createContext({document:{getElementById:id=>elements.get(id)},requestAnimationFrame:f=>f(),
    performance:{now:()=>1000},setTimeout:f=>timers.push(f),fetch:async(url,options)=>{
      calls.push({url,options});
      if(url.endsWith('apresentacao'))state.modo_apresentacao=JSON.parse(options.body).ativo;
      return {ok:true,json:async()=>state};
    }});
  vm.runInContext(await readFile(new URL('../static/performance.js',import.meta.url),'utf8'),context);
  await new Promise(r=>setImmediate(r));
  assert.match(elements.get('performanceStatus').textContent,/FPS exibido: aguardando/);
  const button=elements.get('modoApresentacao');
  await button.handlers.click();await timers.shift()();
  assert.equal(button.textContent,'Voltar ao modo normal');
  assert.equal(button.attributes['aria-pressed'],'true');
  await button.handlers.click();await timers.shift()();
  assert.equal(button.textContent,'Modo Apresentação — Capacete e Postura');
  assert.equal(button.attributes['aria-pressed'],'false');
  assert.equal(calls.filter(x=>x.url.endsWith('display')).length,0);
});
