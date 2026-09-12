'use strict';
let selectedNodes=new Set(), copiedNodes=null, commentDrag=null;
const signatureTypes=['bool','integer','float','string','bytes','set','dict','reference','reference:Dataset','reference:Point','reference:list','reference:tuple'];
function functionNodeKind(node,owner=graph()){
 const base=catalog[node.type];if(!base)return null;
 if(node.type==='FunctionParameter')return {...base,title:'Parameter: '+node.parameter,inputs:{},outputs:{value:owner.parameters?.[node.parameter]||'reference'}};
 if(node.type==='FunctionReturn')return {...base,title:'Return',inputs:owner.return_types||{},outputs:{}};
 if(node.type==='FunctionCall'){
  const target=project.graphs[node.function];
  return {...base,title:'Call '+node.function,description:target?.description||base.description,inputs:target?.parameters||{},outputs:target?.return_types||Object.fromEntries(Object.keys(target?.outputs||{}).map(k=>[k,'reference']))};
 }
 return null;
}
function freshId(nodes,base){let id=base,n=1;while(Object.hasOwn(nodes,id))id=base+'_'+n++;return id;}
function validName(name){return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name)&&!['__proto__','constructor','prototype'].includes(name);}
function rewrite(value,visit){
 const changed=visit(value);if(changed!==value)return changed;
 if(Array.isArray(value))return value.map(v=>rewrite(v,visit));
 if(object(value))return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,rewrite(v,visit)]));
 return value;
}

