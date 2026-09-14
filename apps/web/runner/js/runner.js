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
  emulator:        {},   // shared ADB emulator setting {kind, path}
  emulatorDefault: {},   // as shipped by the workflow (what "clear" falls back to)
  logCount:        0,
  speedhack: { enabled:false, speed:2.0, package:"", active:false },
  runScope:        null,   // activity ids of a single-activity run; null = full Start
};

// This Runner's own version + self-update state (standalone builds only).
const U = { supported:false, version:"", repo:"", update:null, checking:false, applying:false };

const $ = id => document.getElementById(id);
const ACT_DOT_TITLE = { pending:"Pending", running:"Running", completed:"Completed", failed:"Failed", skipped:"Skipped", active:"Active" };
// Status word on an activity's second line (pending shows "Waiting" only mid-run).
const ACT_ST_LABEL = { running:"Running", completed:"Done", failed:"Failed", skipped:"Skipped" };
const LOG_TAG = { info:"INF", success:"OK ", warning:"WRN", error:"ERR" };
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
function uiDialog(spec){
  return new Promise(resolve=>{
    const wrap = document.createElement("div"); wrap.className = "ui-modal-wrap";
    const box = document.createElement("div"); box.className = "ui-modal";
    box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
    if(spec.title){
      const hd = document.createElement("div"); hd.className = "ui-modal-hd"; hd.textContent = spec.title;
      box.appendChild(hd); box.setAttribute("aria-label", spec.title);
    }
    const bd = document.createElement("div"); bd.className = "ui-modal-bd";
    const msg = document.createElement("p"); msg.className = "ui-modal-msg"; msg.textContent = spec.message || "";
    bd.appendChild(msg); box.appendChild(bd);
    const ft = document.createElement("div"); ft.className = "ui-modal-ft";
    let primary = null;
    const onKey = e=>{ if(e.key === "Escape"){ e.preventDefault(); close(undefined); } };
    const close = v=>{ document.removeEventListener("keydown", onKey, true); wrap.remove(); resolve(v); };
    (spec.buttons || [{ label:"OK", value:true, kind:"ok" }]).forEach(b=>{
      const btn = document.createElement("button"); btn.type = "button";
      btn.className = "btn" + (b.kind ? " " + b.kind : ""); btn.textContent = b.label;
      btn.onclick = ()=>close(b.value);
      if(b.kind) primary = btn;
      ft.appendChild(btn);
    });
    box.appendChild(ft); wrap.appendChild(box);
    wrap.addEventListener("mousedown", e=>{ if(e.target === wrap) close(undefined); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    (primary || ft.lastChild).focus();
  });
}

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
  if(_elapsedTimer){ clearInterval(_elapsedTimer); _elapsedTimer=null; }
}
function updateProgress(){
  // A full Start only runs the enabled sequence activities — counting disabled
  // ones too left the bar stuck short of 100% on every run.
  const seq = S.runScope
    ? S.activities.filter(a=>S.runScope.includes(a.id))
    : S.activities.filter(a=>a.type!=="background" && a.enabled);
  const done = seq.filter(a=>["completed","failed","skipped"].includes(a.status)).length;
  const total = seq.length;
  $('prog-count').textContent = `${done}/${total}`;
  $('prog-bar').style.transform = `scaleX(${total ? done/total : 0})`;
}

// ── Status pill ──────────────────────────────────────────────────────────────
function setStatusPill(key){
  const pill = $("status-pill"); pill.className = "";
  if(key==="running"){ pill.classList.add("status-running"); $("status-text").textContent="RUNNING"; }
  else if(key==="paused"){ pill.classList.add("status-paused"); $("status-text").textContent="PAUSED"; }
  else if(key==="stopped"){ pill.classList.add("status-stopped"); $("status-text").textContent="STOPPED"; }
  else { pill.classList.add("status-ready"); $("status-text").textContent="READY"; }
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
  document.querySelectorAll(".runtime-setting-control").forEach(el=>el.disabled=running);
  const reqCopy = $("btn-req-copy");
  if(reqCopy) reqCopy.disabled = running || !(S.requirements && S.requirements.gameDir);
  updateRowRunButtons();
  $("app").classList.toggle("is-running", running);
  S.activities.forEach(a=>paintRow(a));   // "Waiting" / "Active" follow the run state
  renderUpdate();
  setStatusPill(running ? (paused ? "paused" : "running") : "ready");
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab){
  document.querySelectorAll(".tab-btn").forEach(b=>{ const on=b.dataset.tab===tab; b.classList.toggle("active",on); b.setAttribute("aria-selected",String(on)); });
  document.querySelectorAll(".tab-pane").forEach(p=>p.classList.toggle("active", p.id==="tab-"+tab));
}
// Right column: Activity settings | Log | Settings.
function switchRTab(tab){
  document.querySelectorAll("#r-tabs .rtab").forEach(b=>{ const on=b.dataset.rtab===tab; b.classList.toggle("active",on); b.setAttribute("aria-selected",String(on)); });
  document.querySelectorAll("#r-content .rpane").forEach(p=>p.classList.toggle("active", p.id==="r-"+tab));
  // Lines that arrived while the pane was hidden couldn't scroll it — jump to the newest.
  if(tab==="log"){ const body = $("log-body"); body.scrollTop = body.scrollHeight; }
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
  const st = isBg ? (inRun ? "active" : "pending") : (a.status || "pending");
  const dot = row.querySelector("[data-dot]");
  if(dot){
    dot.className = "act-dot act-dot-" + st;
    dot.title = ACT_DOT_TITLE[st] || ACT_DOT_TITLE.pending;
    dot.setAttribute("aria-label", `Status: ${dot.title}`);
  }
  row.classList.toggle("task-running", st==="running");
  row.classList.toggle("task-failed", st==="failed");
  row.classList.toggle("task-off", !a.enabled);
  const meta = row.querySelector("[data-meta]");
  if(meta) renderMeta(meta, a, st, inRun);
}

// Second line under the activity name: status word, then its settings summary.
function renderMeta(el, a, st, inRun){
  const parts = [];
  if(a.type==="background"){
    if(st==="active") parts.push('<span class="act-st st-active">Active</span>');
    parts.push(`Every ${Number(a.pollInterval)||1}s`);
  } else {
    if(st==="pending"){ if(inRun) parts.push('<span class="act-st st-waiting">Waiting</span>'); }
    else if(ACT_ST_LABEL[st]) parts.push(`<span class="act-st st-${st}">${ACT_ST_LABEL[st]}</span>`);
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
    const g = group("Timing");
    const row = document.createElement("div"); row.className = "setting-row";
    const lbl = document.createElement("span"); lbl.className = "setting-label"; lbl.textContent = "Repeat every";
    const inp = document.createElement("input");
    inp.type = "number"; inp.className = "setting-input";
    inp.setAttribute("aria-label", "Background interval in seconds");
    inp.min = 0.05; inp.step = 0.5; inp.value = a.pollInterval;
    inp.onchange = ()=>{
      const v = Math.max(0.05, parseFloat(inp.value)||a.pollInterval);
      inp.value = v; a.pollInterval = v; api().set_interval(a.id, v);
      paintRow(a);
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
        let ok = false; try{ ok = await api().set_node_runtime_param(setting.nodeId,setting.param,value); }catch(_){ }
        if(ok){ syncRuntimeSetting(setting.nodeId,setting.param,value); inp.title = value; }
        else inp.value = old;
      };
      const pick = document.createElement("button"); pick.type = "button";
      pick.className = "btn-path-pick runtime-setting-control"; pick.textContent = "Choose…";
      pick.title = setting.kind==="folder"?"Choose folder":"Choose program file"; pick.disabled = !!S.running;
      pick.onclick = async()=>{
        let value = "";
        try{ value = await api().pick_node_runtime_path(setting.nodeId,setting.param,setting.kind,inp.value); }catch(_){ }
        if(value){ inp.value = value; inp.title = value; syncRuntimeSetting(setting.nodeId,setting.param,value); }
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
    const g = group();
    vars.forEach(v=>{
      const row = document.createElement("div"); row.className = "setting-row";
      const lbl = document.createElement("span"); lbl.className = "setting-label";
      lbl.textContent = v.label || v.name;
      row.appendChild(lbl);

      const type = v.type || "bool";
      if(type==="bool"){
        const cb = document.createElement("button"); cb.type = "button"; cb.className = "cb"+(v.value?" checked":""); cb.innerHTML = CHECK;
        cb.setAttribute("aria-label", v.label||v.name); cb.setAttribute("aria-pressed",String(!!v.value));
        cb.onclick = ()=>{ v.value=!v.value; cb.classList.toggle("checked",v.value); cb.setAttribute("aria-pressed",String(!!v.value)); api().set_activity_var(a.id,v.name,v.value); };
        row.appendChild(cb);
      } else if(type==="select"){
        const sel = document.createElement("select");
        (v.options||[]).forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; if(String(v.value)===String(o))op.selected=true; sel.appendChild(op); });
        sel.onchange = ()=>{ v.value=sel.value; api().set_activity_var(a.id,v.name,sel.value); };
        row.appendChild(sel);
      } else {
        const inp = document.createElement("input");
        inp.type = type==="number" ? "number" : "text"; inp.className = "setting-input";
        inp.value = (v.value!=null ? v.value : "");
        inp.onchange = ()=>{ const val = type==="number" ? (parseFloat(inp.value)||0) : inp.value; v.value=val; api().set_activity_var(a.id,v.name,val); };
        row.appendChild(inp);
      }
      g.appendChild(row);
    });
    panel.appendChild(g);
  }

  // Retry count — a RUNNER setting (saved to this Runner's config, never to the
  // workflow). Default 1; an activity is tried this many times before failing.
  // Always last, after the activity's own config.
  {
    const g = group();
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
      let res = null; try{ res = await api().set_activity_retries(a.id, v); }catch(_){ }
      if(res && res.ok) v = res.retries; else v = a.maxRetries || 1;
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
function closeActivitySettings(){
  S.expandedId = null;
  document.querySelectorAll(".btn-gear.active").forEach(g=>g.classList.remove("active"));
  const title = $("act-set-title"); if(title) title.textContent = "Activity settings";
  showSettingsEmpty();
}
function toggleSettings(id){
  const a = S.activities.find(x=>x.id===id); if(!a) return;
  const host = $("act-set-body");
  if(!host) return;
  if(S.expandedId === id){ closeActivitySettings(); return; }
  document.querySelectorAll(".btn-gear.active").forEach(g=>g.classList.remove("active"));
  const gear = document.querySelector(`.task-row[data-id="${id}"] [data-gear]`);
  if(gear) gear.classList.add("active");
  S.expandedId = id;
  host.innerHTML = "";
  host.appendChild(buildSettingsPanel(a));
  const title = $("act-set-title"); if(title) title.textContent = a.name || "Activity settings";
  switchRTab("act");
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
  if(gear) gear.classList.add("active"); else closeActivitySettings();
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
function updateLogCount(){
  const n = S.logCount ? String(S.logCount) : "";
  const el = $("log-count"); if(el) el.textContent = n;
  const tab = $("rtab-log-count"); if(tab) tab.textContent = n;
}
function appendLog(e){
  const body = $("log-body");
  const query = $("log-search").value.trim().toLowerCase();
  // Follow new lines only when already at the bottom — scrolling up to read an
  // earlier error must not be yanked away by the next line.
  const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
  const line = document.createElement("div");
  line.className = `log-line fade-in lv-${e.level||"info"} k-${e.kind||"app"}`;
  // Every line starts with "[Activity]" (or "[Runner]"); older entries only carry msg.
  const text = e.text != null ? e.text : e.msg;
  const scope = e.scope
    ? `<span class="log-scope${e.scope===APP_SCOPE ? " is-app" : ""}">[${escHtml(e.scope)}]</span> `
    : "";
  line.innerHTML =
    `<span class="log-ts">${escHtml(e.ts)}</span>`+
    `<span class="log-tag log-${e.level}">${LOG_TAG[e.level]||"INF"}</span>`+
    `<span class="log-msg">${scope}${escHtml(text)}</span>`;
  if(query && !line.querySelector(".log-msg").textContent.toLowerCase().includes(query)) line.classList.add("hidden");
  body.appendChild(line);
  while(body.children.length>500) body.removeChild(body.firstChild);
  S.logCount = body.children.length;
  updateLogCount();
  if(atBottom) body.scrollTop = body.scrollHeight;
}
function filterLog(query){
  const q = query.trim().toLowerCase();
  $("log-body").querySelectorAll(".log-line").forEach(line=>{
    const msg = line.querySelector(".log-msg").textContent;
    line.classList.toggle("hidden", !!q && !msg.toLowerCase().includes(q));
  });
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
      ? "No game path yet — choose the game's .exe so Launch program blocks can start it."
      : (st && st.path === path && !st.exists)
        ? "Nothing at this path — choose the game's .exe again. Runs stay blocked until it exists."
      : (def && path !== def)
        ? `Overrides the workflow's default (${def}). Clear it to go back.`
        : "Launch program blocks set to “Project game path” start this program.";
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
      ? "No install folder set — emulator blocks auto-detect it. Choose a folder to pin it."
      : (def.path && S.emulator.path !== def.path)
        ? `Overrides the workflow's default (${def.path}).`
        : "Launch / Resize / Kill / Restart emulator blocks set to “Project emulator setting” use this family and folder.";
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
    : "This game is started from its .exe. Choose the game's .exe once before the first run — the Runner remembers it.");
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
  $("req-list").innerHTML = (r.items || []).map(n => `<li title="${escHtml(n)}">${escHtml(n)}</li>`).join("");
  const copy = $("btn-req-copy");
  if(copy) copy.style.display = isWin ? "" : "none";
  const st = $("req-status");
  const files = `${r.fileCount} file${r.fileCount === 1 ? "" : "s"}`;
  st.className = "req-status " + (r.installed ? "ok" : "warn");
  if(r.installed) st.textContent = `Installed — all ${files} found in ${r.gameDir}.`;
  else if(!isWin) st.textContent = `Copy these ${files} into the game's install folder.`;
  else if(!r.gameDir) st.textContent = `Not installed — set the Game path above, then copy these ${files} into the game folder.`;
  else st.textContent = `${r.missing} of ${files} missing in ${r.gameDir} — copy them into the game folder.`;
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
  $("flow-sub").textContent = ((data.controller === "win32") ? "Win32 · PC window" : "ADB · Device / emulator")
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
  if(type==="log_cleared"){ $("log-body").innerHTML=""; S.logCount=0; updateLogCount(); return; }
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
  if(type==="launch_blocked"){ onLaunchBlocked(data); return; }
  if(type==="running_state"){
    S.running=!!data.running; S.paused=!!data.paused;
    if(S.running){ $('header-progress').style.display='flex'; if(!_elapsedTimer) startElapsedTimer(); }
    else { stopElapsedTimer(); }
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

// ── Version + self-update ────────────────────────────────────────────────────
function applyRunnerInfo(r){
  r = r || {};
  U.supported = !!r.supported; U.version = r.version || ""; U.repo = r.repo || "";
  if(r.update && Object.keys(r.update).length) U.update = r.update;
  $("upd-version").textContent = U.version ? `v${U.version}` : "Not a standalone build";
  $("upd-repo").textContent = U.repo || "—";
  $("upd-repo").title = U.repo ? `https://github.com/${U.repo}` : "";
  renderUpdate();
}
function renderUpdate(){
  const pill = $("update-pill"), check = $("btn-upd-check"), apply = $("btn-upd-apply"), status = $("upd-status");
  if(!pill) return;
  const up = U.update;
  const available = !!(up && up.available);
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
  switchRTab("settings");
  const card = $("updates-card");
  if(card) card.scrollIntoView({ block:"nearest", behavior:"smooth" });
  const apply = $("btn-upd-apply");
  if(apply && !apply.hidden && !apply.disabled) apply.focus();
}
function focusUpdateProgress(){
  // Move the user to the live progress card before the blocking API call starts.
  switchRTab("settings");
  const card = $("updates-card");
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
  if(!S.loaded) return;
  S.runScope = null;
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
  if(!S.loaded || S.running) return;
  if(!S.activities.some(a=>a.id===id)) return;
  S.runScope = [id];
  setActStatus(id, "pending");
  $('header-progress').style.display='flex'; startElapsedTimer(); updateProgress();
  let ok = false;
  try{ ok = await api().run_activity(id); }catch(_){ }
  if(!ok){ stopElapsedTimer(); S.runScope = null; updateProgress(); }
}
async function onStop(){ await api().stop(); }
async function onPause(){ const r=await api().pause(); S.paused=!!(r&&r.paused); refreshButtons(); }
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
let pvActive = true;    // body shown (not collapsed)
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
window.__recvFrame = function(dataUrl,w,h){
  const img=$("pv-img"), empty=$("pv-empty");
  if(!img) return;
  img.src = dataUrl;
  if(empty) empty.style.display="none";
  const st=$("pv-state"); if(st && w && h) st.textContent = w+"×"+h;
};

// ── Appearance ────────────────────────────────────────────────────────────────
// Theme and density are suite-wide: web/shared/theme.js applies them to <html>
// and persists them through pywebview.api.save_settings(), which every Macro2k
// window reads on launch. These two segmented controls just mirror its state.
function syncAppearance(){
  const cur = (window.uiTheme && window.uiTheme.current()) || { theme:"light", density:"comfortable" };
  document.querySelectorAll("[data-theme-set]").forEach(b => {
    const on = b.dataset.themeSet === cur.theme;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
  });
  document.querySelectorAll("[data-density-set]").forEach(b => {
    const on = b.dataset.densitySet === cur.density;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
  });
}

function wireAppearance(){
  document.querySelectorAll("[data-theme-set]").forEach(b => {
    b.onclick = () => { if(window.uiTheme) window.uiTheme.setTheme(b.dataset.themeSet); syncAppearance(); };
  });
  document.querySelectorAll("[data-density-set]").forEach(b => {
    b.onclick = () => { if(window.uiTheme) window.uiTheme.setDensity(b.dataset.densitySet); syncAppearance(); };
  });
  // theme.js also reconciles against the backend once pywebview is ready, which
  // can land after first paint — follow it rather than showing a stale selection.
  window.addEventListener("m2k-theme", syncAppearance);
  syncAppearance();
}

// ── Init ───────────────────────────────────────────────────────────────────
async function init(){
  wireAppearance();
  setupListDnD($("seq-list"));
  setupListDnD($("bg-list"));
  let tries=0;
  while(!(window.pywebview&&window.pywebview.api)&&tries<40){ await new Promise(r=>setTimeout(r,100)); tries++; }
  if(!window.pywebview||!window.pywebview.api){ $("dev-label").textContent="PyWebView unavailable"; return; }
  const st = await api().get_state();
  applyRunnerInfo(st.runner);
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
