const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(tag,cls='',text=''){this.tag=tag;this.className=cls;this.textContent=text;this.children=[];this.dataset={};this.value='';this.classList={add:c=>this.className+=' '+c,remove:()=>{}};}
 append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
 replaceChildren(...children){this.children=[];this.append(...children);}
 after(){}
 setAttribute(key,value){this[key]=value;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 querySelectorAll(selector){return this.children.flatMap(child=>[
  ...(selector==='input'&&child.tag==='input'||selector.startsWith('.')&&child.className.split(' ').includes(selector.slice(1))?[child]:[]),
  ...child.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0];}
 replaceWith(next){const index=this.parent.children.indexOf(this);this.parent.children[index]=next;next.parent=this.parent;}
}
const elements={};const $=id=>elements[id]||=(new Element('div'));
const main={parameters:{enabled:'bool'},parameter_defaults:{enabled:false},outputs:{},nodes:{start:{type:'Start',inputs:{},next:{}}},entry:'start'};
const sub={parameters:{name:'string'},outputs:{},nodes:{start:{type:'Start',inputs:{},next:{}}},entry:'start'};
const added=[];
const sandbox={$,element:(...args)=>new Element(...args),button:(text,onclick)=>Object.assign(new Element('button','',text),{onclick}),
 project:{main:'Main',graphs:{Main:main,Sub:sub}},graphName:'Main',catalog:{Start:{flows:['then']},FunctionReturn:{flows:[]},FunctionParameter:{flows:[]}},
 object:v=>v!==null&&typeof v==='object'&&!Array.isArray(v),copy:structuredClone,ref:v=>v&&Array.isArray(v.ref),param:v=>v&&typeof v.param==='string',
 selectedNodes:new Set(),change:fn=>fn(),report:e=>{throw e;},fit:()=>{},selected:null,
 fallback:type=>type==='bool'?false:'',parseLiteral:(raw,type)=>type==='integer'?Number(raw):raw,
 addNode:(type,position,inputs,metadata)=>added.push({type,...metadata}),disconnectNode:()=>{},screenPoint:(x,y)=>({x,y})};
sandbox.graph=()=>sandbox.project.graphs[sandbox.graphName];
vm.createContext(sandbox);
vm.runInContext('function kind(node){return functionNodeKind(node)||catalog[node.type];}',sandbox);
const source=fs.readFileSync('autoflow/web/editor-features.js','utf8');
vm.runInContext(source.slice(source.indexOf('const signatureTypes'),source.indexOf('// Copy selection')),sandbox);
const run=code=>vm.runInContext(code,sandbox);
// The same parameter can be inserted repeatedly through the sidebar and drop target.
run('renderParameters()');const row=run('parameterList.children[0]');
row.children[0].onclick();row.children[0].onclick();
assert.deepEqual(added,[{type:'FunctionParameter',parameter:'enabled'},{type:'FunctionParameter',parameter:'enabled'}]);
let transfer;row.children[0].ondragstart({dataTransfer:{setData:(type,value)=>transfer={type,value}}});
const app=fs.readFileSync('autoflow/web/app.js','utf8');
run(app.slice(app.indexOf("$('canvas').ondragover="),app.indexOf("window.addEventListener('pointermove'")));
$('canvas').ondrop({preventDefault(){},clientX:30,clientY:40,dataTransfer:{getData:type=>type===transfer.type?transfer.value:''}});
assert.equal(added.length,3);assert.equal(added[2].parameter,'enabled');
// Changing the checkbox updates the shared saved setting and editor run arguments.
row.children[1].checked=true;row.children[1].onchange();
assert.equal(main.parameter_defaults.enabled,true);assert.equal(sandbox.project.editor.arguments.enabled,true);
// Settings rename every existing reader and retain the boolean value.
main.nodes.reader={type:'FunctionParameter',parameter:'enabled',inputs:{}};
main.nodes.reader2={type:'FunctionParameter',parameter:'enabled',inputs:{}};
$('graph-settings').onclick();run("parameterRows.children[0].querySelector('input').value='dry_run'");
$('settings-form').onsubmit({preventDefault(){}});
assert.equal(run('settingsError.textContent'),'');
assert.equal(main.parameter_defaults.dry_run,true);assert.equal(main.parameter_defaults.enabled,undefined);
assert.equal(main.nodes.reader.parameter,'dry_run');assert.equal(main.nodes.reader2.parameter,'dry_run');
// Editing a function keeps the main setting intact; a new bool gets a checkbox.
sandbox.graphName='Sub';$('graph-settings').onclick();$('settings-form').onsubmit({preventDefault(){}});
assert.equal(sandbox.project.editor.arguments.dry_run,true);
sandbox.graphName='Main';$('graph-settings').onclick();
run("signatureRow(parameterRows); parameterRows.children[1].querySelectorAll('input')[1].value='bool'; parameterRows.children[1].querySelectorAll('input')[1].onchange()");
assert.equal(run("parameterRows.children[1].querySelector('.parameter-value').type"),'checkbox');
console.log('Parameter settings, shared values, repeated insertion and drop checks passed');
