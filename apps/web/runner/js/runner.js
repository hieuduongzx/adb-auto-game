// ── State ──────────────────────────────────────────────────────────────────
const S = {
  activities:      [],
  running:         false,
  paused:          false,
  loaded:          false,
  expandedId:      null,
  devices:         [],
  connectedSerial: null,
  captureBackend:  "scrcpy",
  controller:      "adb",
  win32:           {},
  bridge:          null,  // unity_bridge plugin status {port, ok, reply} | null
  emulator:        {},   // shared ADB emulator setting {kind, path}
  emulatorDefault: {},   // as shipped by the workflow (what "clear" falls back to)
  logCount:        0,
  logTotal:        0,      // every line received this session (the DOM keeps the newest 500)
  logLevel:        "all",
  outcome:         "",     // how the last run ended: completed | stopped | failed ("" = none)
  exporting:       false,
  diagnostics:     null,
  elapsedText:     "",
  speedhack: { enabled:false, speed:2.0, package:"", active:false },
  runScope:        null,   // activity ids of a single-activity run; null = full Start
  mobileView:      "activities",
};

// This Runner's own version + self-update state (standalone builds only).
const U = { supported:false, version:"", repo:"", update:null, checking:false, applying:false };

const $ = id => document.getElementById(id);
const ACT_DOT_TITLE = { pending:"Waiting", enabled:"Enabled", disabled:"Disabled", running:"Running", paused:"Paused", active:"Active", completed:"Succeeded", succeeded:"Succeeded", failed:"Failed", stopped:"Stopped", skipped:"Skipped" };
// Status word on an activity's second line (pending shows "Waiting" only mid-run).
const ACT_ST_LABEL = { enabled:"Enabled", disabled:"Disabled", running:"Running", paused:"Paused", active:"Active", completed:"Succeeded", succeeded:"Succeeded", failed:"Failed", stopped:"Stopped", skipped:"Skipped", pending:"Waiting" };
// An activity is settled once it reaches one of these — it will not change again
// until the next run, so the progress count may include it.
const SETTLED = ["completed","failed","skipped","stopped"];
const LOG_TAG = { info:"INF", success:"OK ", warning:"WRN", error:"ERR" };
// Log level filter — each entry is the set of levels that stays visible, so the
// wording in the dropdown is exactly what the operator sees.
const LOG_LEVELS = { all:null, warning:["warning","error"], error:["error"] };
// How the last run ended → { pill, banner class, headline }.
const OUTCOME = {
  completed: { pill:"done",    cls:"ok",   word:"Completed" },
  stopped:   { pill:"stopped", cls:"warn", word:"Stopped"   },
  failed:    { pill:"failed",  cls:"err",  word:"Failed"    },
};
const APP_SCOPE = "Runner";   // log prefix for lines that belong to no activity
// Icons come from the shared set (shared/icons.js) — see its header for why
// nothing inlines its own paths.
const CHECK = uiIco("check", "uico-0");
const PLAY  = uiIco("play", "uico-fill");
const PLAY_SM = uiIco("play", "uico-0 uico-fill");   // per-row Run, one ladder step down
const STOP_SM = uiIco("square", "uico-0 uico-fill"); // per-row Stop while its activity runs solo
const GRIP  = uiIco("grip-vertical", "uico-0");

function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