// A row editor keeps signatures visible without requiring hand-written JSON.
const settings=$('settings-form');
settings.replaceChildren();
const heading=element('div','dialog-heading');heading.append(element('h2','','Function settings'),button('Close',()=>$('settings-dialog').close()));settings.append(heading);
const functionName=element('input');functionName.required=true;functionName.setAttribute('aria-label','Function name');
const nameLabel=element('label','','Name');nameLabel.append(functionName);settings.append(nameLabel);
const description=element('textarea');description.rows=2;description.setAttribute('aria-label','Function description');
const descriptionLabel=element('label','','Description');descriptionLabel.append(description);settings.append(descriptionLabel);
const typeList=element('datalist');typeList.id='signature-types';for(const type of signatureTypes){const option=element('option');option.value=type;typeList.append(option);}settings.append(typeList);
const parameterRows=element('div','signature-rows'),returnRows=element('div','signature-rows');
function signatureRow(container,name='',type='string',original=name){
 const row=element('div','signature-row'),key=element('input'),kindInput=element('input');
 key.value=name;key.placeholder='Name';key.setAttribute('aria-label','Variable name');key.dataset.original=original;
 kindInput.value=type;kindInput.setAttribute('list','signature-types');kindInput.setAttribute('aria-label','Variable type');
 row.append(key,kindInput,button('Remove',()=>row.remove()));container.append(row);
}
for(const [title,container] of [['Parameters',parameterRows],['Return values',returnRows]]){
 const head=element('div','signature-heading');head.append(element('strong','',title),button('Add '+title.toLowerCase(),()=>signatureRow(container)));settings.append(head,container);
}
const args=element('textarea');args.rows=3;args.setAttribute('aria-label','Main run arguments');
const argsLabel=element('label','','Main run arguments (JSON)');argsLabel.append(args);settings.append(argsLabel);
const settingsError=element('p','error');settings.append(settingsError);
const actions=element('div','dialog-actions'),deleteFunction=button('Delete function',()=>{
 try{
  if(graphName===project.main)throw Error('The main graph cannot be deleted.');
  const callers=Object.entries(project.graphs).filter(([name,g])=>name!==graphName&&Object.values(g.nodes).some(n=>n.function===graphName||(n.type==='CallFunction'&&n.inputs?.graph===graphName)));
  if(callers.length)throw Error('Remove calls from '+callers.map(([name])=>name).join(', ')+' before deleting this function.');
  change(()=>{delete project.graphs[graphName];graphName=project.main;selected=null;selectedNodes.clear();});$('settings-dialog').close();fit();
 }catch(e){settingsError.textContent=e.message;}
});
const apply=element('button','save','Apply');apply.type='submit';actions.append(deleteFunction,apply);settings.append(actions);
function readSignature(container){
 const types={},renames={};
 for(const row of container.children){const [key,type]=row.querySelectorAll('input'),name=key.value.trim(),kind=type.value.trim();
  if(!validName(name)||Object.hasOwn(types,name))throw Error('Variable names must be unique identifiers.');
  if(!signatureTypes.includes(kind)&&!/^reference:[A-Za-z_][\w.]*\??$/.test(kind))throw Error('Choose a supported type or reference:ClassName.');
  types[name]=kind;if(key.dataset.original)renames[key.dataset.original]=name;
 }
 return {types,renames};
}
$('graph-settings').onclick=()=>{
 const g=graph();functionName.value=graphName;description.value=g.description||'';parameterRows.replaceChildren();returnRows.replaceChildren();
 for(const [name,type] of Object.entries(g.parameters||{}))signatureRow(parameterRows,name,type);
 const returns=g.return_types||Object.fromEntries(Object.entries(g.outputs||{}).map(([name,value])=>[name,ref(value)?kind(g.nodes[value.ref[0]])?.outputs[value.ref[1]]||'reference':typeof value==='string'?'string':'reference']));
 for(const [name,type] of Object.entries(returns))signatureRow(returnRows,name,type);
 args.value=JSON.stringify(project.editor?.arguments||{},null,2);settingsError.textContent='';deleteFunction.disabled=graphName===project.main;$('settings-dialog').showModal();
};
settings.onsubmit=e=>{
 e.preventDefault();try{
  const name=functionName.value.trim(),oldName=graphName,g=graph(),params=readSignature(parameterRows),returns=readSignature(returnRows),argumentsValue=JSON.parse(args.value);
  if(!validName(name)||(name!==oldName&&Object.hasOwn(project.graphs,name)))throw Error('Use a unique function name.');
  if(!object(argumentsValue))throw Error('Run arguments must be a JSON object.');
  change(()=>{
   if(name!==oldName){project.graphs[name]=g;delete project.graphs[oldName];if(project.main===oldName)project.main=name;graphName=name;}
   g.description=description.value;g.parameters=params.types;g.return_types=returns.types;
   for(const [id,node] of Object.entries(g.nodes))if(node.type==='FunctionParameter'){
    const renamed=params.renames[node.parameter]||node.parameter;
    if(!Object.hasOwn(params.types,renamed)){disconnectNode(id);delete g.nodes[id];}else node.parameter=renamed;
   }
   const remapParam=value=>param(value)?(params.renames[value.param]?{param:params.renames[value.param]}:Object.hasOwn(params.types,value.param)?value:null):value;
   for(const node of Object.values(g.nodes))node.inputs=rewrite(node.inputs||{},remapParam);
   g.outputs=rewrite(g.outputs||{},remapParam);
   for(const [index,paramName] of Object.keys(params.types).entries())if(!Object.values(g.nodes).some(n=>n.type==='FunctionParameter'&&n.parameter===paramName)){
    g.nodes[freshId(g.nodes,'parameter_'+paramName)]={type:'FunctionParameter',parameter:paramName,inputs:{},position:[60,260+index*130]};
   }
   let returnNodes=Object.entries(g.nodes).filter(([,n])=>n.type==='FunctionReturn');
   if(!returnNodes.length){const id=freshId(g.nodes,'return');g.nodes[id]={type:'FunctionReturn',inputs:copy(g.outputs||{}),position:[850,120]};returnNodes=[[id,g.nodes[id]]];
    // Connect a simple graph's terminal Then path; branch graphs can wire Return explicitly.
    const terminals=Object.entries(g.nodes).filter(([key,n])=>key!==id&&kind(n)?.flows.includes('then')&&!n.next?.then);
    for(const [,node] of terminals){node.next ||= {};node.next.then=id;}
   }
   for(const [,node] of returnNodes){const old=node.inputs||{};node.inputs=Object.fromEntries(Object.entries(returns.types).map(([key,type])=>{const previous=Object.keys(returns.renames).find(k=>returns.renames[k]===key)||key;return [key,Object.hasOwn(old,previous)?old[previous]:fallback(type)];}));}
   g.outputs={};
   for(const owner of Object.values(project.graphs)){
    const callIds=new Set();
    for(const [id,node] of Object.entries(owner.nodes)){
     if(node.type==='CallFunction'&&node.inputs?.graph===oldName)node.inputs.graph=name;
     if(node.type==='FunctionCall'&&node.function===oldName){node.function=name;callIds.add(id);const old=node.inputs||{};node.inputs=Object.fromEntries(Object.entries(params.types).map(([key,type])=>{const previous=Object.keys(params.renames).find(k=>params.renames[k]===key)||key;return [key,Object.hasOwn(old,previous)?old[previous]:fallback(type)];}));}
    }
    const remapReturn=value=>ref(value)&&callIds.has(value.ref[0])?(returns.renames[value.ref[1]]?{ref:[value.ref[0],returns.renames[value.ref[1]]]}:Object.hasOwn(returns.types,value.ref[1])?value:null):value;
    for(const node of Object.values(owner.nodes))node.inputs=rewrite(node.inputs||{},remapReturn);
    owner.outputs=rewrite(owner.outputs||{},remapReturn);
   }
   project.editor ||= {};project.editor.arguments=project.main===name?Object.fromEntries(Object.entries(argumentsValue).map(([key,value])=>[params.renames[key]||key,value])):argumentsValue;selected=null;selectedNodes.clear();
  });$('settings-dialog').close();fit();
 }catch(error){settingsError.textContent=error.message;}
};
const originalCreate=$('name-form').onsubmit;
$('name-form').onsubmit=e=>{originalCreate(e);if(!$('name-dialog').open)$('graph-settings').click();};

