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
    if(data.id) wfLiveNode=data.id;   // the true running node, even if in an off-screen graph
    // Follow-focus first: if the running node lives in another graph (a function
    // we stepped into, or the activity we stepped back out to), switch to it and
    // centre. This rebuilds the canvas so the node is now present for the guard.
    if(data.id && wfFocusOn) wfFocusFollow(data.id);
    if(data.id && !wfNode(data.id)) return;   // off-graph & focus off → leave call block lit
    wfSetRunningNode(data.id);
    return;
  }
  if(type==="node_result"){ if(!wfRunning) return; if(data.id && !wfNode(data.id)) return; wfMarkNodeResult(data.id, data.status, data.port); if(typeof wfDebugAutoStep==="function") wfDebugAutoStep(); return; }
  // Activity-level run status: mark the row blinking-green while the engine
  // executes it, then solid-red if it finished with failure. Cleared on the
  // next run start (wfResetActStatus in wfResetRunViz).
  if(type==="activity_active"){ if(data.id) wfSetActStatus(data.id, "running"); return; }
  if(type==="activity_result"){ if(data.id) wfSetActStatus(data.id, data.status==="ok" ? null : "errored"); return; }
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
function updateLogCount(){ const c=$("log-count"), b=$("log-body"); if(c&&b) c.textContent = b.children.length? String(b.children.length):""; }
function wfToggleVarsPanel(ev){
  if(ev && ev.target.closest(".wf-vars-actions")) return;
  wfVarsCollapsed = !wfVarsCollapsed;
  wfRenderVarsPanel();
}

function wfToggleLog(ev){
  if(ev && ev.target.closest(".btn-log-clear")) return;   // let "Clear" act without toggling
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
  if((WF.activities.length || WF.functions.length) &&
     !confirm("Create a new workflow? Unsaved changes will be lost.")) return;
  WF.name="My Workflow"; WF.version=2; WF.templatesDir="templates";
  WF.speedhack={enabled:false, speed:2.0, package:""};
  WF.activities=[]; WF.functions=[]; WF.edit={kind:"activity",id:null};
  WF.sel=[]; WF.selectedNode=null; wfPan={x:0,y:0}; wfZoom=1; wfRunNode=null;
  const nm=$("wf-name"); if(nm) nm.value=WF.name;
  wfSyncSpeedUI();
  try{ await api().workflow_new(); }catch{}
  wfAddActivity("sequence");   // seed one activity so the canvas isn't empty
  setStatus("New workflow");
}