// Small modal on the shared .ui-modal styles (shared/base.css). Resolves with the
// clicked button's value; Escape or a backdrop click resolves undefined.
//
// While it is open the rest of the page is inert: Tab and Shift+Tab cycle inside
// the dialog instead of walking out into the Runner behind it, and the element
// that had focus before it opened gets focus back when it closes — a run can be
// interrupted at any moment, so the keyboard must never end up lost.
function uiDialog(spec){
  return new Promise(resolve=>{
    const prevFocus = document.activeElement;
    const wrap = document.createElement("div"); wrap.className = "ui-modal-wrap";
    const box = document.createElement("div"); box.className = "ui-modal";
    box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
    const titleId = "ui-modal-title-" + (++_dialogSeq);
    if(spec.title){
      const hd = document.createElement("div"); hd.className = "ui-modal-hd";
      hd.id = titleId; hd.textContent = spec.title;
      box.appendChild(hd); box.setAttribute("aria-labelledby", titleId);
    }
    const bd = document.createElement("div"); bd.className = "ui-modal-bd";
    if(spec.message){
      const msg = document.createElement("p"); msg.className = "ui-modal-msg"; msg.textContent = spec.message;
      bd.appendChild(msg);
    }
    if(typeof spec.body === "function") spec.body(bd);
    box.appendChild(bd);
    const ft = document.createElement("div"); ft.className = "ui-modal-ft";
    let primary = null;
    const onKey = e=>{
      if(e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); close(undefined); return; }
      if(e.key !== "Tab") return;
      // Focus trap: keep Tab inside the dialog. The dialog owns every stop, so
      // the list is rebuilt on each Tab rather than cached (buttons can hide).
      const stops = [...box.querySelectorAll("button, [href], input, select, textarea, [tabindex]")]
        .filter(el=>!el.disabled && el.tabIndex !== -1 && el.offsetParent !== null);
      if(!stops.length){ e.preventDefault(); box.focus(); return; }
      const first = stops[0], last = stops[stops.length-1];
      const active = document.activeElement;
      if(e.shiftKey && (active === first || !box.contains(active))){ e.preventDefault(); last.focus(); }
      else if(!e.shiftKey && (active === last || !box.contains(active))){ e.preventDefault(); first.focus(); }
    };
    const close = v=>{
      document.removeEventListener("keydown", onKey, true);
      wrap.remove();
      // Hand focus back to whatever the user was on before the dialog opened.
      if(prevFocus && document.contains(prevFocus) && typeof prevFocus.focus === "function") prevFocus.focus();
      resolve(v);
    };
    (spec.buttons || [{ label:"OK", value:true, kind:"ok" }]).forEach(b=>{
      const btn = document.createElement("button"); btn.type = "button";
      btn.className = "btn" + (b.kind ? " " + b.kind : ""); btn.textContent = b.label;
      btn.onclick = ()=>close(b.value);
      if(b.kind) primary = btn;
      ft.appendChild(btn);
    });
    box.appendChild(ft); wrap.appendChild(box);
    box.tabIndex = -1;   // focusable as a last resort (a dialog with no buttons)
    wrap.addEventListener("mousedown", e=>{ if(e.target === wrap) close(undefined); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    (primary || ft.lastChild).focus();
  });
}
let _dialogSeq = 0;

// ── Elapsed timer ──────────────────────────────────────────────────────────
let _elapsedTimer = null, _elapsedStart = 0;
function startElapsedTimer(){
  _elapsedStart = Date.now();
  if(_elapsedTimer) clearInterval(_elapsedTimer);
  _elapsedTimer = setInterval(()=>{
    const s = Math.floor((Date.now()-_elapsedStart)/1000);
    const h = Math.floor(s/3600).toString().padStart(2,'0');
    const m = Math.floor((s%3600)/60).toString().padStart(2,'0');
    const ss = (s%60).toString().padStart(2,'0');
    $('elapsed').textContent = `${h}:${m}:${ss}`;
  }, 1000);
}
function stopElapsedTimer(){
  if(_elapsedTimer){
    clearInterval(_elapsedTimer); _elapsedTimer=null;
    const el = $('elapsed'); if(el) S.elapsedText = el.textContent;
  }
}
// The activities a run is actually working through: the ones in a single-activity
// scope, or (for a full Start) the enabled sequence activities. Background
// activities loop and never "finish", so they are not part of this count.
function scopedActivities(){
  return S.runScope
    ? S.activities.filter(a=>S.runScope.includes(a.id))
    : S.activities.filter(a=>a.type!=="background" && a.enabled);
}
function updateProgress(){
  // A full Start only runs the enabled sequence activities — counting disabled
  // ones too left the bar stuck short of 100% on every run.
  const seq = scopedActivities();
  const done = seq.filter(a=>SETTLED.includes(a.status)).length;
  const total = seq.length;
  $('prog-count').textContent = total ? `${done}/${total}` : "0/0";
  const succeeded = seq.filter(a=>a.status === "completed").length;
  const failed = seq.filter(a=>a.status === "failed").length;
  $('prog-count').setAttribute("aria-label", `${done} settled, ${succeeded} succeeded, ${failed} failed, ${total} total`);
  $('prog-bar').style.transform = `scaleX(${total ? done/total : 0})`;
  // The bar's colour carries the result, so a full bar that ended in a failure
  // never reads as a clean finish.
  const bar = $('prog-bar');
  if(bar) bar.className = "prog-bar-fill" + (S.outcome ? " outcome-" + S.outcome : "");
  renderQueueMonitor(seq);
}

function renderQueueMonitor(seq){
  const sequence = S.activities.filter(a=>a.type!=="background");
  const background = S.activities.filter(a=>a.type==="background");
  const summary = $("queue-summary");
  if(summary){
    summary.textContent = S.runScope
      ? "Single activity run"
      : `${sequence.filter(a=>a.enabled).length} sequence · ${background.filter(a=>a.enabled).length} background enabled`;
  }
  const current = $("queue-current");
  if(!current) return;
  const running = seq.find(a=>a.status === "running");
  const next = seq.find(a=>!SETTLED.includes(a.status));
  current.textContent = running ? `Running: ${running.name}` : next ? `Next: ${next.name}` : (seq.length ? "Queue settled" : "Next: —");
  current.title = current.textContent;
}

// ── Run outcome ──────────────────────────────────────────────────────────────
// The backend reports how a run ended (completed / stopped / failed) with its
// final running_state. Older builds send no outcome at all, so one is derived
// from the activities' own final statuses — every scoped activity settled and
// none failed means the run completed; anything else is an interrupted run.
function derivedOutcome(){
  const seq = scopedActivities();
  if(!seq.length) return "";
  if(seq.some(a=>a.status === "failed")) return "failed";
  if(seq.some(a=>a.status === "stopped")) return "stopped";
  if(seq.every(a=>SETTLED.includes(a.status))) return "completed";
  return "stopped";   // it ran, nothing failed, but not everything finished
}
function outcomeMessage(outcome, data){
  const seq = scopedActivities();
  const total = seq.length;
  const settled = seq.filter(a=>SETTLED.includes(a.status)).length;
  const failed  = seq.filter(a=>a.status === "failed").length;
  const noun = total === 1 ? "activity" : "activities";
  const took = S.elapsedText && S.elapsedText !== "00:00:00" ? ` in ${S.elapsedText}` : "";
  if(outcome === "completed") return `All ${total} ${noun} finished${took}.`;
  if(outcome === "failed"){
    const first = seq.find(a=>a.status === "failed");
    const which = first && first.name ? `: “${first.name}” failed` : "";
    return `${failed} of ${total} ${noun} failed${which}.`;
  }
  if(outcome === "stopped") return `Stopped after ${settled} of ${total} ${noun}${took}.`;
  return "";
}
// Show (or clear) the header's run result. `data` may carry the backend's own
// wording, which wins over anything derived here.
function setOutcome(outcome, data){
  const spec = OUTCOME[outcome];
  S.outcome = spec ? outcome : "";
  const row = $("run-outcome"), text = $("outcome-text");
  if(!row || !text) return;
  if(!spec){ row.hidden = true; text.textContent = ""; paintStatusPill(); updateProgress(); return; }
  const msg = (data && typeof data.message === "string" && data.message.trim()) || outcomeMessage(outcome, data);
  row.hidden = false;
  row.className = "run-outcome outcome-" + spec.cls;
  text.textContent = msg ? `${spec.word}: ${msg}` : spec.word;
  paintStatusPill(); updateProgress();
}
function dismissOutcome(){
  const row = $("run-outcome");
  if(row) row.hidden = true;
  S.outcome = "";
  paintStatusPill(); updateProgress();
}

// ── Status pill ──────────────────────────────────────────────────────────────
// Idle, the pill reports the last run's outcome (COMPLETED / STOPPED / FAILED)
// rather than a bare READY, so the header never looks happier than the run was.
function paintStatusPill(){
  if(S.running){ setStatusPill(S.paused ? "paused" : "running"); return; }
  const spec = OUTCOME[S.outcome];
  setStatusPill(spec ? spec.pill : "ready", spec ? spec.word.toUpperCase() : "");
}
function setStatusPill(key, label){
  const pill = $("status-pill"); pill.className = "";
  if(key==="running"){ pill.classList.add("status-running"); $("status-text").textContent = label || "RUNNING"; }
  else if(key==="paused"){ pill.classList.add("status-paused"); $("status-text").textContent = label || "PAUSED"; }
  else if(key==="done"){ pill.classList.add("status-done"); $("status-text").textContent = label || "COMPLETED"; }
  else if(key==="failed"){ pill.classList.add("status-failed"); $("status-text").textContent = label || "FAILED"; }
  else if(key==="stopped"){ pill.classList.add("status-stopped"); $("status-text").textContent = label || "STOPPED"; }
  else { pill.classList.add("status-ready"); $("status-text").textContent = label || "READY"; }
}

// ── Primary button — Start while idle, Stop while running ────────────────────
// One button rather than two, so there is exactly one obvious way to stop. The
// label and icon are rebuilt only on an actual state change: rewriting innerHTML
// every refresh would drop focus from the button mid-run.
let _primaryRunning = null;
function setPrimary(running){
  if(_primaryRunning === running) return;
  _primaryRunning = running;
  const b = $("btn-primary");
  b.classList.toggle("is-stop", running);
  b.innerHTML = uiIco(running ? "square" : "play", "uico-fill") + (running ? "Stop" : "Start");
  b.title = running ? "Stop the run" : "Start the run (F5 or Ctrl+Enter)";
  b.setAttribute("aria-label", running ? "Stop workflow" : "Start workflow");
}
// The swapping handler the button's onclick points at.
async function onPrimary(){ if(S.running) await onStop(); else await onStart(); }

// ── Button states ────────────────────────────────────────────────────────────
function refreshButtons(){
  const running = S.running, paused = S.paused;
  setPrimary(running);
  $("btn-primary").disabled = !S.loaded;
  $("btn-pause").disabled = !running;
  $("btn-pause").textContent = paused ? "Resume" : "Pause";
  $("btn-pause").setAttribute("aria-label", paused ? "Resume workflow" : "Pause workflow");
  document.querySelectorAll(".runtime-setting-control").forEach(el=>el.disabled=running);
  const reqCopy = $("btn-req-copy");
  if(reqCopy) reqCopy.disabled = running || !(S.requirements && S.requirements.gameDir);
  updateRowRunButtons();
  $("app").classList.toggle("is-running", running);
  if(S.expandedId){
    const save = $("activity-save-status");
    if(running) setActivitySaveState("Stop to edit");
    else if(save && save.textContent === "Stop to edit") setActivitySaveState("");
  }
  S.activities.forEach(a=>paintRow(a));   // "Waiting" / "Active" follow the run state
  renderUpdate();
  paintStatusPill();
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab){
  document.querySelectorAll(".tab-btn").forEach(b=>{ const on=b.dataset.tab===tab; b.classList.toggle("active",on); b.setAttribute("aria-selected",String(on)); });
  document.querySelectorAll(".tab-pane").forEach(p=>p.classList.toggle("active", p.id==="tab-"+tab));
  syncTabIndex($("tabs-bar"));
}
// Right column: Activity settings | Log. Changelog and runner settings are header popovers.
function switchRTab(tab){
  if(tab!=="act" && tab!=="log") tab="log";
  document.querySelectorAll("#r-tabs .rtab").forEach(b=>{ const on=b.dataset.rtab===tab; b.classList.toggle("active",on); b.setAttribute("aria-selected",String(on)); });
  document.querySelectorAll("#r-content .rpane").forEach(p=>p.classList.toggle("active", p.id==="r-"+tab));
  syncTabIndex($("r-tabs"));
  if(tab==="log"){
    const body = $("log-body"); if(body){ body.scrollTop = body.scrollHeight; }
    renderLogCount();
  }
  if(window.matchMedia && window.matchMedia("(max-width: 640px)").matches){
    switchMobileView(tab==="log" ? "log" : "activity", false);
  }
}

// At the Runner's minimum width, the activity list and the right panel cannot
// both stay useful. This navigation makes them three predictable views while
// preserving the desktop split above the breakpoint.
function switchMobileView(view, syncPanel=true){
  const allowed = ["activities", "activity", "log", "settings"];
  if(!allowed.includes(view)) view = "activities";
  S.mobileView = view;
  const shell = $("main-split");
  const settings = $("mobile-settings");
  if(shell) shell.dataset.mobileView = view;
  if(settings) settings.hidden = view !== "settings";
  syncRunnerSettingsHost();
  const publicView = view === "activity" ? "activities" : view;
  document.querySelectorAll("#mobile-tabs [data-mobile-view]").forEach(btn=>{
    const on = btn.dataset.mobileView === publicView;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", String(on));
    btn.tabIndex = on ? 0 : -1;
  });
  if(syncPanel && view === "log") switchRTab(view);
}

// Roving tabindex: the selected tab is the one Tab reaches; the arrows move
// between tabs (WAI-ARIA tablist pattern) so the whole ring is one tab stop.
function syncTabIndex(bar){
  if(!bar) return;
  bar.querySelectorAll('[role="tab"]').forEach(b=>{ b.tabIndex = b.classList.contains("active") ? 0 : -1; });
}
function wireTabNav(barId, attr, activate){
  const bar = $(barId);
  if(!bar) return;
  const tabs = [...bar.querySelectorAll('[role="tab"]')];
  tabs.forEach((btn, i)=>{
    btn.addEventListener("keydown", e=>{
      let next = -1;
      if(e.key === "ArrowRight" || e.key === "ArrowDown") next = (i + 1) % tabs.length;
      else if(e.key === "ArrowLeft" || e.key === "ArrowUp") next = (i - 1 + tabs.length) % tabs.length;
      else if(e.key === "Home") next = 0;
      else if(e.key === "End") next = tabs.length - 1;
      else return;
      e.preventDefault();
      const target = tabs[next];
      activate(target.dataset[attr]);
      target.focus();
      syncTabIndex(bar);
    });
  });
  syncTabIndex(bar);
}

// ── Build activity rows ──────────────────────────────────────────────────────
function buildRow(a){
  const isBg = a.type==="background";
  const row = document.createElement("div");
  row.className = "task-row";
  row.dataset.id = a.id;

  const handle = document.createElement("div");
  handle.className = "drag-handle"; handle.title = "Drag or use arrow keys to reorder";
  handle.tabIndex = 0; handle.setAttribute("role", "button");
  handle.setAttribute("aria-label", `Reorder ${a.name}`);
  handle.innerHTML = GRIP;
  attachDragHandle(row, handle, isBg ? "bg-list" : "seq-list");

  const cb = document.createElement("button");
  cb.type = "button";
  cb.className = "cb" + (a.enabled ? " checked" : "");
  cb.title = "Enable or disable activity"; cb.innerHTML = CHECK;
  cb.setAttribute("aria-label", `Enable ${a.name}`);
  cb.setAttribute("aria-pressed", String(!!a.enabled));
  cb.onclick = ()=>{
    a.enabled = !a.enabled;
    cb.classList.toggle("checked", a.enabled);
    cb.setAttribute("aria-pressed", String(!!a.enabled));
    paintRow(a, row); updateListSummary(); updateProgress();
    api().toggle_activity(a.id, a.enabled);
  };

  const dot = document.createElement("span");
  dot.className = "act-dot";
  dot.setAttribute("role", "status");
  dot.dataset.dot = "1";

  const block = document.createElement("div");
  block.className = "task-name-block";
  const name = document.createElement("div");
  name.className = "task-name";
  name.textContent = a.name;
  name.title = a.name;   // long names are ellipsised
  block.appendChild(name);
  const meta = document.createElement("div");
  meta.className = "task-meta"; meta.dataset.meta = "1";
  block.appendChild(meta);

  const btns = document.createElement("div");
  btns.className = "task-btns";
  // Settings first, Run last — the calm action, then the loud one.
  const hasSettings = activityHasSettings(a);
  if(hasSettings){
    const gear = gearButton(a.id);
    gear.onclick = ()=>toggleSettings(a.id);
    btns.appendChild(gear);
  }
  // Run just this activity — ignores its checkbox; a background one loops until
  // Stop. While THIS activity is the one running solo, it becomes Stop.
  const runOne = document.createElement("button");
  runOne.type = "button"; runOne.className = "btn-icon btn-run-one"; runOne.dataset.runOne = a.id;
  runOne.onclick = ()=>onRunToggle(a.id);
  btns.appendChild(runOne);

  row.appendChild(handle); row.appendChild(cb); row.appendChild(dot); row.appendChild(block); row.appendChild(btns);
  paintRow(a, row);
  // Clicking the row (not one of its controls) opens the activity's settings —
  // the gear remains as the affordance, and the row is the shortcut.
  row.addEventListener("click", e=>{
    if(e.target.closest("button, input, select, .cb, .drag-handle")) return;
    openActivitySettings(a.id);
  });
  return row;
}

// ── Drag-to-reorder ──────────────────────────────────────────────────────────
function attachDragHandle(row, handle, listId){
  handle.addEventListener("mousedown", ()=>{ if(!S.running) row.draggable = true; });
  handle.addEventListener("mouseup",   ()=>{ row.draggable = false; });

  row.addEventListener("dragstart", e=>{
    if(S.running){ e.preventDefault(); return; }
    if(S.expandedId){ toggleSettings(S.expandedId); }
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    try{ e.dataTransfer.setData("text/plain", row.dataset.id); }catch(_){}
  });
  row.addEventListener("dragend", ()=>{
    row.draggable = false;
    row.classList.remove("dragging");
    commitOrder();
  });
  handle.addEventListener("keydown", e=>{
    if(S.running || !["ArrowUp","ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const sibling = e.key==="ArrowUp" ? row.previousElementSibling : row.nextElementSibling;
    if(!sibling || !sibling.classList.contains("task-row")) return;
    if(e.key==="ArrowUp") row.parentElement.insertBefore(row, sibling);
    else row.parentElement.insertBefore(sibling, row);
    commitOrder();
    handle.focus();
  });
}

function dragAfterElement(list, y){
  const rows = [...list.querySelectorAll(".task-row:not(.dragging)")];
  let closest = null, closestOffset = Number.NEGATIVE_INFINITY;
  for(const r of rows){
    const box = r.getBoundingClientRect();
    const offset = y - box.top - box.height/2;
    if(offset < 0 && offset > closestOffset){ closestOffset = offset; closest = r; }
  }
  return closest;
}

function setupListDnD(list){
  list.addEventListener("dragover", e=>{
    const dragging = document.querySelector(".task-row.dragging");
    if(!dragging || dragging.parentElement !== list) return;  // same-list only
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const after = dragAfterElement(list, e.clientY);
    if(after == null) list.appendChild(dragging);
    else list.insertBefore(dragging, after);
  });
}

function commitOrder(){
  const ids = [];
  $("seq-list").querySelectorAll(".task-row").forEach(r=>ids.push(r.dataset.id));
  $("bg-list").querySelectorAll(".task-row").forEach(r=>ids.push(r.dataset.id));
  S.activities.sort((a,b)=> ids.indexOf(a.id) - ids.indexOf(b.id));
  try{ api().reorder_activities(ids); }catch(_){}
}

// Dot, status line and row tint from an activity's state. Background activities
// loop every few seconds, so they show a steady Active / idle state instead of
// flashing running → done on every tick.
function paintRow(a, row){
  row = row || document.querySelector(`.task-row[data-id="${a.id}"]`);
  if(!row) return;
  const isBg = a.type==="background";
  const inRun = S.running && (S.runScope ? S.runScope.includes(a.id) : !!a.enabled);
  const status = a.status || "pending";
  let st = status;
  if(isBg && inRun && status !== "failed" && status !== "stopped") st = S.paused ? "paused" : "active";
  else if(inRun && status === "running" && S.paused) st = "paused";
  else if(status === "pending" && !inRun) st = a.enabled ? "enabled" : "disabled";
  row.classList.toggle("task-paused", st === "paused");
  const dot = row.querySelector("[data-dot]");
  if(dot){
    dot.className = "act-dot act-dot-" + st;
    dot.title = ACT_DOT_TITLE[st] || ACT_DOT_TITLE.pending;
    dot.setAttribute("aria-label", `Status: ${dot.title}`);
  }
  row.classList.toggle("task-running", st==="running");
  row.classList.toggle("task-failed", st==="failed");
  row.classList.toggle("task-stopped", st==="stopped");
  row.classList.toggle("task-off", !a.enabled);
  const meta = row.querySelector("[data-meta]");
  if(meta) renderMeta(meta, a, st, inRun);
}

// Second line under the activity name: status word, then its settings summary.
function renderMeta(el, a, st, inRun){
  const parts = [];
  if(a.type==="background"){
    if(st==="active") parts.push('<span class="act-st st-active">Active</span>');
    else if(ACT_ST_LABEL[st]) parts.push(`<span class="act-st st-${st}">${ACT_ST_LABEL[st]}</span>`);
    parts.push(`Every ${Number(a.pollInterval)||1}s`);
  } else {
    if(ACT_ST_LABEL[st]) parts.push(`<span class="act-st st-${st}">${ACT_ST_LABEL[st]}</span>`);
    if(a.maxRetries > 1) parts.push(`${a.maxRetries} attempts`);
  }
  el.innerHTML = parts.join('<span class="sep" aria-hidden="true">·</span>');
}

// "3 of 5 enabled" above each list.
function updateListSummary(){
  [["seq-sum", a=>a.type!=="background"], ["bg-sum", a=>a.type==="background"]].forEach(([id, pick])=>{
    const el = $(id); if(!el) return;
    const list = S.activities.filter(pick);
    el.textContent = list.length ? `${list.filter(a=>a.enabled).length} of ${list.length} enabled` : "";
  });
}

function gearButton(id){
  const g = document.createElement("button");
  g.type = "button"; g.className = "btn-icon btn-gear"; g.title = "Activity settings"; g.dataset.gear = id;
  g.setAttribute("aria-label", "Activity settings");
  g.innerHTML = uiIco("settings", "uico-1");
  return g;
}

// ── Inline settings panel ────────────────────────────────────────────────────
// Grouped into labelled sections (Timing / Files & folders / Variables) so the
// panel reads as a small form instead of a flat list. Path fields get their own
// full-width line — long folders never fight the label for space.
function buildSettingsPanel(a){
  const panel = document.createElement("div");
  panel.className = "task-settings"; panel.dataset.settingsFor = a.id;

  const group = title=>{
    const g = document.createElement("div"); g.className = "setting-group";
    if(title){ const h = document.createElement("div"); h.className = "setting-group-title"; h.textContent = title; g.appendChild(h); }
    return g;
  };

  // Background activities run on a timer — that's their only runtime setting.
  if(a.type==="background"){
    const g = group("Schedule");
    const row = document.createElement("div"); row.className = "setting-row";
    const lbl = document.createElement("span"); lbl.className = "setting-label"; lbl.textContent = "Repeat every";
    const inp = document.createElement("input");
    inp.type = "number"; inp.className = "setting-input";
    inp.setAttribute("aria-label", "Background interval in seconds");
    inp.min = 0.05; inp.step = 0.5; inp.value = a.pollInterval;
    inp.onchange = ()=>{
      const v = Math.max(0.05, parseFloat(inp.value)||a.pollInterval);
      inp.value = v; setActivitySaveState("Saving…");
      Promise.resolve(api().set_interval(a.id, v)).then(ok=>{
        if(ok === false) throw new Error();
        a.pollInterval = v; paintRow(a); setActivitySaveState("Saved", "ok");
      }).catch(()=>{ inp.value=a.pollInterval; setActivitySaveState("Couldn't save", "error"); });
    };
    const unit = document.createElement("span"); unit.className = "setting-unit"; unit.textContent = "seconds";
    row.appendChild(lbl); row.appendChild(inp); row.appendChild(unit);
    g.appendChild(row); panel.appendChild(g);
  }

  // Machine-specific file/folder paths the run needs (emulator folder, APK…).
  const paths = a.runtimeSettings || [];
  if(paths.length){
    const g = group("Files & folders");
    paths.forEach(setting=>{
      const field = document.createElement("div"); field.className = "setting-field";
      const lbl = document.createElement("span"); lbl.className = "setting-label";
      lbl.innerHTML = escHtml(setting.label||"Path")
        + (setting.nodeLabel ? `<span class="sub">${escHtml(setting.nodeLabel)}</span>` : "");
      const control = document.createElement("div"); control.className = "setting-path-control";
      const inp = document.createElement("input"); inp.type = "text";
      inp.className = "setting-path-input runtime-setting-control";
      inp.value = setting.value||""; inp.placeholder = setting.kind==="folder"?"Choose a folder…":"Choose a program…";
      inp.setAttribute("aria-label", setting.label||"Runtime path");
      inp.title = inp.value; inp.disabled = !!S.running;
      inp.onchange = async()=>{
        const old = setting.value||"", value = inp.value.trim();
        setActivitySaveState("Saving…");
        let ok = false; try{ ok = await api().set_node_runtime_param(setting.nodeId,setting.param,value); }catch(_){ }
        if(ok){ syncRuntimeSetting(setting.nodeId,setting.param,value); inp.title = value; setActivitySaveState("Saved", "ok"); }
        else { inp.value = old; setActivitySaveState("Couldn't save", "error"); }
      };
      const pick = document.createElement("button"); pick.type = "button";
      pick.className = "btn-path-pick runtime-setting-control"; pick.textContent = "Choose…";
      pick.title = setting.kind==="folder"?"Choose folder":"Choose program file"; pick.disabled = !!S.running;
      pick.onclick = async()=>{
        let value = "";
        setActivitySaveState("Saving…");
        try{ value = await api().pick_node_runtime_path(setting.nodeId,setting.param,setting.kind,inp.value); }catch(_){ }
        if(value){ inp.value = value; inp.title = value; syncRuntimeSetting(setting.nodeId,setting.param,value); setActivitySaveState("Saved", "ok"); }
        else setActivitySaveState("");
      };
      control.appendChild(inp); control.appendChild(pick);
      field.appendChild(lbl); field.appendChild(control);
      g.appendChild(field);
    });
    panel.appendChild(g);
  }

  // Per-activity variable values (toggles, numbers, text) — the human label
  // only; the variable's code name is noise for the player.
  const vars = a.vars || [];
  if(vars.length){
    const g = group("");
    const activeOptions=v=>{
      if(v.display==="toggle-group"&&v.multiple) return Array.isArray(v.value)?v.value.slice():[];
      return v.value!=null&&v.value!==""?[String(v.value)]:[];
    };
    function appendSettingVar(container, v, path){
      const block=document.createElement("div"); block.className="setting-var-block";
      const row = document.createElement("div"); row.className = "setting-row";
      const lbl = document.createElement("span"); lbl.className = "setting-label";
      lbl.textContent = v.label || v.name;
      row.appendChild(lbl);
      const sub=document.createElement("div"); sub.className="setting-var-nested";
      function fillSub(){
        sub.replaceChildren();
        (v.children||[]).forEach(child=>{
          if(child&&child.name) appendSettingVar(sub, child, path+"."+child.name);
        });
        if((v.type||"bool")!=="select") return;
        const owner=v.label||v.name||"this setting";
        activeOptions(v).forEach(opt=>{
          const kids=((v.optionChildren||{})[opt])||[];
          if(!kids.length) return;
          const nest=document.createElement("div"); nest.className="setting-option-nest";
          nest.setAttribute("aria-label", owner);
          kids.forEach(child=>{
            if(child&&child.name) appendSettingVar(nest, child, path+"."+opt+"."+child.name);
          });
          sub.appendChild(nest);
        });
      }

      const type = v.type || "bool";
      if(type==="bool"){
        const cb = document.createElement("button"); cb.type = "button"; cb.className = "cb"+(v.value?" checked":""); cb.innerHTML = CHECK;
        cb.setAttribute("aria-label", v.label||v.name); cb.setAttribute("aria-pressed",String(!!v.value));
        cb.onclick = async()=>{
          const old = v.value, next = !old;
          cb.disabled = true; setActivitySaveState("Saving…");
          try{
            const ok = await api().set_activity_var(a.id,path,next);
            if(!ok) throw new Error();
            v.value=next; cb.classList.toggle("checked",next); cb.setAttribute("aria-pressed",String(next));
            setActivitySaveState("Saved", "ok");
          }catch(_){ setActivitySaveState("Couldn't save", "error"); }
          finally{ cb.disabled = false; }
        };
        row.appendChild(cb);
      } else if(type==="select" && v.display==="toggle-group"){
        row.classList.add("setting-row-options");
        const choices=document.createElement("div"); choices.className="setting-toggle-group";
        const multi=!!v.multiple;
        const checked=option=>multi?(Array.isArray(v.value)&&v.value.includes(option)):String(v.value)===String(option);
        choices.setAttribute("role",multi?"group":"radiogroup"); choices.setAttribute("aria-label",v.label||v.name);
        const options=[...new Set(v.options||[])];
        const inputs=[];
        const error=document.createElement("span"); error.className="setting-choice-error";
        error.setAttribute("role","alert"); error.hidden=true;
        // Native radios provide exclusive selection and arrow-key navigation.
        const name="var-choice-"+a.id+"-"+path;
        options.forEach(option=>{
          const label=document.createElement("label"); label.className="setting-choice";
          const input=document.createElement("input"); input.type=multi?"checkbox":"radio"; input.name=name;
          input.value=option; input.checked=checked(option);
          const text=document.createElement("span"); text.textContent=option;
          input.onchange=async()=>{
            if(!multi&&!input.checked) return;
            const value=multi?options.filter((o,i)=>inputs[i].checked):option;
            error.hidden=true; setActivitySaveState("Saving…");
            const hadFocus=document.activeElement===input;
            inputs.forEach(el=>{ el.disabled=true; });
            try{
              const ok=await api().set_activity_var(a.id,path,value);
              if(!ok) throw new Error("Setting was not saved");
              v.value=value;
              fillSub();
              setActivitySaveState("Saved", "ok");
            }catch(_){
              error.textContent="Couldn't save this choice. Please try again."; error.hidden=false;
              setActivitySaveState("Couldn't save", "error");
            }finally{
              inputs.forEach((el,i)=>{ el.checked=checked(options[i]); el.disabled=false; });
              if(hadFocus) input.focus();
            }
          };
          inputs.push(input); label.append(input,text); choices.appendChild(label);
        });
        if(!options.length){
          const empty=document.createElement("span"); empty.className="setting-label";
          empty.textContent="Add options in Designer"; choices.appendChild(empty);
        }
        row.appendChild(choices);
        row.appendChild(error);
      } else if(type==="select"){
        const sel = document.createElement("select");
        (v.options||[]).forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; if(String(v.value)===String(o))op.selected=true; sel.appendChild(op); });
        sel.onchange = async()=>{
          const old=v.value, value=sel.value; sel.disabled=true; setActivitySaveState("Saving…");
          try{
            if(!await api().set_activity_var(a.id,path,value)) throw new Error();
            v.value=value; fillSub(); setActivitySaveState("Saved", "ok");
          }
          catch(_){ sel.value=old; setActivitySaveState("Couldn't save", "error"); }
          finally{ sel.disabled=false; }
        };
        row.appendChild(sel);
      } else {
        const inp = document.createElement("input");
        inp.type = type==="number" ? "number" : "text"; inp.className = "setting-input";
        inp.value = (v.value!=null ? v.value : "");
        inp.onchange = async()=>{
          const old=v.value, val=type==="number" ? (parseFloat(inp.value)||0) : inp.value;
          inp.disabled=true; setActivitySaveState("Saving…");
          try{ if(!await api().set_activity_var(a.id,path,val)) throw new Error(); v.value=val; setActivitySaveState("Saved", "ok"); }
          catch(_){ inp.value=old ?? ""; setActivitySaveState("Couldn't save", "error"); }
          finally{ inp.disabled=false; }
        };
        row.appendChild(inp);
      }
      block.appendChild(row);
      block.appendChild(sub);
      fillSub();
      container.appendChild(block);
    }
    vars.forEach(v=>{ if(v&&v.name) appendSettingVar(g, v, v.name); });
    panel.appendChild(g);
  }

  // Retry count — a RUNNER setting (saved to this Runner's config, never to the
  // workflow). Default 1; an activity is tried this many times before failing.
  // Always last, after the activity's own config.
  {
    const g = group("");
    const row = document.createElement("div"); row.className = "setting-row";
    const lbl = document.createElement("span"); lbl.className = "setting-label"; lbl.textContent = "Attempts";
    const inp = document.createElement("input");
    inp.type = "number"; inp.className = "setting-input runtime-setting-control";
    inp.min = 1; inp.step = 1; inp.value = a.maxRetries || 1;
    inp.setAttribute("aria-label", "Number of attempts");
    inp.title = "How many times this activity is tried before it fails (Runner setting)";
    inp.disabled = !!S.running;
    inp.onchange = async()=>{
      let v = Math.max(1, parseInt(inp.value, 10) || 1);
      inp.value = v;
      setActivitySaveState("Saving…");
      let res = null; try{ res = await api().set_activity_retries(a.id, v); }catch(_){ }
      if(res && res.ok){ v = res.retries; setActivitySaveState("Saved", "ok"); }
      else { v = a.maxRetries || 1; setActivitySaveState("Couldn't save", "error"); }
      a.maxRetries = v; inp.value = v;
      paintRow(a);
    };
    row.appendChild(lbl); row.appendChild(inp);
    g.appendChild(row); panel.appendChild(g);
  }

  return panel;
}

function syncRuntimeSetting(nodeId,param,value){
  S.activities.forEach(a=>(a.runtimeSettings||[]).forEach(s=>{
    if(s.nodeId===nodeId&&s.param===param) s.value=value;
  }));
}

// The right column's Activity settings tab shows the settings of the activity
// whose gear was pressed. Clicking the same gear again (or the ×) closes it.
function showSettingsEmpty(){
  const host = $("act-set-body"); if(!host) return;
  host.innerHTML = '<div class="act-set-empty">Select the <b>⚙</b> on an activity to edit its settings here.</div>';
}
let _activitySaveTimer = null;
function setActivitySaveState(message, kind=""){
  const el = $("activity-save-status"); if(!el) return;
  if(_activitySaveTimer){ clearTimeout(_activitySaveTimer); _activitySaveTimer=null; }
  el.textContent = message || "";
  el.className = "activity-save-status" + (kind ? " " + kind : "");
  if(message === "Saved") _activitySaveTimer = setTimeout(()=>{ el.textContent=""; }, 1800);
}
function closeActivitySettings(){
  S.expandedId = null;
  document.querySelectorAll(".btn-gear.active").forEach(g=>g.classList.remove("active"));
  document.querySelectorAll(".task-row.is-selected").forEach(row=>row.classList.remove("is-selected"));
  const title = $("act-set-title"); if(title) title.textContent = "Activity settings";
  setActivitySaveState("");
  showSettingsEmpty();
  if(S.mobileView === "activity") switchMobileView("activities");
  else switchRTab("log");
}
function toggleSettings(id){
  const a = S.activities.find(x=>x.id===id); if(!a) return;
  const host = $("act-set-body");
  if(!host) return;
  if(S.expandedId === id){ closeActivitySettings(); return; }
  document.querySelectorAll(".btn-gear.active").forEach(g=>g.classList.remove("active"));
  const gear = document.querySelector(`.task-row[data-id="${id}"] [data-gear]`);
  if(gear) gear.classList.add("active");
  document.querySelectorAll(".task-row.is-selected").forEach(row=>row.classList.remove("is-selected"));
  const selectedRow = document.querySelector(`.task-row[data-id="${id}"]`);
  if(selectedRow) selectedRow.classList.add("is-selected");
  S.expandedId = id;
  host.innerHTML = "";
  host.appendChild(buildSettingsPanel(a));
  const title = $("act-set-title"); if(title) title.textContent = a.name || "Activity settings";
  switchRTab("act");
  switchMobileView("activity", false);
}
// Every activity has settings now (at least a Runner-only retry count), so the
// gear shows on all rows and clicking any row opens its config.
function activityHasSettings(a){
  return !!a;
}
// Open the Activity settings tab for this activity (row click shortcut).
function openActivitySettings(id){
  const a = S.activities.find(x=>x.id===id);
  if(!activityHasSettings(a)) return;
  if(S.expandedId === id){ switchRTab("act"); return; }
  toggleSettings(id);
}
// Keep the right column in sync after rows are rebuilt (populateLists).
function syncActivitySettings(){
  if(!S.expandedId) return;
  const a = S.activities.find(x=>x.id===S.expandedId);
  if(!a){ closeActivitySettings(); return; }
  const gear = document.querySelector(`.task-row[data-id="${S.expandedId}"] [data-gear]`);
  const row = document.querySelector(`.task-row[data-id="${S.expandedId}"]`);
  if(gear){ gear.classList.add("active"); if(row) row.classList.add("is-selected"); }
  else closeActivitySettings();
}

// ── Populate lists ───────────────────────────────────────────────────────────
function populateLists(){
  const seqList = $("seq-list"), bgList = $("bg-list");
  seqList.innerHTML = ""; bgList.innerHTML = "";
  const seq = S.activities.filter(a=>a.type!=="background");
  const bg  = S.activities.filter(a=>a.type==="background");
  if(seq.length) seq.forEach(a=>seqList.appendChild(buildRow(a)));
  else seqList.innerHTML = '<div class="empty-note">No sequence activities.</div>';
  if(bg.length) bg.forEach(a=>bgList.appendChild(buildRow(a)));
  else bgList.innerHTML = '<div class="empty-note">No background activities.</div>';
  $("bg-hint").style.display = bg.length ? "" : "none";
  updateListSummary();
  syncActivitySettings();
  updateRowRunButtons();
}

function setActStatus(id, status){
  const a = S.activities.find(x=>x.id===id);
  if(a){ a.status = status; paintRow(a); }
  updateProgress();
}

// ── Devices ──────────────────────────────────────────────────────────────────
function rebuildDevices(devices, connected){
  const sel = $("device-select"), prev = sel.value; sel.innerHTML = "";
  if(!devices||!devices.length){
    const o=document.createElement("option"); o.value=""; o.textContent="No devices";
    sel.appendChild(o); sel.disabled=true; return;
  }
  sel.disabled = false;
  devices.forEach(d=>{ const o=document.createElement("option"); o.value=d.serial||"";
    o.textContent=(d.name||d.serial)+(d.serial?` (${d.serial})`:""); sel.appendChild(o); });
  sel.value = connected || S.connectedSerial || prev || (devices[0]&&devices[0].serial) || "";
}
function setConnected(on, name, serial){
  $("dev-dot").classList.toggle("connected", !!on);
  const lbl = $("dev-label");
  lbl.textContent = on ? "Connected" : "Disconnected";
  lbl.title = on ? `${name||""} ${serial||""}`.trim() : "";
}

// ── Log ──────────────────────────────────────────────────────────────────────
// The badge counts what the operator can actually read: while a search or a
// level filter is hiding lines it shows "shown/total", otherwise just the total.
// S.logTotal keeps counting past the 500 lines the DOM retains, so the number
// never silently stops at the trim cap.
function renderLogCount(){
  const body = $("log-body");
  const total = S.logTotal;
  let shown = 0;
  if(body){
    body.querySelectorAll(".log-line").forEach(l=>{ if(!l.classList.contains("hidden")) shown++; });
    // Lines trimmed off the top are gone for good; the visible count can never
    // exceed what the DOM holds.
    shown = Math.min(shown, body.children.length);
  }
  const filtered = shown !== total;
  const txt = total ? (filtered ? `${shown}/${total}` : String(total)) : "";
  const el = $("log-count");
  if(el){
    el.textContent = txt;
    el.title = filtered ? `${shown} of ${total} lines shown` : `${total} lines`;
  }
  const tab = $("rtab-log-count"); if(tab) tab.textContent = txt;
}
let _logCountTimer = null;
function scheduleLogCount(){
  if(_logCountTimer) return;
  _logCountTimer = setTimeout(()=>{ _logCountTimer = null; renderLogCount(); }, 150);
}
function appendLog(e){
  const body = $("log-body");
  // Follow new lines only when already at the bottom — scrolling up to read an
  // earlier error must not be yanked away by the next line.
  const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
  const level = e.level || "info";
  const line = document.createElement("div");
  line.className = `log-line fade-in lv-${level} k-${e.kind||"app"}`;
  line.dataset.level = level;
  // Every line starts with "[Activity]" (or "[Runner]"); older entries only carry msg.
  const text = e.text != null ? e.text : e.msg;
  const scope = e.scope
    ? `<span class="log-scope${e.scope===APP_SCOPE ? " is-app" : ""}">[${escHtml(e.scope)}]</span> `
    : "";
  line.innerHTML =
    `<span class="log-ts">${escHtml(e.ts)}</span>`+
    `<span class="log-tag log-${level}">${LOG_TAG[level]||"INF"}</span>`+
    `<span class="log-msg">${scope}${escHtml(text)}</span>`;
  line.hiddenByFilter = !logLineVisible(line);
  line.classList.toggle("hidden", line.hiddenByFilter);
  body.appendChild(line);
  S.logTotal++;
  while(body.children.length>500) body.removeChild(body.firstChild);
  S.logCount = body.children.length;
  scheduleLogCount();
  if(atBottom) body.scrollTop = body.scrollHeight;
}
// Does this line pass the current search text and level filter?
function logLineVisible(line){
  const query = ($("log-search")?.value || "").trim().toLowerCase();
  if(query && !line.querySelector(".log-msg").textContent.toLowerCase().includes(query)) return false;
  const levels = LOG_LEVELS[S.logLevel];
  if(levels && !levels.includes(line.dataset.level || "info")) return false;
  return true;
}
// One pass over the lines, applying search + level together — the two filters
// must not undo each other (each used to write .hidden on its own).
function applyLogFilter(){
  $("log-body").querySelectorAll(".log-line").forEach(line=>{
    line.classList.toggle("hidden", !logLineVisible(line));
  });
  renderLogCount();
}
function filterLog(){ applyLogFilter(); }
function setLogLevel(level){
  S.logLevel = LOG_LEVELS[level] !== undefined ? level : "all";
  applyLogFilter();
}
function clearLog(){
  $("log-body").innerHTML = "";
  S.logCount = 0; S.logTotal = 0;
  renderLogCount();
}

// ── Log export / diagnostics notes ───────────────────────────────────────────
// Short-lived feedback under the log header (and in the Diagnostics card), so
// "Export" says where the file went instead of failing silently.
let _noteTimer = null;
function setLogNote(text, kind, autoClear){
  const el = $("log-note");
  if(el){
    el.className = "log-note" + (kind ? " " + kind : "");
    el.textContent = text || "";
  }
  if(_noteTimer){ clearTimeout(_noteTimer); _noteTimer = null; }
  if(text && autoClear) _noteTimer = setTimeout(()=>{ _noteTimer = null; setLogNote("", ""); }, 6000);
}
function setDiagNote(text, kind){
  const el = $("diag-status");
  if(el){ el.className = "diag-status" + (kind ? " " + kind : ""); el.textContent = text || ""; }
}
// Whether this build exposes a given bridge method — older Runners don't have
// diagnostics or log export, and a missing method must read as "not available"
// rather than throwing.
function hasApi(name){
  const a = window.pywebview && window.pywebview.api;
  return !!(a && typeof a[name] === "function");
}
async function onExportLog(){
  if(S.exporting) return;
  if(!hasApi("export_log")){
    setLogNote("Exporting the log isn't available in this build.", "warn");
    setDiagNote("Exporting the log isn't available in this build.", "warn");
    return;
  }
  S.exporting = true;
  const btns = ["btn-log-export","btn-diag-export"].map($).filter(Boolean);
  btns.forEach(b=>b.disabled = true);
  setLogNote("Saving the log…", "");
  let res = null;
  try{ res = await api().export_log(); }catch(e){ res = { ok:false, error:String(e) }; }
  S.exporting = false;
  btns.forEach(b=>b.disabled = false);
  // The backend opens a native save dialog: ok + path, cancelled, or an error.
  if(res && res.ok){
    const where = res.path ? ` to ${res.path}` : "";
    setLogNote(`Log saved${where}.`, "ok", true);
    setDiagNote(`Log saved${where}.`, "ok");
  } else if(res && res.cancelled){
    setLogNote("Export cancelled. Nothing was saved.", "", true);
    setDiagNote("Export cancelled. Nothing was saved.", "");
  } else {
    const why = (res && res.error) ? `: ${res.error}` : ".";
    setLogNote(`Couldn't save the log${why}`, "warn");
    setDiagNote(`Couldn't save the log${why}`, "warn");
  }
}
async function onOpenDataFolder(){
  if(!hasApi("open_data_folder")){
    setDiagNote("Opening the data folder isn't available in this build.", "warn");
    return;
  }
  let ok = false;
  try{ ok = await api().open_data_folder(); }catch(_){ }
  setDiagNote(ok ? "Opened the Runner's data folder." : "Couldn't open the data folder.", ok ? "ok" : "warn");
}

// ── Diagnostics ──────────────────────────────────────────────────────────────
// A read-only summary of the build, the loaded workflow, its files and the
// device — the questions a bug report always asks. Rendered generically, so a
// backend that reports more (or different) keys still shows up here.
let _diagDone = false;
function ensureDiagnostics(force){
  if(_diagDone && !force) return;
  if(!$("diag-list")) return;
  _diagDone = true;
  onDiagnostics(!!force);
}
function diagLabel(key){
  const s = String(key).replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "";
}
function diagRows(d){
  if(d == null) return [];
  if(typeof d === "string") return d.trim() ? [["Report", d]] : [];
  if(Array.isArray(d)) return d.filter(x=>x && x.label != null).map(x=>[String(x.label), String(x.value ?? "")]);
  const src = (d.items && typeof d.items === "object" && !Array.isArray(d.items)) ? d.items : d;
  const out = [];
  for(const [k, v] of Object.entries(src)){
    if(v == null || v === "") continue;
    if(Array.isArray(v)){
      if(!v.length || v.some(x=>x != null && typeof x === "object")) continue;
      out.push([diagLabel(k), v.join(", ")]);
    } else if(typeof v === "object"){
      continue;   // nested detail belongs to the exported log, not this list
    } else {
      out.push([diagLabel(k), String(v)]);
    }
  }
  return out;
}
async function onDiagnostics(force){
  const list = $("diag-list");
  if(!list) return;
  if(!hasApi("get_diagnostics")){
    list.innerHTML = "";
    setDiagNote("Diagnostics aren't available in this build. Export log… still works.", "warn");
    ["btn-diag-refresh","btn-diag-export","btn-diag-folder"].forEach(id=>{ const b = $(id); if(b) b.disabled = true; });
    return;
  }
  setDiagNote("Reading this Runner's details…", "");
  let d = null;
  try{ d = await api().get_diagnostics(); }catch(e){ d = { error:String(e) }; }
  S.diagnostics = d;
  const rows = diagRows(d);
  list.innerHTML = rows.map(([k,v])=>
    `<dt>${escHtml(k)}</dt><dd class="mono" title="${escHtml(v)}">${escHtml(v)}</dd>`).join("");
  const failed = !!(d && d.ok === false && d.error);
  if(failed) setDiagNote(`Couldn't read diagnostics: ${d.error}`, "warn");
  else if(!rows.length) setDiagNote("This build reported no diagnostics.", "");
  else setDiagNote(`Read from ${rows.length} source${rows.length === 1 ? "" : "s"}.`, "ok");
}

// ── Speedhack ────────────────────────────────────────────────────────────────
function applySpeedhack(info){
  if(!info) return;
  S.speedhack = Object.assign({enabled:false,speed:2.0,package:"",active:false}, info);
  $("speed-toggle").classList.toggle("on", !!S.speedhack.enabled);
  $("speed-toggle").setAttribute("aria-checked", String(!!S.speedhack.enabled));
  const rng = $("speed-range"); rng.value = S.speedhack.speed; rng.disabled = !S.speedhack.enabled;
  $("speed-val").textContent = (parseFloat(S.speedhack.speed)||1).toFixed(1)+"x";
  $("speed-pkg").textContent = S.speedhack.package ? ("→ "+S.speedhack.package) : "(workflow package / Launch app node)";
  const summary = $("runtime-summary");
  if(summary) summary.textContent = S.speedhack.enabled ? `${(parseFloat(S.speedhack.speed)||1).toFixed(1)}× enabled` : "Speed hack off";
}
async function onSpeedToggle(){
  const en = !S.speedhack.enabled;
  const speed = parseFloat($("speed-range").value)||2.0;
  applySpeedhack(await api().set_speedhack(en, speed, null));
}
function onSpeedInput(v){ $("speed-val").textContent = (parseFloat(v)||1).toFixed(1)+"x"; }
async function onSpeedCommit(v){
  const speed = parseFloat(v)||2.0;
  const info = S.running ? await api().set_speed_scale(speed)
                         : await api().set_speedhack(S.speedhack.enabled, speed, null);
  applySpeedhack(info);
}

// ── Controller footer (ADB device vs Win32 window) ───────────────────────────
function applyController(ctrl, win32){
  S.controller = (ctrl === "win32") ? "win32" : "adb";
  S.win32 = win32 || {};
  const isWin = S.controller === "win32";
  const adbRow = $("footer-adb");
  const winRow = $("footer-win32");
  if(adbRow) adbRow.style.display = isWin ? "none" : "";
  if(winRow) winRow.style.display = isWin ? "" : "none";

  // Speed hack and the shared Emulator setting are ADB-only; the Game card
  // (project game path) is Win32-only.
  const speedCard = $("speed-card");
  if(speedCard) speedCard.style.display = isWin ? "none" : "";
  const emuCard = $("emu-card");
  if(emuCard) emuCard.style.display = isWin ? "none" : "";
  const gameCard = $("game-card");
  if(gameCard) gameCard.style.display = isWin ? "" : "none";

  if(!isWin){ renderEmulator(S.emulator || {}); return; }
  const cfg = S.win32 || {};
  renderGamePath(cfg.path || "");
  const target = (cfg.window || "").trim();
  const el = $("win32-target");
  if(el){
    el.textContent = target || "(not configured)";
    el.classList.toggle("empty", !target);
    el.title = target;
  }
  const mode = (cfg.inputMode || "background").replace(/_/g, " ");
  const modeEl = $("win32-mode-lbl");
  if(modeEl){
    modeEl.textContent = mode;
    modeEl.style.display = target ? "" : "none";
    modeEl.title = "Input mode: " + mode;
  }
  const dot = $("win-dot");
  if(dot){
    dot.style.cssText = "width:8px;height:8px;border-radius:50%;flex-shrink:0;background:" +
      (target ? "var(--ok)" : "var(--muted)");
  }
  renderBridge();
}

// unity_bridge: the in-game plugin not answering is why "the window is there
// but nothing happens", so surface it in the footer instead of the log only.
function renderBridge(){
  const modeEl = $("win32-mode-lbl");
  if(!modeEl) return;
  const cfg = S.win32 || {};
  const mode = (cfg.inputMode || "background").replace(/_/g, " ");
  if(S.controller !== "win32" || (cfg.inputMode || "") !== "unity_bridge"){
    modeEl.textContent = mode; modeEl.style.color = ""; return;
  }
  const b = S.bridge;
  if(!b){ modeEl.textContent = mode; modeEl.style.color = ""; return; }
  const on = !!b.ok;
  modeEl.textContent = mode + (on ? " \u00b7 bridge OK" : " \u00b7 bridge OFF");
  modeEl.style.color = on ? "var(--ok)" : "var(--warn)";
  modeEl.title = on
    ? ("Unity Bridge online (127.0.0.1:" + b.port + ") \u2014 " + (b.reply || "ok"))
    : ("Unity Bridge kh\u00f4ng ph\u1ea3n h\u1ed3i \u1edf 127.0.0.1:" + b.port +
       ". Game ch\u01b0a n\u1ea1p BepInEx/Macro2kBridge (kh\u1edfi \u0111\u1ed9ng l\u1ea1i game " +
       "sau khi copy file game), ho\u1eb7c plugin l\u1ed7i \u2014 xem BepInEx\\\\LogOutput.log.");
}

// ── Project game path (Win32 Settings → Game) ─────────────────────────────────
// Used by Launch program blocks set to "Project game path"; blocks on "Custom"
// keep their own path control in the activity's inline settings.
function renderGamePath(path){
  S.win32 = Object.assign({}, S.win32, { path: path || "" });
  const inp = $("game-path");
  if(inp && document.activeElement !== inp){ inp.value = path || ""; inp.title = path || ""; }
  const note = $("game-path-note");
  if(note){
    const def = S.gamePathDefault || "";
    const st = S.gamePathStatus;
    note.textContent = !path
      ? "Required before this workflow can start."
      : (st && st.path === path && !st.exists)
        ? "Game not found. Choose the executable again."
      : (def && path !== def)
        ? "Custom path. Clear it to restore the workflow default."
        : "Workflow default";
  }
}
async function onGamePathChange(value){
  const old = (S.win32 || {}).path || "";
  let res = null;
  try{ res = await api().set_game_path(value); }catch(_){ }
  const inp = $("game-path");
  if(inp) inp.blur();
  if(res && res.ok) S.gamePathStatus = res.gamePath || S.gamePathStatus;
  renderGamePath(res && res.ok ? res.path : old);
  if(res && res.ok) renderRequirements(res.requirements);
}
async function onGamePathPick(){
  let res = null;
  try{ res = await api().pick_game_path(($("game-path")||{}).value || ""); }catch(_){ }
  if(res && res.ok){
    S.gamePathStatus = res.gamePath || S.gamePathStatus;
    renderGamePath(res.path); renderRequirements(res.requirements);
  }
  return !!(res && res.ok);
}

// ── Shared emulator setting (ADB Settings → Emulator) ────────────────────────
// Used by Launch / Resize / Kill / Restart emulator blocks set to "Project
// emulator setting"; a node on "Custom" keeps its own path control.
function renderEmulator(emu){
  S.emulator = Object.assign({kind:"ldplayer", path:""}, emu || {});
  const sel = $("emu-kind");
  if(sel && document.activeElement !== sel) sel.value = S.emulator.kind || "ldplayer";
  const inp = $("emu-path");
  if(inp && document.activeElement !== inp){ inp.value = S.emulator.path || ""; inp.title = S.emulator.path || ""; }
  const note = $("emu-note");
  if(note){
    const def = S.emulatorDefault || {};
    note.textContent = !S.emulator.path
      ? "Auto-detect"
      : (def.path && S.emulator.path !== def.path)
        ? "Custom folder"
        : "Workflow default";
  }
}
async function onEmulatorKindChange(value){
  const old = S.emulator || {};
  let res = null;
  try{ res = await api().set_emulator(value, old.path || ""); }catch(_){ }
  renderEmulator(res && res.ok ? res.emulator : old);
}
async function onEmulatorPathChange(value){
  const old = S.emulator || {};
  let res = null;
  try{ res = await api().set_emulator(old.kind || "ldplayer", value); }catch(_){ }
  renderEmulator(res && res.ok ? res.emulator : old);
}
async function onEmulatorPathPick(){
  const old = S.emulator || {};
  let res = null;
  try{ res = await api().pick_emulator_path(old.path || ""); }catch(_){ }
  if(res && res.ok) renderEmulator(res.emulator);
  return !!(res && res.ok);
}

// Ask for the game .exe up front — once per loaded game — instead of letting a
// run start and die at its Launch program block.
let _gamePromptFor = null;
async function promptGamePath(message){
  const choose = await uiDialog({
    title: "Choose the game path",
    message,
    buttons: [{ label:"Later", value:false }, { label:"Choose game .exe…", value:true, kind:"ok" }],
  });
  if(!choose) return false;
  await onGamePathPick();
  return !!(S.gamePathStatus && S.gamePathStatus.exists);
}
async function maybePromptGamePath(key){
  const st = S.gamePathStatus;
  if(S.controller !== "win32" || !st || !st.needed || st.exists) return;
  if(_gamePromptFor === key) return;
  _gamePromptFor = key;
  await promptGamePath(st.path
    ? `The game is not at the saved path any more:\n${st.path}\n\nChoose the game's .exe so the Runner can start it.`
    : "This game is started from its .exe. Choose the game's .exe once before the first run. The Runner remembers it.");
}
// Game files: when a game ships required files and they aren't in the game
// folder yet, offer to copy them — one prompt per loaded game, same idea as the
// game-path prompt. The copy raises a UAC prompt when the folder needs rights.
let _reqPromptFor = null;
async function maybePromptRequirements(key){
  const r = S.requirements;
  if(!r || !r.fileCount || r.installed || !r.gameDir || S.running) return;
  if(_reqPromptFor === key) return;
  _reqPromptFor = key;
  const go = await uiDialog({
    title: "Game files needed",
    message: `This game needs ${r.fileCount} file(s) inside its folder:\n${r.gameDir}\n\n`
           + `${r.missing} still missing. Copy them into the game folder now?`,
    buttons: [{ label:"Later", value:false }, { label:"Copy files…", value:true, kind:"ok" }],
  });
  if(go) await doReqCopy();
}
async function onLaunchBlocked(data){
  stopElapsedTimer(); S.runScope = null; updateProgress();
  if(data.gamePath){ S.gamePathStatus = data.gamePath; renderGamePath(data.gamePath.path || ""); }
  const text = "The run was not started:\n\n• " + (data.problems || []).join("\n• ");
  if(data.needsGamePath){ await promptGamePath(text); return; }
  await uiDialog({ title:"Program path missing", message: text, buttons:[{ label:"OK", value:true, kind:"ok" }] });
}

// ── Game files (requirements\ → the game's install folder) ───────────────────
function renderRequirements(req){
  S.requirements = (req && req.folder) ? req : null;
  const card = $("req-card");
  if(!card) return;
  card.style.display = S.requirements ? "" : "none";
  if(!S.requirements){ refreshButtons(); return; }
  const r = S.requirements, isWin = S.controller === "win32";
  const summary = $("req-summary");
  if(summary) summary.textContent = r.installed ? "Installed" : `${r.missing || r.fileCount} missing`;
  if(!r.installed) card.open = true;
  $("req-list").innerHTML = (r.items || []).map(n => `<li title="${escHtml(n)}">${escHtml(n)}</li>`).join("");
  const copy = $("btn-req-copy");
  if(copy) copy.style.display = isWin ? "" : "none";
  const st = $("req-status");
  const files = `${r.fileCount} file${r.fileCount === 1 ? "" : "s"}`;
  st.className = "req-status " + (r.installed ? "ok" : "warn");
  if(r.installed) st.textContent = "Files installed. Restart the game if it is open.";
  else if(!isWin) st.textContent = `Copy these ${files} into the game's install folder.`;
  else if(!r.gameDir) st.textContent = `Not installed. Set the Game path above, then copy these ${files} into the game folder.`;
  else st.textContent = `${r.missing} of ${files} missing in ${r.gameDir}. Copy them into the game folder.`;
  refreshButtons();
}
async function onReqOpen(){
  let ok = false;
  try{ ok = await api().open_requirements(); }catch(_){ }
  if(!ok) $("req-status").textContent = "Couldn't open the requirements folder.";
}
async function onReqCopy(){
  const r = S.requirements;
  if(!r || !r.gameDir || S.running) return;
  const msg = `Copy ${r.fileCount} file(s) into\n${r.gameDir}?\n\n`
            + `Existing files with the same name are overwritten. Close the game first.\n\n`
            + `If the folder needs it, Windows will ask for administrator rights.`;
  const go = await uiDialog({ title:"Copy game files", message:msg,
    buttons:[{ label:"Cancel", value:false }, { label:"Copy", value:true, kind:"ok" }] });
  if(!go) return;
  await doReqCopy();
}
// Perform the copy (no confirm) — shared by the button and the auto-prompt. The
// backend falls back to an elevated robocopy when the folder refuses the write.
async function doReqCopy(){
  const r = S.requirements;
  if(!r || !r.gameDir || S.running) return;
  const btn = $("btn-req-copy");
  const st = $("req-status");
  if(btn) btn.disabled = true;
  if(st){ st.className = "req-status warn"; st.textContent = "Copying game files…"; }
  let res = null;
  try{ res = await api().copy_requirements_to_game(); }catch(e){ res = { ok:false, error:String(e) }; }
  if(res && res.requirements) renderRequirements(res.requirements);
  else refreshButtons();
  if(res && !res.ok){ if(st){ st.className = "req-status warn"; st.textContent = res.error || "Copy failed."; } }
}

// ── Game icon ─────────────────────────────────────────────────────────────────
// Same initials + hue as the Hub (hub.js toneFor / initialsFor) when there is no
// icon image, so a game looks the same in every window.
const TONES = [214, 158, 256, 32, 346, 190];
function toneFor(key){ let h = 0; for(const ch of String(key||"")) h = (h*31 + ch.codePointAt(0)) >>> 0; return TONES[h % TONES.length]; }
function initialsFor(name){
  const words = String(name||"").replace(/([a-z])([A-Z0-9])/g, "$1 $2").split(/[\s_\-.]+/).filter(Boolean);
  if(!words.length) return "?";
  return words.length === 1 ? words[0].slice(0,2).toUpperCase() : (words[0][0] + words[1][0]).toUpperCase();
}
function renderAppIcon(data){
  const el = $("app-icon");
  if(!el) return;
  el.style.setProperty("--tone", toneFor(data.iconKey || data.name));
  const initials = () => { el.innerHTML = ""; el.classList.add("mono"); el.textContent = initialsFor(data.name); };
  if(data.icon){
    el.classList.remove("mono");
    el.innerHTML = "";
    const img = document.createElement("img");
    img.alt = ""; img.src = data.icon; img.onerror = initials;
    el.appendChild(img);
  } else {
    initials();
  }
  el.hidden = false;
}

// ── Flow ──────────────────────────────────────────────────────────────────────
function applyFlow(data){
  S.activities = data.activities || [];
  S.loaded = true;
  closeActivitySettings();
  const nm = $("flow-name");
  nm.textContent = data.name || "(unnamed)"; nm.classList.remove("empty");
  renderAppIcon(data);
  $("flow-sub").textContent = (data.controller === "win32" ? "Window" : "Android")
    + (U.version ? ` · v${U.version}` : "");
  populateLists();
  updateProgress();
  const seq = S.activities.filter(a=>a.type!=="background").length;
  const bg  = S.activities.filter(a=>a.type==="background").length;
  document.querySelector('[data-tab="seq"]').innerHTML = `Sequence <span class="tab-count">${seq}</span>`;
  document.querySelector('[data-tab="bg"]').innerHTML  = `Background <span class="tab-count">${bg}</span>`;
  if(data.speedhack) applySpeedhack(data.speedhack);
  if(data.captureBackend){
    S.captureBackend=data.captureBackend;
    const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
  }
  S.gamePathDefault = data.gamePathDefault || "";
  S.gamePathStatus = data.gamePath || null;
  S.emulator = data.emulator || {};
  S.emulatorDefault = data.emulatorDefault || {};
  applyController(data.controller, data.win32);
  renderRequirements(data.requirements);
  refreshButtons();
  // Ask for the game path first (requirements need it), then offer to copy the
  // game's required files if some are still missing.
  const promptKey = data.name || "";
  maybePromptGamePath(promptKey).then(()=>maybePromptRequirements(promptKey));
}

// ── Python events ────────────────────────────────────────────────────────────
window.__recv = function(raw){
  let ev; try{ ev=JSON.parse(raw); }catch{ return; }
  const { type, data } = ev;
  if(type==="log"){ appendLog(data); return; }
  if(type==="log_cleared"){ clearLog(); return; }
  if(type==="devices_update"){
    S.devices=data.devices||[]; S.connectedSerial=data.serial||null;
    setConnected(data.connected, data.name, data.serial); rebuildDevices(S.devices, data.serial);
    $("btn-refresh").classList.remove("spinning"); return;
  }
  if(type==="device_status"){
    S.connectedSerial=data.serial||null; setConnected(data.connected, data.name, data.serial);
    rebuildDevices(S.devices, data.serial); return;
  }
  if(type==="capture_backend"){
    S.captureBackend=data.backend||"scrcpy";
    const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
    return;
  }
  if(type==="flow_loaded"){ applyFlow(data); return; }
  if(type==="bridge_status"){ S.bridge=data; renderBridge(); return; }
  if(type==="launch_blocked"){ onLaunchBlocked(data); return; }
  if(type==="running_state"){
    const wasRunning = S.running;
    S.running=!!data.running; S.paused=!!data.paused;
    if(S.running){
      setOutcome("");   // a new run clears the previous run's result
      $('header-progress').style.display='flex'; if(!_elapsedTimer) startElapsedTimer();
    } else {
      stopElapsedTimer();
      // New backends name the outcome; older ones send none, so fall back to
      // what the activities' own statuses say happened.
      if("outcome" in data) setOutcome(data.outcome, data);
      else if(wasRunning) setOutcome(derivedOutcome(), data);
    }
    refreshButtons(); return;
  }
  if(type==="activity_update"){
    if(data.status==="pending"){ $('header-progress').style.display='flex'; }
    setActStatus(data.id, data.status); return;
  }
  if(type==="speedhack_update"){ applySpeedhack(data); return; }
  if(type==="update_available"){
    U.update=data; renderUpdate();
    maybePromptUpdate();
    return;
  }
  if(type==="update_progress"){ showUpdateProgress(data.pct, data.stage); return; }
};

// ── Changelog ────────────────────────────────────────────────────────────────
// Release notes are untrusted Markdown. Build DOM nodes only — never innerHTML.
const UCL = { history: [], pending: null, autoShowEnabled: true, shownVersion: "", shouldAutoShow: false, selected: "" };
let _autoChangelogFor = null;

function applyChangelog(data){
  data = data || {};
  UCL.history = (data.history || []).map(row => Object.assign({}, row));
  UCL.pending = data.pending ? Object.assign({}, data.pending) : null;
  UCL.autoShowEnabled = data.autoShowEnabled !== false;
  UCL.shownVersion = data.shownVersion || "";
  UCL.shouldAutoShow = !!data.shouldAutoShow;
  if(!UCL.history.some(row => row.version === UCL.selected)) UCL.selected = UCL.history.length ? UCL.history[0].version : "";
  const box = $("changelog-auto-show");
  if(box) box.checked = UCL.autoShowEnabled;
  const dot = $("notes-dot");
  if(dot) dot.hidden = !(UCL.pending && UCL.shouldAutoShow);
  renderChangelog();
}

function renderMarkdown(host, markdown){
  host.textContent = "";
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  let list = null, listKind = "", quote = null, code = null, para = [];
  const flushPara = () => {
    if(!para.length) return;
    const p = document.createElement("p");
    appendInline(p, para.join(" "));
    host.appendChild(p);
    para = [];
  };
  const closeBlocks = () => { flushPara(); list = null; quote = null; };
  lines.forEach(line => {
    if(code){
      if(line.trim().startsWith("```")){ host.appendChild(code); code = null; }
      else code.appendChild(document.createTextNode(line + "\n"));
      return;
    }
    if(line.trim().startsWith("```")){ closeBlocks(); code = document.createElement("pre"); const c = document.createElement("code"); code.appendChild(c); return; }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if(heading){ closeBlocks(); const h = document.createElement("h" + (heading[1].length + 2)); appendInline(h, heading[2]); host.appendChild(h); return; }
    const item = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(line);
    if(item){
      flushPara(); quote = null;
      const kind = item[2] === "-" || item[2] === "*" ? "ul" : "ol";
      if(!list || listKind !== kind){ list = document.createElement(kind); listKind = kind; host.appendChild(list); }
      const li = document.createElement("li"); appendInline(li, item[3]); list.appendChild(li); return;
    }
    if(line.startsWith(">")){ flushPara(); list = null; if(!quote){ quote = document.createElement("blockquote"); host.appendChild(quote); } appendInline(quote, line.replace(/^>\s?/, "")); quote.appendChild(document.createElement("br")); return; }
    if(!line.trim()){ closeBlocks(); return; }
    list = null; quote = null; para.push(line.trim());
  });
  closeBlocks();
  if(code) host.appendChild(code);
}

function appendInline(parent, text){
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https:\/\/[^)\s]+\))/g;
  let last = 0, match;
  const src = String(text || "");
  while((match = re.exec(src))){
    if(match.index > last) parent.appendChild(document.createTextNode(src.slice(last, match.index)));
    if(match[1]){ const code = document.createElement("code"); code.textContent = match[1].slice(1, -1); parent.appendChild(code); }
    else if(match[2]){ const strong = document.createElement("strong"); strong.textContent = match[2].slice(2, -2); parent.appendChild(strong); }
    else if(match[3]){
      const labeled = /^\[([^\]]+)\]\((https:\/\/[^)\s]+)\)$/.exec(match[3]);
      const a = document.createElement("a");
      a.href = labeled[2]; a.textContent = labeled[1]; a.rel = "noopener noreferrer";
      a.addEventListener("click", (e) => { e.preventDefault(); api().open_external_url(labeled[2]); });
      parent.appendChild(a);
    }
    last = match.index + match[0].length;
  }
  if(last < src.length) parent.appendChild(document.createTextNode(src.slice(last)));
}

