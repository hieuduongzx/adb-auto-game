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
  logCount:        0,
  speedhack: { enabled:false, speed:2.0, package:"", active:false },
};

const $ = id => document.getElementById(id);
const ACT_DOT_TITLE = { pending:"Pending", running:"Running", completed:"Completed", failed:"Failed", skipped:"Skipped" };
const LOG_TAG = { info:"INF", success:"OK ", warning:"WRN", error:"ERR" };
const CHECK = `<svg class="icon" width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>`;
const GRIP = `<svg width="9" height="14" viewBox="0 0 9 14" fill="currentColor"><circle cx="2" cy="2" r="1.4"/><circle cx="7" cy="2" r="1.4"/><circle cx="2" cy="7" r="1.4"/><circle cx="7" cy="7" r="1.4"/><circle cx="2" cy="12" r="1.4"/><circle cx="7" cy="12" r="1.4"/></svg>`;

function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

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
  const seq = S.activities.filter(a=>a.type!=="background");
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

// ── Button states ────────────────────────────────────────────────────────────
function refreshButtons(){
  const running = S.running, paused = S.paused;
  $("btn-start").disabled = running || !S.loaded;
  $("btn-pause").disabled = !running;
  $("btn-stop").disabled  = !running;
  $("btn-load").disabled  = running;   // loading mid-run would stop the engine
  $("btn-pause").textContent = paused ? "Resume" : "Pause";
  document.querySelectorAll(".runtime-setting-control").forEach(el=>el.disabled=running);
  setStatusPill(running ? (paused ? "paused" : "running") : "ready");
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab){
  document.querySelectorAll(".tab-btn").forEach(b=>{ const on=b.dataset.tab===tab; b.classList.toggle("active",on); b.setAttribute("aria-selected",String(on)); });
  document.querySelectorAll(".tab-pane").forEach(p=>p.classList.toggle("active", p.id==="tab-"+tab));
}

// ── Build activity rows ──────────────────────────────────────────────────────
function buildRow(a){
  const isBg = a.type==="background";
  const row = document.createElement("div");
  row.className = "task-row" + (a.status==="running" ? " task-running" : "");
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
    row.querySelector(".task-name").classList.toggle("dim", !a.enabled);
    api().toggle_activity(a.id, a.enabled);
  };

  const st = a.status || "pending";
  const dot = document.createElement("span");
  dot.className = "act-dot act-dot-" + st;
  dot.title = ACT_DOT_TITLE[st] || ACT_DOT_TITLE.pending;
  dot.setAttribute("role", "status");
  dot.setAttribute("aria-label", `Status: ${dot.title}`);
  dot.dataset.dot = "1";

  const block = document.createElement("div");
  block.className = "task-name-block";
  const name = document.createElement("div");
  name.className = "task-name" + (a.enabled ? "" : " dim");
  name.textContent = a.name;
  block.appendChild(name);
  const meta = document.createElement("div");
  meta.className = "task-meta"; meta.dataset.meta = "1";
  meta.textContent = actMeta(a);
  block.appendChild(meta);

  const btns = document.createElement("div");
  btns.className = "task-btns";
  const hasSettings = (a.vars && a.vars.length) || (a.runtimeSettings && a.runtimeSettings.length) || isBg;
  if(hasSettings){
    const gear = gearButton(a.id);
    gear.onclick = ()=>toggleSettings(a.id);
    btns.appendChild(gear);
  }

  row.appendChild(handle); row.appendChild(cb); row.appendChild(dot); row.appendChild(block); row.appendChild(btns);
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

// Second line under the activity name.
function actMeta(a){
  if(a.type==="background") return `every ${a.pollInterval}s`;
  return a.maxRetries > 1 ? `${a.maxRetries} attempts` : "";
}

