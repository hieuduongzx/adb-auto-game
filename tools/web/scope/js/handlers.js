// ── Handlers ──────────────────────────────────────────────────────────────
async function onCapture(){ await api().capture(); }
async function onCaptureBackendChange(backend){
  const r=await api().set_capture_backend(backend);
  S.captureBackend=(r&&r.backend)||backend;
  const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
  setStatus("Nguồn ảnh: "+(S.captureBackend==="adb"?"ADB screencap":"scrcpy (nhanh/headless)"));
}
async function onRefreshDevices(){ await api().refresh_devices(); }
async function onScanPorts(){ await api().scan_ports(); }
async function onRestartAdb(){ await api().restart_adb(); }
async function openWorkflowDesigner(){ try{ await api().open_workflow_designer(); setStatus("Đang mở Workflow2k…"); }catch{} }
async function onDeviceChange(serial){ if(serial){S.connectedSerial=serial;await api().select_device(serial);} }
function onHzChange(v){ api().set_refresh_hz(parseFloat(v)||5); }
function onToggleAuto(){
  const cb=$("auto-cb"); cb.classList.toggle("on");
  S.autoRefresh=cb.classList.contains("on"); api().set_auto_refresh(S.autoRefresh);
}

async function onSaveFull(){ await api().save_full($("full-name").value); }
async function onLoadFile(){ const p=prompt("Đường dẫn ảnh (PNG/JPG):"); if(p) await api().save_full(""); }
async function onTapPoint(){ await api().tap(parseInt($("pt-x").value||"0"),parseInt($("pt-y").value||"0")); }

async function onCheckColor(){
  const r=await api().check_color(parseInt($("cc-x").value||"0"),parseInt($("cc-y").value||"0"),$("cc-hex").value.trim(),parseInt($("cc-tol").value||"10"));
  const el=$("cc-result"); el.style.display="block";
  if(r.error){el.className="cc-result bad";el.textContent=r.error;return;}
  el.className="cc-result "+(r.match?"ok":"bad");
  el.innerHTML=r.match
    ?`✓ Khớp &nbsp;·&nbsp; thực tế: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`
    :`✗ Không khớp &nbsp;·&nbsp; thực tế: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`;
}

async function onApplyRegion(){
  const x=parseInt($("rg-x").value||"0"),y=parseInt($("rg-y").value||"0");
  const w=parseInt($("rg-w").value||"0"),h=parseInt($("rg-h").value||"0");
  if(w>0&&h>0){await api().set_region(x,y,w,h);S.region=[x,y,w,h];S.point=null;setRegionBadge(true);draw();setStatus(`Vùng ${x},${y} · ${w}×${h}`);}
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
  el.textContent=r.engine+(r.available?" · sẵn sàng":" · không khả dụng");
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
  if(r.error){el.textContent=r.error;el.className="tpl-result empty";return;}
  el.textContent=r.summary;el.className="tpl-result";S.overlay=r.rects||[];draw();
}
async function onClearOverlay(){ await api().clear_overlay(); S.overlay=[]; draw(); }
async function onRefreshInfo(){ await api().refresh_info(); }
async function onCopyInfo(){ await api().copy_info(); }
async function onClearLog(ev){ if(ev) ev.stopPropagation(); await api().clear_log(); }
