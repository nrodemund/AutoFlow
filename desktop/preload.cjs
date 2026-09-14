const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('runControl',{
 onStatus:callback=>ipcRenderer.on('status',(_event,status)=>callback(status)),
 action:(action,id)=>ipcRenderer.invoke('control',action,id)
});
