// ── Preview tab — live device screen mirror (scope-like) ────────────────────
// Only activates when the user switches to the Preview view tab. Uses the same
// scrcpy/ADB capture backend as DevScope: frames are pushed from Python via
// window.__recvFrame(dataUrl, w, h). While the tab is hidden we stop auto-refresh
// so no capture work happens in the background.

let wfPvActive = false;        // true only while the Preview tab is visible
let wfPvAuto   = true;         // auto-refresh toggle
let wfPvHz     = 30;           // refresh rate (Hz)
let wfPvReady  = false;        // preview system initialised
let wfPvImg    = null;         // current frame Image
let wfPvImgW   = 0, wfPvImgH = 0;
let wfPvCtx    = null;
let wfPvCanvas = null;
let wfPvWrap   = null;
let wfPvErr    = "";           // last capture error text (shown until next frame)

// Overlay draw colours — pulled from the shared CSS vars (base.css :root) so the
// canvas overlay stays in sync with the same fail/info/warn hues used elsewhere.
const WF_PV_COLOR = (function(){
  const cs=getComputedStyle(document.documentElement);
  const v=(name,fallback)=>(cs.getPropertyValue(name)||fallback).trim();
  return { fail:v("--run-fail","#dc2626"), info:v("--run-info","#06b6d4"), warn:v("--run-warn","#eab308") };
})();

// ── View tab switching ──────────────────────────────────────────────────────
function wfSwitchView(view){
  document.querySelectorAll(".wf-view-tab").forEach(t=>t.classList.toggle("sel", t.dataset.view===view));
  const canvas = document.getElementById("wf-canvas");
  const preview = document.getElementById("wf-preview-pane");
  const world = document.getElementById("wf-world");
  const empty = document.getElementById("wf-canvas-empty");
  // Graph-only chrome: hide the pinned panels + empty hint while previewing.
  const graphOnly = [world, empty,
    document.getElementById("wf-corner-stack"),
    document.getElementById("wf-layout-bar")];

  if(view==="preview"){
    if(canvas) canvas.style.overflow = "hidden";
    graphOnly.forEach(el=>{ if(el) el.style.display="none"; });
    if(typeof wfCloseLayoutMenu==="function") wfCloseLayoutMenu();
    if(preview) preview.style.display = "flex";
    // Swap the inspector from node-properties to the DevScope tool panel.
    const inspBody=document.getElementById("wf-insp-body");
    const scopePanel=document.getElementById("wf-scope-panel");
    const inspTitle=document.getElementById("wf-insp-title");
    if(inspBody) inspBody.style.display="none";
    if(scopePanel){ scopePanel.style.display="flex"; }
    if(inspTitle) inspTitle.textContent="DevScope tools";
    wfPvActive = true;
    wfPvInit();                 // lazy init on first switch
    wfPvResize();
    pvInitOcrBackends();        // populate OCR dropdown (no-op after first)
    api().refresh_info();       // seed the device tab
    api().scope_out_dir().then(p=>{ if(p) pvUpdateOutDir(p); });  // resolve + label the crop folder
    if(wfPvAuto) wfPvStartAuto();
    wfPvCapture();              // grab one frame immediately
    wfZoomApplyMode("preview"); // repurpose the shared zoom cluster for the mirror
  } else {
    wfPvActive = false;
    wfPvStopAuto();
    if(preview) preview.style.display = "none";
    graphOnly.forEach(el=>{ if(el && el!==empty) el.style.display=""; });
    if(empty) empty.style.display = wfGraph() ? "none" : "flex";  // re-evaluate the empty hint
    if(canvas) canvas.style.overflow = "";
    // Restore the node-properties inspector.
    const inspBody=document.getElementById("wf-insp-body");
    const scopePanel=document.getElementById("wf-scope-panel");
    const inspTitle=document.getElementById("wf-insp-title");
    if(inspBody) inspBody.style.display="";
    if(scopePanel) scopePanel.style.display="none";
    if(inspTitle) inspTitle.textContent="Properties";
    wfZoomApplyMode("canvas");  // hand the zoom cluster back to the graph
  }
}

