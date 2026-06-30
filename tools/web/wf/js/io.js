// ── Export / import / run ────────────────────────────────────────────────────
function wfSerialVars(vars){ return vars.map(v=>({name:v.name||"var",label:v.label||"",type:v.type||"bool",value:v.value,options:v.options||[], children:v.children&&v.children.length?wfSerialVars(v.children):undefined})); }
function wfHydVars(vars){ return (vars||[]).map(v=>({name:v.name||"var",label:v.label||"",type:v.type||"bool",value:v.value,options:v.options||[], children:v.children?wfHydVars(v.children):[]})); }
function wfCleanGraph(g){
  return {
    nodes:(g.nodes||[]).map(n=>{ const o={id:n.id,type:n.type,x:Math.round(n.x),y:Math.round(n.y),params:n.params}; if(n.note) o.note=n.note; if(n.log) o.log=n.log; if(n.delayBefore) o.delayBefore=n.delayBefore; if(n.delayAfter) o.delayAfter=n.delayAfter; if(n.showPreview) o.showPreview=true; if(n.stack) o.stack=n.stack; return o; }),
    edges:(g.edges||[]).map(e=>{ const o={from:e.from,fromPort:e.fromPort,to:e.to}; if(e.toPort&&e.toPort!=="in") o.toPort=e.toPort; return o; }),
    groups:(g.groups||[]).map(gr=>({id:gr.id,name:gr.name,x:Math.round(gr.x),y:Math.round(gr.y),w:Math.round(gr.w),h:Math.round(gr.h),color:gr.color||0})),
  };
}
function wfSerialize(){
  wfSpeedFromUI();
  const sh=WF.speedhack||{enabled:false,speed:2.0,package:""};
  return {
    name:$("wf-name").value||"workflow", version:2, templatesDir:WF.templatesDir||"templates",
    speedhack:{ enabled:!!sh.enabled, speed:sh.speed||2.0, package:(sh.package||"").trim() },
    globals: wfSerialVars(WF.globals||[]),
    functions: WF.functions.map(f=>({ id:f.id, name:f.name, graph:wfCleanGraph(f.graph) })),
    activities: WF.activities.map(a=>{
      const o={ id:a.id, name:a.name, type:a.type, enabled:a.enabled,
        vars: wfSerialVars(a.vars||[]), graph:wfCleanGraph(a.graph) };
      if(a.type==="background") o.pollInterval=a.pollInterval; else o.maxRetries=a.maxRetries;
      return o;
    }),
  };
}
function wfHydrateGraph(g){
  g=g||{nodes:[],edges:[]};
  let nodes=(g.nodes||[]).map(n=>{
    const params=n.params||wfDefaults(n.type);
    // Migrate the legacy single `delay` (find-then-wait) → delayBefore
    // (wait-then-find), then drop it so it doesn't linger in params.
    let delayBefore=n.delayBefore;
    if(delayBefore===undefined && params && params.delay!==undefined) delayBefore=params.delay;
    if(params && params.delay!==undefined) delete params.delay;
    return {id:n.id||wfUid(),type:n.type,x:n.x||40,y:n.y||40,params,note:n.note||"",log:n.log||"",
      delayBefore:parseFloat(delayBefore)||0, delayAfter:parseFloat(n.delayAfter)||0,
      showPreview:!!n.showPreview,stack:n.stack||null};
  });
  if(!nodes.some(n=>n.type==="start")) nodes.unshift({id:wfUid(),type:"start",x:40,y:40,params:{}});
  const groups=(g.groups||[]).map(gr=>({id:gr.id||("g"+wfUid().slice(1)),name:gr.name||"Group",x:gr.x||0,y:gr.y||0,w:gr.w||200,h:gr.h||140,color:gr.color||0}));
  return { nodes, edges:(g.edges||[]).map(e=>({from:e.from,fromPort:e.fromPort||"out",to:e.to,toPort:e.toPort||"in"})), groups };
}
function wfHydrate(flow){
  WF.name=flow.name||"workflow"; WF.version=flow.version||2; WF.templatesDir=flow.templatesDir||"templates";
  const sh=flow.speedhack||{}; WF.speedhack={enabled:!!sh.enabled, speed:(parseFloat(sh.speed)||2.0), package:(sh.package||"").trim()};
  WF.functions=(flow.functions||[]).map(f=>({ id:f.id||("fn_"+wfUid().slice(1,6)), name:f.name||"function", graph:wfHydrateGraph(f.graph) }));
  WF.globals = wfHydVars(flow.globals||[]);
  WF.activities=(flow.activities||[]).map(a=>({
    id:a.id||("act_"+wfUid().slice(1,5)), name:a.name||a.id||"activity",
    type:a.type==="background"?"background":"sequence", enabled:a.enabled!==false,
    maxRetries:a.maxRetries||1, pollInterval:a.pollInterval||1.0,
    vars: wfHydVars(a.vars||[]),
    graph:wfHydrateGraph(a.graph),
  }));
  WF.edit={kind:"activity", id:WF.activities[0]?WF.activities[0].id:null}; wfClearSel(); wfPan={x:0,y:0}; wfZoom=1;
  $("wf-name").value=WF.name;
  wfSyncSpeedUI();
  wfRenderAll();
}

