// ── Init ──────────────────────────────────────────────────────────────────
async function init(){
  let tries=0;
  while(!(window.pywebview&&window.pywebview.api)&&tries<40)
    await new Promise(r=>setTimeout(r,100)),tries++;
  if(!window.pywebview||!window.pywebview.api){setStatus("⚠ pywebview is unavailable");return;}
  const state=await api().get_state();
  if(S.connectionState==="unknown"){
    S.connectedSerial=state.connectedSerial||null;
    setConnected(!!S.connectedSerial);
  }
  const capSel=$("capture-backend");
  if(capSel){
    capSel.innerHTML="";
    (state.captureBackends||["scrcpy","adb"]).forEach(b=>{const o=document.createElement("option");o.value=b;o.textContent=b==="adb"?"ADB screencap":"scrcpy (fast)";capSel.appendChild(o);});
    capSel.value=state.captureBackend||"scrcpy";
    S.captureBackend=capSel.value;
    renderCaptureSource();
  }
  const sel=$("ocr-backend");
  const models=state.ocrModels||[];
  models.forEach(model=>{const o=document.createElement("option");o.value=model.id;o.textContent=model.label||model.id;sel.appendChild(o);});
  if(sel.options.length){
    const r=await api().set_ocr_backend(sel.value);
    const el=$("ocr-engine");
    el.textContent=(r.label||r.engine)+(r.available?" · ready":" · unavailable");
    el.className=r.available?"":"unavailable";
  }
  S.autoRefresh=!!state.autoRefresh;
  $("auto-cb").classList.toggle("on",S.autoRefresh);
  document.querySelector(".pill-wrap")?.setAttribute("aria-checked",String(S.autoRefresh));
  $("hz-spin").value=state.refreshHz;
  S.refreshHz=Number(state.refreshHz)||5;
  renderCaptureTelemetry();
  if(state.outDir) updateOutDir(state.outDir);
  (state.log||[]).forEach(appendLog);
  updateLogCount();
  resizeCanvas(); setStatus("Ready");
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