// Repurpose the shared toolbar zoom cluster (−/label/+/fit) for whichever view
// is active. Canvas mode wires it to the graph (wfZoomBy/wfZoomReset/wfFit);
// Preview mode wires it to the mirror (wfPvZoomBy/wfPvResetZoom/wfPvFit) and
// refreshes the label from the current preview zoom.
function wfZoomApplyMode(mode){
  const zspan=document.querySelector(".wf-zoom");
  if(!zspan) return;
  const btns=zspan.querySelectorAll("button");
  const out=btns[0], fit=btns[btns.length-1], inb=btns.length>=3?btns[1]:null;
  const lbl=document.getElementById("wf-zoom-lbl");
  if(mode==="preview"){
    if(out) out.onclick=()=>wfPvZoomBy(1/1.1);
    if(inb) inb.onclick=()=>wfPvZoomBy(1.1);
    if(lbl){ lbl.onclick=wfPvResetZoom; lbl.title="Reset 100% (Preview)"; }
    if(fit){ fit.onclick=wfPvFit; fit.title="Fit image (Preview)"; }
    if(lbl) lbl.textContent=Math.round(wfPvZoom*100)+"%";
  } else {
    if(out) out.onclick=()=>wfZoomBy(1/1.1);
    if(inb) inb.onclick=()=>wfZoomBy(1.1);
    if(lbl){ lbl.onclick=wfZoomReset; lbl.title="Reset 100%"; }
    if(fit){ fit.onclick=wfFit; fit.title="Fit view — show all blocks (F)"; }
    if(lbl) lbl.textContent=Math.round(wfZoom*100)+"%";
  }
}

// ── Lazy initialisation ─────────────────────────────────────────────────────
function wfPvInit(){
  if(wfPvReady) return;
  wfPvReady = true;
  wfPvCanvas = document.getElementById("wf-pv-canvas");
  wfPvWrap   = document.getElementById("wf-pv-wrap");
  if(!wfPvCanvas) return;
  wfPvCtx = wfPvCanvas.getContext("2d");

  const capBtn = document.getElementById("wf-pv-capture");
  if(capBtn) capBtn.onclick = (e)=>{ e.stopPropagation(); wfPvCapture(); };

  const autoBtn = document.getElementById("wf-pv-auto");
  if(autoBtn) autoBtn.onclick = (e)=>{
    e.stopPropagation();
    wfPvAuto = !wfPvAuto;
    const cb = autoBtn.querySelector(".wf-pv-cb");
    if(cb) cb.classList.toggle("on", wfPvAuto);
    if(wfPvAuto && wfPvActive) wfPvStartAuto();
    else wfPvStopAuto();
  };

  const hzInput = document.getElementById("wf-pv-hz");
  if(hzInput) hzInput.onchange = ()=>{
    wfPvHz = Math.max(0.2, Math.min(30, parseFloat(hzInput.value)||30));
    hzInput.value = wfPvHz;
    if(wfPvAuto && wfPvActive){ wfPvStopAuto(); wfPvStartAuto(); }
  };
  if(typeof pvInitDeviceInfoCopy==="function") pvInitDeviceInfoCopy();

  // Tap on the mirror → send a tap to the device at the image-space point.
  // (Replaced by the full DevScope interaction set in wfPvAttachCanvas —
  // left-click picks a point, left-drag selects a region, right-click taps,
  // middle-drag pans, wheel zooms.)
  wfPvAttachCanvas();

  // The preview pane sits inside #wf-canvas; stop graph interactions (box-select,
  // pan, zoom) from firing through it while the mirror is visible.
  const pane = document.getElementById("wf-preview-pane");
  if(pane){
    pane.addEventListener("mousedown", e=>e.stopPropagation());
    pane.addEventListener("wheel",   e=>e.stopPropagation());
    pane.addEventListener("contextmenu", e=>e.preventDefault());
  }

  window.addEventListener("resize", ()=>{ if(wfPvActive) wfPvResize(); });
}

