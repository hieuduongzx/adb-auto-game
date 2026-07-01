// ── Base helpers ────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
const LOG_TAG = {info:"INF",success:"OK ",warning:"WRN",error:"ERR"};
const S = { devices:[], connectedSerial:null, captureBackend:"scrcpy" };
function setStatus(msg){ const e=$("status-text"); if(e) e.textContent=msg; }
function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function setConnected(on){ const a=$("device-dot"),b=$("footer-dot"); if(a)a.className=on?"connected":""; if(b)b.className=on?"connected":""; }

// Load a template thumbnail (data-URL from Python) into an <img>, hide if none.
async function wfLoadThumb(img, path){
  if(!img) return;
  img.removeAttribute("src");
  if(!path){ img.style.display="none"; return; }
  img.style.display="";  // let CSS show checkerboard while loading
  try{ const d=await api().image_thumbnail(path); if(d){ img.src=d; img.style.display="block"; } }catch{}
}

// Run visualisation. The engine reports (a) the node about to run — painted amber
// while live — and (b) each node's result once it finishes. Results accumulate
// into a persistent "trail" for the whole run: a node that ran turns its border
// green (red if an action failed), and a branch node greens the port/wire it took
// and reds the one it didn't. This is why fast blocks now stay visible — they keep
// the trail colour after the amber moves on.
let wfRunNode=null;
let wfLiveNode=null;    // the engine's true current node id (even if in an off-screen graph); drives focus-on-toggle
let wfRunStopped=false; // true once a finished run's trail is on display (greys-out skipped blocks)
let wfSkipIds=null;     // ids greyed out as "not reached", captured once when the run stops
const wfRan={};       // nodeId -> "ok" | "fail"
const wfRanPort={};   // nodeId -> output port actually taken
// Activity run-status tracker: activityId -> "running" | "errored".
// Drives the blinking-green / solid-red indicator on each activity row in the
// bottom-right panel. Cleared at the start of a run and updated live from the
// engine's on_activity_start / on_activity_complete callbacks.
const wfActStatus={};
// Apply a status class to a single activity row (without a full re-render) so
// the indicator updates instantly when an event arrives.
function wfSetActStatus(id, status){
  if(status){ wfActStatus[id]=status; } else { delete wfActStatus[id]; }
  const el=document.querySelector(`.wf-act[data-id="${id}"]`);
  if(el){
    el.classList.toggle("running", status==="running");
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
  const el=wfNodeElById(wfRunNode); if(el) el.classList.add("running");
  if(wfRunStopped) wfMarkUnreached();
}
function wfResetRunViz(){
  wfRunNode=null; wfLiveNode=null; wfRunStopped=false; wfSkipIds=null;
  for(const k in wfRan) delete wfRan[k];
  for(const k in wfRanPort) delete wfRanPort[k];
  wfResetActStatus();
  document.querySelectorAll(".wf-node.running,.wf-node.ran-ok,.wf-node.ran-fail,.wf-node.ran-skip")
    .forEach(el=>el.classList.remove("running","ran-ok","ran-fail","ran-skip"));
  document.querySelectorAll("#wf-wires path.took-wire,#wf-wires path.nottook-wire")
    .forEach(p=>p.classList.remove("took-wire","nottook-wire"));
  document.querySelectorAll(".wf-port.out.took,.wf-port.out.nottook")
    .forEach(p=>p.classList.remove("took","nottook"));
}

function appendLog(entry){
  const body=$("log-body"); if(!body) return;
  const line=document.createElement("div"); line.className="log-line fade-in";
  line.innerHTML=`<span class="log-ts">${entry.ts}</span>`+
    `<span class="log-tag log-${entry.level}">${LOG_TAG[entry.level]||"INF"}</span>`+
    `<span class="log-msg">${escHtml(entry.msg)}</span>`;
  body.appendChild(line);
  while(body.children.length>500) body.removeChild(body.firstChild);
  body.scrollTop=body.scrollHeight;
  updateLogCount();
}
function rebuildDeviceSelect(devices, connected){
  const sel=$("device-select"), prev=sel.value; sel.innerHTML="";
  if(!devices||!devices.length){ const o=document.createElement("option"); o.value=""; o.textContent="No devices"; sel.appendChild(o); sel.disabled=true; return; }
  sel.disabled=false;
  devices.forEach(d=>{ const o=document.createElement("option"); o.value=d.serial||""; o.textContent=(d.name||d.serial)+(d.serial?` (${d.serial})`:""); sel.appendChild(o); });
  sel.value=connected||S.connectedSerial||prev||(devices[0]&&devices[0].serial)||"";
}