function gearButton(id){
  const g = document.createElement("button");
  g.type = "button"; g.className = "btn-icon btn-gear"; g.title = "Activity settings"; g.dataset.gear = id;
  g.setAttribute("aria-label", "Activity settings");
  g.innerHTML = `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
  return g;
}

// ── Inline settings panel ────────────────────────────────────────────────────
function buildSettingsPanel(a){
  const panel = document.createElement("div");
  panel.className = "task-settings"; panel.dataset.settingsFor = a.id;

  if(a.type==="background"){
    const row = document.createElement("div");
    row.className = "setting-row"; row.style.paddingTop = "10px";
    const lbl = document.createElement("span"); lbl.className = "setting-label"; lbl.textContent = "Interval";
    const inp = document.createElement("input");
    inp.type = "number"; inp.className = "setting-input";
    inp.setAttribute("aria-label", "Background interval in seconds");
    inp.min = 0.05; inp.step = 0.5; inp.value = a.pollInterval;
    inp.onchange = ()=>{
      const v = Math.max(0.05, parseFloat(inp.value)||a.pollInterval);
      inp.value = v; a.pollInterval = v; api().set_interval(a.id, v);
      const meta = document.querySelector(`[data-id="${a.id}"] [data-meta]`);
      if(meta) meta.textContent = actMeta(a);
    };
    const unit = document.createElement("span"); unit.className = "setting-unit"; unit.textContent = "seconds";
    row.appendChild(lbl); row.appendChild(inp); row.appendChild(unit);
    panel.appendChild(row);
  }

  (a.runtimeSettings||[]).forEach(setting=>{
    const row=document.createElement("div");
    row.className="setting-row"; row.style.paddingTop="8px";
    const lbl=document.createElement("span"); lbl.className="setting-label";
    lbl.innerHTML=escHtml(setting.label||"Path")+`<span class="sub">${escHtml(setting.nodeLabel||"")}</span>`;
    const control=document.createElement("div"); control.className="setting-path-control";
    const inp=document.createElement("input"); inp.type="text";
    inp.className="setting-path-input runtime-setting-control";
    inp.value=setting.value||""; inp.placeholder=setting.kind==="folder"?"Choose a folder…":"Choose a program…";
    inp.setAttribute("aria-label", setting.label||"Runtime path");
    inp.title=inp.value; inp.disabled=!!S.running;
    inp.onchange=async()=>{
      const old=setting.value||"", value=inp.value.trim();
      let ok=false; try{ ok=await api().set_node_runtime_param(setting.nodeId,setting.param,value); }catch(_){ }
      if(ok){ syncRuntimeSetting(setting.nodeId,setting.param,value); inp.title=value; }
      else inp.value=old;
    };
    const pick=document.createElement("button"); pick.type="button";
    pick.className="btn-path-pick runtime-setting-control"; pick.textContent="Choose…";
    pick.title=setting.kind==="folder"?"Choose folder":"Choose program file"; pick.disabled=!!S.running;
    pick.onclick=async()=>{
      let value="";
      try{ value=await api().pick_node_runtime_path(setting.nodeId,setting.param,setting.kind,inp.value); }catch(_){ }
      if(value){ inp.value=value; inp.title=value; syncRuntimeSetting(setting.nodeId,setting.param,value); }
    };
    control.appendChild(inp); control.appendChild(pick);
    row.appendChild(lbl); row.appendChild(control); panel.appendChild(row);
  });

  (a.vars||[]).forEach(v=>{
    const row = document.createElement("div");
    row.className = "setting-row"; row.style.paddingTop = "8px";
    const lbl = document.createElement("span"); lbl.className = "setting-label";
    lbl.innerHTML = escHtml(v.label||v.name) + (v.label?`<span class="sub">${escHtml(v.name)}</span>`:"");
    row.appendChild(lbl);

    const type = v.type || "bool";
    if(type==="bool"){
      const cb = document.createElement("button"); cb.type="button"; cb.className = "cb"+(v.value?" checked":""); cb.innerHTML = CHECK;
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
    panel.appendChild(row);
  });

  return panel;
}

function syncRuntimeSetting(nodeId,param,value){
  S.activities.forEach(a=>(a.runtimeSettings||[]).forEach(s=>{
    if(s.nodeId===nodeId&&s.param===param) s.value=value;
  }));
}

function toggleSettings(id){
  const a = S.activities.find(x=>x.id===id); if(!a) return;
  const list = a.type==="background" ? $("bg-list") : $("seq-list");
  const existing = list.querySelector(`[data-settings-for="${id}"]`);
  const row = list.querySelector(`[data-id="${id}"]`);
  const gear = row && row.querySelector("[data-gear]");
  if(existing){ existing.remove(); if(gear) gear.classList.remove("active"); S.expandedId=null; return; }
  list.querySelectorAll("[data-settings-for]").forEach(p=>p.remove());
  list.querySelectorAll(".btn-gear.active").forEach(g=>g.classList.remove("active"));
  if(gear) gear.classList.add("active");
  S.expandedId = id;
  const panel = buildSettingsPanel(a);
  if(row && row.nextSibling) list.insertBefore(panel, row.nextSibling);
  else if(row) list.appendChild(panel);
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
}

function setActStatus(id, status){
  const a = S.activities.find(x=>x.id===id);
  if(a) a.status = status;
  const st = status || "pending";
  const row = document.querySelector(`.task-row[data-id="${id}"]`);
  if(row){
    const dot = row.querySelector("[data-dot]");
    if(dot){
      dot.className = "act-dot act-dot-" + st;
      dot.title = ACT_DOT_TITLE[st] || ACT_DOT_TITLE.pending;
      dot.setAttribute("aria-label", `Status: ${dot.title}`);
    }
    row.classList.toggle("task-running", st==="running");
  }
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
  const el = $("log-count");
  if(el) el.textContent = S.logCount ? String(S.logCount) : "";
}
function toggleLog(){
  const card=$("log-card");
  card.classList.toggle("collapsed");
  $("log-toggle").setAttribute("aria-expanded",String(!card.classList.contains("collapsed")));
}
function appendLog(e){
  const body = $("log-body");
  const query = $("log-search").value.trim().toLowerCase();
  const line = document.createElement("div");
  line.className = "log-line fade-in";
  if(query && !String(e.msg).toLowerCase().includes(query)) line.classList.add("hidden");
  line.innerHTML =
    `<span class="log-ts">[${e.ts}]</span>`+
    `<span class="log-tag log-${e.level}">${LOG_TAG[e.level]||"INF"}</span>`+
    `<span class="log-msg">${escHtml(e.msg)}</span>`;
  body.appendChild(line);
  while(body.children.length>500) body.removeChild(body.firstChild);
  S.logCount = body.children.length;
  updateLogCount();
  const card = $("log-card");
  if(card && !card.classList.contains("collapsed"))
    body.scrollTop = body.scrollHeight;
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

  // Speed hack is ADB-only; Appearance is not, so the tab itself always stays.
  const speedCard = document.querySelector("#tab-settings .settings-card");
  if(speedCard) speedCard.style.display = isWin ? "none" : "";

  if(!isWin) return;
  const cfg = S.win32 || {};
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

// ── Flow ──────────────────────────────────────────────────────────────────────
function applyFlow(data){
  S.activities = data.activities || [];
  S.loaded = true;
  const nm = $("flow-name");
  nm.textContent = data.name || "(unnamed)"; nm.classList.remove("empty");
  $("flow-sub").textContent = (data.controller === "win32") ? "Win32 · PC window" : "ADB · Device / emulator";
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
  applyController(data.controller, data.win32);
  refreshButtons();
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
};

// ── Handlers ───────────────────────────────────────────────────────────────
const api = () => window.pywebview.api;
async function onLoadJson(){ const r=await api().load_json(); if(r&&r.ok) applyFlow(r); }
async function onStart(){
  if(!S.loaded) return;
  S.activities.filter(a=>a.type!=="background").forEach(a=>setActStatus(a.id,"pending"));
  $('header-progress').style.display='flex'; startElapsedTimer(); updateProgress();
  await api().start();
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
    if(row){ row.querySelector(".cb").classList.toggle("checked", enabled); row.querySelector(".task-name").classList.toggle("dim", !enabled); }
    api().toggle_activity(a.id, enabled);
  });
}

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
  S.connectedSerial = st.connectedSerial||null;
  S.captureBackend = st.captureBackend||"scrcpy";
  const capSel=$("capture-backend");
  if(capSel){
    capSel.innerHTML="";
    (st.captureBackends||["scrcpy","adb"]).forEach(b=>{ const o=document.createElement("option"); o.value=b; o.textContent=b==="adb"?"ADB":"scrcpy"; capSel.appendChild(o); });
    capSel.value=S.captureBackend;
  }
  if(st.loaded) applyFlow({name:st.name, activities:st.activities, speedhack:st.speedhack,
                           captureBackend:st.captureBackend, controller:st.controller, win32:st.win32});
  else applyController(st.controller, st.win32);
  S.running=!!st.running; S.paused=!!st.paused;
  refreshButtons();
  (st.log||[]).forEach(appendLog);
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