function wfPvResize(){
  if(!wfPvCanvas || !wfPvWrap) return;
  const r = wfPvWrap.getBoundingClientRect();
  wfPvCanvas.width  = Math.max(1, Math.floor(r.width));
  wfPvCanvas.height = Math.max(1, Math.floor(r.height));
  if(wfPvImg) wfPvDraw();
  else wfPvDrawEmpty();
}

// ── Layout: fit + center, with an independent zoom/pan on top (DevScope model)
//    ef = scale * zoomLevel is the effective pixels-per-image-pixel; ox/oy place
//    the image top-left after pan. Scope tool state (point/region/overlay) is
//    drawn on top of the frame each redraw.
let wfPvScale=1, wfPvOx=0, wfPvOy=0;
let wfPvZoom=1, wfPvPanX=0, wfPvPanY=0;
// Scope selection state — shared with scope-tools.js. Set/cleared by canvas
// interactions and Python events; redrawn by wfPvDraw.
let wfPvPoint=null;                 // [x,y] in image coords
let wfPvRegion=null;                // [x,y,w,h] in image coords
let wfPvOverlay=[];                 // [[x,y,w,h,conf], ...] match rects
let wfPvDragging=false, wfPvDragStart=null, wfPvDragEnd=null;
let wfPvPanning=false, wfPvPanStart=null, wfPvPanBase=null;

function wfPvRecompute(){
  if(!wfPvImg || !wfPvImgW || !wfPvCanvas){ wfPvScale=1; wfPvOx=0; wfPvOy=0; return; }
  const cw=Math.max(1,wfPvCanvas.width), ch=Math.max(1,wfPvCanvas.height);
  wfPvScale=Math.min(cw/wfPvImgW, ch/wfPvImgH);
  const ef=wfPvScale*wfPvZoom;
  wfPvOx=(cw-wfPvImgW*ef)/2+wfPvPanX;
  wfPvOy=(ch-wfPvImgH*ef)/2+wfPvPanY;
}
function wfPvImgToCanvas(x,y){ const ef=wfPvScale*wfPvZoom; return [wfPvOx+x*ef, wfPvOy+y*ef]; }
function wfPvCanvasToImg(clientX, clientY){
  const ef=wfPvScale*wfPvZoom; if(!ef) return null;
  const r=wfPvCanvas.getBoundingClientRect();
  const cx=clientX-r.left, cy=clientY-r.top;
  const ix=Math.round((cx-wfPvOx)/ef), iy=Math.round((cy-wfPvOy)/ef);
  if(ix<0||iy<0||ix>=wfPvImgW||iy>=wfPvImgH) return null;
  return [ix, iy];
}
function wfPvCanvasPos(e){ const r=wfPvCanvas.getBoundingClientRect(); return [e.clientX-r.left, e.clientY-r.top]; }

