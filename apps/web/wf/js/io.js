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

// ── Per-entity JSON import (Debug JSON paste) ────────────────────────────────
// Apply a pasted object onto the live entity. Keeps the current id so the
// edit pointer / selection stay valid. Accepts the serialize shape, or (for
// activity) a full workflow JSON with an activities[] array.
function wfApplyActivityJson(act, raw){
  if(!act) throw new Error("No activity selected");
  if(!raw || typeof raw!=="object" || Array.isArray(raw)) throw new Error("JSON must be an object");
  let o=raw;
  // Unwrap a full workflow paste: prefer same id, else first activity.
  if(o.graph===undefined && Array.isArray(raw.activities) && raw.activities.length){
    o=raw.activities.find(a=>a && a.id===act.id) || raw.activities[0];
  }
  if(!o || typeof o!=="object" || Array.isArray(o)) throw new Error("Not a valid activity JSON");
  if(o.graph===undefined && o.vars===undefined && o.name===undefined && o.type===undefined)
    throw new Error("Not an activity JSON (need name, type, vars, or graph)");
  if(o.name!=null && String(o.name).trim()) act.name=String(o.name).trim();
  if(o.type==="background"||o.type==="sequence") act.type=o.type;
  if(o.enabled!==undefined) act.enabled=!!o.enabled;
  if(o.maxRetries!==undefined) act.maxRetries=parseInt(o.maxRetries,10)||1;
  if(o.pollInterval!==undefined) act.pollInterval=parseFloat(o.pollInterval)||1.0;
  if(o.vars!==undefined) act.vars=wfHydVars(o.vars);
  if(o.graph!==undefined) act.graph=wfHydrateGraph(o.graph);
  // act.id is intentionally left alone.
}
function wfApplyFunctionJson(fn, raw){
  if(!fn) throw new Error("No function selected");
  if(!raw || typeof raw!=="object" || Array.isArray(raw)) throw new Error("JSON must be an object");
  let o=raw;
  if(o.graph===undefined && Array.isArray(raw.functions) && raw.functions.length){
    o=raw.functions.find(f=>f && f.id===fn.id) || raw.functions[0];
  }
  if(!o || typeof o!=="object" || Array.isArray(o)) throw new Error("Not a valid function JSON");
  if(o.graph===undefined && o.name===undefined) throw new Error("Not a function JSON (need name or graph)");
  if(o.name!=null && String(o.name).trim()) fn.name=String(o.name).trim();
  if(o.graph!==undefined) fn.graph=wfHydrateGraph(o.graph);
}
function wfApplyNodeJson(node, raw){
  if(!node) throw new Error("No node selected");
  if(!raw || typeof raw!=="object" || Array.isArray(raw)) throw new Error("JSON must be an object");
  if(node.type==="start") throw new Error("Cannot import over the Start node");
  const o=raw.params!==undefined||raw.type!==undefined?raw:(raw.nodes&&raw.nodes[0])||raw;
  if(!o || typeof o!=="object" || Array.isArray(o)) throw new Error("Not a valid node JSON");
  if(o.type==="start") throw new Error("Cannot import a Start node onto another block");
  if(o.type!=null && String(o.type).trim() && o.type!=="start") node.type=String(o.type).trim();
  if(o.params!==undefined) node.params=o.params||{};
  if(o.note!==undefined) node.note=o.note||"";
  if(o.log!==undefined) node.log=o.log||"";
  if(o.delayBefore!==undefined) node.delayBefore=parseFloat(o.delayBefore)||0;
  if(o.delayAfter!==undefined) node.delayAfter=parseFloat(o.delayAfter)||0;
  if(o.retryCount!==undefined) node.retryCount=parseInt(o.retryCount,10)||0;
  if(o.retryDelay!==undefined) node.retryDelay=parseFloat(o.retryDelay)||0;
  if(o.screenshotOnFail!==undefined) node.screenshotOnFail=!!o.screenshotOnFail;
  if(o.showPreview!==undefined) node.showPreview=!!o.showPreview;
  if(o.stack!==undefined) node.stack=o.stack||null;
  // Keep node.id / x / y unless the paste explicitly provides coords.
  if(o.x!==undefined) node.x=Math.round(o.x)||node.x;
  if(o.y!==undefined) node.y=Math.round(o.y)||node.y;
}
function wfSerialize(){
  wfSpeedFromUI();
  if(typeof wfPackageFromUI==="function") wfPackageFromUI();
  const sh=WF.speedhack||{enabled:false,speed:2.0};
  const w=WF.win32||{window:"",matchBy:"title",inputMode:"background"};
  const isWin32=(WF.controller==="win32");
  return {
    name:$("wf-name").value||"workflow", version:2, templatesDir:WF.templatesDir||"templates",
    // Release version for a standalone Runner .exe built from this workflow.
    buildVersion:(WF.buildVersion||"1.0.0"),
    // Target Android package (workflow-level; used by speed hack + as a project hint).
    package:(WF.package||"").trim(),
    controller:isWin32?"win32":"adb",
    ocr:(WF.ocrBackend||"").trim(),
    // ADB frame source for this game/workflow ("scrcpy" | "adb").
    capture:(WF.captureBackend==="adb")?"adb":"scrcpy",
    win32:{ window:(w.window||"").trim(), matchBy:wfNormWinMatchBy(w.matchBy), inputMode:wfNormWinInputMode(w.inputMode) },
    // Speed hack is ADB-only (Frida). Package lives at the top level (key "package").
    // Force speedhack off in Win32 so a stale enabled flag never starts Frida.
    speedhack:{ enabled:isWin32?false:!!sh.enabled, speed:sh.speed||2.0 },
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
    // Package-bearing app nodes: add pkgSrc if missing.
    // Had a free-text package → "custom"; empty → "project" (use Project settings).
    if(params && (n.type==="launch_app"||n.type==="app_stop"||n.type==="app_uninstall"||n.type==="if_app")){
      if(params.pkgSrc===undefined||params.pkgSrc===null||params.pkgSrc===""){
        params.pkgSrc = (String(params.package||"").trim()) ? "custom" : "project";
      }
    }
    // Multi-point tap accepts compact legacy [x,y] pairs, but the inspector
    // edits named coordinates for readable JSON.
    if(params && n.type==="multi_tap"){
      params.points=(Array.isArray(params.points)?params.points:[]).map(pt=>Array.isArray(pt)
        ? {x:Number(pt[0])||0,y:Number(pt[1])||0}
        : {x:Number(pt&&pt.x)||0,y:Number(pt&&pt.y)||0});
    }
    // Random tap used to store top-left + width/height. Convert it to two
    // explicit corners so the inspector shows the same region the engine uses.
    if(params && n.type==="tap_random" && !["x1","y1","x2","y2"].some(k=>params[k]!==undefined)){
      const x=Number(params.x)||0, y=Number(params.y)||0;
      params.x1=x; params.y1=y;
      params.x2=x+(params.w===undefined?100:Math.max(0,Number(params.w)||0));
      params.y2=y+(params.h===undefined?100:Math.max(0,Number(params.h)||0));
      delete params.x; delete params.y; delete params.w; delete params.h;
    }
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
  WF.buildVersion=String(flow.buildVersion||"1.0.0").trim()||"1.0.0";
  const sh=flow.speedhack||{};
  // Speed hack is only {enabled, speed}. Package is top-level; migrate legacy
  // speedhack.package when opening older workflow files.
  WF.speedhack={enabled:!!sh.enabled, speed:(parseFloat(sh.speed)||2.0)};
  WF.package=String(flow.package!=null?flow.package:(sh.package||"")).trim();
  WF.controller=(flow.controller==="win32")?"win32":"adb";
  WF.ocrBackend=String(flow.ocr||"").trim().toLowerCase();
  if(typeof wfSyncOcrUI==="function") wfSyncOcrUI();
  // Capture backend: key "capture" (preferred); accept legacy aliases.
  {
    const raw=String(flow.capture!=null?flow.capture
      :(flow.captureBackend!=null?flow.captureBackend
        :(flow.capture_backend!=null?flow.capture_backend:""))).trim().toLowerCase();
    WF.captureBackend=(raw==="adb")?"adb":"scrcpy";
  }
  if(typeof wfApplyCaptureBackend==="function") wfApplyCaptureBackend(WF.captureBackend);
  // Force speed hack off in Win32 mode (ADB/Frida only) so a file saved with
  // enabled=true under the old cheat.dll path can't revive it.
  if(WF.controller==="win32") WF.speedhack.enabled=false;
  const w=flow.win32||{}; WF.win32={window:(w.window||"").trim(), matchBy:wfNormWinMatchBy(w.matchBy), inputMode:wfNormWinInputMode(w.inputMode)};
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
// Every mutation that goes through wfPushUndo/wfPushUndoDebounced calls
// wfMarkDirty(): the Save button shows an amber "unsaved" dot, and (once the
// flow has a file) a 3s-debounced autosave silently overwrites it —
// workflow_save never opens a dialog, so this is safe.
let wfDirty=false;          // there are changes not yet written to disk
let wfHasFile=false;        // the flow is bound to a concrete file (opened/saved at least once)
let wfAutosaveOn=true;
let _wfAutosaveTimer=null;
let _wfAutosaveFailAt=0;    // throttle the failure toast (autosave retries often)
function wfSyncDirtyUI(){
  const b=$("wf-save-btn");
  if(b){ b.classList.toggle("dirty", wfDirty);
    b.title = wfDirty ? "Save (Ctrl+S) — unsaved changes" : "Save to the current file (Ctrl+S)"; }
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
  if(wfRunning){ _wfAutosaveTimer=setTimeout(wfAutosave, 5000); return; }   // wait for the run to finish
  let failed=false;
  try{
    const r=await api().workflow_save(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
    if(r&&r.ok){ setStatus("Autosaved · "+new Date().toLocaleTimeString()); wfMarkClean(); return; }
    failed = !!(r && r.ok===false);
  }catch{ failed=true; }
  // Autosave failed: the dirty dot stays on, and (throttled to once a minute)
  // a toast says so — a silent catch here used to hide disk-full/locked-file
  // errors until the user lost work.
  if(failed && Date.now()-_wfAutosaveFailAt>60000){
    _wfAutosaveFailAt=Date.now();
    if(typeof uiToast==="function") uiToast("Autosave failed — use Ctrl+S and check the log.","error");
  }
}
// Block closing the window while there are unsaved changes (best-effort in WebView2).
window.addEventListener("beforeunload", e=>{ if(wfDirty){ e.preventDefault(); e.returnValue=""; } });

async function wfExport(){
  const ok=await api().workflow_export(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
  if(ok){ wfHasFile=true; wfMarkClean(); setStatus("Workflow saved"); }
}
let wfSaving=false;
async function wfSave(){
  if(wfSaving) return;
  wfSaving=true;
  const btn=$("wf-save-btn"), oldTitle=btn&&btn.title;
  if(btn){ btn.disabled=true; btn.classList.add("saving"); btn.setAttribute("aria-busy","true"); btn.title="Saving workflow…"; }
  try{
    const r=await api().workflow_save(JSON.stringify(wfSerialize(),null,2), $("wf-name").value);
    if(r&&r.ok){ wfHasFile=true; wfMarkClean(); setStatus("Workflow saved"); uiToast("Workflow saved","success",{dur:1600}); }
    else uiToast("Save failed — check the log for details.","error");
  }catch(e){
    uiToast("Save failed — "+String(e&&e.message||e||"unknown error"),"error");
  }finally{
    wfSaving=false;
    if(btn){ btn.disabled=false; btn.classList.remove("saving"); btn.removeAttribute("aria-busy"); btn.title=oldTitle||"Save workflow"; }
  }
}
async function wfImport(){
  const txt=await api().workflow_import(); if(!txt)return;
  try{ wfHydrate(JSON.parse(txt)); wfHasFile=true; wfMarkClean(); setStatus("Workflow imported"); uiToast("Opened workflow \""+(WF.name||"")+"\"","success"); }
  catch(e){ uiToast("Invalid JSON file: "+e,"error"); }
}

// ── Build EXE — package this workflow into a standalone Runner .exe ────────────
let wfBuilding=false;
// Normalize a version like "1.2" / " v1.0.0 " → "1.2" / "1.0.0" (digits + dots).
function wfNormVersion(raw){
  const cleaned=String(raw||"").trim().replace(/^v/i,"").replace(/[^0-9.]/g,"");
  const parts=cleaned.split(".").filter(s=>s!=="").slice(0,4);
  return parts.length ? parts.join(".") : "1.0.0";
}
async function wfBuildExe(){
  if(wfBuilding){ uiToast("A build is already running — check the log.","info"); return; }
  if(!WF.activities || !WF.activities.length){ uiToast("Add at least one activity before building.","error"); return; }
  const cur=wfNormVersion(WF.buildVersion||"1.0.0");
  let verInp=null;
  const v=await uiModal({
    title:"Build standalone Runner .exe",
    width:"440px",
    body:(bd)=>{
      bd.innerHTML=
        `<div class="wf-new-form">`+
          `<div class="wf-new-field">`+
            `<div class="ui-modal-lbl">Workflow</div>`+
            `<div class="hint" style="margin-top:2px">${escHtml(WF.name||"workflow")} — packages the Runner + this one workflow (no Designer). Only the vendor tools it uses are bundled.</div>`+
          `</div>`+
          `<div class="wf-new-field">`+
            `<label class="ui-modal-lbl" for="wf-build-ver">Version</label>`+
            `<input id="wf-build-ver" class="ui-modal-inp" type="text" value="${escHtml(cur)}" spellcheck="false" autocomplete="off" placeholder="1.0.0">`+
            `<div class="hint">Stamped onto the .exe. Output: <code>dist/${escHtml((WF.name||"workflow").replace(/[^A-Za-z0-9_\-]+/g,"_"))}-Runner/</code></div>`+
          `</div>`+
        `</div>`;
      verInp=bd.querySelector("#wf-build-ver");
      setTimeout(()=>{ try{ verInp.focus(); verInp.select(); }catch{} },0);
    },
    buttons:[
      {label:"Cancel", value:null},
      {label:"Build", value:"ok", kind:"accent"},
    ],
  });
  if(v!=="ok") return;
  const version=wfNormVersion(verInp && verInp.value);
  // Persist the version on the flow so it sticks across sessions.
  if(WF.buildVersion!==version){ WF.buildVersion=version; if(typeof wfMarkDirty==="function") wfMarkDirty(); }

  wfBuilding=true;
  const btn=$("wf-build-btn");
  if(btn){ btn.disabled=true; btn.classList.add("saving"); btn.setAttribute("aria-busy","true"); }
  // Open the log drawer so the streamed PyInstaller progress is visible.
  const card=$("log-card"); if(card && card.classList.contains("collapsed") && typeof wfToggleLog==="function") wfToggleLog();
  uiToast("Building "+(WF.name||"workflow")+" v"+version+" … (this can take a minute)","info",{dur:4000});
  setStatus("Building standalone Runner .exe …");
  try{
    const r=await api().build_runner_exe(JSON.stringify(wfSerialize(),null,2), version);
    if(r && r.ok===false){ wfOnBuildDone({ok:false, error:r.error||"Build could not start"}); }
    // Otherwise the build runs in a worker thread; wfOnBuildDone fires via event.
  }catch(e){
    wfOnBuildDone({ok:false, error:String(e&&e.message||e||"unknown error")});
  }
}
async function wfOnBuildDone(data){
  wfBuilding=false;
  const btn=$("wf-build-btn");
  if(btn){ btn.disabled=false; btn.classList.remove("saving"); btn.removeAttribute("aria-busy"); }
  if(data && data.ok){
    setStatus("Build complete");
    const open=await uiConfirm({title:"Build complete", message:(data.path||"The Runner .exe was built.")+"\n\nOpen the output folder?", ok:"Open folder"});
    if(open && data.path){ try{ await api().reveal_path(data.path); }catch{} }
  }else{
    setStatus("Build failed");
    uiToast("Build failed — "+((data&&data.error)||"see the log for details"),"error");
  }
}

// Play / stop glyphs for the run toggle (icon-only button).
const WF_ICO_PLAY = '<svg viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
const WF_ICO_STOP = '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>';
let wfRunStartedAt=0, wfRunClockTimer=null;
function wfFormatRunTime(ms){
  const total=Math.max(0,Math.floor(ms/1000)), h=Math.floor(total/3600), m=Math.floor(total%3600/60), s=total%60;
  return h>0 ? String(h).padStart(2,"0")+":"+String(m).padStart(2,"0")+":"+String(s).padStart(2,"0")
    : String(m).padStart(2,"0")+":"+String(s).padStart(2,"0");
}
function wfUpdateRunClock(){
  const out=$("wf-run-time"); if(out&&wfRunStartedAt) out.textContent=wfFormatRunTime(Date.now()-wfRunStartedAt);
}
function wfStartRunClock(){
  wfRunStartedAt=Date.now();
  const wrap=$("wf-run-elapsed"); if(wrap) wrap.style.display="inline-flex";
  wfUpdateRunClock();
  if(wfRunClockTimer) clearInterval(wfRunClockTimer);
  wfRunClockTimer=setInterval(wfUpdateRunClock,500);
}
function wfStopRunClock(){
  if(wfRunClockTimer){ clearInterval(wfRunClockTimer); wfRunClockTimer=null; }
  wfRunStartedAt=0;
  const wrap=$("wf-run-elapsed"); if(wrap) wrap.style.display="none";
}
function wfSetRunning(on){
  on=!!on; const wasRunning=wfRunning; wfRunning=on;
  if(on&&!wasRunning) wfStartRunClock(); else if(!on) wfStopRunClock();
  const b=$("wf-run-btn");
  // While live, the taken wires carry a flowing dash (CSS keys off this class).
  const cvs=$("wf-canvas"); if(cvs) cvs.classList.toggle("wf-running", !!on);
  if(!on){
    if(typeof wfDebugMode!=="undefined") wfDebugMode=false;
    if(typeof wfClearDebugPause==="function") wfClearDebugPause();
    // Drop any mid-wait delayBefore/After countdown; trail colours stay.
    if(typeof wfClearNodeDelay==="function") wfClearNodeDelay();
    // Keep the green/red trail so the user can see where execution stopped.
    // Only remove the amber "currently running" pulse and dim unreached blocks.
    if(wfRunNode){ const _re=wfNodeElById(wfRunNode); if(_re) _re.classList.remove("running","delaying"); }
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
  // Running status pill: amber while executing; green Ready / amber Stopped at rest.
  const pill=$("wf-run-status");
  if(pill){
    pill.classList.toggle("running", !!on);
    pill.classList.toggle("ok", !on && !wfRunStopped);
    pill.classList.remove("err");
    const txt=pill.querySelector(".wf-run-txt");
    if(txt) txt.textContent = on ? "Running" : (wfRunStopped ? "Stopped" : "Ready");
  }
  wfRenderVarsPanel();
}
async function wfToggleRun(){
  if(wfRunning){ wfSetRunning(false); await api().workflow_stop(); return; }  // reset first, then stop
  if(!WF.activities.length){ uiToast("No activities to run yet.","warning"); return; }
  await wfStartRunFlow(null);
}
// Run exactly one activity (right-click → "Run this activity only"). Other
// activities are sent as disabled so the engine skips them without mutating
// the designer's enable checkboxes.
async function wfRunOneActivity(actId){
  if(wfRunning){ uiToast("A workflow is already running — stop it first.","warning"); return; }
  const act=(WF.activities||[]).find(a=>a.id===actId);
  if(!act){ uiToast("Activity not found.","error"); return; }
  // Open the target activity so the live node trail paints on the right graph.
  if(typeof wfSelectActivity==="function") wfSelectActivity(actId);
  await wfStartRunFlow(actId);
}
// Shared pre-flight + engine start. ``onlyId`` null → all enabled activities;
// otherwise only that activity is marked enabled in the payload.
async function wfStartRunFlow(onlyId){
  if(typeof wfValidationIssues==="function"){
    const issues=wfValidationIssues();
    const errs=issues.filter(i=>i.sev==="err").length;
    if(errs){
      const pick=await uiModal({
        title:"The workflow has errors",
        body:`<div class="ui-modal-msg">Found <b>${errs} error${errs===1?"":"s"}</b>${issues.length-errs?` and ${issues.length-errs} warning${issues.length-errs===1?"":"s"}`:""} — the flow may stop midway or take the wrong branch.</div>`,
        buttons:[
          {label:"Cancel", value:"cancel"},
          {label:"View errors", value:"view"},
          {label:"Run anyway", value:"run", kind:"err"},
        ],
      });
      if(pick==="view"){ wfValidatePanelShow(issues); return; }
      if(pick!=="run") return;
    }
  }
  wfResetRunViz();
  if(typeof wfPvOverlay!=="undefined"){ wfPvOverlay=[]; wfPvMatchRegion=null; wfPvOverlayMeta=null; if(typeof wfPvDraw==="function") wfPvDraw(); }
  const flow=wfSerialize();
  if(onlyId){
    (flow.activities||[]).forEach(a=>{ a.enabled = (a.id===onlyId); });
    const target=(flow.activities||[]).find(a=>a.id===onlyId);
    setStatus("Running only «"+(target&&target.name?target.name:onlyId)+"»…");
  }
  wfSetRunning(true);
  const ok=await api().workflow_run(JSON.stringify(flow));
  if(!ok) wfSetRunning(false);
}
async function wfRunGui(){
  if(!WF.activities.length){ uiToast("No activities yet.","warning"); return; }
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
    if(st.logOpen===false){ const lc=$("log-card"); if(lc) lc.classList.add("collapsed"); const t=$("log-toggle"); if(t) t.setAttribute("aria-expanded","false"); }
    if(st.logH){ const lc=$("log-card"); if(lc){ const h=Math.max(80, Math.min(480, parseInt(st.logH,10)||140)); lc.style.height=h+"px"; lc.dataset.openH=String(h); } }
    const sd=$("wf-side"), insp=$("wf-inspector");
    if(sd){ const w=st.sideW?Math.max(150,Math.min(480,st.sideW)):sd.offsetWidth; sd.style.width=w+"px"; sd.dataset.openW=String(w); }
    if(insp){ const w=st.inspW?Math.max(180,Math.min(520,st.inspW)):insp.offsetWidth; insp.style.width=w+"px"; insp.dataset.openW=String(w); }
    wfSideCollapsed=st.sideCollapsed===true; wfInspCollapsed=st.inspCollapsed===true;
  }catch{}
  wfApplySidebarState(false);
  wfInitSideResizer();
  wfInitInspResizer();
  if(typeof wfInitLogResizer==="function") wfInitLogResizer();
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
