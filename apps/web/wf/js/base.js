// ── Base helpers ────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
const LOG_TAG = {info:"INF",success:"OK ",warning:"WRN",error:"ERR"};
const S = { devices:[], connectedSerial:null, captureBackend:"scrcpy", inputBackend:"adb" };
function setStatus(msg){ const e=$("status-text"); if(e) e.textContent=msg; }
function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
// Turn a human Title into a variable code name: strip accents (Vietnamese
// included), lowercase, spaces/punctuation → "_". "Đọc email" → "doc_email",
// "Mày là con chó" → "may_la_con_cho". Returns "" when nothing usable remains.
function wfVarSlug(title){
  let s=String(title==null?"":title).normalize("NFD")
    .replace(/[\u0300-\u036f]/g,"")
    .replace(/[đĐ]/g,"d")
    .toLowerCase().trim();
  s=s.replace(/[^a-z0-9]+/g,"_").replace(/_{2,}/g,"_").replace(/^_+|_+$/g,"");
  if(s && /^[0-9]/.test(s)) s="v_"+s;
  return s;
}
// Make a variable name unique against a list of existing names (suffix _2, _3…).
function wfUniqVarName(base,existing){
  base=base||"var";
  const set=new Set((existing||[]).map(n=>String(n||"")));
  if(!set.has(base)) return base;
  let i=2; while(set.has(base+"_"+i)) i++;
  return base+"_"+i;
}
function setConnected(on){ const a=$("device-dot"),b=$("footer-dot"); if(a)a.classList.toggle("connected",on); if(b)b.classList.toggle("connected",on); }

// Load a template thumbnail (data-URL from Python) into an <img>, hide if none.
// Stores the template path on the element so the hover zoom can fetch a larger
// preview without walking back through the node params.
async function wfLoadThumb(img, path){
  if(!img) return;
  img.dataset.path = path || "";
  img.removeAttribute("src");
  if(!path){ img.style.display="none"; return; }
  img.style.display="";  // let CSS show checkerboard while loading
  try{ const d=await api().image_thumbnail(path); if(d){ img.src=d; img.style.display="block"; } }catch{}
}

// ── Thumbnail hover zoom ────────────────────────────────────────────────────
// Hold the pointer over a node image preview for ~1.2s → a larger floating
// frame appears next to it so you can read detail without opening the file.
// Instant show of the already-loaded small src, then upgrade to a bigger
// thumbnail async. Leave the thumb (or the pop) to dismiss.
const WF_THUMB_HOVER_MS = 1200;
const WF_THUMB_POP_W = 420;          // max edge for the hi-res fetch
let _wfThumbSrc = null;              // the <img> currently armed / shown
let _wfThumbShowTimer = null;
let _wfThumbHideTimer = null;
let _wfThumbPopSeq = 0;              // invalidate in-flight hi-res loads

