// ── Keyboard ──────────────────────────────────────────────────────────────
window.addEventListener("keydown", e => {
  if(e.key==="F5"){e.preventDefault();onCapture();}
  if(e.key==="Escape") onClearLog();
  if(e.key==="0"&&(e.ctrlKey||e.metaKey)){e.preventDefault();resetZoom();}
});

// ── Zoom / pan ─────────────────────────────────────────────────────────────
function resetZoom(){
  S.zoomLevel=1;S.panX=0;S.panY=0;recomputeLayout();
  $("zoom-level").textContent="100%"; draw();
}

// ── Groups collapsible ────────────────────────────────────────────────────
function toggleGrp(hdr){
  const closed=hdr.closest(".group").classList.toggle("closed");
  hdr.setAttribute("aria-expanded",String(!closed));
}

function toggleCheck(button,id){
  const checked=$(id).classList.toggle("checked");
  button.setAttribute("aria-checked",String(checked));
}

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(tab){
  document.querySelectorAll(".tab-btn").forEach(b=>{const on=b.dataset.tab===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on));});
  document.querySelectorAll(".tab-pane").forEach(p=>p.classList.toggle("active",p.id==="tab-"+tab));
  if(tab==="library") onRefreshAssets();
}