async function wfExport(){ await api().workflow_export(JSON.stringify(wfSerialize(),null,2), $("wf-name").value); }
async function wfSave(){
  const r=await api().workflow_save(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
  if(r&&r.ok) setStatus("Workflow saved");
}
async function wfImport(){
  const txt=await api().workflow_import(); if(!txt)return;
  try{ wfHydrate(JSON.parse(txt)); setStatus("Workflow imported"); }
  catch(e){ alert("Invalid JSON: "+e); }
}
// Play / stop glyphs for the run toggle (icon-only button).
const WF_ICO_PLAY = '<svg viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
const WF_ICO_STOP = '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>';
function wfSetRunning(on){
  wfRunning=on; const b=$("wf-run-btn");
  if(!on){
    // Keep the green/red trail so the user can see where execution stopped.
    // Only remove the amber "currently running" pulse and dim unreached blocks.
    if(wfRunNode){ const _re=wfNodeElById(wfRunNode); if(_re) _re.classList.remove("running"); }
    wfRunNode=null; wfRunStopped=true;
    wfMarkUnreached();
    wfLiveVars={}; wfFreshVar=null;
    // Clear any activity still blinking "running" (stopped mid-activity), but
    // keep the solid-red "errored" markers so failed activities stay visible.
    for(const id in wfActStatus){ if(wfActStatus[id]==="running") wfSetActStatus(id, null); }
  }
  if(b){
    b.innerHTML = on?WF_ICO_STOP:WF_ICO_PLAY;
    b.title = on?"Stop":"Test run";
    b.classList.toggle("ok",!on); b.classList.toggle("err",on);
  }
  // Running status pill: amber "Running" while executing, grey "Ready" at rest.
  const pill=$("wf-run-status");
  if(pill){
    pill.classList.toggle("running", !!on);
    const txt=pill.querySelector(".wf-run-txt");
    if(txt) txt.textContent = on ? "Running" : (wfRunStopped ? "Stopped" : "Ready");
  }
  wfRenderVarsPanel();
}
async function wfToggleRun(){
  if(wfRunning){ wfSetRunning(false); await api().workflow_stop(); return; }  // reset first, then stop
  if(!WF.activities.length){ alert("No activities."); return; }
  wfResetRunViz();        // clear last run's colours BEFORE the engine starts emitting
  wfSetRunning(true);     // mark running before any node event can arrive
  const ok=await api().workflow_run(JSON.stringify(wfSerialize()));
  if(!ok) wfSetRunning(false);
}
async function wfRunGui(){
  if(!WF.activities.length){ alert("No activities."); return; }
  await api().open_runner(JSON.stringify(wfSerialize()));
  setStatus("Runner GUI opened");
}


// ── Init ──────────────────────────────────────────────────────────────────
async function init(){
  let tries=0;
  while(!(window.pywebview&&window.pywebview.api)&&tries<40){ await new Promise(r=>setTimeout(r,100)); tries++; }
  if(!window.pywebview||!window.pywebview.api){ setStatus("⚠ pywebview unavailable"); return; }
  const state=await api().get_state();
  S.connectedSerial=state.connectedSerial||null;
  S.captureBackend=state.captureBackend||"scrcpy";
  const capSel=$("capture-backend");
  if(capSel){
    capSel.innerHTML="";
    (state.captureBackends||["scrcpy","adb"]).forEach(b=>{ const o=document.createElement("option"); o.value=b; o.textContent=b==="adb"?"ADB screencap":"scrcpy (fast)"; capSel.appendChild(o); });
    capSel.value=S.captureBackend;
  }
  (state.log||[]).forEach(appendLog);
  try{ const st=await api().get_settings(); wfSnapOn=!!st.snap; wfPreviewAll=!!st.previewAll;
    if(st.logOpen===false){ const lc=$("log-card"); if(lc) lc.classList.add("collapsed"); }
    if(st.sideW){ const sd=$("wf-side"); if(sd) sd.style.width=Math.max(150,Math.min(480,st.sideW))+"px"; }
    if(st.inspW){ const insp=$("wf-inspector"); if(insp) insp.style.width=Math.max(180,Math.min(520,st.inspW))+"px"; } }catch{}
  wfInitSideResizer();
  wfInitInspResizer();
  wfSetupSortable($("wf-activities"));
  if($("wf-activities-bg")) wfSetupSortable($("wf-activities-bg"));
  if($("wf-functions")) wfSetupSortable($("wf-functions"));
  wfSyncToggleBtns();
  wfSetRunning(false);   // seed the run button's play icon
  updateLogCount();
  wfInitCanvas();
  // Reopen the workflow that was open when the designer last closed.
  let reopened="", didRender=false;
  try{
    const lw=await api().get_last_workflow();
    if(lw && lw.text){ wfHydrate(JSON.parse(lw.text)); reopened=lw.name||"previous workflow"; didRender=true; }
  }catch(e){}
  // wfHydrate and wfAddActivity both call wfRenderAll() themselves; only fall back here.
  if(!WF.activities.length){ wfAddActivity("sequence"); didRender=true; }
  if(!didRender) wfRenderAll();
  wfZoomApplyMode("canvas");  // ensure the shared zoom cluster targets the graph on load
  setStatus(reopened ? ("Reopened: "+reopened) : "Ready");
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
