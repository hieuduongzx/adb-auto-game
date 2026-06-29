// ── Init ──────────────────────────────────────────────────────────────────
async function init(){
  let tries=0;
  while(!(window.pywebview&&window.pywebview.api)&&tries<40)
    await new Promise(r=>setTimeout(r,100)),tries++;
  if(!window.pywebview||!window.pywebview.api){setStatus("⚠ pywebview không khả dụng");return;}
  const state=await api().get_state();
  const sel=$("ocr-backend");
  (state.ocrBackends||[]).forEach(b=>{const o=document.createElement("option");o.value=o.textContent=b;sel.appendChild(o);});
  if(sel.options.length){
    const r=await api().set_ocr_backend(sel.value);
    const el=$("ocr-engine");
    el.textContent=r.engine+(r.available?" · sẵn sàng":" · không khả dụng");
    el.className=r.available?"":"unavailable";
  }
  S.autoRefresh=!!state.autoRefresh;
  $("auto-cb").classList.toggle("on",S.autoRefresh);
  $("hz-spin").value=state.refreshHz;
  if(state.outDir) updateOutDir(state.outDir);
  (state.log||[]).forEach(appendLog);
  updateLogCount();
  resizeCanvas(); setStatus("Sẵn sàng");
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();