// npm ci --prefix desktop first. Everything needed at runtime stays local.
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),dest=path.join(root,'runtime/electron');
fs.cpSync(path.join(root,'desktop/node_modules/electron/dist'),dest,{recursive:true});
fs.renameSync(path.join(dest,'electron.exe'),path.join(dest,'AutoFlow.exe'));
const app=path.join(dest,'resources/app');fs.mkdirSync(app,{recursive:true});
fs.writeFileSync(path.join(app,'package.json'),JSON.stringify({name:'autoflow',version:'0.1.0',main:'index.cjs'}));
fs.writeFileSync(path.join(app,'index.cjs'),"require('../../../../desktop/main.cjs');\n");
console.log('Portable app ready: runtime/electron/AutoFlow.exe');
