// ── Keyboard (workflow shortcuts) ─────────────────────────────────────────────
window.addEventListener("keydown", e => {
  const typing = e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  // F1 (hoặc ? ngoài ô nhập) — bảng phím tắt.
  if(e.key==="F1" || (e.key==="?" && !typing)){ e.preventDefault(); if(typeof uiShowShortcuts==="function") uiShowShortcuts(); return; }
  if((e.key==="s"||e.key==="S") && (e.ctrlKey||e.metaKey)){
    e.preventDefault();
    // In Preview mode with a selected region, Ctrl+S = "Capture region" (quick crop)
    // straight into the workflow's templates/ folder. Otherwise it saves the flow.
    if(wfPvActive && wfPvRegion){ pvQuickCrop(); return; }
    wfSave(); return;
  }
  // Ctrl+F — node finder (global: works even while typing, like browser find).
  if((e.key==="f"||e.key==="F") && (e.ctrlKey||e.metaKey)){ e.preventDefault(); if(typeof wfFindShow==="function") wfFindShow(); return; }
  // Undo/Redo — works even while typing in inputs (global shortcuts).
  if((e.key==="z"||e.key==="Z") && (e.ctrlKey||e.metaKey) && !e.shiftKey){ e.preventDefault(); wfUndo(); return; }
  if(((e.key==="z"||e.key==="Z") && (e.ctrlKey||e.metaKey) && e.shiftKey) || ((e.key==="y"||e.key==="Y") && (e.ctrlKey||e.metaKey))){ e.preventDefault(); wfRedo(); return; }

  if(typing) return;   // below here: canvas shortcuts only (let inputs keep native Ctrl+C/V)
  // Tab — toggle Canvas ↔ Preview view (skipped while typing in an input).
  if(e.key==="Tab"){ e.preventDefault(); wfSwitchView(wfPvActive?"canvas":"preview"); return; }
  // Ctrl+= / Ctrl+- / Ctrl+0 — zoom whichever view is active (graph or mirror).
  if((e.ctrlKey||e.metaKey) && (e.key==="="||e.key==="+")){ e.preventDefault();
    if(wfPvActive) wfPvZoomBy(1.2); else wfZoomBy(1.2); return; }
  if((e.ctrlKey||e.metaKey) && e.key==="-"){ e.preventDefault();
    if(wfPvActive) wfPvZoomBy(1/1.2); else wfZoomBy(1/1.2); return; }
  if((e.ctrlKey||e.metaKey) && e.key==="0"){ e.preventDefault();
    if(wfPvActive) wfPvResetZoom(); else wfZoomReset(); return; }
  if((e.key==="c"||e.key==="C") && (e.ctrlKey||e.metaKey)){ if(WF.sel.length){ e.preventDefault(); wfCopy(); } return; }
  if((e.key==="x"||e.key==="X") && (e.ctrlKey||e.metaKey)){ if(WF.sel.length){ e.preventDefault(); wfCut(); } return; }
  if((e.key==="v"||e.key==="V") && (e.ctrlKey||e.metaKey)){ e.preventDefault(); wfPaste(wfPointer.inside?{clientX:wfPointer.x,clientY:wfPointer.y}:null); return; }
  if((e.key==="d"||e.key==="D") && (e.ctrlKey||e.metaKey)){ if(WF.sel.length){ e.preventDefault(); wfDuplicate(); } return; }
  if(e.key===" "){ wfSpace=true; }
  if(e.key==="Delete"||e.key==="Backspace"){ if(WF.sel.length){ e.preventDefault(); wfDeleteSelected(); return; } }
  if((e.key==="a"||e.key==="A") && (e.ctrlKey||e.metaKey)){ const g=wfGraph(); if(g){ e.preventDefault(); WF.sel=g.nodes.map(n=>n.id); WF.selectedNode=null; wfMarkSel(); wfRenderInspector(); return; } }
  if((e.key==="f"||e.key==="F") && !e.ctrlKey && !e.metaKey){ e.preventDefault(); wfFit(); return; }
  if(e.key==="Escape"){ if(typeof wfRunning!=="undefined"&&wfRunning){ e.preventDefault(); wfToggleRun(); return; }
    const vald=document.getElementById("wf-vald"); if(vald){ vald.remove(); return; }
    if(wfGroupMode) wfSetGroupMode(false); wfClearSel(); wfMarkSel(); wfRenderInspector(); }
  if(e.key==="ArrowLeft"||e.key==="ArrowRight"||e.key==="ArrowUp"||e.key==="ArrowDown"){
    if(WF.sel.length){ e.preventDefault();
      const dx=e.key==="ArrowLeft"?-1:e.key==="ArrowRight"?1:0;
      const dy=e.key==="ArrowUp"?-1:e.key==="ArrowDown"?1:0;
      const step=e.shiftKey?10:1;
      const g=wfGraph(); if(g){ WF.sel.forEach(id=>{ const n=g.nodes.find(x=>x.id===id); if(n){ n.x+=dx*step; n.y+=dy*step; } }); wfRenderCanvas(); }
    }
    return;
  }
});
window.addEventListener("keyup", e => { if(e.key===" ") wfSpace=false;
  // Push undo on arrow-key nudge release (batch all nudging into one undo step).
  if(e.key==="ArrowLeft"||e.key==="ArrowRight"||e.key==="ArrowUp"||e.key==="ArrowDown"){ if(WF.sel.length && typeof wfPushUndo==="function") wfPushUndo(); }
});
