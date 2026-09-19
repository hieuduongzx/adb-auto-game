// ── Scope tool panel (Preview tab inspector) ────────────────────────────────
// Mirrors DevScope's tool handlers but targets the pv-* elements inside the
// workflow designer's inspector and the live preview canvas (preview.js owns the
// frame + overlays). Shares wfPvPoint / wfPvRegion / wfPvOverlay / wfPvDraw.

function pvCopyText(text, btn){
  navigator.clipboard.writeText(text);
  const m=String(text||"").match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if(m && typeof wfPvPoint!="undefined"){
    wfPvPoint=[Number(m[1]),Number(m[2])];
    window.wfCopiedPoint=wfPvPoint.slice();
  }
  if(btn){ btn.classList.add("flash"); setTimeout(()=>btn.classList.remove("flash"),700); }
}
function pvCopyEl(id, btn){ pvCopyText($(id).value, btn); }

let pvDeviceInfoCopyReady=false;
function pvInitDeviceInfoCopy(){
  if(pvDeviceInfoCopyReady) return;
  const grid=document.querySelector("#pv-tab-device .info-grid");
  if(!grid) return;
  pvDeviceInfoCopyReady=true;
  grid.addEventListener("click", e=>{
    const cell=e.target.closest(".k,.v");
    if(!cell || !grid.contains(cell)) return;
    const cells=[...grid.children];
    const idx=cells.indexOf(cell);
    const val=cells[idx%2===0?idx+1:idx];
    if(!val) return;
    pvCopyText(val.textContent.trim());
    setStatus("Copied");
  });
}

function pvSetRegionBadge(on){ const b=$("pv-region-badge"); if(b) b.style.display=on?"inline-flex":"none"; }

// Fill the Point & Color readouts from a set_point / set_region result.
// pvSetXY writes every coordinate tester at once (some rows are Win32-only and
// may be absent/hidden), so picking a point primes them all.
function pvSetXY(x,y){
  [["pv-tap-x","pv-tap-y"],["pv-lp-x","pv-lp-y"],["pv-cc-x","pv-cc-y"],
   ["pv-win-cx","pv-win-cy"]].forEach(([kx,ky])=>{
    const ex=$(kx), ey=$(ky); if(ex) ex.value=x; if(ey) ey.value=y;
  });
}
function pvFillPoint(r){
  if(!r) return;
  $("pv-pt-x").value=r.x; $("pv-pt-y").value=r.y;
  pvSetXY(r.x, r.y);
  if(r.hex){
    $("pv-pt-hex").value=r.hex; $("pv-pt-rgb").value=r.rgb;
    $("pv-color-swatch").style.background=r.hex;
    $("pv-cc-hex").value=r.hex; $("pv-cc-swatch").style.background=r.hex;
  }
}
function pvFillRegion(r){
  if(!r) return;
  $("pv-rg-x").value=r.x; $("pv-rg-y").value=r.y; $("pv-rg-w").value=r.w; $("pv-rg-h").value=r.h;
  pvSetXY(r.centerX, r.centerY);
  $("pv-pt-x").value=r.centerX;  $("pv-pt-y").value=r.centerY;
  if(r.hex){
    $("pv-pt-hex").value=r.hex; $("pv-pt-rgb").value=r.rgb;
    $("pv-color-swatch").style.background=r.hex;
    $("pv-cc-hex").value=r.hex; $("pv-cc-swatch").style.background=r.hex;
  }
}

// ── Tabs + collapsible groups (scope parity) ────────────────────────────────
function pvSwitchTab(tab){
  document.querySelectorAll("#wf-scope-panel .tab-btn").forEach(b=>{const on=b.dataset.tab===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on));});
  document.querySelectorAll("#wf-scope-panel .tab-pane").forEach(p=>p.classList.toggle("active",p.id==="pv-tab-"+tab));
}
function toggleGrp(hdr){
  const g = hdr.closest ? hdr.closest(".group") : hdr.parentElement;
  if(g){
    const closed=g.classList.toggle("closed");
    hdr.setAttribute("aria-expanded",String(!closed));
  }
}
function pvToggleCheck(button,id){
  const checked=$(id).classList.toggle("checked");
  button.setAttribute("aria-checked",String(checked));
}