// Copy selection as portable JSON; references and flow links within it are remapped.
function selectionIds(){return [...selectedNodes].filter(id=>graph().nodes[id]);}
function copySelection(){
 const ids=selectionIds();if(!ids.length)return;
 copiedNodes={format:'autoflow-nodes-v1',nodes:Object.fromEntries(ids.map(id=>[id,copy(graph().nodes[id])]))};
 navigator.clipboard?.writeText(JSON.stringify(copiedNodes)).catch(()=>{});toast('Copied '+ids.length+' nodes.');
}
async function pasteSelection(){
 let payload=copiedNodes;
 try{const text=await navigator.clipboard?.readText();if(text){const parsed=JSON.parse(text);if(parsed.format==='autoflow-nodes-v1')payload=parsed;}}catch{}
 if(!payload||!object(payload.nodes))return;
 try{
  for(const node of Object.values(payload.nodes)){
   if(!node||!catalog[node.type])throw Error('Clipboard contains an unknown node type.');
   if(node.type==='FunctionCall'&&!project.graphs[node.function])throw Error('The destination project does not contain '+node.function+'.');
   if(node.type==='FunctionParameter'&&!graph().parameters?.[node.parameter])throw Error('Add parameter '+node.parameter+' to the destination function first.');
  }
  change(()=>{
   const ids={},reserved={...graph().nodes};for(const id of Object.keys(payload.nodes)){ids[id]=freshId(reserved,id);reserved[ids[id]]=true;}
   for(const [old,node] of Object.entries(copy(payload.nodes))){
    node.position=[(node.position?.[0]||0)+50,(node.position?.[1]||0)+50];
    node.inputs=rewrite(node.inputs||{},value=>ref(value)?(ids[value.ref[0]]?{ref:[ids[value.ref[0]],value.ref[1]]}:null):param(value)&&!graph().parameters?.[value.param]?null:value);
    for(const [pin,value] of Object.entries(node.inputs))if(value===null)node.inputs[pin]=fallback(kind(node)?.inputs[pin]);
    node.next=Object.fromEntries(Object.entries(node.next||{}).filter(([,id])=>ids[id]).map(([flow,id])=>[flow,ids[id]]));graph().nodes[ids[old]]=node;
   }
   selectedNodes=new Set(Object.values(ids));selected=[...selectedNodes][0];
  });toast('Pasted '+selectedNodes.size+' nodes.');
 }catch(error){report(error);}
}
window.addEventListener('keydown',e=>{
 if(e.target.closest('input,textarea,select')||document.querySelector('dialog[open]'))return;
 if(e.ctrlKey||e.metaKey){const key=e.key.toLowerCase();if(key==='c'){e.preventDefault();copySelection();}if(key==='v'){e.preventDefault();pasteSelection();}if(key==='a'){e.preventDefault();selectedNodes=new Set(Object.keys(graph().nodes));selected=[...selectedNodes][0];render();}}
 else if(e.key.toLowerCase()==='c'){e.preventDefault();addComment();}
});
const graphActions=document.querySelector('.graph-actions');graphActions.prepend(button('Copy',copySelection),button('Paste',pasteSelection),button('Comment',()=>addComment()));

