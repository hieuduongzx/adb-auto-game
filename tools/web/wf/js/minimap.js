// ── Minimap ───────────────────────────────────────────────────────────────────
// A live bird's-eye view of the current graph, bottom-left above the layout
// button. Nodes render as category-tinted chips, groups as faint frames, and
// the viewport as an accent rectangle; click or drag anywhere to jump the
// camera there. It earns its pixels only when it helps — the panel auto-hides
// while the whole graph already fits on screen (and in Preview mode the mirror
// pane covers it). Redraws are rAF-coalesced off wfApplyTransform/wfDrawWires,
// so panning, zooming and node drags all keep it in sync at frame rate.
const WF_MM_PAD = 8;      // inner padding around the world bounds (css px)
const WF_MM_MAXSCALE = .22;
let wfMmQueued=false, wfMmView=null, wfMmColors=null, wfMmDragging=false;

function wfMmPalette(){
  if(wfMmColors) return wfMmColors;
  const cs=getComputedStyle(document.documentElement);
  const v=k=>(cs.getPropertyValue(k)||"").trim();
  wfMmColors={
    basic:v("--cat-basic")||"#6f9be8", image:v("--cat-image")||"#2fb0a3",
    color:v("--cat-color")||"#d6608f", ocr:v("--cat-ocr")||"#e0954b",
    logic:v("--cat-logic")||"#9a78e6", flow:v("--cat-flow")||"#e0a64b",
    input:v("--cat-input")||"#7a86e8", app:v("--cat-app")||"#059669",
    time:v("--cat-time")||"#0284c7", device:v("--cat-device")||"#64748b",
    win32:v("--cat-win32")||"#6366f1", misc:v("--cat-misc")||"#9aa6b4",
    start:v("--term-start")||"#16a34a", end:v("--term-end")||"#dc2626", note:"#e2c56d", def:"#a5b1c2",
    run:v("--run-live")||"#f97316", accent:v("--accent")||"#2f6fed",
  };
  return wfMmColors;
}
function wfMmColorFor(n){
  const P=wfMmPalette(), def=WF_NODES[n.type]||{};
  if(def.kind==="start") return P.start;
  if(def.kind==="end"||def.kind==="stop") return P.end;
  if(def.kind==="note") return P.note;
  return P[def.cat]||P.def;
}

// Coalesce every redraw request into one paint per frame.
function wfMinimapQueue(){
  if(wfMmQueued) return; wfMmQueued=true;
  requestAnimationFrame(()=>{ wfMmQueued=false; wfMinimapDraw(); });
}