function appendChangelog(parent, markdown, title){
  if(!String(markdown || "").trim()) return;
  const wrap = document.createElement("div"); wrap.className = "changelog-md";
  if(title){ const h = document.createElement("h3"); h.textContent = title; wrap.appendChild(h); }
  renderMarkdown(wrap, markdown);
  parent.appendChild(wrap);
}

function renderChangelog(){
  const list = $("changelog-list"), body = $("changelog-body"), empty = $("changelog-empty");
  const title = $("changelog-title"), date = $("changelog-date"), link = $("btn-changelog-release");
  if(!list || !body) return;
  list.textContent = "";
  const head = $("changelog-body-hd");
  if(!UCL.history.length){
    if(empty) empty.hidden = false;
    body.hidden = true;
    if(head) head.hidden = true;
    if(title) title.textContent = "";
    if(date) date.textContent = "";
    if(link) link.hidden = true;
    return;
  }
  if(empty) empty.hidden = true;
  body.hidden = false;
  if(head) head.hidden = false;
  UCL.history.forEach(row => {
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "changelog-ver"; btn.textContent = "v" + row.version;
    btn.setAttribute("aria-current", row.version === UCL.selected ? "true" : "false");
    btn.onclick = () => { UCL.selected = row.version; renderChangelog(); };
    list.appendChild(btn);
  });
  const row = UCL.history.find(item => item.version === UCL.selected) || UCL.history[0];
  if(title) title.textContent = "v" + row.version;
  if(date) date.textContent = row.publishedAt ? String(row.publishedAt).slice(0, 10) : "";
  body.textContent = "";
  renderMarkdown(body, row.markdown || "No notes for this version.");
  if(link){
    link.hidden = !row.page;
    link.onclick = () => { if(row.page) api().open_external_url(row.page); };
  }
}