// ── Capture / save ──────────────────────────────────────────────────────────
function pvCapture(){ wfPvCapture(); }
async function pvSaveFull(){ await api().save_full($("pv-full-name").value); }
async function pvTapPoint(){ await api().tap(parseInt($("pv-pt-x").value||"0"),parseInt($("pv-pt-y").value||"0")); }

// ── Color check ─────────────────────────────────────────────────────────────
async function pvCheckColor(){
  const r=await api().check_color(parseInt($("pv-cc-x").value||"0"),parseInt($("pv-cc-y").value||"0"),$("pv-cc-hex").value.trim(),parseInt($("pv-cc-tol").value||"10"));
  const el=$("pv-cc-result"); el.style.display="block";
  if(r.error){ el.className="cc-result bad"; el.textContent=r.error; return; }
  el.className="cc-result "+(r.match?"ok":"bad");
  el.innerHTML=r.match
    ?`✓ Match &nbsp;·&nbsp; actual: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`
    :`✗ No match &nbsp;·&nbsp; actual: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`;
}

// ── Region ──────────────────────────────────────────────────────────────────
// "Capture region" saves the current drag-region crop into the open workflow's
// templates/ folder (resolved by the backend) so it's ready to use as a node
// template. The path comes back from Python so we can confirm where it landed.
async function pvQuickCrop(){
  const path = await api().quick_crop($("pv-crop-name").value);
  if(!path){ setStatus("No region — drag-select a region on the image first"); return; }
  setStatus(`Saved region → ${path}`);
  // The crop landed in the workflow's templates folder, which is exactly what
  // the Library lists — point the user at it rather than leaving them to guess
  // where a new crop goes (the old inline asset browser is gone).
  uiToast("Đã lưu crop vào thư viện template", "success");
}
async function pvClearRegion(){
  $("pv-rg-x").value=$("pv-rg-y").value=$("pv-rg-w").value=$("pv-rg-h").value=0;
  await api().clear_selection();
  wfPvRegion=null; wfPvPoint=null; wfPvOverlay=[]; pvSetRegionBadge(false); wfPvDraw();
}

