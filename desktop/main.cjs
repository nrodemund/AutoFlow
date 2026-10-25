'use strict';
const {app,BrowserWindow,globalShortcut,ipcMain,screen,dialog}=require('electron');
const {spawn}=require('node:child_process');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const OVERLAY_WIDTH=340, NORMAL_HEIGHT=112, MANUAL_HEIGHT=184, DEBUG_HEIGHT=280;
let overlayMode=null;
let backend,main,overlay,url,timer,busy=false,wasRunning=false,registered='',closing=false;
let latestDebug=null;
if(process.argv.includes('--smoke-test'))app.setPath('userData',path.join(__dirname,'.smoke-profile'));
if(!app.requestSingleInstanceLock())app.quit();
else {
app.on('second-instance',()=>{main?.show();});
app.whenReady().then(start).catch(error=>{dialog.showErrorBox('AutoFlow could not start',error.message);app.quit();});
}
async function api(endpoint,data){
 const r=await fetch(url+'/api/'+endpoint,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(3000)});
 const result=await r.json();if(!r.ok)throw Error(result.error||'Backend error');return result;
}
async function dispatchControl(action,requestId){
 if(['success','failed'].includes(action))return api('manual-response',{id:requestId,choice:action});
 if(action==='debug-delay')return api('debug-continue',{id:requestId,delay:2});
 if(action==='debug-continue'||action==='debug-capture')return api(action,{id:requestId});
 return api(action,{});
}
function secure(win){
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.webContents.on('will-navigate',(event,target)=>{if(!url||!target.startsWith(url+'/'))event.preventDefault();});
}
async function start(){
 backend=spawn(path.join(root,'runtime/python/python.exe'),['-m','autoflow','editor','--port','0','--no-browser'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
 url=await new Promise((resolve,reject)=>{
  let output='';const timeout=setTimeout(()=>reject(Error('Backend startup timed out')),15000);
  backend.on('error',reject);backend.once('exit',code=>reject(Error('Backend exited: '+code)));
  backend.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});
  backend.stderr.on('data',chunk=>{console.error(String(chunk));});
 });
 backend.on('exit',()=>{if(!closing){dialog.showErrorBox('AutoFlow backend stopped','Restart AutoFlow to reconnect.');app.quit();}});
 main=new BrowserWindow({width:1500,height:950,minWidth:950,minHeight:650,title:'AutoFlow',autoHideMenuBar:true,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});
 secure(main);await main.loadURL(url);
 overlay=new BrowserWindow({width:OVERLAY_WIDTH,height:NORMAL_HEIGHT,show:false,frame:false,thickFrame:false,resizable:false,alwaysOnTop:true,skipTaskbar:true,focusable:false,backgroundColor:'#142130',webPreferences:{partition:'autoflow-overlay',zoomFactor:1,preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 secure(overlay);await overlay.loadFile(path.join(__dirname,'overlay.html'));
 overlay.setAlwaysOnTop(true,'screen-saver');
 overlay.webContents.setZoomFactor(1);
 overlay.webContents.setVisualZoomLevelLimits(1,1);
 ipcMain.handle('control',async(event,action,requestId)=>{
  if(event.sender!==overlay.webContents||!['pause','stop','success','failed','debug-continue','debug-delay','debug-capture'].includes(action))return;
  await dispatchControl(action,requestId);
 });
 main.on('close',event=>{
  if(closing)return;
  if(wasRunning){event.preventDefault();api('stop',{}).catch(()=>{});main.hide();const end=setInterval(()=>{if(!wasRunning){clearInterval(end);app.quit();}},100);}
 });
 main.on('closed',()=>{if(!wasRunning)app.quit();});
 timer=setInterval(poll,150);
 if(process.argv.includes('--smoke-test'))smoke().catch(error=>{require('node:fs').writeFileSync(path.join(__dirname,'smoke-result.json'),JSON.stringify({error:error.stack}));app.quit();});
}
async function smoke(){
 const fs=require('node:fs'),assert=require('node:assert/strict');
 const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 await wait(500);
 assert(await main.webContents.executeJavaScript("!!document.getElementById('pause-run')"));
 assert(await main.webContents.executeJavaScript("document.getElementById('graph-settings').click(); document.getElementById('settings-form').textContent.includes('Run controls (main graph)')"));
 await main.webContents.executeJavaScript("document.getElementById('settings-dialog').close()");
 const project={version:1,main:'Main',graphs:{Main:{entry:'status',run_settings:{start_delay:0,minimize:false,pause_key:'F23',stop_key:'F24'},nodes:{status:{type:'SetRunStatus',inputs:{text:'Desktop controls test'},next:{then:'wait'}},wait:{type:'Wait',inputs:{milliseconds:30000}}}}}};
 await api('run',{project});await wait(650);
 assert(globalShortcut.isRegistered('F23'));assert(globalShortcut.isRegistered('F24'));assert(overlay.isVisible());
 assert.equal((await api('events')).status.text,'Desktop controls test');
 await api('pause',{});await wait(300);assert.equal((await api('events')).status.state,'paused');
 fs.writeFileSync(path.join(__dirname,'overlay-preview.png'),(await overlay.webContents.capturePage()).toPNG());
 await api('pause',{});await wait(250);assert.equal((await api('events')).status.state,'running');
 await api('stop',{});await wait(400);assert.equal((await api('events')).status.state,'stopped');
 assert(!globalShortcut.isRegistered('F23'));assert(!overlay.isVisible());
 project.graphs.Main.entry='ask';
 project.graphs.Main.nodes.ask={type:'ManualInteraction',inputs:{prompt:'Correct this entry, then Continue or Ignore.\n'.repeat(30)}};
 await api('run',{project});await wait(500);
 assert.equal(overlay.getBounds().width,OVERLAY_WIDTH);
 assert.equal(overlay.getBounds().height,MANUAL_HEIGHT);
 assert.equal(overlay.webContents.getZoomFactor(),1);
 assert(await overlay.webContents.executeJavaScript("document.getElementById('text').scrollHeight>document.getElementById('text').clientHeight"));
 fs.writeFileSync(path.join(__dirname,'manual-overlay-preview.png'),(await overlay.webContents.capturePage()).toPNG());
 const request=(await api('events')).status.manual;
 await api('manual-response',{id:request.id,choice:'failed'});await wait(1000);
 assert.equal(overlay.getBounds().height,NORMAL_HEIGHT);
 fs.writeFileSync(path.join(__dirname,'smoke-result.json'),JSON.stringify({passed:true,checks:['backend startup','status node','overlay visible','global shortcuts registered','pause','resume','stop','shortcuts released','overlay hidden']}));
 app.quit();
}
async function poll(){
 if(busy||closing)return;busy=true;
 try{
  const data=await api('events?after=999999'),s=data.status;
  latestDebug=s.debug||null;
  const config=s.settings,bindings=[['pause_key','pause'],['stop_key','stop']];
  if(latestDebug){bindings.push(['debug_resume_key','debug-continue'],['debug_delay_key','debug-delay']);if(latestDebug.can_capture)bindings.push(['debug_capture_key','debug-capture']);}
  const keys=data.running?bindings.map(([key])=>config[key]).join('|'):'';
  if(keys!==registered){
   globalShortcut.unregisterAll();registered=keys;
   if(keys){
    let ok=false;
    try{ok=bindings.every(([key,action])=>globalShortcut.register(config[key],()=>{
     if(action.startsWith('debug-')&&(!latestDebug||latestDebug.resuming))return;
     dispatchControl(action,latestDebug?.id).catch(()=>{});
    }));}catch{}
    if(!ok){globalShortcut.unregisterAll();await api('stop',{});dialog.showErrorBox('Run stopped: shortcut unavailable','Another app may own the shortcut. Choose different run shortcuts in Graph settings.');}
   }
  }
  if(data.running&&!wasRunning){
   const area=screen.getDisplayMatching(main.getBounds()).workArea;
   overlay.setPosition(config.position.endsWith('right')?area.x+area.width-OVERLAY_WIDTH-16:area.x+16,config.position.startsWith('top')?area.y+16:area.y+area.height-NORMAL_HEIGHT-16);
   if(config.minimize)main.minimize();
  }
  overlay.webContents.send('status',s);
  const manualMode=s.debug?'debug':s.manual?'manual':'normal';
  const overlayHeight=s.debug?DEBUG_HEIGHT:s.manual?MANUAL_HEIGHT:NORMAL_HEIGHT;
  if(overlayMode!==manualMode){
   overlayMode=manualMode;
   overlay.setResizable(true);
   overlay.setSize(OVERLAY_WIDTH,overlayHeight);
   overlay.setResizable(false);
   const bounds=overlay.getBounds(),area=screen.getDisplayMatching(bounds).workArea;
   overlay.setPosition(Math.max(area.x,Math.min(bounds.x,area.x+area.width-OVERLAY_WIDTH)),Math.max(area.y,Math.min(bounds.y,area.y+area.height-overlayHeight)));
  }
  if(data.running&&(config.overlay||s.manual||s.debug))overlay.showInactive();else overlay.hide();
  wasRunning=data.running;
 }catch(error){overlay.webContents.send('status',{state:'disconnected',text:error.message,settings:{}});}
 finally{busy=false;}
}
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{closing=true;clearInterval(timer);globalShortcut.unregisterAll();backend?.kill();});
