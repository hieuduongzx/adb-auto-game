// ── Export / import / run ────────────────────────────────────────────────────
function wfSerialVars(vars){ return vars.map(v=>({name:v.name||"var",label:v.label||"",type:v.type||"bool",value:v.value,options:v.options||[], children:v.children&&v.children.length?wfSerialVars(v.children):undefined})); }
function wfHydVars(vars){ return (vars||[]).map(v=>({name:v.name||"var",label:v.label||"",type:v.type||"bool",value:v.value,options:v.options||[], children:v.children?wfHydVars(v.children):[]})); }
function wfCleanGraph(g){
  return {
    nodes:(g.nodes||[]).map(n=>{ const o={id:n.id,type:n.type,x:Math.round(n.x),y:Math.round(n.y),params:n.params}; if(n.note) o.note=n.note; if(n.log) o.log=n.log; if(n.delayBefore) o.delayBefore=n.delayBefore; if(n.delayAfter) o.delayAfter=n.delayAfter; if(n.retryCount) o.retryCount=n.retryCount; if(n.retryDelay) o.retryDelay=n.retryDelay; if(n.screenshotOnFail) o.screenshotOnFail=true; if(n.showPreview) o.showPreview=true; if(n.stack) o.stack=n.stack; return o; }),
    edges:(g.edges||[]).map(e=>{ const o={from:e.from,fromPort:e.fromPort,to:e.to}; if(e.toPort&&e.toPort!=="in") o.toPort=e.toPort; return o; }),
    groups:(g.groups||[]).map(gr=>({id:gr.id,name:gr.name,x:Math.round(gr.x),y:Math.round(gr.y),w:Math.round(gr.w),h:Math.round(gr.h),color:gr.color||0})),
  };
}
// ── Per-entity serializers (debug / copy) ────────────────────────────────────
// Emit the same JSON shape the engine consumes, but for a SINGLE activity or
// function — handy for copying one piece out to debug in isolation.
function wfSerializeActivity(a){
  if(!a) return null;
  const o={ id:a.id, name:a.name, type:a.type, enabled:a.enabled,
    vars: wfSerialVars(a.vars||[]), graph:wfCleanGraph(a.graph) };
  if(a.type==="background") o.pollInterval=a.pollInterval; else o.maxRetries=a.maxRetries;
  return o;
}
function wfSerializeFunction(f){
  if(!f) return null;
  return { id:f.id, name:f.name, graph:wfCleanGraph(f.graph) };
}
// A single node (with its params + per-node options), as stored in a graph.
function wfSerializeNode(n){
  if(!n) return null;
  return wfCleanGraph({nodes:[n],edges:[]}).nodes[0];
}
function wfSerialize(){
  wfSpeedFromUI();
  const sh=WF.speedhack||{enabled:false,speed:2.0,package:""};
  const w=WF.win32||{window:"",matchBy:"title",inputMode:"background"};
  const isWin32=(WF.controller==="win32");
  return {
    name:$("wf-name").value||"workflow", version:2, templatesDir:WF.templatesDir||"templates",
    controller:isWin32?"win32":"adb",
    ocr:(WF.ocrBackend||"").trim(),
    win32:{ window:(w.window||"").trim(), matchBy:w.matchBy||"title", inputMode:w.inputMode||"background" },
    // Speed hack is ADB-only (Frida). Force it off in Win32 so a stale enabled
    // flag never makes the Runner try to start a non-existent cheat path.
    speedhack:{ enabled:isWin32?false:!!sh.enabled, speed:sh.speed||2.0, package:(sh.package||"").trim() },
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
      retryCount:parseInt(n.retryCount,10)||0, retryDelay:parseFloat(n.retryDelay)||0, screenshotOnFail:!!n.screenshotOnFail,
      showPreview:!!n.showPreview,stack:n.stack||null};
  });
  if(!nodes.some(n=>n.type==="start")) nodes.unshift({id:wfUid(),type:"start",x:40,y:40,params:{}});
  const groups=(g.groups||[]).map(gr=>({id:gr.id||("g"+wfUid().slice(1)),name:gr.name||"Group",x:gr.x||0,y:gr.y||0,w:gr.w||200,h:gr.h||140,color:gr.color||0}));
  // Migrate legacy call wires: the call node used to have a single "out" port,
  // now it exposes "true"/"false" — an old "out" wire is the success path.
  const callIds=new Set(nodes.filter(n=>n.type==="call").map(n=>n.id));
  const edges=(g.edges||[]).map(e=>{
    let fp=e.fromPort||"out";
    if(fp==="out" && callIds.has(e.from)) fp="true";
    return {from:e.from,fromPort:fp,to:e.to,toPort:e.toPort||"in"};
  });
  return { nodes, edges, groups };
}
function wfHydrate(flow){
  WF.name=flow.name||"workflow"; WF.version=flow.version||2; WF.templatesDir=flow.templatesDir||"templates";
  const sh=flow.speedhack||{}; WF.speedhack={enabled:!!sh.enabled, speed:(parseFloat(sh.speed)||2.0), package:(sh.package||"").trim()};
  WF.controller=(flow.controller==="win32")?"win32":"adb";
  WF.ocrBackend=String(flow.ocr||"").trim().toLowerCase();
  if(typeof wfSyncOcrUI==="function") wfSyncOcrUI();
  // Force speed hack off in Win32 mode (ADB/Frida only) so a file saved with
  // enabled=true under the old cheat.dll path can't revive it.
  if(WF.controller==="win32") WF.speedhack.enabled=false;
  const w=flow.win32||{}; WF.win32={window:(w.window||"").trim(), matchBy:w.matchBy||"title", inputMode:w.inputMode||"background"};
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
  if(typeof wfSyncControllerUI==="function") wfSyncControllerUI();
  wfRenderAll();
}

