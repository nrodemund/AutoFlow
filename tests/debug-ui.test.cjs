const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements={};
function element(tag,cls='',text=''){
 return {tag,className:cls,textContent:text,children:[],attributes:{},dataset:{},
  append(...children){this.children.push(...children);},setAttribute(key,value){this.attributes[key]=value;},
  classList:{toggle(){}}};
}
const actions=[];
const logs=[];
const sandbox={element,button:(text,onclick,cls)=>Object.assign(element('button',cls,text),{onclick}),
 change:fn=>fn(),document:{body:element('body'),querySelectorAll:()=>[]},graphName:'Main',
 api:async(path,body)=>actions.push({path,body}),report:e=>{throw e;},render:()=>{},fit:()=>{},poll:async()=>{},
 debugRunId:'run-1',appliedDebugEdits:new Set(),log:(kind,text)=>logs.push({kind,text}),
 project:{graphs:{Main:{nodes:{offset:{type:'OffsetPoint',inputs:{x:0,y:0}}}}}}};
vm.createContext(sandbox);
const app=fs.readFileSync('autoflow/web/app.js','utf8');
vm.runInContext(app.slice(app.indexOf('function debugToggle('),app.indexOf('function renderNodes(')),sandbox);
const node={};sandbox.node=node;
vm.runInContext("globalThis.toggle=debugToggle(node);toggle.onclick({stopPropagation(){}})",sandbox);
assert.equal(node.debug,true);
vm.runInContext("toggle.onclick({stopPropagation(){}})",sandbox);assert.equal(node.debug,false);
vm.runInContext(app.slice(app.indexOf('let activeDebug=null;')),sandbox);
const request={id:'debug-1',graph:'Main',node:'click',title:'Click',preview:'No click sent.',inputs:[{name:'point',type:'Point',value:'{x: 4, y: 8}',deferred:false}]};
sandbox.request=request;
vm.runInContext('updateDebugPrompt(request)',sandbox);
assert.equal(vm.runInContext('debugPanel.hidden',sandbox),false);
assert.match(vm.runInContext('debugInputs.textContent',sandbox),/point \(Point\)/);
assert.match(vm.runInContext('debugPreview.textContent',sandbox),/No click sent/);
request.preview='Offset from base: X = +24, Y = -10';
vm.runInContext('updateDebugPrompt(request)',sandbox);
assert.match(vm.runInContext('debugPreview.textContent',sandbox),/X = \+24, Y = -10/);
request.preview='No click sent.';
assert.equal(actions.length,0);
const edit={id:1,graph:'Main',node:'offset',previous:{x:0,y:0},changes:{x:12,y:-4}};
sandbox.status={run_id:'old-run',debug_edits:[edit]};
vm.runInContext('applyDebugEdits(status)',sandbox);
assert.equal(sandbox.project.graphs.Main.nodes.offset.inputs.x,0);
sandbox.status.run_id='run-1';vm.runInContext('applyDebugEdits(status)',sandbox);
assert.deepEqual(sandbox.project.graphs.Main.nodes.offset.inputs,{x:12,y:-4});
vm.runInContext('applyDebugEdits(status)',sandbox);assert.equal(logs.length,1);
// A later capture must not overwrite changes made in the editor during the run.
sandbox.project.graphs.Main.nodes.offset.inputs.x=88;
sandbox.status.debug_edits.push({id:2,graph:'Main',node:'offset',previous:{x:12,y:-4},changes:{x:15,y:16}});
vm.runInContext('applyDebugEdits(status)',sandbox);assert.equal(sandbox.project.graphs.Main.nodes.offset.inputs.x,88);
assert.equal(logs.at(-1).kind,'error');
(async()=>{
 await vm.runInContext('debugContinue.onclick()',sandbox);
 assert.equal(actions[0].path,'debug-continue');assert.equal(actions[0].body.id,'debug-1');
 await vm.runInContext('debugDelay.onclick()',sandbox);assert.equal(actions.at(-1).body.delay,2);
 request.can_capture=true;request.resuming=true;request.resume_in_ms=1700;
 vm.runInContext('updateDebugPrompt(request)',sandbox);
 assert.equal(vm.runInContext('debugCapture.disabled',sandbox),true);
 assert.match(vm.runInContext('debugPreview.textContent',sandbox),/Resuming in 1.7/);
 request.resuming=false;
 vm.runInContext('updateDebugPrompt(null)',sandbox);assert.equal(vm.runInContext('debugPanel.hidden',sandbox),true);
 // Desktop overlay uses the debug endpoint, retaining manual and pause controls.
 let receive;
 const desktop={window:{runControl:{onStatus:fn=>receive=fn,action:async(action,id)=>actions.push({action,id})}},
  document:{body:element('body'),getElementById:id=>elements[id]||=(element('div'))}};
 vm.createContext(desktop);vm.runInContext(fs.readFileSync('desktop/overlay.js','utf8'),desktop);
 receive({state:'debug',debug:request,settings:{}});
 assert.equal(elements.pause.hidden,true);assert.equal(elements.ignore.hidden,true);assert.equal(elements.continue.hidden,false);
 assert.match(elements.text.textContent,/No click sent/);
 await elements.continue.onclick();assert.deepEqual(actions.at(-1),{action:'debug-continue',id:'debug-1'});
 await elements.capture.onclick();assert.deepEqual(actions.at(-1),{action:'debug-capture',id:'debug-1'});
 await elements.delay.onclick();assert.deepEqual(actions.at(-1),{action:'debug-delay',id:'debug-1'});
 receive({state:'manual',manual:{id:'manual-1',prompt:'Please correct'},settings:{}});
 assert.equal(elements.ignore.hidden,false);await elements.continue.onclick();
 assert.deepEqual(actions.at(-1),{action:'success',id:'manual-1'});
 receive({state:'paused',settings:{}});assert.equal(elements.pause.hidden,false);assert.equal(elements.continue.hidden,true);
 console.log('Debug toggles, input inspection and desktop Continue routing checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