function wfPvDraw(){
  const cvs=wfPvCanvas; if(!cvs||!wfPvCtx||!wfPvImg) return;
  const ctx=wfPvCtx, cw=cvs.width, ch=cvs.height;
  wfPvRecompute();
  ctx.clearRect(0,0,cw,ch);
  ctx.fillStyle="#121316"; ctx.fillRect(0,0,cw,ch);
  ctx.imageSmoothingEnabled=true; ctx.imageSmoothingQuality="high";
  const [x0,y0]=wfPvImgToCanvas(0,0), [x1,y1]=wfPvImgToCanvas(wfPvImgW,wfPvImgH);
  ctx.drawImage(wfPvImg, x0, y0, x1-x0, y1-y0);

  // Template-match overlay rects (red, with confidence label).
  ctx.strokeStyle=WF_PV_COLOR.fail; ctx.lineWidth=2; ctx.fillStyle=WF_PV_COLOR.fail;
  ctx.font="11px IBM Plex Mono,monospace"; ctx.textAlign="left";
  for(const r of wfPvOverlay){
    const [cx,cy]=wfPvImgToCanvas(r[0],r[1]), [cx2,cy2]=wfPvImgToCanvas(r[0]+r[2],r[1]+r[3]);
    ctx.strokeRect(cx,cy,cx2-cx,cy2-cy);
    ctx.fillText((r[4]||0).toFixed(2), cx+2, cy-4);
  }
  // Selected region (cyan).
  if(wfPvRegion){
    const [x,y,w,h]=wfPvRegion;
    const [cx,cy]=wfPvImgToCanvas(x,y), [cx2,cy2]=wfPvImgToCanvas(x+w,y+h);
    ctx.strokeStyle=WF_PV_COLOR.info; ctx.lineWidth=2; ctx.strokeRect(cx,cy,cx2-cx,cy2-cy);
  }
  // Picked point (yellow crosshair).
  if(wfPvPoint){
    const [cx,cy]=wfPvImgToCanvas(wfPvPoint[0],wfPvPoint[1]);
    ctx.strokeStyle=WF_PV_COLOR.warn; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(cx-8,cy); ctx.lineTo(cx+8,cy);
    ctx.moveTo(cx,cy-8); ctx.lineTo(cx,cy+8); ctx.stroke();
  }
  // Live drag rectangle while selecting a region.
  if(wfPvDragging && wfPvDragStart && wfPvDragEnd){
    const r=wfPvNormRect(wfPvDragStart, wfPvDragEnd);
    ctx.strokeStyle="rgba(6,182,212,.8)"; ctx.lineWidth=1;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
  }
  const res=document.getElementById("wf-pv-res");
  if(res) res.textContent = `${wfPvImgW} × ${wfPvImgH}`;
  // Mirror the zoom into the shared toolbar label (#wf-zoom-lbl) so the same
  // cluster serves both Canvas and Preview views.
  const zl=document.getElementById("wf-zoom-lbl");
  if(zl) zl.textContent = Math.round(wfPvZoom*100)+"%";
}
function wfPvNormRect(a,b){
  return {x:Math.min(a[0],b[0]), y:Math.min(a[1],b[1]),
          w:Math.abs(a[0]-b[0]), h:Math.abs(a[1]-b[1])};
}

function wfPvDrawEmpty(){
  const cvs=wfPvCanvas; if(!cvs||!wfPvCtx) return;
  const ctx=wfPvCtx, cw=cvs.width, ch=cvs.height, cx=cw/2, cy=ch/2;
  ctx.clearRect(0,0,cw,ch);
  // Soft radial vignette instead of a flat void — reads as a "screen off" panel.
  const g=ctx.createRadialGradient(cx,cy*0.9,0,cx,cy,Math.max(cw,ch)*0.7);
  g.addColorStop(0,"#1c2027"); g.addColorStop(1,"#0e1013");
  ctx.fillStyle=g; ctx.fillRect(0,0,cw,ch);

  // Win32 projects capture a native window — no ADB device required, so the
  // placeholder must not claim "No device connected" there.
  const isWin32 = (typeof WF!=="undefined" && WF.controller==="win32");
  const hasSrc = isWin32 ? !!((WF.win32||{}).window) : !!S.connectedSerial;
  const err=!!wfPvErr, busy=!err && hasSrc;
  const accent = err ? "#e0736b" : busy ? "#5aa9e6" : "#5b6675";
  // Phone-outline glyph, centred just above the text.
  const iw=44, ih=72, ix=cx-iw/2, iy=cy-ih/2-26;
  ctx.save();
  ctx.strokeStyle=accent; ctx.lineWidth=2.4; ctx.lineJoin="round"; ctx.globalAlpha=err?.9:.55;
  const rr=(x,y,w,h,r)=>{ ctx.beginPath();
    ctx.moveTo(x+r,y); ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
    ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath(); ctx.stroke(); };
  rr(ix,iy,iw,ih,8);
  ctx.globalAlpha=err?.9:.4; ctx.beginPath();
  ctx.moveTo(cx-6,iy+ih-7); ctx.lineTo(cx+6,iy+ih-7); ctx.stroke();  // home bar
  ctx.restore();

  ctx.textAlign="center";
  const title = err ? "Capture error" : busy ? "Capturing…" : (isWin32 ? "No target window" : "No device connected");
  const sub   = err ? String(wfPvErr) : busy ? "Waiting for the first frame"
    : (isWin32 ? "Pick a target window in Project settings, then press Capture"
               : "Connect a device or emulator, then press Capture");
  ctx.fillStyle = err ? "#eab3ad" : "#c2cad4";
  ctx.font="600 15px IBM Plex Sans,Segoe UI,sans-serif";
  ctx.fillText(title, cx, cy+18);
  ctx.fillStyle="#7c8795";
  ctx.font="12px IBM Plex Sans,Segoe UI,sans-serif";
  ctx.fillText(sub.length>70?sub.slice(0,67)+"…":sub, cx, cy+40);
}

