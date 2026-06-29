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
    setStatus("Nguồn ảnh: "+(S.captureBackend==="adb"?"ADB screencap":"scrcpy (nhanh/headless)"));
    return;
  }
  if(type==="workflow_state"){ wfSetRunning(!!data.running); return; }
  // Ignore node events for a graph we're not viewing (e.g. a function's internal
  // nodes while a call node runs) so the call block stays lit instead of the
  // highlight vanishing into the off-screen function graph. Also drop late events
  // that land after the run already stopped.
  if(type==="node_active"){ if(!wfRunning) return; if(data.id && !wfNode(data.id)) return; wfSetRunningNode(data.id); return; }
  if(type==="node_result"){ if(!wfRunning) return; if(data.id && !wfNode(data.id)) return; wfMarkNodeResult(data.id, data.status, data.port); return; }
  if(type==="speedhack_state"){
    wfSpeedRunning=!!data.running; wfSyncSpeedUI();
    if(data.running && data.active) setStatus("Speed hack đang chạy");
    else if(!data.running) setStatus("Speed hack đã tắt");
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
  if(ev && ev.target.closest(".btn-log-clear")) return;   // let "Xoá" act without toggling
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
  setStatus("Nguồn ảnh: "+(S.captureBackend==="adb"?"ADB screencap":"scrcpy (nhanh/headless)"));
}
async function openDevHelper(){ try{ await api().open_dev_helper(JSON.stringify(wfSerialize())); setStatus("Đang mở DevScope…"); }catch{} }

// New blank workflow.
async function wfNew(){
  if((WF.activities.length || WF.functions.length) &&
     !confirm("Tạo workflow mới? Các thay đổi chưa lưu sẽ mất.")) return;
  WF.name="My Workflow"; WF.version=2; WF.templatesDir="templates";
  WF.speedhack={enabled:false, speed:2.0, package:""};
  WF.activities=[]; WF.functions=[]; WF.edit={kind:"activity",id:null};
  WF.sel=[]; WF.selectedNode=null; wfPan={x:0,y:0}; wfZoom=1; wfRunNode=null;
  const nm=$("wf-name"); if(nm) nm.value=WF.name;
  wfSyncSpeedUI();
  try{ await api().workflow_new(); }catch{}
  wfAddActivity("sequence");   // seed one activity so the canvas isn't empty
  setStatus("Workflow mới");
}