function wfMinimapDraw(){
  const box=$("wf-minimap"), cv=$("wf-minimap-cv");
  if(!box||!cv) return;
  // Opt-in via the toolbar toggle (persisted in settings; default off).
  if(typeof wfMinimapOn!=="undefined" && !wfMinimapOn){ box.classList.remove("show"); return; }
  const canvas=$("wf-canvas"), g=(typeof wfGraph==="function")?wfGraph():null;
  const nodes=g?(g.nodes||[]):[];
  if(!canvas||!g||!nodes.length){ box.classList.remove("show"); return; }
  // Viewport in world coords.
  const cw=canvas.clientWidth, ch=canvas.clientHeight;
  const vx=-wfPan.x/wfZoom, vy=-wfPan.y/wfZoom, vw=cw/wfZoom, vh=ch/wfZoom;
  // Node bounds (live DOM sizes; fallback to the canonical card).
  let nx0=Infinity,ny0=Infinity,nx1=-Infinity,ny1=-Infinity;
  const rects=nodes.map(n=>{
    const el=wfNodeElById(n.id);
    const w=el?el.offsetWidth:160, h=el?el.offsetHeight:60;
    if(n.x<nx0)nx0=n.x; if(n.y<ny0)ny0=n.y;
    if(n.x+w>nx1)nx1=n.x+w; if(n.y+h>ny1)ny1=n.y+h;
    return {n,w,h};
  });
  // Earn-your-pixels rule: hide while a small graph is fully on screen.
  const allVisible = nx0>=vx && ny0>=vy && nx1<=vx+vw && ny1<=vy+vh;
  if(nodes.length<6 && allVisible){ box.classList.remove("show"); wfMmView=null; return; }
  box.classList.add("show");
  // Fit bounds = nodes ∪ viewport so the view rectangle never leaves the map.
  const bx0=Math.min(nx0,vx), by0=Math.min(ny0,vy);
  const bx1=Math.max(nx1,vx+vw), by1=Math.max(ny1,vy+vh);
  const W=box.clientWidth, H=box.clientHeight, dpr=window.devicePixelRatio||1;
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){
    cv.width=Math.round(W*dpr); cv.height=Math.round(H*dpr);
  }
  const scale=Math.min((W-WF_MM_PAD*2)/Math.max(1,bx1-bx0),
                       (H-WF_MM_PAD*2)/Math.max(1,by1-by0), WF_MM_MAXSCALE);
  const offX=(W-(bx1-bx0)*scale)/2, offY=(H-(by1-by0)*scale)/2;
  wfMmView={bx0,by0,scale,offX,offY};
  const X=w=>offX+(w-bx0)*scale, Y=w=>offY+(w-by0)*scale;
  const ctx=cv.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,W,H);
  const P=wfMmPalette();
  // Group frames first (behind the chips), matching their canvas tint.
  (g.groups||[]).forEach(gr=>{
    const c=(typeof wfGroupColor==="function")?wfGroupColor(gr):null;
    ctx.fillStyle=c?c.bg:"rgba(140,150,165,.08)";
    ctx.strokeStyle=c?c.b:"#b9c2cf"; ctx.lineWidth=.75; ctx.globalAlpha=.8;
    ctx.beginPath(); ctx.roundRect(X(gr.x),Y(gr.y),gr.w*scale,gr.h*scale,2);
    ctx.fill(); ctx.stroke(); ctx.globalAlpha=1;
  });
  // Node chips.
  rects.forEach(({n,w,h})=>{
    const running = typeof wfRunNode!=="undefined" && n.id===wfRunNode;
    const sel = WF.sel.includes(n.id);
    ctx.fillStyle = running ? P.run : wfMmColorFor(n);
    ctx.globalAlpha = running||sel ? 1 : .82;
    ctx.beginPath();
    ctx.roundRect(X(n.x),Y(n.y),Math.max(2.5,w*scale),Math.max(2,h*scale),1.5);
    ctx.fill();
    if(sel){ ctx.globalAlpha=1; ctx.strokeStyle=P.accent; ctx.lineWidth=1;
      ctx.stroke(); }
  });
  ctx.globalAlpha=1;
  // Viewport rectangle.
  ctx.strokeStyle=P.accent; ctx.lineWidth=1.25;
  ctx.fillStyle="rgba(47,111,237,.05)";
  ctx.beginPath(); ctx.roundRect(X(vx)+.5,Y(vy)+.5,vw*scale-1,vh*scale-1,2);
  ctx.fill(); ctx.stroke();
}

// Click / drag on the map = move the camera so that world point is centred.
function wfMmJump(e){
  const box=$("wf-minimap"), canvas=$("wf-canvas");
  if(!box||!canvas||!wfMmView) return;
  const r=box.getBoundingClientRect();
  const wx=wfMmView.bx0+(e.clientX-r.left-wfMmView.offX)/wfMmView.scale;
  const wy=wfMmView.by0+(e.clientY-r.top -wfMmView.offY)/wfMmView.scale;
  wfCancelCamAnim();
  wfPan.x=canvas.clientWidth/2 - wx*wfZoom;
  wfPan.y=canvas.clientHeight/2 - wy*wfZoom;
  wfApplyTransform();
}
function wfMinimapInit(){
  const box=$("wf-minimap"); if(!box||box.__wired) return; box.__wired=true;
  box.addEventListener("mousedown",e=>{
    if(e.button!==0) return;
    e.preventDefault(); e.stopPropagation();
    wfMmDragging=true; wfMmJump(e);
  });
  window.addEventListener("mousemove",e=>{ if(wfMmDragging) wfMmJump(e); });
  window.addEventListener("mouseup",()=>{ wfMmDragging=false; });
  // The map is a navigator, not a zoom surface — swallow wheel/context events.
  box.addEventListener("wheel",e=>{ e.preventDefault(); e.stopPropagation(); },{passive:false});
  box.addEventListener("contextmenu",e=>{ e.preventDefault(); e.stopPropagation(); });
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",wfMinimapInit);
else wfMinimapInit();