async function onChangelogRefresh(){
  try{ applyChangelog(await api().changelog_refresh()); }catch(e){}
}
async function onChangelogAutoShow(checked){
  try{ applyChangelog(await api().set_changelog_auto_show(!!checked)); }catch(e){}
}
async function maybeShowPendingChangelog(){
  if(!UCL.shouldAutoShow || !UCL.pending) return;
  const version = String(UCL.pending.version || "");
  if(!version || _autoChangelogFor === version) return;
  _autoChangelogFor = version;
  await uiDialog({
    title: "What's new in v" + version,
    body(bd){ appendChangelog(bd, UCL.pending.markdown, ""); },
    buttons: [{ label:"Close", value:true, kind:"ok" }],
  });
  try{ applyChangelog(await api().acknowledge_changelog(version)); }catch(e){}
}

// ── Version + self-update ────────────────────────────────────────────────────
function applyRunnerInfo(r){
  r = r || {};
  U.supported = !!r.supported; U.version = r.version || ""; U.repo = r.repo || "";
  if(r.update && Object.keys(r.update).length) U.update = r.update;
  $("upd-version").textContent = U.version ? `v${U.version}` : "Not a standalone build";
  $("upd-repo").textContent = U.repo || "-";
  $("upd-repo").title = U.repo ? `https://github.com/${U.repo}` : "";
  applyChangelog(r.changelog || {});
  renderUpdate();
}
function renderUpdate(){
  const pill = $("update-pill"), check = $("btn-upd-check"), apply = $("btn-upd-apply"), status = $("upd-status");
  if(!pill) return;
  const up = U.update;
  const available = !!(up && up.available);
  const summary = $("updates-summary");
  if(summary) summary.textContent = available ? `v${up.version} available`
    : U.checking ? "Checking"
    : (up && up.supported) ? "Up to date"
    : (U.supported ? "Automatic" : "Build only");
  const section = $("updates-section");
  if(section && available) section.open = true;
  pill.hidden = !available || U.applying;
  if(available) pill.textContent = `Update v${up.version}`;
  check.disabled = !U.supported || U.checking || U.applying;
  apply.hidden = !available;
  apply.disabled = U.applying || S.running;
  if(available) apply.textContent = `Update to v${up.version} & restart`;
  if(U.applying) return;   // progress text owns the status line
  if(!U.supported) status.textContent = "Updates are available in a Runner built from the Macro2k Hub.";
  else if(U.checking) status.textContent = "Checking GitHub for a newer version…";
  else if(up && up.error) status.textContent = `Couldn't check for updates: ${up.error}`;
  else if(available) status.textContent = S.running ? `v${up.version} is ready. Stop the run to update.` : `v${up.version} is ready to install.`;
  else if(up && up.supported) status.textContent = "You're on the latest version.";
  else status.textContent = "Checks for a newer version when the Runner opens.";
}
function showUpdates(){
  openHeaderPop("settings");
  const section = $("updates-section"); if(section) section.open = true;
  const card = section || $("updates-card");
  if(card) card.scrollIntoView({ block:"nearest", behavior:"smooth" });
  const apply = $("btn-upd-apply");
  if(apply && !apply.hidden && !apply.disabled) apply.focus();
}
function focusUpdateProgress(){
  openHeaderPop("settings");
  const section = $("updates-section"); if(section) section.open = true;
  const card = section || $("updates-card");
  if(card) card.scrollIntoView({ block:"nearest", behavior:"smooth" });
  const bar = $("upd-bar");
  if(bar) bar.hidden = false;
  const status = $("upd-status");
  if(status) status.textContent = "Preparing update…";
}
let _updatePromptFor = null;
async function maybePromptUpdate(){
  const up = U.update;
  if(!up || !up.available || U.applying || S.running) return;
  const key = String(up.version || "");
  if(!key || _updatePromptFor === key) return;
  _updatePromptFor = key;
  const install = await uiDialog({
    title: "Runner update available",
    message: `Version v${key} is available. You are using v${U.version || "?"}.\n\nUpdate replaces the files in this Runner folder, keeps your data and settings, then restarts the Runner.`,
    body(bd){ appendChangelog(bd, up.markdown, "What's new"); },
    buttons: [
      { label:"Later", value:false },
      { label:"Update & restart", value:true, kind:"ok" },
    ],
  });
  if(install) await onUpdateApply();
}
async function onUpdateCheck(){
  if(!U.supported || U.checking) return;
  U.checking = true; renderUpdate();
  try{ U.update = await api().update_check(); }catch(e){ U.update = { error: String(e) }; }
  if(U.update && U.update.changelog) applyChangelog(U.update.changelog);
  U.checking = false; renderUpdate();
  await maybePromptUpdate();
}
function showUpdateProgress(pct, stage){
  const bar = $("upd-bar"), fill = $("upd-bar-fill");
  bar.hidden = false;
  bar.classList.toggle("indet", pct < 0);
  if(pct >= 0) fill.style.transform = `scaleX(${Math.min(100, pct)/100})`;
  $("upd-status").textContent = stage === "Downloading" && pct >= 0 ? `Downloading… ${pct}%` : `${stage}…`;
}
async function onUpdateApply(){
  if(U.applying || S.running || !(U.update && U.update.available)) return;
  focusUpdateProgress();
  U.applying = true; renderUpdate();
  showUpdateProgress(0, "Downloading");
  let res = null;
  try{ res = await api().update_apply(); }catch(e){ res = { error: String(e) }; }
  // Only returns when nothing was installed (success restarts the Runner).
  U.applying = false;
  $("upd-bar").hidden = true;
  if(res && res.upToDate) U.update = Object.assign({}, U.update, { available:false });
  renderUpdate();
  if(res && res.error) $("upd-status").textContent = `Update failed: ${res.error}`;
}

