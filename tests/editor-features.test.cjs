const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('autoflow/web/editor-features.js','utf8');
const current={parameters:{name:'string'},return_types:{message:'string'},nodes:{}};
const sandbox={catalog:{FunctionParameter:{},FunctionReturn:{},FunctionCall:{},StringAppend:{inputs:{a:'string',b:'string'},outputs:{result:'string'}}},
 project:{graphs:{Greet:current}},graph:()=>current,object:v=>v!==null&&typeof v==='object'&&!Array.isArray(v),
 ref:v=>v&&Array.isArray(v.ref),param:v=>v&&typeof v.param==='string',copy:structuredClone,
 selectedNodes:new Set(['a','b']),selected:'a',copiedNodes:null,navigator:{},toast:()=>{},report:e=>{throw e;},
 change:fn=>fn(),fallback:()=>'',kind:node=>sandbox.catalog[node.type]};
vm.createContext(sandbox);
vm.runInContext(source.slice(source.indexOf('function functionNodeKind('),source.indexOf('// A row editor')),sandbox);
assert.equal(vm.runInContext("functionNodeKind({type:'FunctionCall',function:'Greet'}).outputs.message",sandbox),'string');
assert.equal(vm.runInContext("functionNodeKind({type:'FunctionParameter',parameter:'name'}).outputs.value",sandbox),'string');
vm.runInContext(source.slice(source.indexOf('function selectionIds('),source.indexOf("window.addEventListener('keydown'")),sandbox);
current.nodes={a:{type:'StringAppend',inputs:{a:'hello',b:''},next:{then:'b'},position:[0,0]},
 b:{type:'StringAppend',inputs:{a:{ref:['a','result']},b:{ref:['outside','value']}},next:{then:'outside'},position:[100,0]}};
(async()=>{
 vm.runInContext('copySelection()',sandbox);await vm.runInContext('pasteSelection()',sandbox);
 assert.equal(Object.keys(current.nodes).length,4);
 assert.deepEqual(JSON.parse(JSON.stringify(current.nodes.b_1.inputs.a)),{ref:['a_1','result']});
 assert.equal(current.nodes.b_1.inputs.b,'');
 assert.equal(current.nodes.a_1.next.then,'b_1');
 assert.equal(Object.keys(current.nodes.b_1.next).length,0);
 assert.equal(sandbox.selectedNodes.size,2);
 console.log('Function pin and clipboard remapping checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