function wfThumbEl(el){
  return el && el.closest ? el.closest(".wf-node-thumb, .wf-node-thumb-sm") : null;
}
function wfThumbPopEl(){
  let pop = document.getElementById("wf-thumb-pop");
  if(pop) return pop;
  pop = document.createElement("div");
  pop.id = "wf-thumb-pop";
  pop.setAttribute("role", "tooltip");
  pop.innerHTML = '<div class="wf-thumb-pop-frame"><img alt=""></div><div class="wf-thumb-pop-name"></div>';
  document.body.appendChild(pop);
  // Moving into the pop keeps it open; leaving dismisses.
  pop.addEventListener("mouseenter", ()=>{ clearTimeout(_wfThumbHideTimer); _wfThumbHideTimer=null; });
  pop.addEventListener("mouseleave", ()=> wfThumbPopHide());
  return pop;
}
function wfThumbPopPosition(pop, anchor){
  const r = anchor.getBoundingClientRect();
  const pad = 10;
  const vw = window.innerWidth, vh = window.innerHeight;
  // Measure after show so we know the real box size (capped by CSS).
  const pr = pop.getBoundingClientRect();
  const pw = pr.width || 280, ph = pr.height || 200;
  // Prefer right of the thumb; flip left / above / below when near edges.
  let left = r.right + pad;
  let top  = r.top + (r.height/2) - ph/2;
  if(left + pw > vw - 8) left = r.left - pad - pw;
  if(left < 8) left = Math.max(8, Math.min(vw - pw - 8, r.left));
  if(top < 8) top = 8;
  if(top + ph > vh - 8) top = Math.max(8, vh - ph - 8);
  // If still overlapping the thumb (tiny viewport), park below it.
  const overlaps = !(left+pw < r.left || left > r.right || top+ph < r.top || top > r.bottom);
  if(overlaps){
    top = r.bottom + pad;
    if(top + ph > vh - 8) top = Math.max(8, r.top - pad - ph);
    left = Math.max(8, Math.min(vw - pw - 8, r.left + r.width/2 - pw/2));
  }
  pop.style.left = Math.round(left)+"px";
  pop.style.top  = Math.round(top)+"px";
}
function wfThumbPopShow(img){
  if(!img || !img.isConnected) return;
  // Only while the node is actually showing previews (global or per-node eye).
  const node = img.closest(".wf-node");
  if(!node || !node.classList.contains("showing-thumb")) return;
  if(!img.src && !img.dataset.path) return;

  const pop = wfThumbPopEl();
  const big = pop.querySelector("img");
  const nameEl = pop.querySelector(".wf-thumb-pop-name");
  const path = img.dataset.path || "";
  const base = path ? path.split(/[\\/]/).pop() : "";
  // Paint immediately with whatever we already have (small thumb), then upgrade.
  if(img.src) big.src = img.src;
  else big.removeAttribute("src");
  if(nameEl){ nameEl.textContent = base; nameEl.title = path; nameEl.style.display = base ? "" : "none"; }
  pop.classList.add("show");
  // First layout pass with current image, then re-pin once the hi-res arrives.
  wfThumbPopPosition(pop, img);

  const seq = ++_wfThumbPopSeq;
  if(path){
    try{
      api().image_thumbnail(path, WF_THUMB_POP_W).then(d=>{
        if(!d || seq !== _wfThumbPopSeq || _wfThumbSrc !== img) return;
        big.src = d;
        // Re-measure after the larger image loads (size may change).
        if(big.complete) wfThumbPopPosition(pop, img);
        else big.onload = ()=>{ if(seq === _wfThumbPopSeq) wfThumbPopPosition(pop, img); };
      });
    }catch{}
  }
}
function wfThumbPopHide(){
  clearTimeout(_wfThumbShowTimer); _wfThumbShowTimer=null;
  clearTimeout(_wfThumbHideTimer); _wfThumbHideTimer=null;
  _wfThumbSrc = null;
  _wfThumbPopSeq++;
  const pop = document.getElementById("wf-thumb-pop");
  if(pop) pop.classList.remove("show");
}
function wfThumbPopScheduleHide(){
  clearTimeout(_wfThumbHideTimer);
  // Short grace so the cursor can travel from the thumb into the pop.
  _wfThumbHideTimer = setTimeout(()=>{
    const pop = document.getElementById("wf-thumb-pop");
    if(pop && pop.matches(":hover")) return;
    wfThumbPopHide();
  }, 120);
}
function wfInitThumbHover(){
  if(document.documentElement.__wfThumbHover) return;
  document.documentElement.__wfThumbHover = true;

  // Capture-phase so we see enter/leave on the imgs even if something stops bubble.
  document.addEventListener("pointerover", e=>{
    const img = wfThumbEl(e.target);
    if(!img) return;
    const node = img.closest(".wf-node");
    if(!node || !node.classList.contains("showing-thumb")) return;
    clearTimeout(_wfThumbHideTimer); _wfThumbHideTimer=null;
    // Same thumb again (left briefly, or move into the pop and back): keep the
    // open pop, or re-arm the delay if it was cancelled mid-wait.
    if(_wfThumbSrc === img){
      const pop = document.getElementById("wf-thumb-pop");
      if(pop && pop.classList.contains("show")) return;
      if(_wfThumbShowTimer) return;   // still counting down
    }
    // Arm a new hover; cancel any previous pending show.
    clearTimeout(_wfThumbShowTimer);
    _wfThumbSrc = img;
    _wfThumbShowTimer = setTimeout(()=>{
      _wfThumbShowTimer = null;
      if(_wfThumbSrc === img) wfThumbPopShow(img);
    }, WF_THUMB_HOVER_MS);
  }, true);

  document.addEventListener("pointerout", e=>{
    const img = wfThumbEl(e.target);
    if(!img) return;
    // Still inside the same thumb (moving between its children — none usually).
    const to = e.relatedTarget;
    if(to && img.contains(to)) return;
    // Moving into the pop itself — keep showing.
    if(to && to.closest && to.closest("#wf-thumb-pop")) return;
    if(_wfThumbSrc === img){
      clearTimeout(_wfThumbShowTimer); _wfThumbShowTimer=null;
      wfThumbPopScheduleHide();
    }
  }, true);

  // Dragging / panning / scrolling the canvas should dismiss immediately.
  const dismiss = ()=> wfThumbPopHide();
  document.addEventListener("pointerdown", dismiss, true);
  document.addEventListener("wheel", dismiss, {capture:true, passive:true});
  window.addEventListener("blur", dismiss);
  window.addEventListener("resize", dismiss);
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", wfInitThumbHover);
else wfInitThumbHover();

// Run visualisation. The engine reports (a) the node about to run — painted amber
// while live — and (b) each node's result once it finishes. Results accumulate
// into a persistent "trail" for the whole run: a node that ran turns its border
// green (red if an action failed), and a branch node greens the port/wire it took
// and reds the one it didn't. This is why fast blocks now stay visible — they keep
// the trail colour after the amber moves on.
let wfRunNode=null;
let wfLiveNode=null;    // the engine's true current node id (even if in an off-screen graph); drives focus-on-toggle
let wfRunStopped=false; // true once a finished run's trail is on display (greys-out skipped blocks)
// True while "Test block" (single node) is in flight — events.js accepts
// node_active / node_result without requiring a full graph run (wfRunning).
let wfNodeTesting=false;
const wfRan={};       // nodeId -> "ok" | "fail"
const wfRanPort={};   // nodeId -> output port actually taken
// Per-node timing, measured UI-side between node_active and node_result:
// nodeId -> {last: ms of the latest run, n: how many times it ran}. Shown as a
// small mono chip under the block's bottom-right corner; cleared per run.
const wfNodeT0={};
const wfNodeDur={};
// nodeId -> absolute path of the failure screenshot the engine saved for this
// node's final failed attempt (designer test runs capture these automatically).
const wfFailShots={};
function wfFmtDur(ms){
  if(ms<995)   return (ms/1000).toFixed(2)+"s";
  if(ms<60000) return (ms/1000).toFixed(1)+"s";
  return Math.floor(ms/60000)+"m"+String(Math.round(ms%60000/1000)).padStart(2,"0");
}
function wfApplyNodeTime(id){
  const d=wfNodeDur[id]; const el=wfNodeElById(id);
  if(!d||!el) return;
  let chip=el.querySelector(".wf-node-time");
  if(!chip){ chip=document.createElement("span"); chip.className="wf-node-time"; el.appendChild(chip); }
  chip.textContent=wfFmtDur(d.last)+(d.n>1?" ×"+d.n:"");
  chip.title="Last run duration"+(d.n>1?` (ran ${d.n} times)`:"");
}
function wfNoteNodeStart(id){ if(id) wfNodeT0[id]=performance.now(); }
function wfNoteNodeDone(id){
  if(!id || wfNodeT0[id]===undefined) return;
  const dt=performance.now()-wfNodeT0[id]; delete wfNodeT0[id];
  const prev=wfNodeDur[id];
  wfNodeDur[id]={last:dt, n:(prev?prev.n:0)+1};
  wfApplyNodeTime(id);
}
// Activity run-status tracker: activityId -> "running" | "done" | "errored".
// Drives the row indicator in the bottom-right panel: blinking green while the
// engine executes it, solid green once completed, solid red on failure. Cleared
// at the start of a run and updated live from the engine's
// on_activity_start / on_activity_complete callbacks.
const wfActStatus={};
// Apply a status class to a single activity row (without a full re-render) so
// the indicator updates instantly when an event arrives.
function wfSetActStatus(id, status){
  if(status){ wfActStatus[id]=status; } else { delete wfActStatus[id]; }
  const el=document.querySelector(`.wf-act[data-id="${id}"]`);
  if(el){
    el.classList.toggle("running", status==="running");
    el.classList.toggle("done",    status==="done");
    el.classList.toggle("errored", status==="errored");
  }
}
// Clear every activity's run-status (called when a run starts or stops).
function wfResetActStatus(){
  for(const id in wfActStatus) wfSetActStatus(id, null);
}

// ── Crash point ──────────────────────────────────────────────────────────────
// activityId -> {node,type,label,name,reason,message,ts}: the block an activity
// actually died on, from the engine's on_activity_crash. Deliberately OUTLIVES
// the run-trail reset (wfResetRunViz) — after a long unattended run the whole
// point is that the marker is still there when you come back, and after the
// NEXT run starts you can still see where the previous one stopped. An entry
// clears only when that activity starts running again (a fresh verdict is
// coming) or when its crash block is edited away.
const wfActCrash={};
// nodeId -> activityId, so the canvas can mark the block itself without
// scanning every activity on each render.
const wfCrashNodes={};
function wfIsCrashNode(id){ return !!id && Object.prototype.hasOwnProperty.call(wfCrashNodes, id); }
function wfSetActCrash(actId, info){
  if(!actId) return;
  wfClearActCrash(actId);
  if(!info || !info.node) return;
  wfActCrash[actId]=info;
  wfCrashNodes[info.node]=actId;
  const el=wfNodeElById(info.node); if(el) el.classList.add("crashed");
}
function wfClearActCrash(actId){
  const prev=wfActCrash[actId];
  if(!prev) return;
  delete wfActCrash[actId];
  if(prev.node){
    delete wfCrashNodes[prev.node];
    const el=wfNodeElById(prev.node); if(el) el.classList.remove("crashed");
  }
}
function wfClearAllActCrash(){
  Object.keys(wfActCrash).forEach(wfClearActCrash);
}
// One-line "why it stopped" for tooltips and the status bar.
function wfCrashWhy(info){
  if(!info) return "";
  const what = info.name || info.label || info.type || "block";
  const why = { failed:"this block did not complete successfully",
                error:"this block raised an error",
                dead_end:"the outgoing branch is not connected" }[info.reason] || info.reason || "";
  return `${what}${why?" — "+why:""}${info.message?": "+info.message:""}`;
}
// Jump the editor to an activity's crash block: switch to its graph, select it
// and centre the camera — the same move as clicking a validation issue.
function wfJumpToCrash(actId){
  const info=wfActCrash[actId]; if(!info || !info.node) return false;
  const owner=(typeof wfFindNodeOwner==="function") ? wfFindNodeOwner(info.node) : null;
  if(!owner){ setStatus("This node is no longer in the workflow"); wfClearActCrash(actId); wfRenderActivities(); return false; }
  if(owner.kind==="activity") wfSelectActivity(owner.id); else wfEditFunction(owner.id);
  WF.sel=[info.node]; WF.selectedNode=info.node;
  wfRenderCanvas(); wfRenderInspector();
  const n=wfNode(info.node); if(n) wfCenterOnNode(n);
  setStatus("Stopped at: "+wfCrashWhy(info));
  return true;
}
function wfNodeElById(id){ return id ? document.querySelector(`.wf-node[data-node="${id}"]`) : null; }

// ── Call stack ───────────────────────────────────────────────────────────────
// While a function runs, the live node lives in the FUNCTION's graph, so the
// call block that started it gets no marker of its own — and with follow-focus
// on, the editor switches away from the parent entirely. Looking at the parent
// canvas afterwards you could not tell a function was executing at all.
// So track which call blocks are currently on the engine's stack and ring them,
// whichever graph is on screen. Nested calls ring every block on the path.
let wfCallStack = [];
// wfNode() only searches the graph being viewed; this one answers "what kind of
// node is this id, anywhere in the workflow" for ids arriving from the engine.
function wfNodeAnywhere(id){
  if(!id) return null;
  const pools=[(WF.activities||[]), (WF.functions||[])];
  for(const pool of pools){
    for(const t of pool){
      const n=t && t.graph && t.graph.nodes && t.graph.nodes.find(n=>n.id===id);
      if(n) return n;
    }
  }
  return null;
}
// Repaint the rings. Cheap: the class is only ever on a handful of blocks, and
// this runs on stack changes and after every canvas rebuild.
function wfPaintCallStack(){
  document.querySelectorAll(".wf-node.running-call").forEach(el=>{
    if(!wfCallStack.includes(el.dataset.node)) el.classList.remove("running-call");
  });
  wfCallStack.forEach(id=>{ const el=wfNodeElById(id); if(el) el.classList.add("running-call"); });
}
function wfCallStackEnter(id){
  const n=wfNodeAnywhere(id);
  if(!n || n.type!=="call") return;
  if(!wfCallStack.includes(id)) wfCallStack.push(id);
  wfPaintCallStack();
}
// A call reports its result only once its function has finished, so seeing one
// pops it — and anything still above it, which is how an aborted inner call or
// a dropped event self-heals instead of leaving a ring behind forever.
function wfCallStackExit(id){
  const i=wfCallStack.indexOf(id);
  if(i<0) return;
  wfCallStack.length=i;
  wfPaintCallStack();
}
function wfCallStackClear(){ wfCallStack.length=0; wfPaintCallStack(); }
let wfRunLitAt=0;            // when the current amber node lit up (ms)
const WF_RUN_MIN_MS=220;    // floor on amber dwell, so instant blocks (if image…) still flash yellow
function wfSetRunningNode(id){
  // Move the amber glow to the new node, leaving the green/red trail untouched.
  // Conditions like "if image" finish in a few ms — without a dwell floor their
  // amber is added and removed within one frame and never paints. So keep the
  // previous node amber for at least WF_RUN_MIN_MS before clearing it.
  const now=Date.now();
  const prevId=wfRunNode, prevEl=wfNodeElById(prevId);
  if(prevEl && prevId!==id){
    const remain=WF_RUN_MIN_MS-(now-wfRunLitAt);
    if(remain>0) setTimeout(()=>{ if(wfRunNode!==prevId) prevEl.classList.remove("running"); }, remain);
    else prevEl.classList.remove("running");
  }
  wfRunNode=id||null;
  wfRunLitAt=now;
  const el=wfNodeElById(wfRunNode); if(el) el.classList.add("running");
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();   // amber chip follows on the map
}
function wfColorBranch(id, takenPort){
  // The wire and its flow marker are siblings inside one .wire-grp — paint both
  // so the marker never keeps its idle colour on a branch the run dimmed.
  document.querySelectorAll("#wf-wires .wire-grp").forEach(grp=>{
    const p=grp.querySelector("path.wire");
    if(!p || p.dataset.from!==id) return;
    const cls = p.dataset.fromport===takenPort ? "took-wire"
              : wfIsBranchPort(p.dataset.fromport) ? "nottook-wire" : null;
    [p, grp.querySelector(".wire-flow")].forEach(el=>{
      if(!el) return;
      el.classList.remove("took-wire","nottook-wire");
      if(cls) el.classList.add(cls);
    });
  });
}
// Ports that are mutually-exclusive branches (so the not-taken ones dim on a run):
// condition true/false, and a switch node's c0.. / default ports.
function wfIsBranchPort(port){ return port==="true"||port==="false"||port==="default"||/^c\d+$/.test(port); }
function wfMarkNodeResult(id, status, port){
  if(!id) return;
  wfRan[id] = status==="fail" ? "fail" : "ok";
  if(port!==undefined && port!==null) wfRanPort[id]=port; else delete wfRanPort[id];
  // Record always — even for nodes in a graph we're not viewing (a call node's
  // function graph). DOM painting needs the node present, but the result stays
  // in wfRan so switching back to that graph re-paints its trail/tones.
  const el=wfNodeElById(id); if(!el) return;
  // A condition that took its 'false' branch (e.g. "tap image" didn't find the
  // image) didn't really succeed — paint the node red to match its red false-wire,
  // instead of a misleading green. Only 'true'/'out'/'body'/'done' stay green.
  const failish = wfRan[id]==="fail" || wfRanPort[id]==="false";
  el.classList.toggle("ran-ok",   !failish);
  el.classList.toggle("ran-fail", failish);
  // Output ports: the one taken goes green, the other true/false sibling red.
  const taken = wfRanPort[id];
  el.querySelectorAll(".wf-port.out").forEach(p=>{
    p.classList.remove("took","nottook");
    if(taken==null) return;
    if(p.dataset.port===String(taken)) p.classList.add("took");
    else if(wfIsBranchPort(p.dataset.port)) p.classList.add("nottook");
  });
  if(taken!=null) wfColorBranch(id, String(taken));
}
// Once a run has stopped, red-bar every executable block it never entered, so the
// taken path (green) stands out against the skipped branches (dim red top). 'start'
// has no result event (the walk begins after it) and 'note' isn't executable, so
// both are left alone. Re-evaluated per graph on every call (runs can cross
// activity/function boundaries), so switching back to a graph still dims its
// unreached blocks, while nodes added after the run stay undimmed.
function wfMarkUnreached(){
  const g=wfGraph(); if(!g) return;             // no graph — nothing to grey out
  if(!Object.keys(wfRan).length) return;        // no run happened — nothing to grey out
  // Per-graph on every call: a run may cross activity/function boundaries, so
  // results for THIS graph's nodes drive the skip set. Blocks in a graph we
  // switch into after the run are dimmed correctly, and never-dragged-in nodes
  // (added after the run) stay undimmed.
  const ranSet=new Set(Object.keys(wfRan));
  (g.nodes||[]).forEach(n=>{
    if(n.type==="note"||n.type==="start"||ranSet.has(n.id)) return;
    const el=wfNodeElById(n.id); if(el) el.classList.add("ran-skip");
  });
}
// Re-paint the whole trail after a canvas redraw (nodes/wires are rebuilt fresh).
function wfReapplyRunViz(){
  Object.keys(wfRan).forEach(id=>wfMarkNodeResult(id, wfRan[id], wfRanPort[id]));
  Object.keys(wfNodeDur).forEach(wfApplyNodeTime);
  const el=wfNodeElById(wfRunNode); if(el) el.classList.add("running");
  wfPaintCallStack();
  if(wfRunStopped) wfMarkUnreached();
  // Canvas rebuilds wipe delay chips — re-bind the live countdown if one is mid-wait.
  if(wfDelayState) wfPaintNodeDelay();
}
function wfResetRunViz(){
  wfRunNode=null; wfLiveNode=null; wfRunStopped=false;
  wfCallStackClear();
  for(const k in wfRan) delete wfRan[k];
  for(const k in wfRanPort) delete wfRanPort[k];
  for(const k in wfNodeT0) delete wfNodeT0[k];
  for(const k in wfNodeDur) delete wfNodeDur[k];
  for(const k in wfFailShots) delete wfFailShots[k];
  document.querySelectorAll(".wf-node-time").forEach(el=>el.remove());
  wfClearNodeDelay();
  wfResetActStatus();
  document.querySelectorAll(".wf-node.running,.wf-node.paused,.wf-node.ran-ok,.wf-node.ran-fail,.wf-node.ran-skip,.wf-node.delaying")
    .forEach(el=>el.classList.remove("running","paused","ran-ok","ran-fail","ran-skip","delaying"));
  document.querySelectorAll("#wf-wires .took-wire,#wf-wires .nottook-wire")
    .forEach(p=>p.classList.remove("took-wire","nottook-wire"));
  document.querySelectorAll(".wf-port.out.took,.wf-port.out.nottook")
    .forEach(p=>p.classList.remove("took","nottook"));
}

// ── Live delayBefore / delayAfter countdown on the active node ───────────────
// Engine emits node_delay {id, phase:"before"|"after"|null, seconds} when a
// per-node wait starts or ends. We tick client-side from the start event so the
// chip next to the block shows remaining time without flooding the WS.
let wfDelayState=null;   // {id, phase, endAt, total} while counting; null when idle
let wfDelayTimer=null;
function wfFmtRemain(sec){
  if(sec>=10) return Math.ceil(sec)+"s";
  if(sec>=1)  return sec.toFixed(1)+"s";
  return Math.max(0, sec).toFixed(1)+"s";
}
function wfDelaySign(phase){ return phase==="after"?"+":"−"; }
function wfRestoreDelayChip(chip){
  if(!chip) return;
  chip.classList.remove("counting");
  chip.style.removeProperty("--pct");
  if(chip.classList.contains("wf-node-timeout")){
    // Corner badge: back to the static limit the block was rendered with.
    const label=chip.querySelector(".wf-timeout-label");
    const n=typeof wfNode==="function"?wfNode(chip.closest(".wf-node")?.dataset.node):null;
    const secs=n?parseFloat(n.params&&n.params.timeout):parseFloat(chip.dataset.secs);
    const shown=(typeof wfDelaySecs==="function"&&Number.isFinite(secs)&&secs>0)?wfDelaySecs(secs):(chip.dataset.secs?chip.dataset.secs+"s":"⏱");
    if(label) label.textContent=shown;
    chip.title="Timeout: "+(Number.isFinite(secs)&&secs>0?wfDelaySecs(secs):"set by expression / default");
    return;
  }
  const secs=parseFloat(chip.dataset.secs)||0;
  const phase=chip.dataset.phase;
  const label=chip.querySelector(".wf-delay-label");
  const shown=typeof wfDelaySecs==="function"?wfDelaySecs(secs):secs+"s";
  if(label) label.textContent=wfDelaySign(phase)+shown;
  chip.title=phase==="after"?"Wait "+shown+" after this block":"Wait "+shown+" before this block";
}
function wfClearNodeDelay(){
  if(wfDelayTimer){ clearInterval(wfDelayTimer); wfDelayTimer=null; }
  const prev=wfDelayState; wfDelayState=null;
  document.querySelectorAll(".wf-node.delaying").forEach(el=>el.classList.remove("delaying"));
  document.querySelectorAll(".wf-delay-chip.counting").forEach(wfRestoreDelayChip);
  document.querySelectorAll(".wf-node-timeout.counting").forEach(wfRestoreDelayChip);
  // Floating badge (shown when the node has no static delay row, e.g. stack join).
  document.querySelectorAll(".wf-node-delay-live").forEach(el=>el.remove());
  if(prev){ const el=wfNodeElById(prev.id); if(el) el.querySelectorAll(".wf-delay-chip").forEach(wfRestoreDelayChip); }
}
function wfPaintNodeDelay(){
  const st=wfDelayState; if(!st) return;
  const remain=Math.max(0,(st.endAt-performance.now())/1000);
  const pct=st.total>0?Math.max(0,Math.min(100,(remain/st.total)*100)):0;
  const el=wfNodeElById(st.id);
  if(!el) return;
  el.classList.add("delaying");
  if(st.phase==="timeout"){
    // Countdown against the block's own timeout deadline, painted on the corner
    // badge. Runs purely off the local clock — the engine's node_result ends it.
    const chip=el.querySelector(".wf-node-timeout");
    if(!chip) return;
    chip.classList.add("counting");
    chip.style.setProperty("--pct", pct.toFixed(1));
    const label=chip.querySelector(".wf-timeout-label");
    const left=wfFmtRemain(remain);
    if(label) label.textContent=left;
    chip.title="Timeout — "+left+" left";
    return;
  }
  // Prefer the existing static chip for this phase; fall back to a floating badge
  // when the chip row is hidden (stacked join-bottom) or missing.
  let chip=el.querySelector(`.wf-delay-chip[data-phase="${st.phase}"]`);
  if(!chip || getComputedStyle(el.querySelector(".wf-node-delay")||el).display==="none"){
    chip=null;
  }
  const sign=wfDelaySign(st.phase);
  const left=wfFmtRemain(remain);
  const text=sign+left;
  if(chip){
    chip.classList.add("counting");
    chip.style.setProperty("--pct", pct.toFixed(1));
    const label=chip.querySelector(".wf-delay-label");
    if(label) label.textContent=text;
    else chip.innerHTML=`<span class="wf-delay-label">${text}</span>`;
    chip.title=(st.phase==="after"?"After":"Before")+" wait — "+left+" left";
    const live=el.querySelector(".wf-node-delay-live"); if(live) live.remove();
  } else {
    let live=el.querySelector(".wf-node-delay-live");
    if(!live){
      live=document.createElement("div");
      live.className="wf-node-delay-live";
      el.appendChild(live);
    }
    live.dataset.phase=st.phase;
    live.style.setProperty("--pct", pct.toFixed(1));
    live.innerHTML=`<span class="wf-delay-label">${text}</span>`;
    live.title=(st.phase==="after"?"After":"Before")+" wait — "+left+" left";
  }
  if(remain<=0){
    // Local clock finished; leave paint until engine's end event restores chips
    // (or the next node arrives). Don't clear state here so a late end still matches.
    if(chip){ /* keep counting class at 0 briefly */ }
  }
}
function wfStartNodeDelay(id, phase, seconds){
  wfClearNodeDelay();
  const secs=parseFloat(seconds)||0;
  if(!id || (phase!=="before" && phase!=="after" && phase!=="timeout") || secs<=0) return;
  wfDelayState={id, phase, endAt:performance.now()+secs*1000, total:secs};
  // Keep the amber "running" look during After wait (node_result already painted
  // green trail) so the operator still sees which block is holding the graph.
  if(phase==="after"){
    const el=wfNodeElById(id);
    if(el){ el.classList.add("running"); wfRunNode=id; }
  }
  wfPaintNodeDelay();
  if(wfDelayTimer) clearInterval(wfDelayTimer);
  wfDelayTimer=setInterval(()=>{
    if(!wfDelayState){ clearInterval(wfDelayTimer); wfDelayTimer=null; return; }
    wfPaintNodeDelay();
    if(performance.now()>=wfDelayState.endAt){
      // Snap to 0 then wait for engine end (or clear on next node / stop).
      clearInterval(wfDelayTimer); wfDelayTimer=null;
    }
  }, 50);
}
function wfEndNodeDelay(id){
  // Only clear if this end matches the active countdown (ignore stale ends).
  if(wfDelayState && id && wfDelayState.id!==id) return;
  wfClearNodeDelay();
}
// Start a countdown against the node's own timeout param. Called when the node
// goes live (and again when a delayBefore ends, since the engine's timeout
// clock only starts once the block actually runs). No engine event needed —
// the deadline is just params.timeout seconds from now. Skipped for {var}
// expressions, which can't be resolved on the designer side.
function wfStartNodeTimeout(id){
  const n=typeof wfNode==="function"?wfNode(id):null;
  if(!n||!n.params) return;
  const def=WF_NODES[n.type];
  if(!def||!(def.fields||[]).some(f=>f.k==="timeout")) return;
  const secs=parseFloat(n.params.timeout);
  if(!Number.isFinite(secs)||secs<=0) return;
  wfStartNodeDelay(id, "timeout", secs);
}

function appendLog(entry){
  const body=$("log-body"); if(!body) return;
  const line=document.createElement("div"); line.className=`log-line fade-in lv-${entry.level||"info"} k-${entry.kind||"app"}`;
  // Filter state lives on data-* rather than being re-derived from rendered
  // text: the level chips, the scope picker and the search box then compose
  // without any of them having to know about the others. `node` is the engine's
  // block id, which is what makes "click the line, land on the block" possible.
  line.dataset.level=entry.level||"info";
  line.dataset.kind=entry.kind||"app";
  line.dataset.scope=entry.scope||"Designer";
  if(entry.node){ line.dataset.node=entry.node; line.classList.add("has-node"); }
  // "[Activity]" prefix styled apart from the text; older entries only carry msg.
  const text=entry.text!=null ? entry.text : entry.msg;
  const scope=entry.scope ? `<span class="log-scope${entry.scope==="Designer"?" is-app":""}">[${escHtml(entry.scope)}]</span> ` : "";
  line.innerHTML=`<span class="log-ts">${escHtml(entry.ts||"")}</span>`+
    `<span class="log-tag log-${entry.level}">${LOG_TAG[entry.level]||"INF"}</span>`+
    `<span class="log-msg">${scope}${escHtml(text)}</span>`;
  body.appendChild(line);
  wfLogNoteScope(line.dataset.scope);   // keeps the scope picker's options current
  line.classList.toggle("hidden", !wfLogLineOK(line));
  // Cap matches the backend buffer (2000) — long unattended runs keep more
  // history in view; the Save button exports the full buffer to a file anyway.
  while(body.children.length>2000) body.removeChild(body.firstChild);
  if(wfLogAtBottom(body)) body.scrollTop=body.scrollHeight;
  updateLogCount();
}
function rebuildDeviceSelect(devices, connected){
  const sel=$("device-select"), prev=sel.value; sel.innerHTML="";
  if(!devices||!devices.length){
    const o=document.createElement("option"); o.value="";
    o.textContent="No devices — auto-scanning…";
    sel.appendChild(o); sel.disabled=true; return;
  }
  sel.disabled=false;
  devices.forEach(d=>{ const o=document.createElement("option"); o.value=d.serial||""; o.textContent=(d.name||d.serial)+(d.serial?` (${d.serial})`:""); sel.appendChild(o); });
  sel.value=connected||S.connectedSerial||prev||(devices[0]&&devices[0].serial)||"";
}
