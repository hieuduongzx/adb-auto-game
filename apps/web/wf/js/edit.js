// ── Edit target (activity or function) ───────────────────────────────────────
function wfActById(id){ return WF.activities.find(a=>a.id===id)||null; }
function wfFnById(id){ return WF.functions.find(f=>f.id===id)||null; }
function wfEditTarget(){ return WF.edit.kind==="function" ? wfFnById(WF.edit.id) : wfActById(WF.edit.id); }
function wfCurAct(){ return WF.edit.kind==="activity" ? wfActById(WF.edit.id) : null; }
function wfCurFn(){ return WF.edit.kind==="function" ? wfFnById(WF.edit.id) : null; }
function wfGraph(){ const t=wfEditTarget(); return t?t.graph:null; }
function wfNode(id){ const g=wfGraph(); return g?g.nodes.find(n=>n.id===id):null; }

// ── Follow-focus ─────────────────────────────────────────────────────────────
// When ON (default), the canvas auto-centres on the node the engine is running.
// If the flow steps into a function's graph (or back out into an activity), the
// editor switches to that graph too — so focus follows execution across the
// call boundary. The toggle lives on the activity panel header.
let wfFocusOn = false;
// Debug overlay — when ON, every image/color/OCR match the engine reports is
// drawn on the Preview tab (box + confidence + search region). Off by default
// so a normal test run stays clean; turn on to diagnose template misses.
// Persisted in localStorage so the preference survives restarts.
let wfDebugOverlayOn = false;
try{ wfDebugOverlayOn = localStorage.getItem("wfDebugOverlay")==="1"; }catch{}
// Locate which activity or function graph contains a node id → {kind,id,node}.
function wfFindNodeOwner(nodeId){
  if(!nodeId) return null;
  for(const a of WF.activities){
    const n=(a.graph&&a.graph.nodes||[]).find(n=>n.id===nodeId);
    if(n) return {kind:"activity", id:a.id, node:n};
  }
  for(const f of WF.functions){
    const n=(f.graph&&f.graph.nodes||[]).find(n=>n.id===nodeId);
    if(n) return {kind:"function", id:f.id, node:n};
  }
  return null;
}
// Switch the edit target WITHOUT resetting pan/zoom (unlike wfSelectActivity /
// wfEditFunction which reset the camera). Used by focus so following execution
// keeps the current zoom level and just re-centres on the running node.
function wfFocusSwitchTarget(kind, id){
  if(typeof wfSwitchEditTarget==="function"){
    if(!wfSwitchEditTarget(kind,id)) return false;
  } else {
    if(WF.edit.kind===kind && WF.edit.id===id) return false;
    WF.edit={kind,id}; wfClearSel();
  }
  wfRenderAll();
  return true;
}
// Follow the engine to `nodeId`: switch graphs if the node lives in another
// activity/function, then centre the viewport on it. No-op when focus is off.
function wfFocusFollow(nodeId){
  if(!wfFocusOn || !nodeId) return;
  const owner=wfFindNodeOwner(nodeId);
  if(!owner) return;
  const switched=wfFocusSwitchTarget(owner.kind, owner.id);
  const n = switched ? owner.node : (wfNode(nodeId)||owner.node);
  if(n) wfCenterOnNode(n);
}
// Reflect the focus flag on the header toggle button (on/off tint).
function wfSyncFocusBtn(){
  const b=$("wf-act-focus");
  if(b){ b.classList.toggle("on", wfFocusOn); b.setAttribute("aria-pressed",String(wfFocusOn)); b.title = wfFocusOn
    ? "Focus: ON - auto-centre on the running block (follows into/out of functions). Click to turn off."
    : "Focus: OFF - canvas stays put during a run. Click to turn on."; }
}
function wfSyncDebugOverlayBtn(){
  const b=$("wf-act-dbg");
  if(b){ b.classList.toggle("on", wfDebugOverlayOn); b.setAttribute("aria-pressed",String(wfDebugOverlayOn)); b.title = wfDebugOverlayOn
    ? "Debug overlay: ON - image/color/OCR matches draw box + conf on Preview (doesn't switch tabs). Click to turn off."
    : "Debug overlay: OFF - matches aren't drawn during a run. Click to turn on."; }
}
// Toggle follow-focus. When turned on mid-run, immediately snap to the block
// that's running right now — using the engine's true current node (wfLiveNode),
// which may live in an off-screen function graph, not just the last node lit in
// the viewed graph (wfRunNode).
function wfToggleFocus(){
  wfFocusOn=!wfFocusOn;
  wfSyncFocusBtn();
  setStatus("Focus "+(wfFocusOn?"on":"off"));
  if(wfFocusOn){ const id=wfLiveNode||wfRunNode; if(id) wfFocusFollow(id); }
}
// Toggle match overlay on Preview. When turned off mid-run, clear the current
// boxes so the screen is clean again; when on, next engine match paints immediately.
function wfToggleDebugOverlay(){
  wfDebugOverlayOn=!wfDebugOverlayOn;
  try{ localStorage.setItem("wfDebugOverlay", wfDebugOverlayOn?"1":"0"); }catch{}
  wfSyncDebugOverlayBtn();
  if(!wfDebugOverlayOn){
    if(typeof wfPvOverlay!=="undefined"){
      wfPvOverlay=[]; wfPvMatchRegion=null; wfPvOverlayMeta=null;
      if(typeof wfPvDraw==="function") wfPvDraw();
    }
    setStatus("Debug overlay off");
  } else {
    // Never force a tab switch — just arm the draw flag; the user opens Preview when they want to look.
    setStatus("Debug overlay on - match boxes draw on the Preview tab");
  }
}
// Should the current match event be painted? Debug-overlay toggle, or a
// single-block Test (always shows overlay — that's the point of Test).
function wfWantMatchOverlay(){
  return !!wfDebugOverlayOn || !!(typeof wfNodeTesting!=="undefined" && wfNodeTesting);
}
// ── Node usage memory ────────────────────────────────────────────────────────
// Remembers which block types the user actually creates so the quick menu can
// rank a "Recent" + "Frequently used" shortcut above the full catalog. Persisted
// in localStorage; capped and pruned by recency so it cannot grow unbounded.
const WF_USE_KEY="wfNodeUse", WF_USE_MAX=100;
let wfNodeUse={};
try{ wfNodeUse=JSON.parse(localStorage.getItem(WF_USE_KEY)||"{}")||{}; }catch{}
function wfRecordNodeUse(type){
  if(!type||typeof WF_NODES==="undefined"||!WF_NODES[type]||WF_NODES[type].hidden) return;
  const e=wfNodeUse[type]||{n:0,t:0};
  e.n=(e.n||0)+1; e.t=Date.now(); wfNodeUse[type]=e;
  const keys=Object.keys(wfNodeUse);
  if(keys.length>WF_USE_MAX){
    keys.sort((a,b)=>(wfNodeUse[a].t||0)-(wfNodeUse[b].t||0));
    keys.slice(0,keys.length-WF_USE_MAX).forEach(k=>{ delete wfNodeUse[k]; });
  }
  try{ localStorage.setItem(WF_USE_KEY, JSON.stringify(wfNodeUse)); }catch{}
}
// Ranked picks for the quick menu: most recently created first, then the
// overall most-created — the frequent list drops anything already in recent so
// the same block never shows twice.
function wfNodeUsePicks(recentMax,freqMax){
  if(typeof WF_NODES==="undefined") return {recent:[],freq:[]};
  const rows=Object.keys(wfNodeUse).map(type=>({type,n:wfNodeUse[type].n||0,t:wfNodeUse[type].t||0}))
    .filter(r=>WF_NODES[r.type]&&!WF_NODES[r.type].hidden);
  const recent=rows.slice().sort((a,b)=>b.t-a.t).slice(0,recentMax||6);
  const seen=new Set(recent.map(r=>r.type));
  const freq=rows.slice().sort((a,b)=>b.n-a.n||b.t-a.t)
    .filter(r=>!seen.has(r.type)).slice(0,freqMax||6);
  return {recent:recent.map(r=>r.type),freq:freq.map(r=>r.type)};
}

