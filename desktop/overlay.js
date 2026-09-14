let manualId=null;
window.runControl.onStatus(s=>{
 manualId=s.manual?.id||null;
 document.body.classList.toggle('manual',!!manualId);
 document.getElementById('state').textContent=manualId?'Your action needed':s.state;
 document.getElementById('text').textContent=s.manual?.prompt||s.text||'Executing graph';
 document.getElementById('pause').hidden=!!manualId;
 document.getElementById('continue').hidden=!manualId;
 document.getElementById('ignore').hidden=!manualId;
 document.getElementById('pause').textContent=(['paused','pausing'].includes(s.state)?'Resume':'Pause')+' · '+(s.settings.pause_key||'');
 document.getElementById('stop').textContent='Stop · '+(s.settings.stop_key||'');
});
for(const [id,action] of [['pause','pause'],['stop','stop'],['continue','success'],['ignore','failed']])document.getElementById(id).onclick=()=>window.runControl.action(action,manualId).catch(error=>{document.getElementById('text').textContent=error.message;});
