const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('desktop/main.cjs','utf8'),callbacks=new Map(),calls=[];
const status={debug:{id:'first',can_capture:true},settings:{pause_key:'F8',stop_key:'F9',debug_capture_key:'F6',debug_resume_key:'F10',debug_delay_key:'Shift+F10',overlay:true}};
const data={running:true,status};
const sandbox={busy:false,closing:false,latestDebug:null,registered:'',wasRunning:true,overlayMode:'debug',
 OVERLAY_WIDTH:340,NORMAL_HEIGHT:112,MANUAL_HEIGHT:184,DEBUG_HEIGHT:280,
 globalShortcut:{unregisterAll:()=>callbacks.clear(),register:(key,callback)=>{callbacks.set(key,callback);return true;}},
 api:async(path,body)=>{if(path.startsWith('events'))return data;calls.push({path,body});return {};},
 overlay:{webContents:{send(){}},showInactive(){},hide(){},setResizable(){},setSize(){},getBounds:()=>({x:0,y:0}),setPosition(){}},
 screen:{getDisplayMatching:()=>({workArea:{x:0,y:0,width:1920,height:1080}})},
 dialog:{showErrorBox:()=>{throw Error('Unexpected shortcut registration error');}}};
vm.createContext(sandbox);
vm.runInContext(source.slice(source.indexOf('async function dispatchControl'),source.indexOf('function secure')),sandbox);
vm.runInContext(source.slice(source.indexOf('async function poll(){'),source.indexOf("app.on('window-all-closed'")),sandbox);
(async()=>{
 await vm.runInContext('poll()',sandbox);
 assert.deepEqual([...callbacks.keys()].sort(),['F6','F8','F9','F10','Shift+F10'].sort());
 callbacks.get('F6')();assert.deepEqual(calls.at(-1).body.id,'first');assert.equal(calls.at(-1).path,'debug-capture');
 callbacks.get('Shift+F10')();assert.equal(calls.at(-1).path,'debug-continue');assert.equal(calls.at(-1).body.delay,2);
 status.debug={id:'second',can_capture:true};await vm.runInContext('poll()',sandbox);
 callbacks.get('F10')();assert.equal(calls.at(-1).body.id,'second');
 status.debug.resuming=true;await vm.runInContext('poll()',sandbox);const count=calls.length;
 callbacks.get('F10')();callbacks.get('F6')();assert.equal(calls.length,count);
 status.debug=null;await vm.runInContext('poll()',sandbox);
 assert.deepEqual([...callbacks.keys()],['F8','F9']);
 data.running=false;await vm.runInContext('poll()',sandbox);assert.equal(callbacks.size,0);
 console.log('Global debug shortcut routing, countdown guards and cleanup checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