// ── Designer handoff context ────────────────────────────────────────────────
// Preview picks are creation context: a crop, point, or swipe can seed several
// related blocks until the user captures something newer or opens a new flow.
let wfLatestTemplate="";
function wfTemplateRef(path){
  const norm=String(path||"").trim().replace(/\\/g,"/");
  if(!norm) return "";
  const dir=String((typeof WF!=="undefined"&&WF.templatesDir)||"templates").replace(/^\.?[\\/]+|[\\/]+$/g,"")||"templates";
  const marker="/"+dir+"/", at=norm.toLowerCase().lastIndexOf(marker.toLowerCase());
  if(at>=0) return dir+"/"+norm.slice(at+marker.length);
  if(norm.toLowerCase().startsWith((dir+"/").toLowerCase())) return norm;
  return norm;
}
function wfTemplateIdentity(path){
  const ref=wfTemplateRef(path), dir=String((typeof WF!=="undefined"&&WF.templatesDir)||"templates").replace(/^\.?[\\/]+|[\\/]+$/g,"")||"templates";
  return ref.toLowerCase().startsWith((dir+"/").toLowerCase())?ref.slice(dir.length+1):ref;
}
function wfRememberTemplate(path){
  wfLatestTemplate=wfTemplateRef(path);
  return wfLatestTemplate;
}
function wfTemplateContextRenamed(oldPath,newPath){
  const oldRef=wfTemplateRef(oldPath);
  if(!wfLatestTemplate || wfTemplateIdentity(oldRef)!==wfTemplateIdentity(wfLatestTemplate)) return;
  const next=wfTemplateRef(newPath);
  const dir=String((typeof WF!=="undefined"&&WF.templatesDir)||"templates").replace(/^\.?[\\/]+|[\\/]+$/g,"")||"templates";
  wfLatestTemplate=next.includes("/")?next:`${dir}/${next}`;
}
function wfTemplateContextDeleted(path){
  const ref=wfTemplateRef(path);
  if(wfLatestTemplate && wfTemplateIdentity(ref)===wfTemplateIdentity(wfLatestTemplate)) wfLatestTemplate="";
}
function wfForgetDesignerContext(){
  wfLatestTemplate="";
  if(typeof wfPvPoint!=="undefined") wfPvPoint=null;
  if(typeof wfPvRegion!=="undefined") wfPvRegion=null;
  if(typeof wfPvSwipe!=="undefined") wfPvSwipe=null;
  if(typeof wfPvSyncOverlayBtn==="function") wfPvSyncOverlayBtn();
}

