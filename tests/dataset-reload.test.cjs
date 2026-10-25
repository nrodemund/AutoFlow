const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('autoflow/web/app.js','utf8');
const elements={};
const original={columns:['name'],rows:[{name:'old'}]};
const replacement={columns:['id'],types:{id:'integer'},rows:[{id:42}]};
let history=[],renders=0;
const sandbox={project:{datasets:{Data:structuredClone(original)},graphs:{Main:{dataset:'Data'}}},
 activeDataset:'Data',datasetPage:4,datasetSort:{name:true},
 $:id=>elements[id]||=( {value:'old search',click(){this.clicked=true;}}),
 fileBase64:async()=> 'encoded',api:async()=>({dataset:structuredClone(replacement),sheets:[]}),
 change:fn=>{history.push(structuredClone(sandbox.project));fn();},renderDatasetTable:()=>renders++,log:()=>{},report:error=>{throw error;}};
vm.createContext(sandbox);
vm.runInContext(source.slice(source.indexOf('async function reloadDatasetFile'),source.indexOf('function datasetColumnType')),sandbox);
const file={name:'different-name.csv'};
const target=()=>({project:sandbox.project,name:'Data',baseline:JSON.stringify(sandbox.project.datasets.Data)});
(async()=>{
 await sandbox.reloadDatasetFile(file,target());
 assert.deepEqual(sandbox.project.datasets,{Data:replacement});
 assert.equal(sandbox.project.graphs.Main.dataset,'Data');
 assert.equal(sandbox.datasetPage,0);assert.equal(elements['dataset-search'].value,'');assert.equal(renders,1);
 sandbox.project=history.pop();assert.deepEqual(sandbox.project.datasets.Data,original);
 const before=JSON.stringify(sandbox.project);
 await sandbox.reloadDatasetFile(undefined,target());assert.equal(JSON.stringify(sandbox.project),before);
 sandbox.api=async()=>{throw Error('Invalid CSV');};
 await assert.rejects(sandbox.reloadDatasetFile(file,target()),/Invalid CSV/);
 assert.equal(JSON.stringify(sandbox.project),before);
 sandbox.api=async()=>{sandbox.project.datasets.Data.rows.push({name:'edited'});return {dataset:replacement,sheets:[]};};
 await assert.rejects(sandbox.reloadDatasetFile(file,target()),/Dataset changed/);
 assert.equal(sandbox.project.datasets.Data.rows[1].name,'edited');
 sandbox.api=async()=>{sandbox.project=structuredClone(sandbox.project);return {dataset:replacement,sheets:[]};};
 await assert.rejects(sandbox.reloadDatasetFile(file,target()),/Project changed/);
 sandbox.api=async()=>({dataset:replacement,sheets:[]});
 elements['dataset-reload'].onclick();assert.equal(elements['dataset-reload-file'].clicked,true);
 const input={files:[file],value:'chosen file'};
 await elements['dataset-reload-file'].onchange({target:input});
 assert.equal(input.value,'');assert.deepEqual(sandbox.project.datasets.Data,replacement);
 console.log('Dataset reload, undo snapshot, cancellation, errors and concurrent edits passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