// Comments are editor metadata, behind the graph, with optional grouped movement.
const commentsLayer=element('div');commentsLayer.id='comments';$('world').prepend(commentsLayer);
function addComment(){
 const ids=selectionIds(),bounds=ids.map(id=>{const node=graph().nodes[id],el=[...document.querySelectorAll('.node')].find(e=>e.dataset.id===id);return {x:node.position?.[0]||0,y:node.position?.[1]||0,w:el?.offsetWidth||242,h:el?.offsetHeight||150};});
 const left=bounds.length?Math.min(...bounds.map(b=>b.x))-25:80,top=bounds.length?Math.min(...bounds.map(b=>b.y))-65:80;
 change(()=>{graph().comments ||= [];graph().comments.push({id:crypto.randomUUID(),text:'Comment',color:'#596a92',position:[left,top],size:bounds.length?[Math.max(...bounds.map(b=>b.x+b.w))-left+25,Math.max(...bounds.map(b=>b.y+b.h))-top+25]:[420,260],move_nodes:true});});
}
function renderComments(){
 commentsLayer.replaceChildren();
 for(const comment of graph().comments||[]){
  const box=element('section','graph-comment');box.style.left=comment.position[0]+'px';box.style.top=comment.position[1]+'px';box.style.width=comment.size[0]+'px';box.style.height=comment.size[1]+'px';box.style.setProperty('--comment-color',/^#[\da-f]{6}$/i.test(comment.color)?comment.color:'#596a92');
  const header=element('div','comment-heading'),text=element('textarea');text.value=comment.text;text.rows=2;text.setAttribute('aria-label','Comment text');
  text.onchange=()=>change(()=>comment.text=text.value);header.append(element('span','comment-grip','Move'),text);
  const color=element('input');color.type='color';color.value=comment.color;color.setAttribute('aria-label','Comment color');color.onchange=()=>change(()=>comment.color=color.value);
  const group=element('input');group.type='checkbox';group.checked=comment.move_nodes;group.setAttribute('aria-label','Move enclosed nodes');group.onchange=()=>change(()=>comment.move_nodes=group.checked);
  header.append(color,group,button('Delete',()=>change(()=>graph().comments=graph().comments.filter(c=>c.id!==comment.id))));box.append(header);
  const resize=element('button','comment-resize','Resize');resize.setAttribute('aria-label','Resize comment');box.append(resize);
  const begin=(event,mode)=>{if(event.button!==0||event.target.closest('textarea,input')||(event.target.closest('button')&&mode!=='resize'))return;event.preventDefault();event.stopPropagation();
   const members=Object.entries(graph().nodes).filter(([,n])=>comment.move_nodes&&n.position&&n.position[0]>=comment.position[0]&&n.position[1]>=comment.position[1]&&n.position[0]<comment.position[0]+comment.size[0]&&n.position[1]<comment.position[1]+comment.size[1]);
   commentDrag={comment,mode,x:event.clientX,y:event.clientY,position:[...comment.position],size:[...comment.size],members:members.map(([id,n])=>[id,[...n.position]]),moved:false};};
  header.onpointerdown=e=>begin(e,'move');resize.onpointerdown=e=>begin(e,'resize');box.onpointerdown=e=>e.stopPropagation();commentsLayer.append(box);
 }
}
window.addEventListener('pointermove',e=>{
 if(!commentDrag)return;const d=commentDrag,dx=(e.clientX-d.x)/view.z,dy=(e.clientY-d.y)/view.z;
 if(!d.moved&&Math.abs(dx)+Math.abs(dy)<2)return;if(!d.moved){remember();d.moved=true;}
 if(d.mode==='resize')d.comment.size=[Math.max(280,d.size[0]+dx),Math.max(130,d.size[1]+dy)];
 else{d.comment.position=[d.position[0]+dx,d.position[1]+dy];for(const [id,p] of d.members)graph().nodes[id].position=[p[0]+dx,p[1]+dy];}
 render();
});
window.addEventListener('pointerup',()=>{if(commentDrag?.moved){mark();render();}commentDrag=null;});
window.addEventListener('pointercancel',()=>{if(commentDrag?.moved){mark();render();}commentDrag=null;});

if(project)render();
