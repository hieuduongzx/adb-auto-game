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
  if(WF.edit.kind===kind && WF.edit.id===id) return false;
  WF.edit={kind, id};
  wfClearSel();
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
  if(b){ b.classList.toggle("on", wfFocusOn); b.title = wfFocusOn
    ? "Focus: ON — auto-centre on the running block (follows into/out of functions). Click to turn off."
    : "Focus: OFF — canvas stays put during a run. Click to turn on."; }
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
function wfNewNode(type,x,y){ return {id:wfUid(),type,x,y,params:wfDefaults(type),note:"",log:"",delayBefore:0,delayAfter:0,retryCount:0,retryDelay:0,screenshotOnFail:false,showPreview:false,stack:null}; }
function wfNewGraph(){ return { nodes:[{id:wfUid(),type:"start",x:60,y:70,params:{}}], edges:[], groups:[] }; }

// ── Merge / stack blocks ─────────────────────────────────────────────────────
// A "merged" block is a vertical stack of nodes shown flush and moved as one.
// Membership is a shared `node.stack` id; their order is the REAL sequential
// edges between them, so the engine runs them in order with no special-casing.
// Drop a block just above/below another to merge; right-click → "Unmerge".
// Supported: action, call, AND condition nodes. For condition nodes the "true"
// (success) port is the sequential continuation; "false" stays free externally.
const wfStackId=()=>"st"+Math.random().toString(36).slice(2,8);
function wfMergeable(n){ const d=n&&WF_NODES[n.type]; return !!d && (d.kind==="action"||d.kind==="call"||d.kind==="condition"); }
// Port used as the sequential "next" link inside a merged stack.
// Condition and call nodes continue via their "true" (success) branch;
// everything else uses "out".
function wfMergeOutPort(n){ const d=n&&WF_NODES[n.type]; return (d&&(d.kind==="condition"||d.kind==="call"))?"true":"out"; }
function wfStackMembers(sid){ const g=wfGraph(); return g?g.nodes.filter(n=>n.stack===sid):[]; }
function wfSameStack(aId,bId){ const a=wfNode(aId),b=wfNode(bId); return !!(a&&b&&a.stack&&a.stack===b.stack); }
function wfHasInternalIn(n){ const g=wfGraph(); return !!(g&&n.stack&&g.edges.some(e=>e.to===n.id&&wfSameStack(e.from,e.to))); }
// Check only the merge-out port so a condition node with a free "false" edge
// is not incorrectly treated as "already has a successor".
function wfHasInternalOut(n){
  const g=wfGraph(); if(!g||!n.stack) return false;
  const fp=wfMergeOutPort(n);
  return g.edges.some(e=>e.from===n.id&&(e.fromPort||"out")===fp&&wfSameStack(e.from,e.to));
}
function wfStackChain(sid){
  const g=wfGraph(); if(!g) return [];
  const members=g.nodes.filter(n=>n.stack===sid); if(!members.length) return [];
  const byId=new Map(members.map(n=>[n.id,n]));
  const head=members.find(n=>!g.edges.some(e=>e.to===n.id&&byId.has(e.from)))||members[0];
  const chain=[]; const seen=new Set(); let cur=head;
  while(cur&&!seen.has(cur.id)){ seen.add(cur.id); chain.push(cur);
    const e=g.edges.find(ed=>ed.from===cur.id&&byId.has(ed.to)&&!seen.has(ed.to)); cur=e?byId.get(e.to):null; }
  members.forEach(m=>{ if(!seen.has(m.id)) chain.push(m); });   // stragglers (defensive)
  return chain;
}
// Lay every stack out flush: members snap under the head with borders touching.
// Called after each canvas render (nodes must be in the DOM to measure heights).
function wfReflowStacks(){
  const g=wfGraph(); if(!g) return;
  const sids=[...new Set(g.nodes.filter(n=>n.stack).map(n=>n.stack))];
  for(const sid of sids){
    const chain=wfStackChain(sid);
    if(chain.length<2) continue;   // a lone survivor is dissolved on delete, not here
    const x=chain[0].x; let y=chain[0].y;
    for(const n of chain){
      n.x=x; n.y=y;
      const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
      if(el){ el.style.left=x+"px"; el.style.top=y+"px"; }
      y += (el?el.offsetHeight:46)-1;   // -1 so adjacent borders overlap into one
    }
  }
}
// Insert dragged node D adjacent to target T ("after" = below, "before" = above),
// rewiring so the surrounding chain stays intact, then tag both into one stack.
function wfMergeInsert(dragId, targetId, where){
  wfPushUndo();
  const g=wfGraph(); if(!g) return;
  const D=wfNode(dragId), T=wfNode(targetId); if(!D||!T) return;
  g.edges=g.edges.filter(e=>e.from!==dragId&&e.to!==dragId);   // D starts free
  const sid=T.stack||wfStackId(); T.stack=sid; D.stack=sid;
  const tfp=wfMergeOutPort(T), dfp=wfMergeOutPort(D);
  if(where==="after"){
    // Find the edge from T's sequential-exit port specifically (not any port).
    const oe=g.edges.find(e=>e.from===targetId&&(e.fromPort||"out")===tfp);
    const tgt=oe?oe.to:null, tgtPort=oe?(oe.toPort||"in"):"in";
    if(oe) g.edges=g.edges.filter(e=>e!==oe);
    g.edges.push({from:targetId,fromPort:tfp,to:dragId,toPort:"in"});
    if(tgt&&tgt!==dragId) g.edges.push({from:dragId,fromPort:dfp,to:tgt,toPort:tgtPort});
  } else {
    g.edges.filter(e=>e.to===targetId&&(e.toPort||"in")==="in").forEach(e=>{ e.to=dragId; });
    g.edges.push({from:dragId,fromPort:dfp,to:targetId,toPort:"in"});
  }
  wfSelectOne(dragId); wfRenderCanvas(); wfRenderInspector();
  setStatus("Blocks merged");
}
// Find where a lone dragged block would merge: the nearest mergeable block whose
// top/bottom edge it landed flush against. Returns {target, where} or null.
function wfFindMergeTarget(dragId){
  const g=wfGraph(); if(!g) return null;
  const D=wfNode(dragId); if(!D||D.stack||!wfMergeable(D)) return null;
  const dEl=wfNodeElById(dragId); if(!dEl) return null;
  const dh=dEl.offsetHeight, dcx=D.x+dEl.offsetWidth/2;
  let best=null, bestWhere=null, bestScore=Infinity;
  for(const T of g.nodes){
    if(T.id===dragId||!wfMergeable(T)) continue;
    const tEl=wfNodeElById(T.id); if(!tEl) continue;
    const th=tEl.offsetHeight, tcx=T.x+tEl.offsetWidth/2;
    const dxc=Math.abs(dcx-tcx); if(dxc>80) continue;             // must roughly line up
    const gapBelow=Math.abs(D.y-(T.y+th));                        // D sits under T
    const gapAbove=Math.abs((D.y+dh)-T.y);                        // D sits over T
    if(gapBelow<=30 && !wfHasInternalOut(T)){                     // append after a tail
      const s=gapBelow+dxc*0.25; if(s<bestScore){bestScore=s;best=T;bestWhere="after";} }
    if(gapAbove<=30 && !wfHasInternalIn(T)){                      // prepend before a head
      const s=gapAbove+dxc*0.25; if(s<bestScore){bestScore=s;best=T;bestWhere="before";} }
  }
  return best?{target:best, where:bestWhere}:null;
}
// On drop, merge the dragged block into the candidate target (if any).
function wfTryMerge(dragId){
  const c=wfFindMergeTarget(dragId);
  if(c){ wfMergeInsert(dragId, c.target.id, c.where); return true; }
  return false;
}
// Live preview while dragging: outline the edge the block will snap onto.
function wfClearMergeHint(){
  document.querySelectorAll(".wf-merge-top,.wf-merge-bot")
    .forEach(el=>el.classList.remove("wf-merge-top","wf-merge-bot"));
}
function wfShowMergeHint(dragId){
  wfClearMergeHint();
  const c=wfFindMergeTarget(dragId); if(!c) return;
  const el=wfNodeElById(c.target.id); if(el) el.classList.add(c.where==="after"?"wf-merge-bot":"wf-merge-top");
}
// Split a stack: clear membership (edges kept so the flow still runs) and spread
// the blocks apart so each is independently editable again.
function wfUnmerge(sid){
  wfPushUndo();
  const g=wfGraph(); if(!g) return;
  const chain=wfStackChain(sid); if(!chain.length) return;
  const x=chain[0].x; let y=chain[0].y;
  chain.forEach(n=>{ n.stack=null; });
  chain.forEach(n=>{ const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
    n.x=x; n.y=y; y += (el?el.offsetHeight:46)+26; });
  wfRenderCanvas(); wfRenderInspector();
  setStatus("Unmerged");
}