// ── Swipe capture (copy on Preview → paste on the Canvas) ───────────────────
// Drawing a swipe on the mirror (right-drag) fills the Swipe row of the Actions
// group and leaves the path drawn on the frame. This mirrors the region
// copy/paste flow: the readout below the fields is copy-ready, and pasting that
// text into a Swipe block's X1/Y1/X2/Y2 field fills the whole gesture.
function pvSwipeVals(){
  const num=(id,fallback)=>{ const el=$(id); const v=el?parseFloat(el.value):NaN;
    return Number.isFinite(v)?v:fallback; };
  return {
    x1:num("pv-sw-x1",0), y1:num("pv-sw-y1",0),
    x2:num("pv-sw-x2",0), y2:num("pv-sw-y2",0),
    duration:Math.max(0, Math.round(num("pv-sw-dur",300))),
  };
}
// Called from preview.js when a right-drag swipe is released.
function pvFillSwipe(x1,y1,x2,y2,dur){
  const set=(id,v)=>{ const el=$(id); if(el) el.value=v; };
  set("pv-sw-x1",x1); set("pv-sw-y1",y1); set("pv-sw-x2",x2); set("pv-sw-y2",y2);
  if(Number.isFinite(dur)) set("pv-sw-dur",dur);
  pvUpdateSwipePreview();
}
function pvUpdateSwipePreview(){
  const s=pvSwipeVals();
  const summary=$("pv-sw-summary");
  if(summary) summary.textContent=`${s.x1}, ${s.y1} → ${s.x2}, ${s.y2} · ${s.duration} ms`;
  pvDrawSwipeMini(s);
}
// Mini device diagram: the panel is too narrow for the full mirror, so the
// swipe is redrawn against the same device aspect ratio at a glanceable size.
function pvDrawSwipeMini(s){
  const cv=$("pv-sw-preview"); if(!cv) return;
  const ctx=cv.getContext("2d");
  const dpr=window.devicePixelRatio||1;
  const w=Math.max(120, cv.clientWidth||220), h=Math.max(44, cv.clientHeight||72);
  if(cv.width!==Math.round(w*dpr)||cv.height!==Math.round(h*dpr)){
    cv.width=Math.round(w*dpr); cv.height=Math.round(h*dpr);
  }
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,h);
  // Live frame dimensions when a capture exists; otherwise assume a phone.
  const sw=(typeof wfPvImgW==="number"&&wfPvImgW>0)?wfPvImgW:1080;
  const sh=(typeof wfPvImgH==="number"&&wfPvImgH>0)?wfPvImgH:1920;
  const pad=7, scale=Math.min((w-pad*2)/sw,(h-pad*2)/sh);
  const dw=sw*scale, dh=sh*scale, dx=(w-dw)/2, dy=(h-dh)/2;
  ctx.fillStyle="rgba(127,140,160,.08)"; ctx.fillRect(dx,dy,dw,dh);
  ctx.strokeStyle="rgba(127,140,160,.45)"; ctx.lineWidth=1;
  ctx.strokeRect(dx+0.5, dy+0.5, dw-1, dh-1);
  const toX=x=>dx+Math.max(0,Math.min(sw,x))*scale;
  const toY=y=>dy+Math.max(0,Math.min(sh,y))*scale;
  const x1=toX(s.x1), y1=toY(s.y1), x2=toX(s.x2), y2=toY(s.y2);
  const ang=Math.atan2(y2-y1,x2-x1);
  ctx.strokeStyle="#4f8df0"; ctx.fillStyle="#4f8df0"; ctx.lineWidth=2; ctx.lineCap="round";
  ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
  if(Math.hypot(x2-x1,y2-y1)>2){   // arrowhead (skipped for a zero-length swipe)
    ctx.beginPath(); ctx.moveTo(x2,y2);
    ctx.lineTo(x2-8*Math.cos(ang-.45), y2-8*Math.sin(ang-.45));
    ctx.lineTo(x2-8*Math.cos(ang+.45), y2-8*Math.sin(ang+.45));
    ctx.closePath(); ctx.fill();
  }
  ctx.beginPath(); ctx.arc(x1,y1,4,0,Math.PI*2); ctx.stroke();   // start ring
  ctx.beginPath(); ctx.arc(x2,y2,3,0,Math.PI*2); ctx.fill();     // end dot
}
function pvCopySwipe(btn){
  const s=pvSwipeVals();
  pvCopyText(`${s.x1}, ${s.y1}, ${s.x2}, ${s.y2}, ${s.duration}`, btn);
  setStatus(`Swipe copied (${s.x1},${s.y1}) → (${s.x2},${s.y2}) · ${s.duration}ms — paste into a Swipe block`);
}
function pvClearSwipePreview(){
  if(typeof wfPvSwipe!=="undefined") wfPvSwipe=null;
  if(typeof wfPvActive!=="undefined" && wfPvActive && typeof wfPvDraw==="function") wfPvDraw();
  setStatus("Swipe overlay cleared");
}

// ── OCR ─────────────────────────────────────────────────────────────────────
async function pvOcrBackendChange(name){
  const r=await api().set_ocr_backend(name);
  const el=$("pv-ocr-engine");
  el.textContent=(r.label||wfOcrModelLabel(r.engine))+(r.available?" · ready":" · unavailable");
  el.className=r.available?"":"unavailable";
}
async function pvReadText(){ $("pv-ocr-result").value=await api().read_text($("pv-ocr-wl").value); }