// Each activity/function keeps its own viewport, like tabs in a graphics tool.
// The map is session-only; workflow JSON remains focused on executable data.
const wfGraphCameras=new Map();
function wfCameraKey(edit){ return edit&&edit.id?`${edit.kind}:${edit.id}`:""; }
function wfSaveGraphCamera(){
  if(typeof wfPan==="undefined"||typeof wfZoom==="undefined") return;
  const key=wfCameraKey(WF.edit); if(!key) return;
  wfGraphCameras.set(key,{pan:{x:wfPan.x,y:wfPan.y},zoom:wfZoom});
}
function wfRestoreGraphCamera(kind,id){
  if(typeof wfPan==="undefined"||typeof wfZoom==="undefined") return;
  const saved=wfGraphCameras.get(wfCameraKey({kind,id}));
  wfPan=saved?{x:saved.pan.x,y:saved.pan.y}:{x:0,y:0};
  wfZoom=saved?saved.zoom:1;
}
function wfResetGraphCameras(){ wfGraphCameras.clear(); }
function wfSwitchEditTarget(kind,id){
  if(WF.edit.kind===kind&&WF.edit.id===id) return false;
  wfSaveGraphCamera();
  WF.edit={kind,id}; wfClearSel(); wfRestoreGraphCamera(kind,id);
  return true;
}
function wfApplyTemplateToNode(node,path){
  if(!node||!path) return false;
  const def=typeof WF_NODES!=="undefined"&&WF_NODES[node.type];
  const field=def&&(def.fields||[]).find(f=>f.t==="tpl"||f.t==="tpls"||f.t==="sequence_images");
  if(!field) return false;
  const ref=wfTemplateRef(path); if(!ref) return false;
  node.params=node.params||{};
  if(field.t==="tpl") node.params[field.k]=ref;
  else if(field.t==="tpls"){
    const list=Array.isArray(node.params[field.k])?node.params[field.k]:[];
    if(!list.includes(ref)) list.push(ref);
    node.params[field.k]=list;
  } else {
    const list=Array.isArray(node.params[field.k])?node.params[field.k]:[];
    if(list.length) list[0]={...list[0],template:ref};
    else list.push({template:ref,threshold:.85,timeout:10,offsetX:0,offsetY:0,delayAfterFind:0,delay:.1});
    node.params[field.k]=list;
  }
  return true;
}
function wfNewNode(type,x,y){
  wfRecordNodeUse(type);
  // Seed the universal per-node fields (timing + failure handling) from the
  // project defaults where set — see WF.nodeDefaults and the Inspector's
  // Timing ▸ (gear) dialog. Existing nodes are unaffected; this is a stamp.
  const nd=(typeof WF!=="undefined"&&WF.nodeDefaults)||{};
  const num=(k,fallback)=>{ const v=parseFloat(nd[k]); return Number.isFinite(v)?v:fallback; };
  const params=wfDefaults(type);
  const picked=(typeof wfPvPoint!=="undefined"&&Array.isArray(wfPvPoint))?wfPvPoint:
    ((Array.isArray(window.wfCopiedPoint))?window.wfCopiedPoint:null);
  if(picked && ["tap","double_tap","long_press","win_click"].includes(type)) {
    params.x=picked[0]; params.y=picked[1]; params.target="pos";
  }
  if(picked && type==="sequence_tap" && Array.isArray(params.points) && params.points.length)
    params.points[0].x=picked[0], params.points[0].y=picked[1];
  const swipe=(typeof wfPvSwipe!=="undefined"&&wfPvSwipe)?wfPvSwipe:null;
  if(swipe && type==="swipe") Object.assign(params,{mode:"coordinates",x1:swipe.x1,y1:swipe.y1,x2:swipe.x2,y2:swipe.y2,duration:swipe.duration});
  const node=wfNormalizeNode({id:wfUid(),type,x,y,params,note:"",log:"",outputLogs:{},
    delayBefore:num("delayBefore",0), delayAfter:num("delayAfter",0),
    retryCount:num("retryCount",0), retryDelay:num("retryDelay",0),
    screenshotOnFail:!!nd.screenshotOnFail,
    showPreview:false});
  if(wfLatestTemplate) wfApplyTemplateToNode(node,wfLatestTemplate);
  return node;
}
// Every fresh graph seeds both terminals: Start, and an End further right —
// reaching End is what makes a function call return true, so it should always
// be there to wire into.
function wfNewGraph(){ return { nodes:[
  {id:wfUid(),type:"start",x:48,y:72,params:{}},
  {id:wfUid(),type:"end",x:440,y:72,params:{}},
], edges:[], groups:[] }; }

