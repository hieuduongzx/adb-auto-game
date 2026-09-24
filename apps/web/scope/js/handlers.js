// ── Handlers ──────────────────────────────────────────────────────────────
async function onCapture(){
  S.capturePending=true;
  setOperation("Capture requested…","pending");
  let accepted;
  try{ accepted=await api().capture(); }
  catch(err){ S.capturePending=false; setOperation(`Capture failed: ${err.message||err}`,"failed"); return; }
  if(accepted===false){S.capturePending=false;setOperation("Capture was not started","failed");}
}
async function onCaptureBackendChange(backend){
  const r=await api().set_capture_backend(backend);
  S.captureBackend=(r&&r.backend)||backend;
  const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
  renderCaptureSource();
  setOperation("Capture source changed","success");
}
async function onRefreshDevices(){ await api().refresh_devices(); }
async function onScanPorts(){ await api().scan_ports(); }
async function onRestartAdb(){ await api().restart_adb(); }
async function openWorkflowDesigner(){ try{ await api().open_workflow_designer(); setStatus("Opening Macro2k…"); }catch{} }
async function onDeviceChange(serial){
  if(!serial) return;
  S.connectedSerial=null;
  S.connectionState="pending";
  $("device-dot").classList.remove("connected");
  $("footer-dot").classList.remove("connected");
  const label=$("device-state"); label.textContent=`Connecting · ${serial}`; label.dataset.state="pending";
  try{
    if(await api().select_device(serial)===false) throw Error("request declined");
  }catch(err){
    S.connectionState="unknown"; label.textContent="Connection unconfirmed"; label.dataset.state="unknown";
    setOperation(`Device selection failed: ${err.message||err}`,"failed");
  }
}
function onHzChange(v){ S.refreshHz=parseFloat(v)||5; api().set_refresh_hz(S.refreshHz); }
function onToggleAuto(){
  const cb=$("auto-cb"); cb.classList.toggle("on");
  S.autoRefresh=cb.classList.contains("on");
  document.querySelector(".pill-wrap")?.setAttribute("aria-checked",String(S.autoRefresh));
  api().set_auto_refresh(S.autoRefresh);
}

async function onSaveFull(){ await api().save_full($("full-name").value); }
async function onLoadFile(){
  if(await api().open_image()){
    S.autoRefresh=false;
    $("auto-cb").classList.remove("on");
    document.querySelector(".pill-wrap")?.setAttribute("aria-checked","false");
  }
}
async function onTapPoint(){ await api().tap(parseInt($("pt-x").value||"0"),parseInt($("pt-y").value||"0")); }

async function onCheckColor(){
  const r=await api().check_color(parseInt($("cc-x").value||"0"),parseInt($("cc-y").value||"0"),$("cc-hex").value.trim(),parseInt($("cc-tol").value||"10"));
  const el=$("cc-result"); el.style.display="block";
  if(r.error){el.className="cc-result bad";el.textContent=r.error;setOperation(`Color check failed: ${r.error}`,"failed");return;}
  setOperation(`Color check: ${r.match?"Match":"No match"} · actual ${r.actual} · Δ${r.dist}`,r.match?"success":"idle");
  el.className="cc-result "+(r.match?"ok":"bad");
  el.innerHTML=r.match
    ?`✓ Match &nbsp;·&nbsp; actual: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`
    :`✗ No match &nbsp;·&nbsp; actual: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`;
}

async function onApplyRegion(){
  const x=parseInt($("rg-x").value||"0"),y=parseInt($("rg-y").value||"0");
  const w=parseInt($("rg-w").value||"0"),h=parseInt($("rg-h").value||"0");
  if(w>0&&h>0){await api().set_region(x,y,w,h);S.region=[x,y,w,h];S.point=null;setRegionBadge(true);draw();setStatus(`Region ${x},${y} · ${w}×${h}`);}
}
async function onSaveCropDialog(){ await api().save_crop_dialog($("crop-name").value); }
async function onQuickCrop(){ const ok=await api().quick_crop($("crop-name").value); if(ok) onRefreshAssets(); }
async function onPickOutDir(){
  const p=await api().pick_out_dir();
  if(p) updateOutDir(p);
}
function updateOutDir(p){
  const norm=p.replace(/\\/g,'/');
  const parts=norm.split('/').filter(Boolean);
  const short=parts.length>2?'…/'+parts.slice(-2).join('/')+'/' : norm;
  $('out-dir-label').textContent=short; $('out-dir-label').title=p;
  $('footer-out').textContent='crops → '+short;
  const lib=$('lib-out-label'); if(lib){lib.textContent=short;lib.title=p;}
}
async function onClearRegion(){
  $("rg-x").value=$("rg-y").value=$("rg-w").value=$("rg-h").value=0;
  await api().clear_selection(); setRegionBadge(false); draw();
}
async function onOcrBackendChange(name){
  const r=await api().set_ocr_backend(name);
  const el=$("ocr-engine");
  el.textContent=(r.label||r.engine)+(r.available?" · ready":" · unavailable");
  el.className=r.available?"":"unavailable";
}
async function onReadText(){ $("ocr-result").value=await api().read_text($("ocr-wl").value); }
async function onSendTap(){ await api().tap(parseInt($("tap-x").value||"0"),parseInt($("tap-y").value||"0")); }
async function onSendLongPress(){ await api().long_press(parseInt($("lp-x").value||"0"),parseInt($("lp-y").value||"0"),parseInt($("lp-dur").value||"800")); }
async function onSendSwipe(){ await api().swipe(parseInt($("sw-x1").value||"0"),parseInt($("sw-y1").value||"0"),parseInt($("sw-x2").value||"0"),parseInt($("sw-y2").value||"0"),parseInt($("sw-dur").value||"300")); }
async function onSendText(){ const t=$("inp-text").value; if(t){await api().input_text(t);$("inp-text").value="";} }

async function onBrowseTpl(){ const p=await api().pick_template(); if(p) $("tpl-path").value=p; }
async function onRunMatch(all){
  const r=await api().match_template($("tpl-path").value,parseFloat($("tpl-thr").value||".85"),$("cb-gray").classList.contains("checked"),$("cb-multiscale").classList.contains("checked"),all);
  const el=$("tpl-result");
  if(r.error){el.textContent=r.error;el.className="tpl-result empty";setOperation(`Match failed: ${r.error}`,"failed");return;}
  setOperation(r.summary,"idle");
  el.textContent=r.summary;el.className="tpl-result";S.overlay=r.rects||[];draw();
}
async function onClearOverlay(){ await api().clear_overlay(); S.overlay=[]; draw(); }
async function onRefreshInfo(){ await api().refresh_info(); }
async function onCopyInfo(){ await api().copy_info(); }
async function onClearLog(ev){ if(ev) ev.stopPropagation(); await api().clear_log(); }