function wfPvResetZoom(){
  wfPvZoom=1; wfPvPanX=0; wfPvPanY=0; wfPvDraw();
}
// Zoom the preview by a factor (used by the shared toolbar +/− buttons while
// the Preview tab is active).
function wfPvZoomBy(f){ wfPvZoom=Math.max(.3, Math.min(10, wfPvZoom*f)); wfPvDraw(); }
// Fit the device image to the canvas (reset zoom/pan) — the Preview analogue of
// the graph's "Fit view" button.
function wfPvFit(){ wfPvResetZoom(); }

// ── Canvas interactions (DevScope parity) ───────────────────────────────────
//   left-click    → pick a point (sets point + color)
//   left-drag     → select a region
//   right-click   → tap the device at that point
//   middle-drag   → pan
//   wheel         → zoom (cursor-anchored)
//   double-click  → reset zoom
// Handlers are attached once in wfPvInit.
function wfPvAttachCanvas(){
  const c=wfPvCanvas; if(!c || c.__pvWired) return; c.__pvWired=true;

  c.addEventListener("mousedown", e=>{
    // Middle button → pan.
    if(e.button===1){ e.preventDefault(); wfPvPanning=true; wfPvPanStart=wfPvCanvasPos(e);
      wfPvPanBase=[wfPvPanX,wfPvPanY]; c.style.cursor="grab"; return; }
    if(!wfPvImg || e.button!==0) return;
    wfPvDragging=true; wfPvDragStart=wfPvCanvasPos(e); wfPvDragEnd=wfPvDragStart.slice();
  });

  c.addEventListener("mousemove", e=>{
    const [cx,cy]=wfPvCanvasPos(e);
    if(wfPvPanning){ wfPvPanX=wfPvPanBase[0]+cx-wfPvPanStart[0];
      wfPvPanY=wfPvPanBase[1]+cy-wfPvPanStart[1]; wfPvDraw(); return; }
    const p=wfPvCanvasToImg(e.clientX,e.clientY);
    const hp=document.getElementById("hover-pos");
    if(hp) hp.textContent = p?`${p[0]}, ${p[1]}`:"—";
    if(wfPvDragging){ wfPvDragEnd=[cx,cy]; wfPvDraw(); }
  });

  c.addEventListener("mouseup", async e=>{
    if(e.button===1){ wfPvPanning=false; c.style.cursor="crosshair"; return; }
    if(e.button!==0 || !wfPvDragging){ wfPvDragging=false; return; }
    wfPvDragging=false;
    const start=wfPvDragStart, end=wfPvDragEnd=wfPvCanvasPos(e);
    wfPvDragStart=wfPvDragEnd=null;
    const dx=Math.abs(end[0]-start[0]), dy=Math.abs(end[1]-start[1]);
    if(dx+dy<5){
      // Click → pick a point.
      const p=wfPvCanvasToImg(e.clientX,e.clientY); if(!p){ wfPvDraw(); return; }
      wfPvPoint=p; wfPvRegion=null; pvSetRegionBadge(false);
      const r=await api().set_point(p[0],p[1]);
      pvFillPoint(r); wfPvDraw();
      setStatus(`Selected (${r.x}, ${r.y})`);
    } else {
      // Drag → select a region.
      const a=wfPvImgFromCanvas(start), b=wfPvImgFromCanvas(end);
      if(!a||!b){ wfPvDraw(); return; }
      const x=Math.min(a[0],b[0]), y=Math.min(a[1],b[1]);
      const w=Math.abs(b[0]-a[0]), h=Math.abs(b[1]-a[1]);
      if(w<=1||h<=1){ wfPvDraw(); return; }
      wfPvRegion=[x,y,w,h]; wfPvPoint=null; pvSetRegionBadge(true);
      const r=await api().set_region(x,y,w,h);
      pvFillRegion(r); wfPvDraw();
      setStatus(`Region ${x},${y} · ${w}×${h}`);
    }
  });

  c.addEventListener("mouseleave", ()=>{
    if(wfPvDragging){ wfPvDragging=false; wfPvDraw(); }
    if(wfPvPanning){ wfPvPanning=false; c.style.cursor="crosshair"; }
    const hp=document.getElementById("hover-pos"); if(hp) hp.textContent="—";
  });

  // Right-click → tap the device at that point. stopPropagation keeps the
  // bubble from reaching #wf-canvas's graph context-menu handler.
  c.addEventListener("contextmenu", async e=>{
    e.preventDefault(); e.stopPropagation();
    const p=wfPvCanvasToImg(e.clientX,e.clientY); if(!p) return;
    await api().tap(p[0],p[1]);
    setStatus(`Tap → (${p[0]}, ${p[1]})`);
  });

  // Wheel → zoom (cursor-anchored).
  c.addEventListener("wheel", e=>{
    if(!wfPvImg) return; e.preventDefault();
    const [mx,my]=wfPvCanvasPos(e);
    const ef0=wfPvScale*wfPvZoom, ix=(mx-wfPvOx)/ef0, iy=(my-wfPvOy)/ef0;
    wfPvZoom=Math.max(.3, Math.min(10, wfPvZoom*(e.deltaY<0?1.15:1/1.15)));
    const ef1=wfPvScale*wfPvZoom;
    const bx=(wfPvCanvas.width-wfPvImgW*ef1)/2+wfPvPanX, by=(wfPvCanvas.height-wfPvImgH*ef1)/2+wfPvPanY;
    wfPvPanX+=mx-(bx+ix*ef1); wfPvPanY+=my-(by+iy*ef1);
    wfPvDraw();
  }, {passive:false});

  c.addEventListener("dblclick", wfPvResetZoom);
}

