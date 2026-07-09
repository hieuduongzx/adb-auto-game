// ── Python events ───────────────────────────────────────────────────────────
window.__recv = function(raw){
  let ev; try{ev=JSON.parse(raw);}catch{return;}
  const {type,data}=ev;
  if(type==="log"){ appendLog(data); return; }
  if(type==="log_cleared"){ const b=$("log-body"); if(b)b.innerHTML=""; updateLogCount(); return; }
  if(type==="devices_update"){ S.devices=data.devices||[]; rebuildDeviceSelect(S.devices,S.connectedSerial); return; }
  if(type==="device_status"){ S.connectedSerial=data.serial||null; setConnected(!!data.connected); rebuildDeviceSelect(S.devices,data.serial); return; }
  if(type==="capture_backend"){
    S.captureBackend=data.backend||"scrcpy";
    const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
    setStatus("Capture source: "+(S.captureBackend==="adb"?"ADB screencap":"scrcpy (nhanh/headless)"));
    return;
  }
  if(type==="workflow_state"){ wfSetRunning(!!data.running); return; }
  if(type==="capture_failed"){
    // From the Preview tab's live mirror — surface the error and refresh the empty state.
    setStatus(`Capture failed: ${data.error||""}`);
    if(typeof wfPvErr!=="undefined"){ wfPvErr=String(data.error||""); if(!wfPvImg && wfPvActive) wfPvDrawEmpty(); }
    return;
  }
  // ── Scope tool events (Preview tab inspector) ───────────────────────────────
  if(type==="captured"){ const rl=$("wf-pv-res"); if(rl) rl.textContent=`${data.w} × ${data.h}`; return; }
  if(type==="overlay"){
    if(typeof wfPvOverlay!=="undefined"){ wfPvOverlay=data.rects||[]; if(typeof wfPvDraw==="function") wfPvDraw(); }
    return;
  }
  if(type==="selection_cleared"){
    if(typeof wfPvRegion!=="undefined"){ wfPvRegion=null; wfPvPoint=null; wfPvOverlay=[]; pvSetRegionBadge(false); if(typeof wfPvDraw==="function") wfPvDraw(); }
    return;
  }
  if(type==="out_dir"){ if(typeof pvUpdateOutDir==="function") pvUpdateOutDir(data.path); return; }
  if(type==="device_info"){
    const D={status:"pv-i-status",serial:"pv-i-serial",model:"pv-i-model",brand:"pv-i-brand",
      android:"pv-i-android",abi:"pv-i-abi",screen_size:"pv-i-screen",density:"pv-i-density",
      app:"pv-i-app",battery:"pv-i-battery",ip:"pv-i-ip",uptime:"pv-i-uptime"};
    Object.keys(D).forEach(k=>{ const e=$(D[k]); if(e) e.textContent=data[k]||"-"; });
    return;
  }
  if(type==="copy_device_info"){
    const D={status:"pv-i-status",serial:"pv-i-serial",model:"pv-i-model",brand:"pv-i-brand",
      android:"pv-i-android",abi:"pv-i-abi",screen_size:"pv-i-screen",density:"pv-i-density",
      app:"pv-i-app",battery:"pv-i-battery",ip:"pv-i-ip",uptime:"pv-i-uptime"};
    navigator.clipboard.writeText(Object.keys(D).map(k=>`${k}: ${$(D[k]).textContent}`).join("\n"));
    setStatus("Device info copied"); return;
  }
  // Ignore node events for a graph we're not viewing (e.g. a function's internal
  // nodes while a call node runs) so the call block stays lit instead of the
  // highlight vanishing into the off-screen function graph. Also drop late events
  // that land after the run already stopped.
  // Follow-focus overrides the off-graph guard: when focus is on, we switch to
  // the node's own graph (activity or function) and centre on it, so execution
  // is followed across call boundaries in and out.
  if(type==="node_active"){
    if(!wfRunning) return;
    if(data.id){ wfLiveNode=data.id; wfNoteNodeStart(data.id); }   // the true running node, even if in an off-screen graph
    // Follow-focus first: if the running node lives in another graph (a function
    // we stepped into, or the activity we stepped back out to), switch to it and
    // centre. This rebuilds the canvas so the node is now present for the guard.
    if(data.id && wfFocusOn) wfFocusFollow(data.id);
    if(data.id && !wfNode(data.id)) return;   // off-graph & focus off → leave call block lit
    wfSetRunningNode(data.id);
    return;
  }
  if(type==="node_result"){ if(!wfRunning) return; wfNoteNodeDone(data.id);
    if(data.id && !wfNode(data.id)) return; wfMarkNodeResult(data.id, data.status, data.port); if(typeof wfDebugAutoStep==="function") wfDebugAutoStep(); return; }
  // Failure screenshot saved for a node's final failed attempt — remember it and
  // refresh the inspector if that node is the one being inspected right now.
  if(type==="node_fail_shot"){
    if(data.id){ wfFailShots[data.id]=data.path||"";
      if(WF.selectedNode===data.id) wfRenderInspector(); }
    return;
  }
  // Activity-level run status: blinking-green while the engine executes it,
  // then solid-green when it completed (reached End) or solid-red on failure.
  // The marks persist after the run and only clear on the next run start
  // (wfResetActStatus in wfResetRunViz). The !wfRunning guard drops late
  // results after a manual Stop so a half-run activity isn't painted.
  if(type==="activity_active"){ if(!wfRunning) return; if(data.id) wfSetActStatus(data.id, "running"); return; }
  if(type==="activity_result"){ if(!wfRunning) return; if(data.id) wfSetActStatus(data.id, data.status==="ok" ? "done" : "errored"); return; }
  if(type==="speedhack_state"){
    wfSpeedRunning=!!data.running; wfSyncSpeedUI();
    if(data.running && data.active) setStatus("Speed hack is running");
    else if(!data.running) setStatus("Speed hack is off");
    return;
  }
  if(type==="var_update"){ wfLiveVars[data.name]=data.value; wfRenderVarsPanel(); return; }
  if(type==="vars_snapshot"){ wfLiveVars=data.vars||{}; wfRenderVarsPanel(); return; }
};