// ── Handlers ───────────────────────────────────────────────────────────────
const api = () => window.pywebview.api;
async function onStart(){
  if(!S.loaded || S.running) return;
  S.runScope = null;
  setOutcome("");   // the previous run's result no longer applies
  S.activities.filter(a=>a.type!=="background").forEach(a=>setActStatus(a.id,"pending"));
  $('header-progress').style.display='flex'; startElapsedTimer(); updateProgress();
  let ok = false;
  try{ ok = await api().start(); }catch(_){ }
  if(!ok){ stopElapsedTimer(); updateProgress(); }   // e.g. blocked by a missing game path
}
// Which single activity is running on its own, if any.
function soloRunningId(){
  return (S.running && S.runScope && S.runScope.length === 1) ? S.runScope[0] : null;
}
// The row button mirrors state: Run normally; Stop while this activity is the
// one running solo, so it stops the run right where it started.
function updateRowRunButtons(){
  const solo = soloRunningId();
  document.querySelectorAll(".btn-run-one").forEach(btn=>{
    const id = btn.dataset.runOne;
    const a = S.activities.find(x=>x.id===id);
    const isThisRunning = !!id && id === solo;
    const blocked = S.running && !isThisRunning;
    btn.classList.toggle("is-stop", isThisRunning);
    btn.disabled = !S.loaded || blocked;
    if(isThisRunning){
      btn.innerHTML = STOP_SM;
      btn.title = "Stop this activity";
      btn.setAttribute("aria-label", `Stop ${a ? a.name : ""}`.trim());
    } else {
      btn.innerHTML = PLAY_SM;
      btn.title = (a && a.type==="background") ? "Run only this activity (loops until Stop)" : "Run only this activity";
      btn.setAttribute("aria-label", `Run only ${a ? a.name : ""}`.trim());
    }
  });
}
async function onRunToggle(id){
  if(soloRunningId() === id){ await onStop(); return; }
  await onRunActivity(id);
}
async function onRunActivity(id){
  if(!S.loaded || S.running || S.exporting) return;
  if(!S.activities.some(a=>a.id===id)) return;
  S.runScope = [id];
  setOutcome("");
  setActStatus(id, "pending");
  $('header-progress').style.display='flex'; startElapsedTimer(); updateProgress();
  let ok = false;
  try{ ok = await api().run_activity(id); }catch(_){ }
  if(!ok){ stopElapsedTimer(); S.runScope = null; updateProgress(); }
}
async function onStop(){ await api().stop(); }
async function onPause(){ const r=await api().pause(); S.paused=!!(r&&r.paused); refreshButtons(); }