function wfAddActivity(type){
  wfPushUndo();
  const n=WF.activities.filter(a=>a.type===type).length+1;
  const id=type+"_"+wfUid().slice(1,5);
  const act={id, name:(type==="background"?"Background task ":"Activity ")+n, type,
    enabled:true, maxRetries:1, pollInterval:1.0, vars:[], graph:wfNewGraph()};
  WF.activities.push(act); wfSwitchEditTarget("activity",id);
  if(typeof wfActTab==="function") wfActTab(type==="background"?"bg":"seq");
  wfRenderAll();
}
function wfDeleteActivity(id,ev){
  ev&&ev.stopPropagation();
  const i=WF.activities.findIndex(a=>a.id===id); if(i<0)return;
  uiConfirm({title:"Delete activity?", message:`Delete activity "${WF.activities[i].name}" and every block inside it?`, ok:"Delete", danger:true}).then(ok=>{
    if(!ok) return;
    const j=WF.activities.findIndex(a=>a.id===id); if(j<0) return;
    wfPushUndo();
    WF.activities.splice(j,1);
    wfActSel.delete(id);
    if(WF.edit.kind==="activity"&&WF.edit.id===id){
      const next=WF.activities[0]?WF.activities[0].id:null;
      wfSwitchEditTarget("activity",next);
    }
    wfRenderAll();
  });
}
// Re-clicking the already-open activity is a no-op (keeps the camera, and lets
// the second click of a rename double-click land on a live row).
function wfSelectActivity(id){ if(!wfSwitchEditTarget("activity",id)) return; wfRenderAll(); }
function wfToggleActivity(id,ev){ ev&&ev.stopPropagation(); const a=wfActById(id); if(a){ wfPushUndo(); a.enabled=!a.enabled; wfRenderActivities(); } }