// ── Dirty state + autosave ────────────────────────────────────────────────────
// Mọi mutation đi qua wfPushUndo/wfPushUndoDebounced đều gọi wfMarkDirty():
// nút Save hiện chấm cam "chưa lưu", và (khi flow đã có file) một autosave
// debounce 3s ghi đè im lặng — workflow_save không bao giờ mở dialog nên an toàn.
let wfDirty=false;          // có thay đổi chưa ghi xuống đĩa
let wfHasFile=false;        // flow đã gắn với một file cụ thể (mở/lưu ít nhất 1 lần)
let wfAutosaveOn=true;
let _wfAutosaveTimer=null;
function wfSyncDirtyUI(){
  const b=$("wf-save-btn");
  if(b){ b.classList.toggle("dirty", wfDirty);
    b.title = wfDirty ? "Lưu (Ctrl+S) — có thay đổi chưa lưu" : "Lưu vào file hiện tại (Ctrl+S)"; }
}
function wfMarkDirty(){
  wfDirty=true; wfSyncDirtyUI();
  if(wfAutosaveOn && wfHasFile){
    clearTimeout(_wfAutosaveTimer);
    _wfAutosaveTimer=setTimeout(wfAutosave, 3000);
  }
}
function wfMarkClean(){ wfDirty=false; clearTimeout(_wfAutosaveTimer); wfSyncDirtyUI(); }
async function wfAutosave(){
  if(!wfDirty || !wfHasFile) return;
  if(wfRunning){ _wfAutosaveTimer=setTimeout(wfAutosave, 5000); return; }   // đợi run xong
  try{
    const r=await api().workflow_save(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
    if(r&&r.ok){ wfMarkClean(); setStatus("Đã tự lưu · "+new Date().toLocaleTimeString()); }
  }catch{}
}
// Chặn đóng cửa sổ khi còn thay đổi chưa lưu (best-effort trong WebView2).
window.addEventListener("beforeunload", e=>{ if(wfDirty){ e.preventDefault(); e.returnValue=""; } });

async function wfExport(){
  const ok=await api().workflow_export(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
  if(ok){ wfHasFile=true; wfMarkClean(); setStatus("Workflow saved"); }
}
async function wfSave(){
  const r=await api().workflow_save(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
  if(r&&r.ok){ wfHasFile=true; wfMarkClean(); setStatus("Workflow saved"); }
  else if(r&&r.ok===false) uiToast("Lưu thất bại — xem log để biết chi tiết.","error");
}
async function wfImport(){
  const txt=await api().workflow_import(); if(!txt)return;
  try{ wfHydrate(JSON.parse(txt)); wfHasFile=true; wfMarkClean(); setStatus("Workflow imported"); uiToast("Đã mở workflow \""+(WF.name||"")+"\"","success"); }
  catch(e){ uiToast("File JSON không hợp lệ: "+e,"error"); }
}
// Play / stop glyphs for the run toggle (icon-only button).
const WF_ICO_PLAY = '<svg viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
const WF_ICO_STOP = '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>';
function wfSetRunning(on){
  wfRunning=on; const b=$("wf-run-btn");
  // While live, the taken wires carry a flowing dash (CSS keys off this class).
  const cvs=$("wf-canvas"); if(cvs) cvs.classList.toggle("wf-running", !!on);
  if(!on){
    if(typeof wfDebugMode!=="undefined") wfDebugMode=false;
    // Keep the green/red trail so the user can see where execution stopped.
    // Only remove the amber "currently running" pulse and dim unreached blocks.
    if(wfRunNode){ const _re=wfNodeElById(wfRunNode); if(_re) _re.classList.remove("running"); }
    wfRunNode=null; wfRunStopped=true;
    wfMarkUnreached();
    wfLiveVars={}; wfFreshVar=null;
    // Clear any activity still blinking "running" (stopped mid-activity), but
    // keep the solid green "done" / red "errored" markers so each activity's
    // outcome stays visible until the next run resets them.
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
  if(!WF.activities.length){ uiToast("Chưa có activity nào để chạy.","warning"); return; }
  // Pre-flight: chặn khi có LỖI cứng (dây đứt, thiếu template…) — cảnh báo thì
  // vẫn chạy bình thường. Người dùng có thể xem danh sách hoặc cố chạy tiếp.
  if(typeof wfValidationIssues==="function"){
    const issues=wfValidationIssues();
    const errs=issues.filter(i=>i.sev==="err").length;
    if(errs){
      const pick=await uiModal({
        title:"Workflow đang có lỗi",
        body:`<div class="ui-modal-msg">Phát hiện <b>${errs} lỗi</b>${issues.length-errs?` và ${issues.length-errs} cảnh báo`:""} — flow có thể dừng giữa chừng hoặc chạy sai nhánh.</div>`,
        buttons:[
          {label:"Hủy", value:"cancel"},
          {label:"Xem lỗi", value:"view"},
          {label:"Vẫn chạy", value:"run", kind:"err"},
        ],
      });
      if(pick==="view"){ wfValidatePanelShow(issues); return; }
      if(pick!=="run") return;
    }
  }
  wfResetRunViz();        // clear last run's colours BEFORE the engine starts emitting
  wfSetRunning(true);     // mark running before any node event can arrive
  const ok=await api().workflow_run(JSON.stringify(wfSerialize()));
  if(!ok) wfSetRunning(false);
}
async function wfRunGui(){
  if(!WF.activities.length){ uiToast("Chưa có activity nào.","warning"); return; }
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
  if(typeof wfPopulateOcrBackends==="function") wfPopulateOcrBackends(state.ocrBackends);
  (state.log||[]).forEach(appendLog);
  try{ const st=await api().get_settings(); wfSnapOn=!!st.snap; wfPreviewAll=!!st.previewAll;
    wfMinimapOn=!!st.minimap;                 // opt-in — default off
    wfAlignOn = st.alignGuides!==false;       // opt-out — default on
    if(st.previewHz){ wfPvHz=Math.max(0.2, Math.min(60, parseFloat(st.previewHz)||30)); const hz=$("wf-pv-hz"); if(hz) hz.value=wfPvHz; }
    if(st.logOpen===false){ const lc=$("log-card"); if(lc) lc.classList.add("collapsed"); }
    if(st.sideW){ const sd=$("wf-side"); if(sd) sd.style.width=Math.max(150,Math.min(480,st.sideW))+"px"; }
    if(st.inspW){ const insp=$("wf-inspector"); if(insp) insp.style.width=Math.max(180,Math.min(520,st.inspW))+"px"; } }catch{}
  wfInitSideResizer();
  wfInitInspResizer();
  wfSetupSortable($("wf-activities"));
  if($("wf-activities-bg")) wfSetupSortable($("wf-activities-bg"));
  if($("wf-functions")) wfSetupSortable($("wf-functions"));
  // Double-click a row name to rename in place.
  const actById=id=>WF.activities.find(a=>a.id===id);
  wfSetupRename($("wf-activities"), actById);
  wfSetupRename($("wf-activities-bg"), actById);
  wfSetupRename($("wf-functions"), id=>WF.functions.find(f=>f.id===id));
  wfSyncToggleBtns();
  if(typeof wfSyncControllerUI==="function") wfSyncControllerUI();
  wfSetRunning(false);   // seed the run button's play icon
  updateLogCount();
  wfInitCanvas();
  // Reopen the workflow that was open when the designer last closed.
  let reopened="", didRender=false;
  try{
    const lw=await api().get_last_workflow();
    if(lw && lw.text){ wfHydrate(JSON.parse(lw.text)); reopened=lw.name||"previous workflow"; didRender=true;
      wfHasFile=true; wfMarkClean(); }
  }catch(e){}
  // wfHydrate and wfAddActivity both call wfRenderAll() themselves; only fall back here.
  if(!WF.activities.length){ wfAddActivity("sequence"); didRender=true; }
  if(!didRender) wfRenderAll();
  wfZoomApplyMode("canvas");  // ensure the shared zoom cluster targets the graph on load
  setStatus(reopened ? ("Reopened: "+reopened) : "Ready");
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