// ── Keyboard ─────────────────────────────────────────────────────────────────
// Deliberately no single-key shortcut: a stray keypress must never start a
// macro. Start is F5 (or Ctrl+Enter, which the OS does not claim first) and
// pause is F6 — both are keyed on the function keys an operator already reaches
// for, and both are ignored while a dialog or a text field has focus.
function isTypingTarget(el){
  if(!el) return false;
  if(el.isContentEditable) return true;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
}
function onGlobalKey(e){
  if(document.querySelector(".ui-modal-wrap")) return;   // a dialog owns the keyboard
  if(e.ctrlKey && e.key === "Enter" && !e.altKey && !e.shiftKey){
    e.preventDefault();
    if(S.running) onStop(); else onStart();
    return;
  }
  if(e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
  if(isTypingTarget(document.activeElement)) return;
  if(e.key === "F5"){
    // Start only, never a stop: F5 is the key people jab out of habit, and a run
    // half an hour in must not die to a reflex. Stopping stays a deliberate act
    // (the button, or Ctrl+Enter to toggle).
    e.preventDefault();
    if(!S.running) onStart();
  } else if(e.key === "F6"){
    e.preventDefault();
    if(S.running) onPause();
  }
}
async function onClearLog(){ await api().clear_log(); }
async function onDeviceChange(serial){ if(serial){ S.connectedSerial=serial; await api().select_device(serial); } }
async function onCaptureBackendChange(backend){
  const r=await api().set_capture_backend(backend);
  S.captureBackend=(r&&r.backend)||backend;
  const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
}
async function onRefresh(){ $("btn-refresh").classList.add("spinning"); await api().refresh_devices(); }

function selectAll(type, enabled){
  S.activities.filter(a=> type==="sequence" ? a.type!=="background" : a.type==="background").forEach(a=>{
    a.enabled = enabled;
    const row = document.querySelector(`.task-row[data-id="${a.id}"]`);
    if(row){
      const cb = row.querySelector(".cb");
      cb.classList.toggle("checked", enabled); cb.setAttribute("aria-pressed", String(enabled));
      paintRow(a, row);
    }
    api().toggle_activity(a.id, enabled);
  });
  updateListSummary(); updateProgress();
}

// ── Live preview ─────────────────────────────────────────────────────────────
// Python pushes JPEG frames to window.__recvFrame while the panel is open; the
// frame source is the same capture backend a run uses, so the preview is what
// the macro sees. Hide stops the capture loop; maximize lets it fill the pane.
// Preview is opt-in: keeping it off avoids a capture thread and frame buffers
// consuming memory while the Runner is used only as an activity monitor.
let pvActive = false;   // body shown (not collapsed)
let pvMaxed  = false;   // expanded over the right pane

function pvApply(){
  const card=$("preview-card");
  if(card) card.classList.toggle("is-max", pvMaxed);
  const body=$("pv-body");
  if(body) body.style.display = pvActive ? "" : "none";
  const hid=$("pv-hide"); if(hid){ hid.title = pvActive ? "Hide preview" : "Show preview"; hid.classList.toggle("off", !pvActive); }
  const max=$("pv-max");
  if(max){
    max.title = pvMaxed ? "Restore preview" : "Maximize preview";
    max.setAttribute("aria-label", max.title);
    max.innerHTML = uiIco(pvMaxed ? "minimize" : "maximize", "uico-2");
  }
  try{ api().set_refresh_hz(pvMaxed ? 10 : 6); api().set_auto_refresh(pvActive); }catch(_){ }
  if(pvActive){ try{ api().capture(); }catch(_){ } }
}
function togglePreviewMax(){ pvMaxed=!pvMaxed; if(pvMaxed) pvActive=true; pvApply(); }
function togglePreviewHide(){ pvActive=!pvActive; if(pvActive) pvMaxed=false; pvApply(); }
// Escape leaves the maximized preview — the same gesture the shared panel
// chrome uses, and the only way back that does not require finding the button.
function onPreviewKey(e){
  if(e.key !== "Escape" || !pvMaxed) return;
  const t = e.target;
  if(t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
  e.preventDefault();
  pvMaxed = false;
  pvApply();
  const btn = $("pv-max"); if(btn) btn.focus();
}
window.__recvFrame = function(dataUrl,w,h){
  const img=$("pv-img"), empty=$("pv-empty");
  if(!img) return;
  img.src = dataUrl;
  if(empty) empty.style.display="none";
  const st=$("pv-state"); if(st && w && h) st.textContent = w+"×"+h;
};

// ── Header theme switch ───────────────────────────────────────────────────────
function syncThemeToggle(){
  const dark = window.uiTheme?.current().theme === "dark";
  const button = $("theme-toggle");
  const label = dark ? "Switch to light theme" : "Switch to dark theme";
  button.innerHTML = uiIco(dark ? "sun" : "moon", "uico-2");
  button.title = label;
  button.setAttribute("aria-label", label);
}

function placeHeaderPop(pop, anchor){
  const rect = anchor.getBoundingClientRect();
  const width = Math.min(440, window.innerWidth - 16);
  pop.style.width = width + "px";
  let left = rect.right - width;
  left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
  pop.style.left = left + "px";
  pop.style.top = (rect.bottom + 6) + "px";
}
function closeHeaderPops(except){
  ["notes", "settings"].forEach(name=>{
    if(name===except) return;
    const pop = $(name+"-pop"), btn = $(name+"-toggle");
    if(pop) pop.hidden = true;
    if(btn) btn.setAttribute("aria-expanded", "false");
  });
}
function openHeaderPop(name){
  const pop = $(name+"-pop"), btn = $(name+"-toggle");
  if(!pop || !btn) return;
  const open = pop.hidden;
  closeHeaderPops();
  if(!open) return;
  if(name==="settings"){
    mountRunnerSettings();
    if(_runnerSettingsRoot) pop.appendChild(_runnerSettingsRoot);
    ensureDiagnostics();
  }
  if(name==="notes") renderChangelog();
  pop.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  placeHeaderPop(pop, btn);
}
let _runnerSettingsRoot = null;
function mountRunnerSettings(){
  const src = $("runner-settings-src");
  if(!_runnerSettingsRoot){
    const fragment = src && src.content.cloneNode(true);
    _runnerSettingsRoot = fragment && fragment.firstElementChild;
  }
  syncRunnerSettingsHost();
}
function syncRunnerSettingsHost(){
  if(!_runnerSettingsRoot) return;
  const narrow = window.matchMedia && window.matchMedia("(max-width: 640px)").matches;
  const host = narrow && S.mobileView === "settings" ? $("mobile-settings") : $("settings-pop");
  if(host && _runnerSettingsRoot.parentElement !== host) host.appendChild(_runnerSettingsRoot);
}
function wireHeaderPops(){
  mountRunnerSettings();
  $("notes-toggle").onclick = ()=>openHeaderPop("notes");
  $("settings-toggle").onclick = ()=>openHeaderPop("settings");
  document.addEventListener("mousedown", e=>{
    if(e.target.closest(".header-pop, .header-tools, #update-pill")) return;
    closeHeaderPops();
  });
  document.addEventListener("keydown", e=>{
    if(e.key==="Escape") closeHeaderPops();
  });
  window.addEventListener("resize", ()=>{
    syncRunnerSettingsHost();
    ["notes", "settings"].forEach(name=>{
      const pop = $(name+"-pop"), btn = $(name+"-toggle");
      if(pop && !pop.hidden && btn) placeHeaderPop(pop, btn);
    });
  });
}
function wireThemeToggle(){
  $("theme-toggle").onclick = () => window.uiTheme?.toggle();
  window.addEventListener("m2k-theme", syncThemeToggle);
  syncThemeToggle();
  wireHeaderPops();
}

// ── Init ───────────────────────────────────────────────────────────────────
async function init(){
  wireThemeToggle();
  switchMobileView("activities", false);
  wireTabNav("mobile-tabs", "mobileView", switchMobileView);
  document.addEventListener("keydown", onGlobalKey, true);
  setupListDnD($("seq-list"));
  setupListDnD($("bg-list"));
  let tries=0;
  while(!(window.pywebview&&window.pywebview.api)&&tries<40){ await new Promise(r=>setTimeout(r,100)); tries++; }
  if(!window.pywebview||!window.pywebview.api){ $("dev-label").textContent="PyWebView unavailable"; return; }
  const st = await api().get_state();
  applyRunnerInfo(st.runner);
  await maybeShowPendingChangelog();
  await maybePromptUpdate();
  S.connectedSerial = st.connectedSerial||null;
  S.captureBackend = st.captureBackend||"scrcpy";
  const capSel=$("capture-backend");
  if(capSel){
    capSel.innerHTML="";
    (st.captureBackends||["scrcpy","adb"]).forEach(b=>{ const o=document.createElement("option"); o.value=b; o.textContent=b==="adb"?"ADB":"scrcpy"; capSel.appendChild(o); });
    capSel.value=S.captureBackend;
  }
  if(st.loaded) applyFlow({name:st.name, activities:st.activities, speedhack:st.speedhack,
                           captureBackend:st.captureBackend, controller:st.controller, win32:st.win32,
                           gamePathDefault:st.gamePathDefault, requirements:st.requirements, gamePath:st.gamePath,
                           emulator:st.emulator, emulatorDefault:st.emulatorDefault,
                           icon:st.icon, iconKey:st.iconKey});
  else applyController(st.controller, st.win32);
  S.running=!!st.running; S.paused=!!st.paused;
  refreshButtons();
  (st.log||[]).forEach(appendLog);
  pvApply();
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