function wfAddActivity(type){
  wfPushUndo();
  const n=WF.activities.filter(a=>a.type===type).length+1;
  const id=type+"_"+wfUid().slice(1,5);
  const act={id, name:(type==="background"?"Background task ":"Activity ")+n, type,
    enabled:true, maxRetries:1, pollInterval:1.0, vars:[], graph:wfNewGraph()};
  WF.activities.push(act); WF.edit={kind:"activity",id}; wfClearSel(); wfPan={x:0,y:0}; wfZoom=1;
  if(typeof wfActTab==="function") wfActTab(type==="background"?"bg":"seq");
  wfRenderAll();
}
function wfDeleteActivity(id,ev){
  ev&&ev.stopPropagation();
  const i=WF.activities.findIndex(a=>a.id===id); if(i<0)return;
  if(!confirm(`Delete activity "${WF.activities[i].name}"?`))return;
  wfPushUndo();
  WF.activities.splice(i,1);
  if(WF.edit.kind==="activity"&&WF.edit.id===id){ WF.edit={kind:"activity",id:WF.activities[0]?WF.activities[0].id:null}; wfClearSel(); }
  wfRenderAll();
}
// Re-clicking the already-open activity is a no-op (keeps the camera, and lets
// the second click of a rename double-click land on a live row).
function wfSelectActivity(id){ if(WF.edit.kind==="activity"&&WF.edit.id===id) return;
  WF.edit={kind:"activity",id}; wfClearSel(); wfPan={x:0,y:0}; wfZoom=1; wfRenderAll(); }