// ── Multi-select of activity rows (explorer-style) ──────────────────────────
// Ctrl+click toggles a row into the highlighted selection, Shift+click takes a
// range, plain click clears it (and opens the activity as before). The set is
// then what Ctrl+right-click runs. Independent of the enable checkboxes.
const wfActSel=new Set();   // highlighted activity ids
let wfActAnchor=null;       // last plain/ctrl-clicked row — Shift ranges start here
// Repaint the highlight on the current rows without a full re-render.
function wfActSelPaint(){
  document.querySelectorAll(".wf-act[data-id]").forEach(el=>{
    const isFn=el.classList.contains("wf-fn");
    if(isFn) return;
    el.classList.toggle("multisel", wfActSel.has(el.dataset.id));
  });
}
function wfActSelClear(){ wfActSel.clear(); wfActAnchor=null; wfActSelPaint(); }
function wfActSelToggle(id){
  if(wfActSel.has(id)) wfActSel.delete(id); else wfActSel.add(id);
  wfActAnchor=id; wfActSelPaint();
}
// Shift+click: highlight every row between the anchor and this one (list order
// of the visible tab). No anchor yet → behaves like a toggle of just this row.
function wfActSelRange(id){
  const list=(typeof wfActTabList==="function")?wfActTabList():WF.activities;
  const ids=list.map(a=>a.id);
  const a=wfActAnchor&&ids.includes(wfActAnchor)?ids.indexOf(wfActAnchor):null;
  const b=ids.indexOf(id);
  if(a==null||b<0){ wfActSelToggle(id); return; }
  for(let i=Math.min(a,b);i<=Math.max(a,b);i++) wfActSel.add(ids[i]);
  wfActSelPaint();
}

