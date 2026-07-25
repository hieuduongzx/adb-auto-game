// ── Base helpers ────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
const LOG_TAG = {info:"INF",success:"OK ",warning:"WRN",error:"ERR"};
const S = { devices:[], connectedSerial:null, captureBackend:"scrcpy" };
function setStatus(msg){ const e=$("status-text"); if(e) e.textContent=msg; }
function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
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
let wfSkipIds=null;     // ids greyed out as "not reached", captured once when the run stops
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
  if(!d||!el||el.classList.contains("wf-stk-jbot")) return;   // flush stack member: no room below
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
function wfNodeElById(id){ return id ? document.querySelector(`.wf-node[data-node="${id}"]`) : null; }
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
  document.querySelectorAll("#wf-wires path.wire").forEach(p=>{
    if(p.dataset.from!==id) return;
    p.classList.remove("took-wire","nottook-wire");
    if(p.dataset.fromport===takenPort) p.classList.add("took-wire");
    else if(wfIsBranchPort(p.dataset.fromport)) p.classList.add("nottook-wire");
  });
}
// Ports that are mutually-exclusive branches (so the not-taken ones dim on a run):
// condition true/false, and a switch node's c0.. / default ports.
function wfIsBranchPort(port){ return port==="true"||port==="false"||port==="default"||/^c\d+$/.test(port); }
function wfMarkNodeResult(id, status, port){
  if(!id) return;
  wfRan[id] = status==="fail" ? "fail" : "ok";
  if(port!==undefined && port!==null) wfRanPort[id]=port; else delete wfRanPort[id];
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
// both are left alone. The skip set is captured ONCE at stop time from the graph
// that ran — so blocks dragged in afterwards (which aren't in it) never get dimmed.
function wfMarkUnreached(){
  if(!Object.keys(wfRan).length) return;        // no run happened — nothing to grey out
  if(wfSkipIds===null){
    const g=wfGraph();
    wfSkipIds = g ? (g.nodes||[]).filter(n=>n.type!=="note"&&n.type!=="start"&&!wfRan[n.id]).map(n=>n.id) : [];
  }
  wfSkipIds.forEach(id=>{ const el=wfNodeElById(id); if(el) el.classList.add("ran-skip"); });
}
// Re-paint the whole trail after a canvas redraw (nodes/wires are rebuilt fresh).
function wfReapplyRunViz(){
  Object.keys(wfRan).forEach(id=>wfMarkNodeResult(id, wfRan[id], wfRanPort[id]));
  Object.keys(wfNodeDur).forEach(wfApplyNodeTime);
  const el=wfNodeElById(wfRunNode); if(el) el.classList.add("running");
  if(wfRunStopped) wfMarkUnreached();
  // Canvas rebuilds wipe delay chips — re-bind the live countdown if one is mid-wait.
  if(wfDelayState) wfPaintNodeDelay();
}
function wfResetRunViz(){
  wfRunNode=null; wfLiveNode=null; wfRunStopped=false; wfSkipIds=null;
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
  document.querySelectorAll("#wf-wires path.took-wire,#wf-wires path.nottook-wire")
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
function wfRestoreDelayChip(chip){
  if(!chip) return;
  chip.classList.remove("counting");
  chip.style.removeProperty("--pct");
  const secs=parseFloat(chip.dataset.secs)||0;
  const phase=chip.dataset.phase;
  const label=chip.querySelector(".wf-delay-label");
  const name=phase==="after"?"After":"Before";
  if(label) label.textContent=name+" "+secs+"s";
  chip.title="";
}
function wfClearNodeDelay(){
  if(wfDelayTimer){ clearInterval(wfDelayTimer); wfDelayTimer=null; }
  const prev=wfDelayState; wfDelayState=null;
  document.querySelectorAll(".wf-node.delaying").forEach(el=>el.classList.remove("delaying"));
  document.querySelectorAll(".wf-delay-chip.counting").forEach(wfRestoreDelayChip);
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
  // Prefer the existing static chip for this phase; fall back to a floating badge
  // when the chip row is hidden (stacked join-bottom) or missing.
  let chip=el.querySelector(`.wf-delay-chip[data-phase="${st.phase}"]`);
  if(!chip || getComputedStyle(el.querySelector(".wf-node-delay")||el).display==="none"){
    chip=null;
  }
  const name=st.phase==="after"?"After":"Before";
  const text=name+" "+wfFmtRemain(remain);
  if(chip){
    chip.classList.add("counting");
    chip.style.setProperty("--pct", pct.toFixed(1));
    const label=chip.querySelector(".wf-delay-label");
    if(label) label.textContent=text;
    else chip.innerHTML=(st.phase==="after"?wfIco("timer"):wfIco("clock"))+
      `<span class="wf-delay-label">${text}</span>`;
    chip.title=name+" wait — "+wfFmtRemain(remain)+" left";
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
    live.innerHTML=(st.phase==="after"?wfIco("timer"):wfIco("clock"))+
      `<span class="wf-delay-label">${text}</span>`;
    live.title=name+" wait — "+wfFmtRemain(remain)+" left";
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
  if(!id || (phase!=="before" && phase!=="after") || secs<=0) return;
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

function appendLog(entry){
  const body=$("log-body"); if(!body) return;
  const line=document.createElement("div"); line.className=`log-line fade-in lv-${entry.level||"info"}`;
  line.innerHTML=`<span class="log-ts">${entry.ts}</span>`+
    `<span class="log-tag log-${entry.level}">${LOG_TAG[entry.level]||"INF"}</span>`+
    `<span class="log-msg">${escHtml(entry.msg)}</span>`;
  body.appendChild(line);
  // Cap matches the backend buffer (2000) — long unattended runs keep more
  // history in view; the Save button exports the full buffer to a file anyway.
  while(body.children.length>2000) body.removeChild(body.firstChild);
  body.scrollTop=body.scrollHeight;
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
