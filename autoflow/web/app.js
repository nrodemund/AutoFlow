'use strict';
const $ = id => document.getElementById(id);
const copy = value => structuredClone(value);
const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const ref = v => object(v) && Object.keys(v).length === 1 && Array.isArray(v.ref);
const param = v => object(v) && Object.keys(v).length === 1 && typeof v.param === 'string';
const typeBase = t => (t || 'reference').replace('?', '');
const colors = {integer:'#60d7bd',point:'#f0bd63',string:'#df82c3',texture:'#df82c3',bool:'#df6d73',float:'#60b7ed',bytes:'#bb99ed',reference:'#97b7ed',dict:'#97b7ed',set:'#97b7ed','reference:Point':'#f0bd63','reference:list':'#97b7ed','reference:Dataset':'#70c1a0',exec:'#e4e7ef'};
const color = t => colors[typeBase(t)] || colors.reference;
const label = name => name.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
let project, catalog = {}, graphName, selected = null, dirty = false, revision = 0;
let view = {x:30,y:10,z:1}, pending = null, drag = null, pointer = {x:0,y:0};
let undo = [], redo = [], cursor = 0, running = false, toastTimer, polling = false;
let debugRunId=null, appliedDebugEdits=new Set();
const graph = () => project.graphs[graphName];
const kind = node => (typeof functionNodeKind==='function' && functionNodeKind(node)) || catalog[node.type];
function element(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}
function button(text, action, className='') {
  const b = element('button',className,text); b.type='button'; b.onclick=action; return b;
}
async function api(path, data) {
  const response = await fetch('/api/'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}
function report(error) { toast(error.message || String(error)); log('error', error.message || String(error)); }
function toast(message) {
  $('toast').textContent=message; $('toast').style.display='block';
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').style.display='none',4000);
}
function log(kind, message, time=new Date().toLocaleTimeString()) {
  const line=element('div','log '+kind); line.append(element('time','',time),element('span','',message));
  const box=$('console-lines'); box.append(line);
  while(box.children.length>1000) box.firstChild.remove();
  box.scrollTop=box.scrollHeight;
}
function mark() { dirty=true; revision++; $('save-state').textContent='Unsaved'; }
function remember() { undo.push(copy(project)); if(undo.length>80) undo.shift(); redo=[]; }
function change(fn) { remember(); fn(); mark(); render(); }
function restoreHistory(from,to) {
  if(!from.length) return;
  to.push(copy(project)); project=from.pop(); if(!project.graphs[graphName]) graphName=project.main;
  selected=null;if(typeof selectedNodes!=='undefined')selectedNodes.clear(); pending=null; mark(); render();
}
function setProject(next, filename, saved=true) {
  debugRunId=null;appliedDebugEdits.clear();
  activeDataset=null; pendingDatasetResult=null; datasetRun=null; $('apply-dataset-result').hidden=true;
  if(typeof selectedNodes!=='undefined')selectedNodes.clear();
  project=copy(next); project.datasets ||= {}; graphName=project.main; selected=null; pending=null; undo=[]; redo=[];
  for(const g of Object.values(project.graphs))for(const node of Object.values(g.nodes)){node.inputs ||= {};node.next ||= {};}
  $('filename').value=filename; dirty=!saved; revision++; $('save-state').textContent=saved?'Saved':'Unsaved';
  view={x:30,y:10,z:1}; render(); requestAnimationFrame(fit);
}
function fallback(type, defaults, pin) {
  if(Object.hasOwn(defaults || {},pin)) return copy(defaults[pin]);
  switch(typeBase(type)) {case 'reference:Dataset':return null;case 'integer':case 'float':return 0;case 'reference:Point':return {x:0,y:0};case 'bool':return false;case 'reference:list':return [];case 'reference:tuple':return {$type:'tuple',value:[]};case 'dict':return {};case 'set':return {$type:'set',value:[]};case 'bytes':return {$type:'bytes',value:''};default:return '';}
}
function defaultInput(node,pin) {const d=kind(node);return fallback(d.inputs[pin],d.defaults,pin);}
function nodeCategory(d) {
  if(d.category!=='Utilities') return d.category;
  if(['FindOnScreen','IfOnScreen','Click'].includes(d.name)) return 'Screen';
  if(['ForEach','CallFunction','Wait'].includes(d.name)) return 'Flow';
  return 'Data';
}
function renderPalette() {
  const query=$('search').value.toLowerCase(), box=$('palette'); box.replaceChildren();
  const groups={};
  for(const d of Object.values(catalog)) {
    if(['FunctionParameter','FunctionCall'].includes(d.name))continue;
    if(!(d.title+' '+d.name).toLowerCase().includes(query)) continue;
    (groups[nodeCategory(d)] ||= []).push(d);
  }
  for(const [category, definitions] of Object.entries(groups).sort()) {
    box.append(element('div','category',category));
    for(const d of definitions) {
      const b=button('',()=>addNode(d.name),'node-option');
      b.draggable=true;
      b.ondragstart=e=>{e.dataTransfer.setData('application/x-autoflow-node',d.name);e.dataTransfer.effectAllowed='copy';$('canvas').classList.add('library-drop');};
      b.ondragend=()=>$('canvas').classList.remove('library-drop');
      b.title=d.description || 'Add '+d.title;
      b.append(element('span','glyph',d.pure?'+':'◇'),element('span','',d.title),element('small','','+'));
      box.append(b);
    }
  }
}
function addNode(type, position, inputs = {}, metadata = {}) {
  const d=kind({type,...metadata});
  if(!d) {
    report(Error(`The running AutoFlow server does not provide ${type}. Restart AutoFlow, then save or export any unsaved edits before refreshing this page.`));
    return;
  }
  change(()=>{
    let id=type.toLowerCase(), suffix=1; while(graph().nodes[id]) id=type.toLowerCase()+'_'+suffix++;
    const rect=$('canvas').getBoundingClientRect();
    const p=position || [(rect.width/2-view.x)/view.z-100,(rect.height/2-view.y)/view.z-60];
    graph().nodes[id]={type,...metadata,inputs:{...Object.fromEntries(Object.keys(d.inputs).map(pin=>[pin,fallback(d.inputs[pin],d.defaults,pin)])),...inputs},position:p,next:{}};
    if(!graph().entry && !d.pure) graph().entry=id;
    selected=id;if(typeof selectedNodes!=='undefined')selectedNodes=new Set([id]);
  });
}
function renderGraphs() {
  for(const target of ['graph-list','graph-tabs']) {
    $(target).replaceChildren();
    for(const name of Object.keys(project.graphs)) {
      const b=button(name,()=>{ graphName=name; selected=null;if(typeof selectedNodes!=='undefined')selectedNodes.clear(); pending=null; render(); fit(); },name===graphName?'active':'');
      if(target==='graph-list'){b.draggable=true;b.title='Click to open; drag to call this function';b.ondragstart=e=>{e.dataTransfer.setData('application/x-autoflow-function',name);e.dataTransfer.effectAllowed='copy';};}
      if(target==='graph-list') b.append(element('small','',name===project.main?'MAIN':'ƒ'));
      if(target==='graph-list'){const row=element('div','function-entry');const call=button('+',()=>addNode('FunctionCall',undefined,{},{function:name}));call.title='Add call to '+name;call.setAttribute('aria-label','Add call to '+name);row.append(b,call);$(target).append(row);}else $(target).append(b);
    }
  }
  $('graph-title').textContent=graphName;
}
function isConnected(id,pin,direction,category) {
  if(category==='exec') return direction==='out' ? !!graph().nodes[id].next?.[pin] : Object.values(graph().nodes).some(n=>Object.values(n.next || {}).includes(id));
  if(direction==='in') return ref(graph().nodes[id].inputs?.[pin]);
  return Object.values(graph().nodes).some(n=>Object.values(n.inputs || {}).some(v=>ref(v)&&v.ref[0]===id&&v.ref[1]===pin));
}
function makePin(id,name,direction,type='exec') {
  const p=element('button','pin'+(type==='exec'?' execution':'')); p.type='button';
  Object.assign(p.dataset,{node:id,pin:name,direction,type});
  p.style.setProperty('--pin-color',color(type));
  p.setAttribute('aria-label',`${id} ${name} ${direction==='in'?'input':'output'} pin`);
  p.title=`${label(name)} · ${type} · Alt-click to disconnect`;
  if(isConnected(id,name,direction,type)) p.classList.add('connected');
  if(pending && samePin(pending,p.dataset)) p.classList.add('pending');
  p.onpointerdown=e=>{
    e.stopPropagation(); e.preventDefault();
    if(e.altKey) {disconnect(p.dataset);return;}
    beginConnection(p.dataset);
  };
  p.onkeydown=e=>{if(e.key==='Enter'||e.key===' ') {e.preventDefault();beginConnection(p.dataset);}};
  p.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();disconnect(p.dataset);};
  return p;
}
function beginConnection(data) {
  if(pending && !samePin(pending,data)) {connect(pending,data);return;}
  pending={...data}; document.body.classList.add('connecting'); updateWires();
  toast('Choose a compatible pin. Escape cancels.');
}
function half(id,pin,direction,type,text) {
  const e=element('div','pin-half '+(direction==='out'?'output':''));
  const p=makePin(id,pin,direction,type), name=element('span','pin-label',text);
  e.append(...(direction==='in'?[p,name]:[name,p])); return e;
}
function parseLiteral(raw,type) {
  type=typeBase(type);
  if(type==='integer') {if(!/^-?\d+$/.test(raw.trim())) throw Error('Enter a whole integer.'); const n=Number(raw);if(!Number.isSafeInteger(n))throw Error('Integer exceeds the browser’s safe range.');return n;}
  if(type==='float'){const value=Number(raw);if(!raw.trim()||!Number.isFinite(value))throw Error('Enter a finite float.');return value;}
  if(type==='bytes'){if(raw.startsWith('{')){const value=JSON.parse(raw);if(value.$type!=='bytes')throw Error('Expected bytes');atob(value.value);return value;}return {$type:'bytes',value:btoa(String.fromCharCode(...new TextEncoder().encode(raw)))};}
  if(['dict','set','reference:list','reference:tuple'].includes(type)){const value=JSON.parse(raw);if(type==='dict'){if(!object(value))throw Error('Expected dict');return value;}if(type==='set'||type==='reference:tuple'){const kind=type==='set'?'set':'tuple';if(value?.$type===kind&&Array.isArray(value.value))return value;if(!Array.isArray(value))throw Error('Enter a JSON list');return {$type:kind,value};}if(!Array.isArray(value))throw Error('Expected list');return value;}
  if(type.startsWith('reference:'))return JSON.parse(raw);
  return raw;
}
function valueEditor(id,pin,type,value) {
  const node=graph().nodes[id];
  if(ref(value)||param(value)) {
    const text=ref(value)?value.ref.join('.'):'ƒ '+value.param;
    const e=element('span','binding',text);e.title=text;return e;
  }
  if(typeBase(type)==='reference:Dataset') {
    return element('span','binding','Connect Dataset');
  }
  if(typeBase(type)==='reference:Point') {
    if(value?.$type==='Point')value=value.value;
    const row=element('div','point-value');
    for(const axis of ['x','y']) {
      const l=element('label','',axis.toUpperCase()),input=element('input');
      input.type='number';input.step='1';input.value=value?.[axis]??0;
      input.setAttribute('aria-label',`${id} ${pin} ${axis} value`);
      input.onpointerdown=e=>e.stopPropagation();
      input.onkeydown=e=>{e.stopPropagation();if(e.key==='Enter')input.blur();};
      input.onchange=()=>{try{const next=parseLiteral(input.value,'integer');change(()=>node.inputs[pin]={...(value||{x:0,y:0}),[axis]:next});}catch(error){input.setCustomValidity(error.message);input.reportValidity();}};
      input.oninput=()=>input.setCustomValidity('');l.append(input);row.append(l);
    }
    return row;
  }
  const e=element('input','inline-value');
  e.setAttribute('aria-label',`${id} ${pin} value`);
  const base=typeBase(type);
  e.type=base==='bool'?'checkbox':['integer','float'].includes(base)?'number':'text';
  if(['integer','float'].includes(base)) e.step=base==='integer'?'1':'any';
  if(base==='bool') e.checked=!!value;
  else e.value=object(value)||Array.isArray(value)?JSON.stringify(value):String(value ?? '');
  e.onpointerdown=event=>event.stopPropagation();
  e.onkeydown=event=>{event.stopPropagation();if(event.key==='Enter')e.blur();};
  e.onchange=()=>{
    try {
      let v=base==='bool'?e.checked:parseLiteral(e.value,type);
      if(base==='reference') {try {v=JSON.parse(e.value);} catch {v=e.value;}}
      change(()=>node.inputs[pin]=v);
    } catch(error) {e.setCustomValidity(error.message);e.reportValidity();report(error);}
  };
  e.oninput=()=>e.setCustomValidity(''); return e;
}
function debugToggle(node) {
  const toggle=button('●',event=>{event.stopPropagation();change(()=>node.debug=!node.debug);},'debug-toggle');
  toggle.title='Debug: pause before executing this node';
  toggle.setAttribute('aria-label','Debug breakpoint');toggle.setAttribute('aria-pressed',String(!!node.debug));
  toggle.onpointerdown=event=>event.stopPropagation();
  return toggle;
}
function renderNodes() {
  const box=$('nodes');box.replaceChildren();
  let index=0;
  for(const [id,node] of Object.entries(graph().nodes)) {
    const d=kind(node); if(!d) continue;
    const position=node.position || [40+index++*270,120];
    const category=nodeCategory(d).toLowerCase();
    const e=element('article',`node ${category}-node${(typeof selectedNodes!=='undefined'?selectedNodes.has(id):selected===id)?' selected':''}${graph().entry===id?' entry':''}`);
    e.dataset.id=id;e.style.left=position[0]+'px';e.style.top=position[1]+'px';
    const head=element('div','node-header');head.append(element('span','',d.pure?'+':d.name==='Start'?'▶':'◇'),element('strong','',node.title||d.title),element('small','',d.pure?'PURE':''));
    head.append(debugToggle(node));
    if(typeof activeDebug!=='undefined'&&activeDebug?.graph===graphName&&activeDebug.node===id)e.classList.add('debug-current');
    head.onpointerdown=event=>{
      if(event.button!==0)return;
      event.preventDefault();event.stopPropagation();selectNode(id,event.shiftKey);
      drag={kind:'node',id,startX:event.clientX,startY:event.clientY,position:[...position],members:typeof selectedNodes!=='undefined'?[...selectedNodes].filter(key=>graph().nodes[key]).map(key=>[key,[...(graph().nodes[key].position||[0,0])]]):[[id,[...position]]],moved:false};
    };
    e.onpointerdown=event=>{event.stopPropagation();selectNode(id,event.shiftKey);};
    const body=element('div','node-body');
    if(!d.pure) {
      const row=element('div','pin-row');row.append(half(id,'exec','in','exec',''));
      if(d.flows.length)row.append(half(id,d.flows[0],'out','exec',label(d.flows[0])));
      body.append(row);
      for(const flow of d.flows.slice(1)) {const row=element('div','pin-row');row.append(half(id,flow,'out','exec',label(flow)));body.append(row);}
    }
    for(const [pin,type] of Object.entries(d.inputs)) {
      const row=element('div','pin-row input-row');
      row.append(half(id,pin,'in',type,label(pin)));
      const value=Object.hasOwn(node.inputs,pin)?node.inputs[pin]:fallback(type,d.defaults,pin);
      row.append(valueEditor(id,pin,type,value));
      if(pin==='texture' && !ref(value) && !param(value)) {
        const tools=element('div','texture-tools');
        tools.append(textureThumbnail(value,id));
        tools.append(button('Browse…',()=>uploadTexture(id,pin),'texture-upload'),button('From clipboard',()=>pasteTexture(id,pin),'texture-upload'));
        row.classList.add('texture-row');row.append(tools);
      }
      body.append(row);
    }
    for(const [pin,type] of Object.entries(d.outputs)) {
      const row=element('div','pin-row');row.append(half(id,pin,'out',type,label(pin)));body.append(row);
    }
    e.append(head,body);box.append(e);
  }
}
function selectNode(id, additive=false) {
  if(typeof selectedNodes!=='undefined'){if(additive){selectedNodes.has(id)?selectedNodes.delete(id):selectedNodes.add(id);}else if(!selectedNodes.has(id)||!id)selectedNodes=new Set(id?[id]:[]);}
  selected=id;
  document.querySelectorAll('.node').forEach(n=>n.classList.toggle('selected',(typeof selectedNodes!=='undefined'?selectedNodes.has(n.dataset.id):n.dataset.id===id)));
  renderDetails();
}
function renderDetails() {
  const box=$('details-content');box.replaceChildren();
  const node=graph().nodes[selected];
  if(!node) {
    box.append(element('h3','',graphName),element('span','detail-tag',graphName===project.main?'MAIN GRAPH':'FUNCTION GRAPH'),element('p','',`${Object.keys(graph().nodes).length} nodes`),element('p','empty-state','Select a node to edit its details. Add nodes from the library; connect execution pins to set their order.'));
    if(graph().description)box.append(element('p','',graph().description));
    box.append(button('Graph parameters & outputs',()=>$('graph-settings').click()));return;
  }
  const d=kind(node);
  box.append(element('h3','',node.title||d.title),element('span','detail-tag',d.pure?'PURE FUNCTION':nodeCategory(d).toUpperCase()),element('p','',d.description || (d.pure?'Evaluates when another node reads its output.':'Follows the white execution connections.')));
  const titleLabel=element('label','','Node title'), title=element('input');title.value=node.title||d.title;
  title.onchange=()=>change(()=>node.title=title.value);titleLabel.append(title);box.append(titleLabel);
  box.append(element('p','',`ID: ${selected}`));
  if(!d.pure)box.append(button(graph().entry===selected?'✓ Graph entry':'Set as graph entry',()=>change(()=>graph().entry=selected)));
  for(const [pin,type] of Object.entries(d.inputs)) {
    const l=element('label','',label(pin)+' binding'),s=element('select','port-select');
    s.append(new Option(typeBase(type)==='reference:Dataset'?'Connect Dataset pin':'Literal value','literal'));
    for(const name of Object.keys(graph().parameters||{})) s.append(new Option('Parameter: '+name,'param:'+name));
    const value=node.inputs?.[pin];
    if(ref(value))s.append(new Option('Connected: '+value.ref.join('.'),'connected'));
    s.value=param(value)?'param:'+value.param:ref(value)?'connected':'literal';
    s.onchange=()=>change(()=>node.inputs[pin]=s.value.startsWith('param:')?{param:s.value.slice(6)}:defaultInput(node,pin));
    l.append(s);box.append(l);
  }
  box.append(button('Disconnect all pins',()=>change(()=>disconnectNode(selected))));
  box.append(button('Delete node',deleteSelected,'danger'));
}
function render() {if(typeof renderComments==='function')renderComments();if(typeof renderParameters==='function')renderParameters();renderDatasetList();renderGraphs();renderNodes();renderDetails();updateView();$('undo').disabled=!undo.length;$('redo').disabled=!redo.length;}
function updateView() {
  $('world').style.transform=`translate(${view.x}px,${view.y}px) scale(${view.z})`;
  $('canvas').style.backgroundSize=`${24*view.z}px ${24*view.z}px`;
  $('canvas').style.backgroundPosition=`${view.x}px ${view.y}px`;
  $('zoom').value=Math.round(view.z*100)+'%';requestAnimationFrame(updateWires);
}
function screenPoint(x,y) {const r=$('canvas').getBoundingClientRect();return {x:(x-r.left-view.x)/view.z,y:(y-r.top-view.y)/view.z};}
function samePin(a,b) {return ['node','pin','direction','type'].every(k=>a[k]===b[k]);}
function pinElement(id,pin,direction,type) {return [...document.querySelectorAll('.pin')].find(p=>p.dataset.node===id&&p.dataset.pin===pin&&p.dataset.direction===direction&&(type?p.dataset.type===type:p.dataset.type!=='exec'));}
function pinPoint(p) {const r=p.getBoundingClientRect();return screenPoint(r.x+r.width/2,r.y+r.height/2);}
function wire(a,b,stroke,onRemove,temporary=false) {
  const p=document.createElementNS('http://www.w3.org/2000/svg','path');
  const bend=Math.max(65,Math.abs(b.x-a.x)*.5);
  p.setAttribute('d',`M${a.x},${a.y} C${a.x+bend},${a.y} ${b.x-bend},${b.y} ${b.x},${b.y}`);
  p.setAttribute('stroke',stroke);p.classList.add('wire');if(temporary)p.classList.add('temp');
  if(onRemove) {p.onpointerdown=e=>e.stopPropagation();p.ondblclick=e=>{e.stopPropagation();onRemove();};p.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();onRemove();};}
  $('wires').append(p);
}
function updateWires() {
  $('wires').replaceChildren(); if(!project)return;
  for(const [id,node] of Object.entries(graph().nodes)) {
    for(const [flow,target] of Object.entries(node.next||{})) {
      const a=pinElement(id,flow,'out','exec'),b=pinElement(target,'exec','in','exec');
      if(a&&b)wire(pinPoint(a),pinPoint(b),color('exec'),()=>change(()=>delete node.next[flow]));
    }
    for(const [pin,value] of Object.entries(node.inputs||{}))if(ref(value)) {
      const a=pinElement(value.ref[0],value.ref[1],'out'),b=pinElement(id,pin,'in');
      if(a&&b)wire(pinPoint(a),pinPoint(b),color(a.dataset.type),()=>change(()=>node.inputs[pin]=defaultInput(node,pin)));
    }
  }
  if(pending) {
    const p=pinElement(pending.node,pending.pin,pending.direction,pending.type);
    if(p) {const origin=pinPoint(p),dest=screenPoint(pointer.x,pointer.y);wire(pending.direction==='out'?origin:dest,pending.direction==='out'?dest:origin,color(pending.type),null,true);}
  }
}
function compatible(a,b) {
  const out=typeBase(a),input=typeBase(b);
  if(out==='exec'||input==='exec')return out===input;
  return out===input||input==='reference'||out==='reference'||(out==='integer'&&input==='float');
}
function connect(a,b) {
  if(a.direction===b.direction) {toast('Connect an output pin to an input pin.');return;}
  const out=a.direction==='out'?a:b, input=a.direction==='in'?a:b;
  if(out.node===input.node) {toast('A node cannot connect to itself.');return;}
  if(!compatible(out.type,input.type)) {toast(`Cannot connect ${out.type} to ${input.type}.`);return;}
  change(()=>{
    if(out.type==='exec') {graph().nodes[out.node].next ||= {};graph().nodes[out.node].next[out.pin]=input.node;}
    else graph().nodes[input.node].inputs[input.pin]={ref:[out.node,out.pin]};
    pending=null;
  });
  document.body.classList.remove('connecting');toast('Connected. Double-click a wire to remove it.');
}
function disconnect(p) {
  change(()=>{
    if(p.type==='exec') {
      if(p.direction==='out')delete graph().nodes[p.node].next?.[p.pin];
      else for(const n of Object.values(graph().nodes)) for(const [f,target] of Object.entries(n.next||{}))if(target===p.node)delete n.next[f];
    } else if(p.direction==='in')graph().nodes[p.node].inputs[p.pin]=defaultInput(graph().nodes[p.node],p.pin);
    else for(const n of Object.values(graph().nodes))for(const [pin,value] of Object.entries(n.inputs||{}))if(ref(value)&&value.ref[0]===p.node&&value.ref[1]===p.pin)n.inputs[pin]=defaultInput(n,pin);
    pending=null;
  });document.body.classList.remove('connecting');
}
function stripReference(value,id) {
  if(ref(value)&&value.ref[0]===id)return null;
  if(Array.isArray(value))return value.map(v=>stripReference(v,id));
  if(object(value))return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,stripReference(v,id)]));
  return value;
}
function disconnectNode(id) {
  for(const [other,n] of Object.entries(graph().nodes)) {
    for(const [flow,target] of Object.entries(n.next||{}))if(other===id||target===id)delete n.next[flow];
    for(const [pin,value] of Object.entries(n.inputs||{})) {
      if((other===id&&ref(value))||(ref(value)&&value.ref[0]===id))n.inputs[pin]=defaultInput(n,pin);
      else n.inputs[pin]=stripReference(value,id);
    }
  }
  graph().outputs=stripReference(graph().outputs||{},id);
}
function deleteSelected() {
  const ids=typeof selectedNodes!=='undefined'?[...selectedNodes]:[selected];if(!ids.some(id=>graph().nodes[id]))return;
  change(()=>{for(const id of ids){disconnectNode(id);delete graph().nodes[id];}if(typeof selectedNodes!=='undefined')selectedNodes.clear();if(!graph().nodes[graph().entry])graph().entry=Object.keys(graph().nodes).find(id=>!kind(graph().nodes[id]).pure)||null;selected=null;pending=null;});
}
function fit() {
  const nodes=[...document.querySelectorAll('.node')];if(!nodes.length){view={x:30,y:10,z:1};updateView();return;}
  const positions=nodes.map(n=>({x:parseFloat(n.style.left),y:parseFloat(n.style.top),w:n.offsetWidth,h:n.offsetHeight}));
  const left=Math.min(...positions.map(p=>p.x)),top=Math.min(...positions.map(p=>p.y));
  const right=Math.max(...positions.map(p=>p.x+p.w)),bottom=Math.max(...positions.map(p=>p.y+p.h));
  const rect=$('canvas').getBoundingClientRect();const z=Math.min(1.15,Math.max(.25,Math.min((rect.width-100)/(right-left),(rect.height-130)/(bottom-top))));
  view={x:(rect.width-(right-left)*z)/2-left*z,y:(rect.height-(bottom-top)*z)/2-top*z-8,z};updateView();
}
function zoom(factor,x,y) {
  const r=$('canvas').getBoundingClientRect();x ??= r.x+r.width/2;y ??= r.y+r.height/2;
  const p=screenPoint(x,y),z=Math.max(.25,Math.min(2,view.z*factor));
  view={x:x-r.x-p.x*z,y:y-r.y-p.y*z,z};updateView();
}
async function uploadTexture(id,pin) {
  const picker=element('input');picker.type='file';picker.accept='.png,.jpg,.jpeg,.bmp,.webp';
  picker.onchange=async()=>{
    try {
      const file=picker.files[0];if(!file)return;if(file.size>5_000_000)throw Error('Texture must be under 5 MB.');
      const content=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});
      const sourceGraph=graphName;
      const saved=await api('texture',{name:file.name,content});change(()=>project.graphs[sourceGraph].nodes[id].inputs[pin]=saved.path);toast('Texture reference stored.');
    } catch(error) {report(error);}
  };picker.click();
}
async function pasteTexture(id,pin) {
  const sourceGraph=graphName;
  try {const saved=await api('clipboard',{});change(()=>project.graphs[sourceGraph].nodes[id].inputs[pin]=saved.path);toast('Clipboard image saved as a texture.');}
  catch(error){report(error);}
}
function textureThumbnail(path,id) {
  const valid=typeof path==='string' && path.trim();
  const b=button('',()=>showTexture(path,id),'texture-thumbnail');
  b.setAttribute('aria-label','Enlarge texture preview');
  b.title=valid?'Click to enlarge texture':'Choose a texture to preview';
  b.disabled=!valid;
  if(valid) {
    const img=element('img');img.alt='Texture thumbnail';
    img.src='/api/texture-preview?thumbnail=1&path='+encodeURIComponent(path);
    img.onerror=()=>{img.remove();b.textContent='?';b.disabled=true;b.title='Texture preview unavailable: '+path;};
    b.append(img);
  } else b.textContent='·';
  return b;
}
let textureContext=null;
function showTexture(path,id) {
  textureContext=graph().nodes[id]?.type==='FindPointOnScreen'?{graph:graphName,id}:null;
  $('texture-pick-help').textContent=textureContext?'Click the image to set Offset X / Y (replaces connected offset pins).':'';
  const img=$('texture-large');
  $('texture-caption').textContent=path;
  $('texture-dimensions').textContent='Loading…';
  $('texture-coordinates').textContent='Hover over the image for X / Y';
  img.hidden=true;
  img.onload=()=>{
    img.hidden=false;
    img.style.width=Math.max(180,Math.min(img.naturalWidth*4,900))+'px';
    $('texture-dimensions').textContent=img.naturalWidth+' × '+img.naturalHeight+' pixels';
  };
  img.onerror=()=>{$('texture-dimensions').textContent='Could not load this texture.';};
  img.src='/api/texture-preview?path='+encodeURIComponent(path);
  $('texture-dialog').showModal();
}
function texturePosition(e) {
  const img=e.currentTarget, r=img.getBoundingClientRect();
  if(!img.naturalWidth || !img.naturalHeight)return null;
  // object-fit: contain can letterbox when the dialog's height is constrained.
  // Map only the painted image, using original pixels rather than CSS pixels.
  const scale=Math.min(r.width/img.naturalWidth,r.height/img.naturalHeight);
  const width=img.naturalWidth*scale,height=img.naturalHeight*scale;
  const x=e.clientX-r.left-(r.width-width)/2,y=e.clientY-r.top-(r.height-height)/2;
  if(x<0||y<0||x>=width||y>=height)return null;
  return {x:Math.min(img.naturalWidth-1,Math.floor(x/scale)),y:Math.min(img.naturalHeight-1,Math.floor(y/scale))};
}
$('texture-large').onpointermove=e=>{
  const p=texturePosition(e);
  if(!p){resetTextureCoordinates();return;}
  $('texture-coordinates').textContent=`X: ${p.x}   Y: ${p.y}`;
};
$('texture-large').onclick=e=>{
  const p=texturePosition(e);
  if(!p||!textureContext)return;
  const node=project.graphs[textureContext.graph]?.nodes[textureContext.id];
  if(!node)return;
  change(()=>{node.inputs.offset_x=p.x;node.inputs.offset_y=p.y;});
  $('texture-pick-help').textContent=`Offset set to (${p.x}, ${p.y}). Click again to change it.`;
};
function resetTextureCoordinates(){$('texture-coordinates').textContent='Hover over the image for X / Y';}
$('texture-large').onpointerleave=resetTextureCoordinates;
$('close-texture').onclick=()=>$('texture-dialog').close();
$('texture-dialog').onclick=e=>{if(e.target===$('texture-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}};
async function save() {
  const version=revision,filename=$('filename').value.trim();
  try {await api('save',{filename,project});if(revision===version){dirty=false;$('save-state').textContent='Saved';}toast('Saved '+filename+'. It will reopen at startup.');}
  catch(error){report(error);}
}
function discard() {return !dirty||confirm('Discard unsaved changes? Save first to keep them.');}
async function openDialog() {
  try {
    const data=await api('files');$('file-list').replaceChildren();
    if(!data.files.length)$('file-list').append(element('p','','No saved projects yet. Save a graph or import a JSON file.'));
    for(const filename of data.files)$('file-list').append(button(filename,async()=>{
      if(!discard())return;
      try {const data=await api('load',{filename});setProject(data.project,filename);$('open-dialog').close();}catch(error){report(error);}
    }));$('open-dialog').showModal();
    $('file-list').append(element('p','','Examples'));
    for(const filename of data.examples||[])$('file-list').append(button(filename,async()=>{
      if(!discard())return;
      try {const data=await api('load',{filename,example:true});setProject(data.project,filename,false);$('open-dialog').close();}catch(error){report(error);}
    }));
  }catch(error){report(error);}
}
async function run() {
  try {const baseline=JSON.stringify(project.datasets||{});const result=await api('run',{project,parameters:project.editor?.arguments||{}});datasetRun={id:result.run_id,baseline};debugRunId=result.run_id;appliedDebugEdits.clear();setRunning(true);await poll();}
  catch(error){report(error);}
}
function setRunning(value) {running=value;$('run').disabled=value;$('stop').disabled=!value;$('run-state').textContent=value?'Running…':'Ready';}
async function poll() {
  if(polling)return;polling=true;
  try {const data=await api('events?after='+cursor);for(const event of data.events){log(event.kind,event.message,event.time);cursor=event.id;}setRunning(data.running);if(data.status){applyDebugEdits(data.status);updateManualPrompt(data.status.manual);updateDebugPrompt(data.status.debug,data.status.settings);$('run-state').textContent=data.status.state+(data.running?' · '+data.status.text:'');$('pause-run').disabled=!data.running||!!data.status.manual||!!data.status.debug;$('pause-run').textContent=['paused','pausing'].includes(data.status.state)?'Resume':'Pause';}if(!data.running)await applyRunDatasets();}
  catch(error){$('run-state').textContent='Server disconnected';}
  finally{polling=false;}
}
$('canvas').onpointerdown=e=>{
  if(e.button!==0 && e.button!==1)return;
  if(e.target.closest('button,input,.node,.canvas-controls,.graph-comment'))return;
  e.preventDefault();selectNode(null);pending=null;document.body.classList.remove('connecting');
  drag={kind:'pan',startX:e.clientX,startY:e.clientY,x:view.x,y:view.y};updateWires();
};
$('canvas').ondragover=e=>{if([...e.dataTransfer.types].some(t=>['application/x-autoflow-node','application/x-autoflow-dataset','application/x-autoflow-function','application/x-autoflow-parameter'].includes(t))){e.preventDefault();e.dataTransfer.dropEffect='copy';}};
$('canvas').ondrop=e=>{
  e.preventDefault();$('canvas').classList.remove('library-drop');
  const parameter=e.dataTransfer.getData('application/x-autoflow-parameter');
  if(parameter&&Object.hasOwn(graph().parameters||{},parameter)){const p=screenPoint(e.clientX,e.clientY);addNode('FunctionParameter',[p.x,p.y],{},{parameter});return;}
  const fn=e.dataTransfer.getData('application/x-autoflow-function');
  if(fn&&Object.hasOwn(project.graphs,fn)){const p=screenPoint(e.clientX,e.clientY);addNode('FunctionCall',[p.x,p.y],{},{function:fn});return;}
  const name=e.dataTransfer.getData('application/x-autoflow-dataset');
  if(name&&Object.hasOwn(project.datasets,name)){const p=screenPoint(e.clientX,e.clientY);addNode('GetDataset',[p.x-20,p.y-15],{name});return;}
  const type=e.dataTransfer.getData('application/x-autoflow-node');
  if(!Object.hasOwn(catalog,type))return;
  const p=screenPoint(e.clientX,e.clientY);addNode(type,[p.x-20,p.y-15]);
};
window.addEventListener('pointermove',e=>{
  pointer={x:e.clientX,y:e.clientY};
  if(drag?.kind==='node') {
    const dx=(e.clientX-drag.startX)/view.z,dy=(e.clientY-drag.startY)/view.z;
    if(!drag.moved && Math.abs(dx)+Math.abs(dy)>2){remember();drag.moved=true;}
    if(!drag.moved)return;
    for(const [id,origin] of drag.members){const position=[origin[0]+dx,origin[1]+dy];graph().nodes[id].position=position;const n=[...document.querySelectorAll('.node')].find(n=>n.dataset.id===id);n.style.left=position[0]+'px';n.style.top=position[1]+'px';}updateWires();
  } else if(drag?.kind==='pan') {view.x=drag.x+e.clientX-drag.startX;view.y=drag.y+e.clientY-drag.startY;updateView();}
  else if(pending)updateWires();
});
window.addEventListener('pointerup',e=>{
  if(drag?.kind==='node' && drag.moved) {mark();$('undo').disabled=false;$('redo').disabled=true;}
  drag=null;
  const pin=document.elementFromPoint(e.clientX,e.clientY)?.closest('.pin');
  if(pending&&pin&&!samePin(pending,pin.dataset))connect(pending,pin.dataset);
});
window.addEventListener('pointercancel',()=>{drag=null;pending=null;updateWires();});
$('canvas').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1.1:1/1.1,e.clientX,e.clientY);},{passive:false});
$('canvas').oncontextmenu=e=>{if(e.target.closest('.pin,.wire,.node'))return;e.preventDefault();$('search').focus();toast('Choose a node from the library to add it.');};
$('search').oninput=renderPalette;
$('show-details').onclick=()=>document.querySelector('.details').classList.toggle('show');
$('hide-details').onclick=()=>document.querySelector('.details').classList.remove('show');
$('zoom-in').onclick=()=>zoom(1.15);$('zoom-out').onclick=()=>zoom(1/1.15);$('fit').onclick=fit;
$('undo').onclick=()=>restoreHistory(undo,redo);$('redo').onclick=()=>restoreHistory(redo,undo);
$('save').onclick=save;$('open').onclick=openDialog;$('run').onclick=run;
const pauseRun=button('Pause',async()=>{try{await api('pause',{});}catch(error){report(error);}});pauseRun.id='pause-run';pauseRun.disabled=true;$('stop').before(pauseRun);
$('stop').onclick=async()=>{try{await api('stop',{});}catch(error){report(error);}};
$('filename').oninput=mark;
$('clear-console').onclick=()=>$('console-lines').replaceChildren();
const logBox=$('console-lines');
logBox.tabIndex=0;
logBox.addEventListener('pointerdown',()=>logBox.focus({preventScroll:true}));
logBox.addEventListener('keydown',event=>{
  // Leave native text copy alone; never route log shortcuts to graph nodes.
  event.stopPropagation();
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='a'){
    event.preventDefault();const range=document.createRange();range.selectNodeContents(logBox);
    const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
  }
});
async function copyLog(){
  const text=[...logBox.children].map(line=>[...line.children].map(child=>child.textContent).join(' ')).join('\n');
  try{await navigator.clipboard.writeText(text);toast('Output Log copied');}
  catch(error){
    const field=element('textarea');field.value=text;field.style.position='fixed';field.style.opacity='0';document.body.append(field);field.select();
    const copied=document.execCommand('copy');field.remove();logBox.focus({preventScroll:true});
    if(copied)toast('Output Log copied');else report(Error('Could not copy. Select log text and press Ctrl+C.'));
  }
}
const copyLogButton=button('Copy Log',copyLog);copyLogButton.id='copy-log';$('clear-console').before(copyLogButton);
$('export').onclick=async()=>{try{const data=await api('export',{project});downloadData(data.content,($('filename').value||'project.json').replace(/\.json$/i,'')+'.zip');toast('Exported project, datasets and referenced assets.');}catch(error){report(error);}};
$('new-project').onclick=()=>{
  if(!discard())return;
  setProject({version:1,schema_revision:3,name:'Untitled',main:'Main',graphs:{Main:{parameters:{},outputs:{},entry:'start',nodes:{start:{type:'Start',inputs:{},next:{},position:[100,120]}}}}},'untitled.json',false);
};
$('import').onclick=()=>$('import-file').click();
$('import-file').onchange=async e=>{
  try {
    const file=e.target.files[0];if(!file||!discard())return;
    const data=file.name.toLowerCase().endsWith('.zip')?await api('bundle-import',{content:await fileBase64(file)}):await api('import',{project:JSON.parse(await file.text())});setProject(data.project,file.name.replace(/\.zip$/i,'.json'),false);$('open-dialog').close();toast('Imported. Save to reopen this graph at startup.');
  }catch(error){report(error);}finally{e.target.value='';}
};
$('add-graph').onclick=()=>{$('name-error').textContent='';$('graph-name').value='';$('name-dialog').showModal();$('graph-name').focus();};
$('cancel-name').onclick=()=>$('name-dialog').close();
$('name-form').onsubmit=e=>{
  e.preventDefault();const name=$('graph-name').value.trim();
  if((typeof validName==='function'&&!validName(name))||Object.hasOwn(project.graphs,name)){$('name-error').textContent='Use a unique function name containing letters, digits and underscores.';return;}
  change(()=>{project.graphs[name]={entry:'start',parameters:{},outputs:{},nodes:{start:{type:'Start',inputs:{},next:{},position:[100,120]}}};graphName=name;selected=null;});
  $('name-dialog').close();fit();
};
$('graph-settings').onclick=()=>{
  $('parameters').value=JSON.stringify(graph().parameters||{},null,2);$('outputs').value=JSON.stringify(graph().outputs||{},null,2);
  $('run-arguments').value=JSON.stringify(project.editor?.arguments||{},null,2);$('settings-error').textContent='';$('settings-dialog').showModal();
};
$('close-settings').onclick=()=>$('settings-dialog').close();
$('settings-form').onsubmit=e=>{
  e.preventDefault();
  try {
    const parameters=JSON.parse($('parameters').value),outputs=JSON.parse($('outputs').value),args=JSON.parse($('run-arguments').value);
    if(!object(parameters)||!object(outputs)||!object(args))throw Error('All three fields must be JSON objects.');
    if(Object.values(parameters).some(v=>typeof v!=='string'))throw Error('Parameter types must be strings.');
    change(()=>{graph().parameters=parameters;graph().outputs=outputs;project.editor ||= {};project.editor.arguments=args;});$('settings-dialog').close();
  }catch(error){$('settings-error').textContent=error.message;}
};
window.addEventListener('keydown',e=>{
  const editing=e.target.closest('input,textarea,select');
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s') {e.preventDefault();if(editing)e.target.blur();save();return;}
  if(e.key==='Escape') {pending=null;document.body.classList.remove('connecting');updateWires();}
  if(editing||document.querySelector('dialog[open]'))return;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?restoreHistory(redo,undo):restoreHistory(undo,redo);}
  else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();restoreHistory(redo,undo);}
  else if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();deleteSelected();}
  else if(e.key.toLowerCase()==='f')fit();
});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('resize',()=>requestAnimationFrame(updateWires));
'use strict';
let activeDataset=null,datasetPage=0,datasetSort={},datasetRun=null,pendingDatasetResult=null;
async function applyRunDatasets(){if(!datasetRun)return;const run=datasetRun;const result=await api('run-result',{run_id:run.id});if(datasetRun!==run||result.datasets===null)return;datasetRun=null;if(JSON.stringify(result.datasets)===run.baseline)return;if(JSON.stringify(project.datasets||{})===run.baseline){change(()=>project.datasets=result.datasets);renderDatasetTable();log('info','Dataset changes applied. Save to keep them.');}else{pendingDatasetResult=result.datasets;$('apply-dataset-result').hidden=false;log('info','Dataset edited during run. Apply the run result using the button, or keep your edits.');}}
function downloadData(content,name){const bytes=Uint8Array.from(atob(content),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes]));const a=element('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function fileBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file);});}
function renderDatasetList(){
 const box=$('dataset-list');box.replaceChildren();
 for(const [name,table] of Object.entries(project.datasets||{})){
  const row=element('div','dataset-entry');
  const open=button(name+' - '+table.rows.length+' rows',()=>{activeDataset=name;datasetPage=0;$('dataset-search').value='';renderDatasetTable();$('dataset-dialog').showModal();});
  open.draggable=true;open.title='Click to edit; drag onto the canvas to add Get Dataset';
  open.ondragstart=e=>{e.dataTransfer.setData('application/x-autoflow-dataset',name);e.dataTransfer.effectAllowed='copy';$('canvas').classList.add('library-drop');};
  open.ondragend=()=>$('canvas').classList.remove('library-drop');
  const add=button('+',()=>addNode('GetDataset',undefined,{name}));add.setAttribute('aria-label','Add Get Dataset '+name);add.title='Add Get Dataset to graph';
  row.append(open,add);box.append(row);
 }
}
function datasetChange(fn){change(fn);renderDatasetTable();}
function datasetColumnType(data,column){
 const explicit=({text:'string',number:'float',boolean:'bool'})[data.types?.[column]]||data.types?.[column];
 if(['string','integer','float','bool','bytes'].includes(explicit))return explicit;
 const values=data.rows.map(row=>row[column]).filter(value=>value!==null&&value!==undefined&&value!=='');
 if(!values.length)return 'string';
 const guess=value=>{if(value?.$type==='bytes')return 'bytes';if(typeof value==='boolean')return 'bool';if(typeof value==='number')return Number.isFinite(value)?(Number.isInteger(value)?'integer':'float'):'string';if(typeof value!=='string')return 'string';if(/^(true|false)$/i.test(value))return 'bool';if(/^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$/.test(value)&&Number.isFinite(Number(value)))return /[.eE]/.test(value)?'float':'integer';return 'string';};
 const types=new Set(values.map(guess));if(types.size&&[...types].every(t=>['integer','float'].includes(t)))return types.has('float')?'float':'integer';return types.size===1?[...types][0]:'string';
}
function datasetCellValue(value,type){
 const text=String(value??'');
 if(type==='string')return text;
 if(type==='bool'){if(!/^(true|false)$/i.test(text))throw Error('Enter true or false');return text.toLowerCase()==='true';}
 return parseLiteral(text,type);
}
function renderDatasetTable(){
 const data=project.datasets?.[activeDataset];if(!data){if($('dataset-dialog').open)$('dataset-dialog').close();return;}
 $('dataset-title').textContent=activeDataset;$('dataset-table').replaceChildren();
 const query=$('dataset-search').value.toLowerCase(),rows=data.rows.map((row,index)=>({row,index})).filter(({row})=>Object.values(row).some(v=>String(v??'').toLowerCase().includes(query)));
 datasetPage=Math.max(0,Math.min(datasetPage,Math.ceil(rows.length/100)-1));
 const table=element('table'),head=element('tr');head.append(element('th','','Index'));
 for(const column of data.columns){const th=element('th');th.append(button(column+(datasetSort.column===column?(datasetSort.descending?' ↓':' ↑'):''),async()=>{try{const name=activeDataset,baseline=JSON.stringify(data),descending=datasetSort.column===column?!datasetSort.descending:false;const result=await api('dataset-sort',{dataset:data,column,descending});if(JSON.stringify(project.datasets[name])!==baseline)throw Error('Dataset changed while sorting; try again.');datasetSort={column,descending};datasetChange(()=>project.datasets[name]=result.dataset);}catch(e){report(e);}}));const type=element('select');for(const value of ['bool','integer','float','string','bytes']){const option=element('option','',value);option.value=value;type.append(option);}type.value=datasetColumnType(data,column);type.setAttribute('aria-label',column+' column type');
 type.onchange=()=>{try{const values=data.rows.map(row=>datasetCellValue(object(row[column])?JSON.stringify(row[column]):row[column],type.value));datasetChange(()=>{data.types={...data.types,[column]:type.value};data.rows.forEach((row,index)=>row[column]=values[index]);});}catch(e){report(e);renderDatasetTable();}};th.append(type);head.append(th);}head.append(element('th','','Actions'));table.append(head);
 for(const {row,index} of rows.slice(datasetPage*100,(datasetPage+1)*100)){const tr=element('tr');tr.append(element('td','',index));for(const column of data.columns){const td=element('td'),input=element('input'),type=datasetColumnType(data,column);input.value=object(row[column])?JSON.stringify(row[column]):String(row[column]??'');input.setAttribute('aria-label',column+' row '+index);
 input.onchange=()=>{try{const value=datasetCellValue(input.value,type);datasetChange(()=>{data.types={...data.types,[column]:type};data.rows[index][column]=value;});}catch(e){report(e);renderDatasetTable();}};td.append(input);tr.append(td);}
 const actions=element('td');actions.append(button('Delete',()=>datasetChange(()=>data.rows.splice(index,1))));tr.append(actions);table.append(tr);}
 $('dataset-table').append(table);$('dataset-page').textContent=rows.length+' matching / '+data.rows.length+' rows · Page '+(datasetPage+1);$('dataset-prev').disabled=datasetPage===0;$('dataset-next').disabled=(datasetPage+1)*100>=rows.length;
}
$('add-dataset').onclick=()=>{$('dataset-create-error').textContent='';$('dataset-create').showModal();};
$('dataset-create-cancel').onclick=()=>$('dataset-create').close();
$('dataset-create-form').onsubmit=e=>{e.preventDefault();const name=$('dataset-name').value.trim(),columns=$('dataset-columns').value.split(',').map(c=>c.trim());if(!name||['__proto__','constructor','prototype'].includes(name)||Object.hasOwn(project.datasets,name)||columns.some(c=>!c)||new Set(columns).size!==columns.length){$('dataset-create-error').textContent='Use a new dataset name and unique nonempty columns.';return;}change(()=>project.datasets[name]={columns,rows:[]});$('dataset-create').close();activeDataset=name;datasetPage=0;$('dataset-search').value='';renderDatasetTable();$('dataset-dialog').showModal();};
$('dataset-close').onclick=()=>$('dataset-dialog').close();
$('dataset-search').oninput=()=>{datasetPage=0;renderDatasetTable();};
$('dataset-prev').onclick=()=>{datasetPage--;renderDatasetTable();};$('dataset-next').onclick=()=>{datasetPage++;renderDatasetTable();};
$('dataset-add-row').onclick=()=>datasetChange(()=>{const d=project.datasets[activeDataset];d.rows.push(Object.fromEntries(d.columns.map(c=>[c,fallback(datasetColumnType(d,c))])));});
$('dataset-add-column').onclick=()=>{const column=$('dataset-new-column').value.trim(),d=project.datasets[activeDataset];if(!column||d.columns.includes(column)){report(Error('Enter a unique column name'));return;}datasetChange(()=>{d.columns.push(column);d.rows=d.rows.map(r=>Object.fromEntries([...Object.entries(r),[column,'']]));});$('dataset-new-column').value='';};
$('dataset-undo').onclick=()=>{restoreHistory(undo,redo);renderDatasetTable();};
for(const ext of ['csv','xlsx'])$('dataset-'+ext).onclick=async()=>{try{const data=await api('dataset-export',{dataset:project.datasets[activeDataset],extension:'.'+ext});downloadData(data.content,activeDataset+'.'+ext);}catch(e){report(e);}};
$('import-dataset').onclick=()=>$('dataset-file').click();
$('dataset-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;const before=project,content=await fileBase64(file);const result=await api('dataset-import',{name:file.name,content});if(project!==before)throw Error('Project changed during import. Try again.');let name=file.name.replace(/\.[^.]+$/,'')||'Data';if(['__proto__','constructor','prototype'].includes(name))name='Data';const base=name;for(let n=2;Object.hasOwn(project.datasets,name);n++)name=base+' '+n;change(()=>project.datasets[name]=result.dataset);activeDataset=name;datasetPage=0;$('dataset-search').value='';renderDatasetTable();$('dataset-dialog').showModal();if(result.sheets.length>1)log('info','Imported first Excel sheet: '+result.sheets[0]+'. LoadDataset node can select another sheet by name.');}catch(error){report(error);}finally{e.target.value='';}};
$('apply-dataset-result').onclick=()=>{if(!pendingDatasetResult)return;change(()=>{project.datasets=pendingDatasetResult;});pendingDatasetResult=null;$('apply-dataset-result').hidden=true;renderDatasetTable();};

(async()=>{
  try {const data=await api('bootstrap');catalog=Object.fromEntries(data.nodes.map(n=>[n.name,n]));renderPalette();setProject(data.project,data.filename,data.saved!==false);if(['GetDataset','FunctionCall','StringAppend'].some(name=>!catalog[name]))report(Error('AutoFlow is still running an older backend. Restart AutoFlow to enable the latest nodes. Save or export unsaved edits before refreshing.'));if(data.warning)report(Error(data.warning));await poll();setInterval(poll,350);}
  catch(error){log('error',error.message);$('details-content').textContent='Could not load the editor. Restart AutoFlow and refresh.';}
})();

let activeManualId=null;
const manualPanel=element('section');manualPanel.id='manual-prompt';manualPanel.hidden=true;
manualPanel.setAttribute('role','region');manualPanel.setAttribute('aria-label','Manual interaction');
const manualText=element('p');
async function manualAnswer(choice){try{await api('manual-response',{id:activeManualId,choice});manualPanel.hidden=true;}catch(error){report(error);}}
manualPanel.append(element('strong','','Your action needed'),manualText,button('Continue',()=>manualAnswer('success')),button('Ignore',()=>manualAnswer('failed')),button('Stop',()=>api('stop',{}).catch(report)));
document.body.append(manualPanel);
function updateManualPrompt(request){activeManualId=request?.id||null;manualPanel.hidden=!request;manualText.textContent=request?.prompt||'';}

let activeDebug=null;
const debugPanel=element('section');debugPanel.id='debug-prompt';debugPanel.hidden=true;
debugPanel.setAttribute('role','region');debugPanel.setAttribute('aria-label','Node debugger');
const debugTitle=element('strong'),debugPreview=element('p'),debugInputs=element('pre');
async function resumeDebug(delay=0){try{debugContinue.disabled=debugDelay.disabled=true;await api('debug-continue',{id:activeDebug.id,delay});}catch(error){report(error);debugContinue.disabled=debugDelay.disabled=false;}}
const debugContinue=button('Continue (execute node)',()=>resumeDebug());
const debugDelay=button('Resume in 2s',()=>resumeDebug(2));
const debugCapture=button('Capture offset',async()=>{try{await api('debug-capture',{id:activeDebug.id});await poll();}catch(error){report(error);}});
debugPanel.append(debugTitle,debugPreview,debugInputs,element('p','','Continue executes the node normally. Stop ends the run before this node executes.'),
  button('Show node',()=>{if(!activeDebug)return;graphName=activeDebug.graph;selected=activeDebug.node;if(typeof selectedNodes!=='undefined')selectedNodes=new Set([selected]);render();fit();}),
  debugCapture,debugContinue,debugDelay,button('Stop',()=>api('stop',{}).catch(report)));
document.body.append(debugPanel);
function applyDebugEdits(status){
  if(!debugRunId||status.run_id!==debugRunId)return;
  for(const edit of status.debug_edits||[]){
    if(appliedDebugEdits.has(edit.id))continue;appliedDebugEdits.add(edit.id);
    const node=project.graphs[edit.graph]?.nodes[edit.node];
    const keys=['x','y'],same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
    if(node?.type==='OffsetPoint'&&keys.every(key=>same(node.inputs?.[key]??0,edit.changes[key])))continue;
    if(node?.type!=='OffsetPoint'||!keys.every(key=>same(node.inputs?.[key]??0,edit.previous[key]))){
      log('error',`Captured offset X=${edit.changes.x}, Y=${edit.changes.y} for ${edit.graph}/${edit.node}; the editor node changed during the run, so apply these values manually.`);continue;
    }
    change(()=>{node.inputs ||= {};Object.assign(node.inputs,edit.changes);});
    log('info',`Captured offset X=${edit.changes.x}, Y=${edit.changes.y} applied to ${edit.graph}/${edit.node}. Save the project to keep it.`);
  }
}
function updateDebugPrompt(request,settings={}){
  activeDebug=request||null;debugPanel.hidden=!request;
  for(const node of document.querySelectorAll('.node'))node.classList.toggle('debug-current',!!request&&request.graph===graphName&&node.dataset.id===request.node);
  if(!request)return;
  debugPreview.textContent=(request.resuming?`Resuming in ${(request.resume_in_ms/1000).toFixed(1)} seconds.\n`:'')+(request.captured?`Captured X=${request.captured.x}, Y=${request.captured.y}.\n`:'')+(request.preview||'Paused before execution.');
  debugContinue.disabled=debugDelay.disabled=debugCapture.disabled=!!request.resuming;
  debugCapture.hidden=!request.can_capture;
  debugCapture.textContent='Capture offset · '+(settings.debug_capture_key||'F6');
  debugContinue.textContent='Continue · '+(settings.debug_resume_key||'F10');
  debugDelay.textContent='Resume in 2s · '+(settings.debug_delay_key||'Shift+F10');
  debugTitle.textContent=`Debug: ${request.graph} / ${request.title} (${request.node})`;
  debugInputs.textContent=request.inputs.length?request.inputs.map(input=>`${input.name} (${input.deferred?'deferred binding; not evaluated':input.type}): ${input.value}`).join('\n'):'This node has no inputs.';
}