// ── Actions ─────────────────────────────────────────────────────────────────
async function pvSendTap(){ await api().tap(parseInt($("pv-tap-x").value||"0"),parseInt($("pv-tap-y").value||"0")); }
async function pvSendLongPress(){ await api().long_press(parseInt($("pv-lp-x").value||"0"),parseInt($("pv-lp-y").value||"0"),parseInt($("pv-lp-dur").value||"800")); }
async function pvSendSwipe(){ await api().swipe(parseInt($("pv-sw-x1").value||"0"),parseInt($("pv-sw-y1").value||"0"),parseInt($("pv-sw-x2").value||"0"),parseInt($("pv-sw-y2").value||"0"),parseInt($("pv-sw-dur").value||"300")); }
async function pvSendText(){ const t=$("pv-inp-text").value; if(t){ await api().input_text(t); $("pv-inp-text").value=""; } }
// Win32-only: right/middle click + mouse wheel (no ADB equivalent).
async function pvSendWinClick(){
  await api().preview_click(parseInt($("pv-win-cx").value||"0"),parseInt($("pv-win-cy").value||"0"),
    $("pv-win-btn").value||"right",1);
}
async function pvSendWinScroll(){
  await api().preview_scroll(parseInt($("pv-win-cx").value||"0"),parseInt($("pv-win-cy").value||"0"),
    $("pv-win-wdir").value||"down",parseInt($("pv-win-wn").value||"3"));
}

// ── Template matching ───────────────────────────────────────────────────────
async function pvBrowseTpl(){ const p=await api().pick_template(); if(p) $("pv-tpl-path").value=p; }
async function pvRunMatch(all){
  const r=await api().match_template($("pv-tpl-path").value,parseFloat($("pv-tpl-thr").value||".85"),$("pv-cb-gray").classList.contains("checked"),$("pv-cb-multiscale").classList.contains("checked"),all);
  const el=$("pv-tpl-result");
  if(r.error){ el.textContent=r.error; el.className="tpl-result empty"; return; }
  el.textContent=r.summary; el.className="tpl-result";
  // DevScope match_template returns [x,y,w,h,conf] — treat as ok hits.
  wfPvOverlay=(r.rects||[]).map(rect=>{
    if(Array.isArray(rect) && rect.length===5) return rect.concat([1,""]);
    return rect;
  });
  wfPvMatchRegion=null; wfPvOverlayMeta=r;
  wfPvDraw();
}
async function pvClearOverlay(){ await api().clear_overlay(); wfPvOverlay=[]; wfPvMatchRegion=null; wfPvOverlayMeta=null; wfPvDraw(); }

// ── Output dir label ─────────────────────────────────────────────────────────
// The asset browser that used to live here moved to the Library tab, so this
// now only labels where the next crop will land.
function pvUpdateOutDir(p){
  const norm=String(p).replace(/\\/g,'/');
  const parts=norm.split('/').filter(Boolean);
  const short=parts.length>1?'…/'+parts.slice(-2).join('/')+'/' : (norm.endsWith('/')?norm:norm+'/');
  const lbl=$("pv-out-dir-label"); if(lbl){ lbl.textContent=short; lbl.title=p; }
}

// ── Populate OCR backend dropdown from get_state ───────────────────────────
async function pvInitOcrBackends(){
  const sel=$("pv-ocr-backend"); if(!sel) return;
  let models=[];
  try{ const st=await api().get_state(); models=st.ocrModels||st.ocrBackends||[]; }catch{}
  if(!models.length) models=WF_OCR_MODELS;
  sel.innerHTML="";
  models.forEach(model=>{ const id=typeof model==="string"?model:model.id; const o=document.createElement("option"); o.value=id; o.textContent=(typeof model==="string"?wfOcrModelLabel(id):model.label)||id; sel.appendChild(o); });
  if(sel.options.length){ await pvOcrBackendChange(sel.value); }
}