// Convert a canvas-space point (relative to canvas) to image coords.
function wfPvImgFromCanvas(pt){
  const ef=wfPvScale*wfPvZoom; if(!ef) return null;
  const ix=Math.round((pt[0]-wfPvOx)/ef), iy=Math.round((pt[1]-wfPvOy)/ef);
  if(ix<0||iy<0||ix>=wfPvImgW||iy>=wfPvImgH) return null;
  return [ix,iy];
}

// ── Capture a single frame ──────────────────────────────────────────────────
// `api().capture()` is fire-and-forget; the frame arrives via window.__recvFrame
// (wired below). We don't await a return value — that's the same model DevScope
// uses, so captures stay decoupled from the UI thread.
function wfPvCapture(){
  if(!wfPvActive) return;
  try{ api().capture(); }catch{}
}

// Push-based frame receiver — Python calls this when a new frame is ready.
window.__recvFrame = function(dataUrl, w, h){
  // Drop frames that arrive after the user left the tab (avoid needless work).
  if(!wfPvActive) return;
  const img = new Image();
  img.onload = ()=>{
    wfPvImg = img;
    wfPvImgW = w || img.naturalWidth;
    wfPvImgH = h || img.naturalHeight;
    wfPvErr = "";
    wfPvDraw();
  };
  img.src = dataUrl;
};

// ── Auto-refresh control ───────────────────────────────────────────────────
// Delegates to the backend's auto-refresh + Hz settings (shared with DevScope).
function wfPvStartAuto(){
  if(!wfPvActive) return;
  try{ api().set_refresh_hz(wfPvHz); api().set_auto_refresh(true); }catch{}
}
function wfPvStopAuto(){
  try{ api().set_auto_refresh(false); }catch{}
}
