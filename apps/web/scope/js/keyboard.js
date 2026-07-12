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
  if(hdr.target && hdr.target.closest("button,.badge")) return;
  hdr.closest(".group").classList.toggle("closed");
}

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(tab){
  document.querySelectorAll(".tab-btn").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
  document.querySelectorAll(".tab-pane").forEach(p=>p.classList.toggle("active",p.id==="tab-"+tab));
  if(tab==="library") onRefreshAssets();
}