// ── Log drawer ────────────────────────────────────────────────────────────────
function updateLogCount(){
  const c=$("log-count"), b=$("log-body"); if(!c||!b) return;
  const n=b.children.length;
  c.textContent = n ? String(n) : "";
  // Highlight the count when there are errors so the collapsed log still warns.
  const hasErr = !!b.querySelector(".lv-error");
  c.classList.toggle("has-err", hasErr);
}
function wfToggleVarsPanel(ev){
  if(ev && ev.target.closest(".wf-vars-actions")) return;
  wfVarsCollapsed = !wfVarsCollapsed;
  if(typeof wfPersistPanelState==="function") wfPersistPanelState();
  wfRenderVarsPanel();
}

function wfToggleLog(ev){
  if(ev && ev.target.closest(".btn-log-clear, .log-filters")) return;   // let Clear/Copy/filter act without toggling
  const c=$("log-card"); if(!c) return;
  const isCollapsed = c.classList.contains("collapsed");
  if (isCollapsed) {
    c.style.display = "flex"; // Ensure it's not display:none if handled by CSS previously
    // Force reflow
    void c.offsetWidth;
    c.classList.remove("collapsed");
  } else {
    c.classList.add("collapsed");
  }
  wfSaveSettings();
}

// Lọc log theo mức (INF/OK/WRN/ERR) — set data-filter trên #log-card, CSS ẩn
// các dòng khác mức; "Tất cả" gỡ filter.
function wfLogFilter(f, ev){
  if(ev) ev.stopPropagation();
  const card=$("log-card"); if(!card) return;
  if(f==="all") card.removeAttribute("data-filter"); else card.setAttribute("data-filter",f);
  document.querySelectorAll("#log-filters .log-f").forEach(b=>b.classList.toggle("on", b.dataset.f===f));
  if(card.classList.contains("collapsed")) wfToggleLog();   // lọc là để đọc — mở log ra
}
function wfCopyLog(ev){
  if(ev) ev.stopPropagation();
  const body=$("log-body"); if(!body) return;
  const txt=[...body.querySelectorAll(".log-line")].map(l=>l.textContent.replace(/\s+/g," ").trim()).join("\n");
  if(!txt){ setStatus("Log trống"); return; }
  navigator.clipboard.writeText(txt).then(()=>uiToast("Đã copy "+body.children.length+" dòng log","success"))
    .catch(()=>uiToast("Không copy được log","error"));
}

// ── Device handlers ─────────────────────────────────────────────────────────
function onClearLog(ev){ if(ev) ev.stopPropagation(); api().clear_log(); }
async function onRefreshDevices(){ await api().refresh_devices(); }
async function onScanPorts(){ await api().scan_ports(); }
async function onRestartAdb(){ await api().restart_adb(); }
async function onDeviceChange(serial){ if(serial){ S.connectedSerial=serial; await api().select_device(serial); } }
async function onCaptureBackendChange(backend){
  const r=await api().set_capture_backend(backend);
  S.captureBackend=(r&&r.backend)||backend;
  const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
  setStatus("Capture source: "+(S.captureBackend==="adb"?"ADB screencap":"scrcpy (nhanh/headless)"));
}
async function openDevHelper(){ try{ await api().open_dev_helper(JSON.stringify(wfSerialize())); setStatus("Opening DevScope…"); }catch{} }

// New blank workflow.
async function wfNew(){
  if(WF.activities.length || WF.functions.length){
    const ok=await uiConfirm({title:"Tạo workflow mới?", message:"Thay đổi chưa lưu của workflow hiện tại sẽ mất.", ok:"Tạo mới", danger:true});
    if(!ok) return;
  }
  const name = await uiPrompt({title:"Workflow mới", label:"Tên workflow", value:"My Workflow"});
  if(name===null) return; // cancelled
  WF.name = name.trim() || "My Workflow";
  WF.version=2; WF.templatesDir="templates";
  WF.speedhack={enabled:false, speed:2.0, package:""};
  WF.controller="adb"; WF.win32={window:"", matchBy:"title", inputMode:"background"};
  WF.ocrBackend=""; if(typeof wfSyncOcrUI==="function") wfSyncOcrUI();
  WF.activities=[]; WF.functions=[]; WF.edit={kind:"activity",id:null};
  WF.sel=[]; WF.selectedNode=null; wfPan={x:0,y:0}; wfZoom=1; wfRunNode=null;
  const nm=$("wf-name"); if(nm) nm.value=WF.name;
  wfSyncSpeedUI();
  if(typeof wfSyncControllerUI==="function") wfSyncControllerUI();
  try{ await api().workflow_new(WF.name); }catch{}
  wfAddActivity("sequence");   // seed one activity so the canvas isn't empty
  await wfSave();              // auto-create workflow.json inside the named folder
  setStatus("New workflow: " + WF.name);
}