// ── Duplicate (activity / function) ─────────────────────────────────────────
// Last activity the user had open (updated on every render) — the ƒ breadcrumb
// uses it to jump back after stepping into a function.
let wfLastActId=null;
// Deep-clone a graph with fresh ids: nodes, edges and groups
// are all remapped (and params deep-copied) so the copy is fully independent —
// editing it never touches the original.
function wfCloneGraph(g){
  const idMap={};
  const nodes=(g.nodes||[]).map(n=>{
    const nid=wfUid(); idMap[n.id]=nid;
    const c={...n, id:nid, params:JSON.parse(JSON.stringify(n.params||{}))};
    return c;
  });
  const edges=(g.edges||[]).map(e=>({from:idMap[e.from]||e.from, fromPort:e.fromPort||"out",
    to:idMap[e.to]||e.to, toPort:e.toPort||"in"}));
  const groups=(g.groups||[]).map(gr=>({...gr, id:"g"+wfUid().slice(1)}));
  return {nodes, edges, groups};
}
// "Name (copy)", "Name (2)", … — first free variant among `all` entities.
function wfUniqueEntityName(base, all){
  const taken=new Set(all.map(x=>x.name));
  let name=base+" (copy)", i=2;
  while(taken.has(name)){ name=base+" ("+i+")"; i++; }
  return name;
}
function wfDuplicateActivity(id){
  const src=wfActById(id); if(!src) return;
  wfPushUndo();
  const copy={ id:(src.type||"activity")+"_"+wfUid().slice(1,5),
    name:wfUniqueEntityName(src.name||"activity", WF.activities),
    type:src.type, enabled:src.enabled,
    maxRetries:src.maxRetries, pollInterval:src.pollInterval,
    vars:wfHydVars(src.vars||[]),
    graph:wfCloneGraph(src.graph||{nodes:[],edges:[],groups:[]}) };
  const i=WF.activities.findIndex(a=>a.id===id);
  WF.activities.splice(i<0?WF.activities.length:i+1, 0, copy);
  wfSwitchEditTarget("activity",copy.id);
  if(typeof wfActTab==="function") wfActTab(copy.type==="background"?"bg":"seq");
  wfRenderAll();
  setStatus("Duplicated «"+src.name+"» → «"+copy.name+"»");
}
function wfDuplicateFunction(id){
  const src=wfFnById(id); if(!src) return;
  wfPushUndo();
  const copy={ id:"fn_"+wfUid().slice(1,6),
    name:wfUniqueEntityName(src.name||"function", WF.functions),
    graph:wfCloneGraph(src.graph||{nodes:[],edges:[],groups:[]}) };
  const i=WF.functions.findIndex(f=>f.id===id);
  WF.functions.splice(i<0?WF.functions.length:i+1, 0, copy);
  wfSwitchEditTarget("function",copy.id);
  // Bring the Functions tab forward (and unfold the card) so the new row shows.
  if(typeof wfSwitchDockTab==="function") wfSwitchDockTab("fn");
  wfRenderAll();
  setStatus("Duplicated ƒ "+src.name+" → "+copy.name);
}

// ── Functions (reusable subroutines, used via a "call" node) ──────────────────
function wfAddFunction(){
  uiPrompt({title:"New function", label:"Function name", placeholder:"e.g. Go home"}).then(v=>{
    const name=(v||"").trim();
    if(!name) return;
    wfPushUndo();
    const id="fn_"+wfUid().slice(1,6);
    WF.functions.push({id,name,graph:wfNewGraph()});
    wfSwitchEditTarget("function",id);
    // Bring the Functions tab forward (and unfold the card) so the new row shows.
    if(typeof wfSwitchDockTab==="function") wfSwitchDockTab("fn");
    wfRenderAll();
  });
}
function wfEditFunction(id,ev){ ev&&ev.stopPropagation();
  if(!wfSwitchEditTarget("function",id)) return;   // already open — keep camera
  wfRenderAll(); }
function wfDeleteFunction(id,ev){
  ev&&ev.stopPropagation();
  const i=WF.functions.findIndex(f=>f.id===id); if(i<0)return;
  uiConfirm({title:"Delete function?", message:`Delete function "${WF.functions[i].name}"? Blocks calling it will stop working.`, ok:"Delete", danger:true}).then(ok=>{
    if(!ok) return;
    const j=WF.functions.findIndex(f=>f.id===id); if(j<0) return;
    wfPushUndo();
    WF.functions.splice(j,1);
    if(WF.edit.kind==="function"&&WF.edit.id===id){
      const next=WF.activities[0]?WF.activities[0].id:null;
      wfSwitchEditTarget("activity",next);
    }
    wfRenderAll();
  });
}
