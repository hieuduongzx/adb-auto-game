// ── Keyboard (workflow shortcuts) ─────────────────────────────────────────────
let wfNudging=false;
window.addEventListener("keydown", e => {
  const typing = e.target && (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)||e.target.isContentEditable);
  if(e.key==="Escape" && typeof wfCancelConnect==="function" && wfCancelConnect()){ e.preventDefault(); return; }
  // F1 (or ? outside an input) — shortcuts sheet.
  if(e.key==="F1" || (e.key==="?" && !typing)){ e.preventDefault(); if(typeof uiShowShortcuts==="function") uiShowShortcuts(); return; }
  if((e.key==="s"||e.key==="S") && (e.ctrlKey||e.metaKey)){
    e.preventDefault();
    // In Preview mode with a selected region, Ctrl+S = "Capture region" (quick crop)
    // straight into the workflow's templates/ folder. Otherwise it saves the flow.
    if(wfPvActive && wfPvRegion){ pvQuickCrop(); return; }
    wfSave(); return;
  }
  // Ctrl+K / Ctrl+P — command palette (global, works even while typing).
  if((e.key==="k"||e.key==="K"||e.key==="p"||e.key==="P") && (e.ctrlKey||e.metaKey)){ e.preventDefault(); if(typeof wfCmdShow==="function") wfCmdShow(); return; }
  // Ctrl+F — node finder (global: works even while typing, like browser find).
  if((e.key==="f"||e.key==="F") && (e.ctrlKey||e.metaKey)){ e.preventDefault(); if(typeof wfFindShow==="function") wfFindShow(); return; }
   // Ctrl+Enter — test the selected node (match overlay on Preview).
  if(e.key==="Enter" && (e.ctrlKey||e.metaKey)){
    e.preventDefault();
    if(typeof wfRunSingleNode==="function") wfRunSingleNode();
    return;
  }
  const canvasView=typeof wfCurView!=="function"||wfCurView()==="canvas";
  // Keep native text undo/redo while editing a field. Workflow history is a
  // Canvas action, so Preview/Library can never mutate a graph hidden behind it.
  if(!typing && canvasView && (e.key==="z"||e.key==="Z") && (e.ctrlKey||e.metaKey) && !e.shiftKey){ e.preventDefault(); wfUndo(); return; }
  if(!typing && canvasView && (((e.key==="z"||e.key==="Z") && (e.ctrlKey||e.metaKey) && e.shiftKey) || ((e.key==="y"||e.key==="Y") && (e.ctrlKey||e.metaKey)))){ e.preventDefault(); wfRedo(); return; }

  if(typing) return;   // below here: canvas shortcuts only (let inputs keep native Ctrl+C/V)
  if(e.defaultPrevented) return;
  // Space / arrows stay native on buttons (activation, tablist roving) and
  // resizers. Tab is deliberately NOT in this list: it always toggles
  // Canvas ↔ Preview, even with a button focused — otherwise focus left on e.g.
  // the Preview inspector's Copy button made Tab fall back to native focus
  // traversal, wandering through the panel's buttons/inputs instead of
  // switching views (the advertised behaviour). Text fields returned earlier,
  // so Tab between form fields keeps working.
  if(e.target?.closest?.('button,[role="separator"],[role="tab"],[role="button"]') &&
    [" ","ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) return;
  // Tab — toggle Canvas ↔ Preview.
  if(e.key==="Tab"){ e.preventDefault(); wfSwitchView(wfToggleView()); return; }
  // Ctrl+= / Ctrl+- / Ctrl+0 — zoom whichever view is active (graph or mirror).
  if((e.ctrlKey||e.metaKey) && (e.key==="="||e.key==="+")){ e.preventDefault();
    if(wfPvActive) wfPvZoomBy(1.2); else wfZoomBy(1.2); return; }
  if((e.ctrlKey||e.metaKey) && e.key==="-"){ e.preventDefault();
    if(wfPvActive) wfPvZoomBy(1/1.2); else wfZoomBy(1/1.2); return; }
  if((e.ctrlKey||e.metaKey) && e.key==="0"){ e.preventDefault();
    if(wfPvActive) wfPvResetZoom(); else wfZoomReset(); return; }
  // Space — held it is the pan modifier (Space+drag) in both Canvas and Preview;
  // double-tapped without panning it resets the zoom (see keyup below). A single
  // tap does nothing, so a stray Space press can't throw the view away. This
  // sits before the Canvas-only guard so the Preview mirror gets it too.
  if(e.key===" " && !e.ctrlKey && !e.metaKey && !e.altKey && (canvasView || wfCurView()==="preview")){
    if(!e.repeat) wfSpaceUsed=false;
    wfSpace=true; wfSpaceArmed=true;
  }
  if(!canvasView){
    if(e.key==="Escape" && typeof wfClearSel==="function"){ wfClearSel(); if(typeof wfMarkSel==="function") wfMarkSel(); }
    return;
  }
  if((e.key==="c"||e.key==="C") && (e.ctrlKey||e.metaKey)){ if(WF.sel.length){ e.preventDefault(); wfCopy(); } return; }
  if((e.key==="x"||e.key==="X") && (e.ctrlKey||e.metaKey)){ if(WF.sel.length){ e.preventDefault(); wfCut(); } return; }
  if((e.key==="v"||e.key==="V") && (e.ctrlKey||e.metaKey)){ e.preventDefault(); wfPaste(wfPointer.inside?{clientX:wfPointer.x,clientY:wfPointer.y}:null); return; }
  if((e.key==="d"||e.key==="D") && (e.ctrlKey||e.metaKey)){ if(WF.sel.length){ e.preventDefault(); wfDuplicate(); } return; }
  if(e.key==="Delete"||e.key==="Backspace"){ if(WF.sel.length){ e.preventDefault(); wfDeleteSelected(); return; } }
  if((e.key==="a"||e.key==="A") && (e.ctrlKey||e.metaKey)){ const g=wfGraph(); if(g){ e.preventDefault(); WF.sel=g.nodes.map(n=>n.id); WF.selectedNode=null; wfMarkSel(); wfRenderInspector(); return; } }
  if((e.key==="f"||e.key==="F") && !e.ctrlKey && !e.metaKey){ e.preventDefault(); if(e.shiftKey) wfFitSelection(); else wfFit(); return; }
  if(e.key==="Escape"){ if(typeof wfRunning!=="undefined"&&wfRunning){ e.preventDefault(); wfToggleRun(); return; }
    const vald=document.getElementById("wf-vald"); if(vald){ vald.remove(); return; }
    if(wfGroupMode) wfSetGroupMode(false); wfClearSel(); wfMarkSel(); wfRenderInspector(); }
  if(e.key==="ArrowLeft"||e.key==="ArrowRight"||e.key==="ArrowUp"||e.key==="ArrowDown"){
    if(WF.sel.length){ e.preventDefault();
      if(!wfNudging){ wfPushUndo(); wfNudging=true; }
      const dx=e.key==="ArrowLeft"?-1:e.key==="ArrowRight"?1:0;
      const dy=e.key==="ArrowUp"?-1:e.key==="ArrowDown"?1:0;
      const step=e.shiftKey?10:1;
      const g=wfGraph(); if(g){ WF.sel.forEach(id=>{ const n=g.nodes.find(x=>x.id===id); if(n){ n.x+=dx*step; n.y+=dy*step; } }); wfRenderCanvas(); }
    }
    return;
  }
});
// Reset the zoom of whichever view is showing (graph → 100% around the centre,
// mirror → fit). Library has no zoom.
function wfResetViewZoom(){
  const v=wfCurView();
  if(v==="preview") wfPvResetZoom(); else if(v==="canvas") wfZoomReset();
}
// Two clean Space taps closer together than this reset the zoom.
const WF_SPACE_DOUBLE_MS=350;
let wfSpaceLastTap=0;   // performance.now() of the previous clean tap, 0 = none pending
window.addEventListener("keyup", e => {
  if(e.key===" "){
    const tapped=wfSpaceArmed && !wfSpaceUsed;
    wfSpace=false; wfSpaceArmed=false; wfSpaceUsed=false;
    if(!tapped) wfSpaceLastTap=0;            // a pan (or a Space that was never ours) breaks the pair
    else {
      const now=performance.now();
      if(wfSpaceLastTap && now-wfSpaceLastTap<=WF_SPACE_DOUBLE_MS){ wfSpaceLastTap=0; wfResetViewZoom(); }
      else wfSpaceLastTap=now;
    }
  }
  if(e.key.startsWith("Arrow")) wfNudging=false;
});
// Losing focus mid-press must not count as a tap — the keyup never arrives.
window.addEventListener("blur",()=>{ wfNudging=false; wfSpace=false; wfSpaceArmed=false; wfSpaceUsed=false; wfSpaceLastTap=0; });