function wfToggleActivity(id,ev){ ev&&ev.stopPropagation(); const a=wfActById(id); if(a){ wfPushUndo(); a.enabled=!a.enabled; wfRenderActivities(); } }

// ── Functions (reusable subroutines, used via a "call" node) ──────────────────
function wfAddFunction(){
  const name=(prompt("Function name (e.g. Go Home):","")||"").trim();
  if(!name) return;
  wfPushUndo();
  const id="fn_"+wfUid().slice(1,6);
  WF.functions.push({id,name,graph:wfNewGraph()});
  WF.edit={kind:"function",id}; wfClearSel(); wfPan={x:0,y:0}; wfZoom=1;
  // Make sure the sidebar Functions section is open so the new row is visible.
  const fsec=$("wf-side-fns-sec");
  if(fsec && fsec.classList.contains("collapsed")){
    fsec.classList.remove("collapsed");
    try{ localStorage.setItem("wfFnsCollapsed","0"); }catch{}
  }
  wfRenderAll();
}
function wfEditFunction(id,ev){ ev&&ev.stopPropagation();
  if(WF.edit.kind==="function"&&WF.edit.id===id) return;   // already open — keep camera
  WF.edit={kind:"function",id}; wfClearSel(); wfPan={x:0,y:0}; wfZoom=1; wfRenderAll(); }
function wfDeleteFunction(id,ev){
  ev&&ev.stopPropagation();
  const i=WF.functions.findIndex(f=>f.id===id); if(i<0)return;
  if(!confirm(`Delete function "${WF.functions[i].name}"? Nodes calling it will be disabled.`))return;
  wfPushUndo();
  WF.functions.splice(i,1);
  if(WF.edit.kind==="function"&&WF.edit.id===id){ WF.edit={kind:"activity",id:WF.activities[0]?WF.activities[0].id:null}; wfClearSel(); }
  wfRenderAll();
}
