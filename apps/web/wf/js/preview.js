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
let WF_PV_COLOR = null;
function wfPvReadColors(){
  const cs=getComputedStyle(document.documentElement);
  const v=(name,fallback)=>(cs.getPropertyValue(name)||fallback).trim();
  return {
    fail:v("--run-fail","#dc2626"),
    info:v("--run-info","#06b6d4"),
    warn:v("--run-warn","#eab308"),
    // Node-preview geometry gets its own vivid magenta. Yellow remains reserved
    // for actual warning state, cyan for search scope, green/red for matches.
    node:"#f02d92",
    ok:v("--run-ok","#16a34a") || "#16a34a",
    shade:v("--shade","#121316"),
  };
}
function wfPvColors(){
  if(!WF_PV_COLOR) WF_PV_COLOR=wfPvReadColors();
  return WF_PV_COLOR;
}

// ── View tab switching ──────────────────────────────────────────────────────
function wfSwitchView(view){
  document.querySelectorAll(".wf-view-tab").forEach(t=>t.classList.toggle("sel", t.dataset.view===view));
  const canvas = document.getElementById("wf-canvas");
  const preview = document.getElementById("wf-preview-pane");
  const world = document.getElementById("wf-world");
  const empty = document.getElementById("wf-canvas-empty");
  // Graph-only chrome: hide the rail's edit toggles + empty hint while previewing
  // (the zoom cluster stays — it retargets to the mirror).
  const graphOnly = [world, empty,
    document.getElementById("wf-rail-graph"),
    document.getElementById("wf-layout-bar"),
    document.getElementById("wf-cur-act")];

  const wfView = document.getElementById("workflow-view");
  if(view==="preview"){
    if(wfView) wfView.classList.add("wf-preview-on");   // hide the node library — editing chrome is dead weight here
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
    const varsPanel=document.getElementById("wf-vars-panel");
    if(varsPanel) varsPanel.style.display="none";
    if(inspTitle) inspTitle.textContent="DevScope tools";
    wfPvActive = true;
    wfPvInit();                 // lazy init on first switch
    wfPvResize();
    pvInitOcrBackends();        // populate OCR dropdown (no-op after first)
    // Device metadata is Android-only; querying it in Win32 mode caused noisy
    // ADB scans even though the workflow targets a PC window.
    if(WF.controller!=="win32") api().refresh_info();
    api().scope_out_dir().then(p=>{ if(p) pvUpdateOutDir(p); });  // resolve + label the crop folder
    if(wfPvAuto) wfPvStartAuto();
    wfPvCapture();              // grab one frame immediately
    wfZoomApplyMode("preview"); // repurpose the shared zoom cluster for the mirror
  } else {
    if(wfView) wfView.classList.remove("wf-preview-on");   // restore the node library
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
    const varsPanel=document.getElementById("wf-vars-panel");
    if(varsPanel) varsPanel.style.display="";
    if(inspTitle) inspTitle.textContent="Properties";
    wfZoomApplyMode("canvas");  // hand the zoom cluster back to the graph
    // If a wire draw landed while the canvas was hidden (renders during the
    // Preview tab: focus-follow, undo, engine events…), redraw the moment the
    // world is visible again — otherwise the wires vanish until the next render.
    if(typeof wfWiresStale!=="undefined" && wfWiresStale) wfDrawWires();
  }
}

// Repurpose the shared toolbar zoom cluster (−/label/+/fit) for whichever view
// is active. Canvas mode wires it to the graph (wfZoomBy/wfZoomReset/wfFit);
// Preview mode wires it to the mirror (wfPvZoomBy/wfPvResetZoom/wfPvFit) and
// refreshes the label from the current preview zoom.
function wfZoomApplyMode(mode){
  const out=document.getElementById("wf-zoom-out"),
        inb=document.getElementById("wf-zoom-in"),
        fit=document.getElementById("wf-zoom-fit");
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
    autoBtn.setAttribute("aria-checked",String(wfPvAuto));
    const cb = autoBtn.querySelector(".wf-pv-cb");
    if(cb) cb.classList.toggle("on", wfPvAuto);
    if(wfPvAuto && wfPvActive) wfPvStartAuto();
    else wfPvStopAuto();
  };

  const hzInput = document.getElementById("wf-pv-hz");
  if(hzInput) hzInput.onchange = ()=>{
    wfPvHz = Math.max(0.2, Math.min(60, parseFloat(hzInput.value)||30));
    hzInput.value = wfPvHz;
    if(typeof wfSaveSettings==="function") wfSaveSettings();
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
// Match overlay from engine / DevScope: [x,y,w,h,conf,ok(0|1),label?]
let wfPvOverlay=[];
let wfPvMatchRegion=null;           // [x,y,w,h] optional engine search crop
let wfPvOverlayMeta=null;           // {ok,label,threshold,conf} last match summary
// Static geometry preview requested from a node's context menu. Kept separate
// from engine match overlays so a live run can update its boxes without
// destroying the node's reference geometry.
let wfPvNodePreview=null;           // {nodeId,type,label,shapes,summary}
let wfPvNodeShapes=[];
let wfPvDragging=false, wfPvDragStart=null, wfPvDragEnd=null;
let wfPvPanning=false, wfPvPanStart=null, wfPvPanBase=null;
// Hover HUD: image-coords + pixel colour under the cursor, with crosshair
// guides. The pixel cache is an offscreen copy of the frame, rebuilt lazily
// (wfPvPixDirty) so 30Hz streaming never pays for it unless the mouse moves.
let wfPvHover=null, wfPvHoverHex="";
let wfPvPixCanvas=null, wfPvPixCtx=null, wfPvPixDirty=true;
// Tap-feedback ripples ({x,y,t0} in image coords) + right-drag swipe gesture.
let wfPvRipples=[];
let wfPvRDrag=null;            // {s:[cx,cy], c:[cx,cy]} canvas coords while right-dragging
let wfPvAnimReq=null;

function wfPvPixelAt(ix,iy){
  if(!wfPvImg) return "";
  if(wfPvPixDirty || !wfPvPixCtx){
    if(!wfPvPixCanvas) wfPvPixCanvas=document.createElement("canvas");
    wfPvPixCanvas.width=wfPvImgW; wfPvPixCanvas.height=wfPvImgH;
    wfPvPixCtx=wfPvPixCanvas.getContext("2d",{willReadFrequently:true});
    wfPvPixCtx.drawImage(wfPvImg,0,0);
    wfPvPixDirty=false;
  }
  try{
    const d=wfPvPixCtx.getImageData(ix,iy,1,1).data;
    return "#"+[d[0],d[1],d[2]].map(v=>v.toString(16).padStart(2,"0")).join("").toUpperCase();
  }catch{ return ""; }
}
// Keep redrawing while tap ripples are animating (~380ms each).
function wfPvAnimLoop(){
  if(wfPvAnimReq) return;
  const step=()=>{ wfPvAnimReq=null;
    if(wfPvRipples.length && wfPvActive){ wfPvDraw(); wfPvAnimReq=requestAnimationFrame(step); } };
  wfPvAnimReq=requestAnimationFrame(step);
}

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

// ── Static node-geometry preview ─────────────────────────────────────────────
// Right-clicking a spatial node calls wfPvPreviewNodes(). This is deliberately
// read-only: it never executes the node, so "preview Tap" cannot accidentally
// touch the device. Shapes use image coordinates and are clipped at draw time.
const WF_PV_IMAGE_TYPES=new Set([
  "tap_image","wait_image","if_image","scroll_find","loop_until_image",
  "find_image_pos","tap_all_images","tap_image_any","wait_image_any","if_image_any"
]);
const WF_PV_POINT_TYPES=new Set([
  "tap","double_tap","long_press","wait_color","if_color","read_color",
  "win_click","win_scroll","win_mouse_move"
]);
const WF_PV_REGION_TYPES=new Set([
  "wait_text","if_text","read_var","parse_var","loop_until_text"
]);

function wfPvNum(v,d=0){ const n=Number(v); return Number.isFinite(n)?n:d; }
function wfPvRegionOf(p){
  const w=wfPvNum(p.regionW), h=wfPvNum(p.regionH);
  return w>0&&h>0 ? [wfPvNum(p.regionX),wfPvNum(p.regionY),w,h] : null;
}
function wfPvTplRegion(path){
  if(typeof wfParseRegionFromName!=="function") return null;
  const r=wfParseRegionFromName(path||""); return r?[r.x,r.y,r.w,r.h]:null;
}
function wfPvNodeLabel(node){ const d=WF_NODES[node.type]||{}; return d.label||node.type; }

function wfPvCanPreviewNode(node){
  if(!node) return false;
  const p=node.params||{}, t=node.type;
  if(WF_PV_IMAGE_TYPES.has(t)) return !!(p.template||(Array.isArray(p.templates)&&p.templates.some(Boolean))||wfPvRegionOf(p));
  if(WF_PV_POINT_TYPES.has(t)) return p.target!=="found";
  if(WF_PV_REGION_TYPES.has(t)) return t!=="parse_var" || p.source!=="var";
  if(t==="tap_random"||t==="swipe"||t==="multi_tap"||t==="swipe_dir"||t==="tap_color"||t==="wait_stable") return true;
  if(t==="loop_until_color") return true;
  if(t==="screenshot") return true;
  return false;
}

function wfPvShapesForNode(node){
  const p=node.params||{}, t=node.type, label=wfPvNodeLabel(node), out=[];
  const point=(x,y,text=label,color="node",r=9)=>out.push({kind:"point",x:wfPvNum(x),y:wfPvNum(y),label:text,color,r});
  const rect=(x,y,w,h,text=label,color="info",dash=false)=>{
    w=wfPvNum(w); h=wfPvNum(h); if(w>0&&h>0) out.push({kind:"rect",x:wfPvNum(x),y:wfPvNum(y),w,h,label:text,color,dash}); };
  const arrow=(x1,y1,x2,y2,text=label)=>out.push({kind:"arrow",x1:wfPvNum(x1),y1:wfPvNum(y1),x2:wfPvNum(x2),y2:wfPvNum(y2),label:text,color:"node"});
  const search=wfPvRegionOf(p); if(search) rect(...search,"Search region","info",true);

  if(WF_PV_IMAGE_TYPES.has(t)){
    const paths=(Array.isArray(p.templates)?p.templates:[p.template]).filter(Boolean);
    paths.forEach((path,i)=>{ const r=wfPvTplRegion(path); if(r) rect(...r,paths.length>1?`Template ${i+1}`:"Template crop","ok"); });
    return out;
  }
  if(WF_PV_POINT_TYPES.has(t)){
    point(p.x,p.y,label);
    if((t==="win_click"||t==="tap")&&(wfPvNum(p.offsetX)||wfPvNum(p.offsetY)))
      point(wfPvNum(p.x)+wfPvNum(p.offsetX),wfPvNum(p.y)+wfPvNum(p.offsetY),"Tap with offset","ok",7);
    return out;
  }
  if(WF_PV_REGION_TYPES.has(t)){ rect(p.x,p.y,p.w,p.h,label,"node"); return out; }
  if(t==="tap_random"){
    if([p.x1,p.y1,p.x2,p.y2].some(v=>v!==undefined)) rect(Math.min(wfPvNum(p.x1),wfPvNum(p.x2)),Math.min(wfPvNum(p.y1),wfPvNum(p.y2)),Math.abs(wfPvNum(p.x2)-wfPvNum(p.x1)),Math.abs(wfPvNum(p.y2)-wfPvNum(p.y1)),"Random tap area","node");
    else rect(p.x,p.y,p.w,p.h,"Random tap area","node");
    return out;
  }
  if(t==="swipe"){ arrow(p.x1,p.y1,p.x2,p.y2,`${label} · ${wfPvNum(p.duration,300)}ms`); return out; }
  if(t==="swipe_dir"){
    const W=wfPvImgW||1080,H=wfPvImgH||1920,cx=W/2,cy=H/2,d=wfPvNum(p.distance,400); let x2=cx,y2=cy;
    if(p.direction==="down")y2+=d; else if(p.direction==="left")x2-=d; else if(p.direction==="right")x2+=d; else y2-=d;
    arrow(cx,cy,x2,y2,`${label} · ${p.direction||"up"}`); return out;
  }
  if(t==="multi_tap"){
    (Array.isArray(p.points)?p.points:[]).forEach((q,i)=>point(q.x,q.y,`Tap ${i+1}`,"node",8)); return out;
  }
  if(t==="tap_color"){
    if(!search) rect(0,0,wfPvImgW,wfPvImgH,`${label} · whole screen`,"node",true); return out;
  }
  if(t==="loop_until_color"){
    if(p.where!=="anywhere") point(p.x,p.y,`${label} · ${p.color||"?"}`);
    else if(!search) rect(0,0,wfPvImgW,wfPvImgH,`${label} · whole screen`,"node",true);
    return out;
  }
  if(t==="wait_stable"){
    if(!search) rect(0,0,wfPvImgW,wfPvImgH,"Whole screen stability","node",true); return out;
  }
  if(t==="screenshot"){ rect(0,0,wfPvImgW,wfPvImgH,"Captured frame","node"); return out; }
  return out;
}

function wfPvNodePreviewStatus(){
  const chip=document.getElementById("wf-pv-node-chip"); if(!chip) return;
  if(!wfPvNodePreview){ chip.hidden=true; chip.textContent=""; return; }
  chip.hidden=false; chip.textContent=wfPvNodePreview.summary||"Node preview";
  chip.title=(wfPvNodePreview.labels||[]).join(" · ")+" — click to clear";
}
function wfPvClearNodePreview(){
  wfPvNodePreview=null; wfPvNodeShapes=[]; wfPvOverlay=[]; wfPvMatchRegion=null; wfPvOverlayMeta=null; wfPvNodePreviewStatus();
  const strip=document.getElementById("wf-pv-tpl-strip"); if(strip){ strip.hidden=true; strip.innerHTML=""; }
  if(typeof wfPvDraw==="function") wfPvDraw();
}

async function wfPvShowTemplateStrip(nodes){
  const strip=document.getElementById("wf-pv-tpl-strip"); if(!strip) return;
  const paths=[];
  nodes.forEach(n=>{ const p=n.params||{}, a=Array.isArray(p.templates)?p.templates:[p.template];
    a.filter(Boolean).forEach(path=>{ if(!paths.includes(path)) paths.push(path); }); });
  strip.innerHTML=""; strip.hidden=!paths.length;
  for(const path of paths){
    const item=document.createElement("div"); item.className="wf-pv-tpl-item";
    const img=document.createElement("img"); img.alt="";
    const name=document.createElement("span"); name.textContent=path.split(/[\\/]/).pop(); name.title=path;
    item.append(img,name); strip.appendChild(item);
    try{ const src=await api().image_thumbnail(path,220); if(src) img.src=src; else item.remove(); }catch{ item.remove(); }
  }
  if(!strip.children.length) strip.hidden=true;
}

async function wfPvLoadFrameNow(){
  try{
    if(api().capture_now){
      const r=await api().capture_now();
      if(r&&r.dataUrl){
        await new Promise(resolve=>{ const img=new Image(); img.onload=()=>{ wfPvImg=img; wfPvImgW=img.naturalWidth||r.w||0; wfPvImgH=img.naturalHeight||r.h||0; wfPvErr=""; wfPvPixDirty=true; resolve(); }; img.onerror=resolve; img.src=r.dataUrl; });
        return true;
      }
      if(r&&r.error) wfPvErr=String(r.error);
    }
  }catch(e){ wfPvErr=String((e&&e.message)||e||"Capture failed"); }
  return !!wfPvImg;
}

async function wfPvPreviewNodes(nodes){
  nodes=(Array.isArray(nodes)?nodes:[nodes]).filter(wfPvCanPreviewNode);
  if(!nodes.length){ if(typeof uiToast==="function") uiToast("This block has no screen geometry to preview.","warning"); return; }
  if(typeof wfSwitchView==="function") wfSwitchView("preview");
  setStatus("Loading node preview…");
  const ok=await wfPvLoadFrameNow();
  wfPvNodeShapes=nodes.flatMap(wfPvShapesForNode);
  const labels=nodes.map(wfPvNodeLabel);
  wfPvNodePreview={nodeIds:nodes.map(n=>n.id),labels,summary:nodes.length===1?labels[0]:`${nodes.length} blocks`};
  wfPvNodePreviewStatus(); wfPvFit();
  if(!ok && typeof uiToast==="function") uiToast("No live frame — showing geometry when capture becomes available.","warning");
  // Image nodes: match templates against the captured frame without executing
  // Tap/Wait. This paints actual hits; filename/search rectangles stay as the
  // reference layer even when nothing matches.
  const imageNodes=nodes.filter(n=>WF_PV_IMAGE_TYPES.has(n.type));
  await wfPvShowTemplateStrip(imageNodes);
  wfPvOverlay=[];
  wfPvMatchRegion=null;
  wfPvOverlayMeta=null;
  if(ok&&imageNodes.length){
    for(const n of imageNodes){
      const p=n.params||{}, paths=(Array.isArray(p.templates)?p.templates:[p.template]).filter(Boolean);
      for(const path of paths){
        try{
          const rg=wfPvRegionOf(p)||[0,0,0,0];
          const r=await api().preview_match_template(path,wfPvNum(p.threshold,.85),n.type==="tap_all_images",...rg);
          if(r&&!r.error) (r.rects||[]).forEach(a=>wfPvOverlay.push(a.length===5?a.concat([1,path.split(/[\\/]/).pop()]):a));
        }catch{}
      }
    }
  }
  wfPvDraw(); setStatus(`Preview: ${labels.join(", ")}`);
}

function wfPvDrawNodeShapes(ctx,colors,chip){
  if(!wfPvNodeShapes.length) return;
  const col=k=>colors[k]||colors.info;
  const ef=wfPvScale*wfPvZoom;
  for(const s of wfPvNodeShapes){
    ctx.save(); ctx.strokeStyle=col(s.color); ctx.fillStyle=col(s.color); ctx.lineWidth=2.5;
    // A dark keyline keeps the magenta marker legible over both snow-white UI
    // and near-black game scenes without turning it into a warning colour.
    if(s.color==="node"){ ctx.shadowColor="rgba(0,0,0,.9)"; ctx.shadowBlur=2; }
    if(s.dash) ctx.setLineDash([7,5]);
    if(s.kind==="point"){
      const [x,y]=wfPvImgToCanvas(s.x,s.y), r=Math.max(6,(s.r||9));
      ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x-r-5,y); ctx.lineTo(x+r+5,y); ctx.moveTo(x,y-r-5); ctx.lineTo(x,y+r+5); ctx.stroke();
      chip(`${s.label} · ${Math.round(s.x)}, ${Math.round(s.y)}`,x+r+7,y+r+7);
    } else if(s.kind==="rect"){
      const [x,y]=wfPvImgToCanvas(s.x,s.y),[x2,y2]=wfPvImgToCanvas(s.x+s.w,s.y+s.h);
      ctx.strokeRect(x,y,x2-x,y2-y); ctx.globalAlpha=.09; ctx.fillRect(x,y,x2-x,y2-y); ctx.globalAlpha=1;
      chip(`${s.label} · ${Math.round(s.x)},${Math.round(s.y)} · ${Math.round(s.w)}×${Math.round(s.h)}`,x+4,y+4);
    } else if(s.kind==="arrow"){
      const [x,y]=wfPvImgToCanvas(s.x1,s.y1),[x2,y2]=wfPvImgToCanvas(s.x2,s.y2),a=Math.atan2(y2-y,x2-x);
      ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x2,y2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x2,y2); ctx.lineTo(x2-12*Math.cos(a-.45),y2-12*Math.sin(a-.45)); ctx.lineTo(x2-12*Math.cos(a+.45),y2-12*Math.sin(a+.45)); ctx.closePath(); ctx.fill();
      ctx.beginPath(); ctx.arc(x,y,4,0,Math.PI*2); ctx.fill();
      chip(`${s.label} · ${Math.round(s.x1)},${Math.round(s.y1)} → ${Math.round(s.x2)},${Math.round(s.y2)}`,x2+10,y2+10);
    }
    ctx.restore();
  }
}

function wfPvDraw(){
  const colors=wfPvColors();
  const cvs=wfPvCanvas; if(!cvs||!wfPvCtx||!wfPvImg) return;
  const ctx=wfPvCtx, cw=cvs.width, ch=cvs.height;
  wfPvRecompute();
  ctx.clearRect(0,0,cw,ch);
  ctx.fillStyle=colors.shade; ctx.fillRect(0,0,cw,ch);
  ctx.imageSmoothingEnabled=true; ctx.imageSmoothingQuality="high";
  const [x0,y0]=wfPvImgToCanvas(0,0), [x1,y1]=wfPvImgToCanvas(wfPvImgW,wfPvImgH);
  ctx.drawImage(wfPvImg, x0, y0, x1-x0, y1-y0);

  // Engine search region (dashed cyan) — where the template was looked for.
  if(wfPvMatchRegion && wfPvMatchRegion.length>=4){
    const [rx,ry,rw,rh]=wfPvMatchRegion;
    if(rw>0&&rh>0){
      const [cx,cy]=wfPvImgToCanvas(rx,ry), [cx2,cy2]=wfPvImgToCanvas(rx+rw,ry+rh);
      ctx.save();
      ctx.strokeStyle=colors.info; ctx.lineWidth=1.5;
      ctx.setLineDash([5,4]);
      ctx.strokeRect(cx,cy,cx2-cx,cy2-cy);
      ctx.restore();
    }
  }
  // Template-match overlay: green = above threshold, red = best below threshold.
  ctx.font="11px IBM Plex Mono,monospace"; ctx.textAlign="left";
  for(const r of wfPvOverlay){
    const conf=Number(r[4])||0;
    // r[5] may be missing (legacy DevScope match_template) → treat as ok/hit.
    const ok = r[5]===undefined || r[5]===null ? true : !!r[5];
    const label = r[6] ? String(r[6]) : "";
    const col = ok ? colors.ok : colors.fail;
    const [cx,cy]=wfPvImgToCanvas(r[0],r[1]), [cx2,cy2]=wfPvImgToCanvas(r[0]+r[2],r[1]+r[3]);
    const bw=cx2-cx, bh=cy2-cy;
    ctx.strokeStyle=col; ctx.lineWidth=2;
    if(!ok){ ctx.save(); ctx.setLineDash([4,3]); ctx.strokeRect(cx,cy,bw,bh); ctx.restore(); }
    else ctx.strokeRect(cx,cy,bw,bh);
    // Semi-transparent fill so the hit is obvious on busy screens.
    ctx.fillStyle=ok ? "rgba(22,163,74,.12)" : "rgba(220,38,38,.10)";
    ctx.fillRect(cx,cy,bw,bh);
    // Confidence chip above the box.
    const txt=(ok?"✓ ":"✗ ")+conf.toFixed(2)+(label?"  "+label:"");
    ctx.font="11px IBM Plex Mono,monospace";
    const tw=ctx.measureText(txt).width;
    const chipH=16, chipW=tw+10;
    let bx=cx, by=cy-chipH-2;
    if(by<2) by=cy+2;
    ctx.fillStyle="rgba(15,18,22,.88)";
    ctx.beginPath(); ctx.roundRect(bx,by,chipW,chipH,3); ctx.fill();
    ctx.fillStyle=col; ctx.textBaseline="middle";
    ctx.fillText(txt, bx+5, by+chipH/2+0.5);
    ctx.textBaseline="alphabetic";
  }
  // Selected region (cyan) — user crop in Preview inspect tools.
  if(wfPvRegion){
    const [x,y,w,h]=wfPvRegion;
    const [cx,cy]=wfPvImgToCanvas(x,y), [cx2,cy2]=wfPvImgToCanvas(x+w,y+h);
    ctx.strokeStyle=colors.info; ctx.lineWidth=2; ctx.strokeRect(cx,cy,cx2-cx,cy2-cy);
  }
  // Picked point (yellow crosshair).
  if(wfPvPoint){
    const [cx,cy]=wfPvImgToCanvas(wfPvPoint[0],wfPvPoint[1]);
    ctx.strokeStyle=colors.warn; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(cx-8,cy); ctx.lineTo(cx+8,cy);
    ctx.moveTo(cx,cy-8); ctx.lineTo(cx,cy+8); ctx.stroke();
  }
  // Small dark chip with mono text (size badges, hover HUD).
  const ef=wfPvScale*wfPvZoom;
  const chip=(txt,bx,by)=>{
    ctx.font="10px IBM Plex Mono,monospace";
    const tw=ctx.measureText(txt).width;
    const w=tw+10, h=16;
    bx=Math.max(2, Math.min(cw-w-2, bx)); by=Math.max(2, Math.min(ch-h-2, by));
    ctx.fillStyle="rgba(15,18,22,.85)";
    ctx.beginPath(); ctx.roundRect(bx,by,w,h,4); ctx.fill();
    ctx.fillStyle="#d5e2ee"; ctx.textAlign="left"; ctx.textBaseline="middle";
    ctx.fillText(txt,bx+5,by+h/2+0.5); ctx.textBaseline="alphabetic";
    return [bx,by,w,h];
  };
  // Node-context preview sits above the captured frame but below transient
  // hand-picked region/point gestures, so manual inspection remains legible.
  wfPvDrawNodeShapes(ctx,colors,chip);
  // Size badge on the persistent selected region.
  if(wfPvRegion){
    const [x,y,w,h]=wfPvRegion;
    const [bx,by]=wfPvImgToCanvas(x,y+h);
    chip(`${w}×${h}`, bx, by+4);
  }
  // Live drag rectangle while selecting a region — with a live w×h readout.
  if(wfPvDragging && wfPvDragStart && wfPvDragEnd){
    const r=wfPvNormRect(wfPvDragStart, wfPvDragEnd);
    ctx.strokeStyle="rgba(6,182,212,.8)"; ctx.lineWidth=1;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
    if(ef) chip(`${Math.round(r.w/ef)}×${Math.round(r.h/ef)}`, r.x+r.w+6, r.y+r.h+6);
  }
  // Right-drag swipe gesture: accent arrow from press point to cursor.
  if(wfPvRDrag){
    const [sx,sy]=wfPvRDrag.s, [tx,ty]=wfPvRDrag.c;
    ctx.strokeStyle="#4f8df0"; ctx.fillStyle="#4f8df0"; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(sx,sy); ctx.lineTo(tx,ty); ctx.stroke();
    const ang=Math.atan2(ty-sy,tx-sx);
    ctx.beginPath(); ctx.moveTo(tx,ty);
    ctx.lineTo(tx-9*Math.cos(ang-0.42), ty-9*Math.sin(ang-0.42));
    ctx.lineTo(tx-9*Math.cos(ang+0.42), ty-9*Math.sin(ang+0.42));
    ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.arc(sx,sy,3,0,Math.PI*2); ctx.fill();
    if(ef){ const a=wfPvImgFromCanvas(wfPvRDrag.s), b=wfPvImgFromCanvas(wfPvRDrag.c);
      if(a&&b) chip(`swipe (${a[0]},${a[1]}) → (${b[0]},${b[1]})`, tx+10, ty+10); }
  }
  // Tap ripples — a ring expanding from the tapped point (~380ms), so a
  // right-click tap gives visible feedback exactly where it landed.
  if(wfPvRipples.length){
    const now=performance.now();
    const reduce=window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    wfPvRipples=wfPvRipples.filter(rp=>now-rp.t0<380);
    for(const rp of wfPvRipples){
      const t=(now-rp.t0)/380;
      const [cx2,cy2]=wfPvImgToCanvas(rp.x,rp.y);
      ctx.strokeStyle=`rgba(79,141,240,${(1-t)*0.9})`; ctx.lineWidth=2;
      ctx.beginPath(); ctx.arc(cx2,cy2, reduce?12:(5+22*t), 0, Math.PI*2); ctx.stroke();
    }
  }
  // Hover crosshair + coord/colour HUD (hidden while any gesture is active).
  if(wfPvHover && !wfPvDragging && !wfPvPanning && !wfPvRDrag){
    const [hx,hy]=wfPvImgToCanvas(wfPvHover[0]+0.5, wfPvHover[1]+0.5);
    ctx.strokeStyle="rgba(255,255,255,.16)"; ctx.lineWidth=1;
    ctx.beginPath(); ctx.moveTo(0,hy); ctx.lineTo(cw,hy);
    ctx.moveTo(hx,0); ctx.lineTo(hx,ch); ctx.stroke();
    const txt=`${wfPvHover[0]}, ${wfPvHover[1]}${wfPvHoverHex?"  "+wfPvHoverHex:""}`;
    const [bx,by,bw,bh]=chip(txt, hx+14, hy+14);
    if(wfPvHoverHex){ ctx.fillStyle=wfPvHoverHex;
      ctx.fillRect(bx+bw+3, by+3, bh-6, bh-6);
      ctx.strokeStyle="rgba(255,255,255,.45)"; ctx.lineWidth=1;
      ctx.strokeRect(bx+bw+3.5, by+3.5, bh-7, bh-7); }
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
    : (isWin32 ? "Choose a target window beside the workflow title, then press Capture"
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
//   left-click        → pick a point (sets point + color)
//   left-drag         → select a region
//   space + left-drag → pan (same as middle-drag; mirrors the graph canvas)
//   right-click       → tap the device at that point
//   middle-drag       → pan
//   wheel             → zoom (cursor-anchored)
//   double-click      → reset zoom
// Handlers are attached once in wfPvInit.
function wfPvAttachCanvas(){
  const c=wfPvCanvas; if(!c || c.__pvWired) return; c.__pvWired=true;
  // True while Space is held (graph global from keyboard.js); guarded so the
  // preview keeps working even if the graph module isn't loaded.
  const spaceHeld=()=>typeof wfSpace!=="undefined" && wfSpace;

  c.addEventListener("mousedown", e=>{
    // Middle button, or Space + left button → pan (like the graph canvas).
    if(e.button===1 || (e.button===0 && spaceHeld())){
      e.preventDefault(); wfPvPanning=true; wfPvPanStart=wfPvCanvasPos(e);
      wfPvPanBase=[wfPvPanX,wfPvPanY]; c.style.cursor="grabbing"; return; }
    // Right button → tap (click) or swipe (drag) — resolved on mouseup.
    if(e.button===2){ if(!wfPvImg) return; e.preventDefault();
      const p=wfPvCanvasPos(e); wfPvRDrag={s:p, c:p.slice()}; return; }
    if(!wfPvImg || e.button!==0) return;
    wfPvDragging=true; wfPvDragStart=wfPvCanvasPos(e); wfPvDragEnd=wfPvDragStart.slice();
  });

  c.addEventListener("mousemove", e=>{
    const [cx,cy]=wfPvCanvasPos(e);
    if(wfPvPanning){ wfPvPanX=wfPvPanBase[0]+cx-wfPvPanStart[0];
      wfPvPanY=wfPvPanBase[1]+cy-wfPvPanStart[1]; wfPvDraw(); return; }
    // Show the grab hand whenever Space is held so the pan affordance is visible.
    if(!wfPvDragging && !wfPvRDrag) c.style.cursor=spaceHeld()?"grab":"crosshair";
    const p=wfPvCanvasToImg(e.clientX,e.clientY);
    // Hover HUD state: image coords + pixel colour under the cursor.
    wfPvHover=p;
    wfPvHoverHex=p?wfPvPixelAt(p[0],p[1]):"";
    const hp=document.getElementById("hover-pos");
    if(hp) hp.textContent = p?`${p[0]}, ${p[1]}${wfPvHoverHex?" · "+wfPvHoverHex:""}`:"—";
    if(wfPvRDrag){ wfPvRDrag.c=[cx,cy]; wfPvDraw(); return; }
    if(wfPvDragging){ wfPvDragEnd=[cx,cy]; wfPvDraw(); return; }
    if(wfPvImg) wfPvDraw();   // refresh the crosshair/HUD
  });

  c.addEventListener("mouseup", async e=>{
    // End a pan started by either the middle button or Space + left button.
    if(wfPvPanning){ wfPvPanning=false; c.style.cursor=spaceHeld()?"grab":"crosshair"; return; }
    // Right button released → short = tap · long = swipe on the device.
    if(e.button===2 && wfPvRDrag){
      const s=wfPvRDrag.s, t=wfPvCanvasPos(e); wfPvRDrag=null;
      const a=wfPvImgFromCanvas(s), b=wfPvImgFromCanvas(t);
      const dist=Math.hypot(t[0]-s[0], t[1]-s[1]);
      if(dist<6){
        if(a){ await api().tap(a[0],a[1]);
          wfPvRipples.push({x:a[0],y:a[1],t0:performance.now()}); wfPvAnimLoop();
          setStatus(`Tap → (${a[0]}, ${a[1]})`); }
      } else if(a&&b){
        const len=Math.hypot(b[0]-a[0], b[1]-a[1]);
        const dur=Math.max(120, Math.min(800, Math.round(len*0.35)));
        await api().swipe(a[0],a[1],b[0],b[1],dur);
        wfPvRipples.push({x:b[0],y:b[1],t0:performance.now()}); wfPvAnimLoop();
        setStatus(`Swipe (${a[0]},${a[1]}) → (${b[0]},${b[1]}) · ${dur}ms`);
      }
      wfPvDraw(); return;
    }
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
    if(wfPvDragging){ wfPvDragging=false; }
    if(wfPvRDrag){ wfPvRDrag=null; }
    if(wfPvPanning){ wfPvPanning=false; c.style.cursor="crosshair"; }
    wfPvHover=null; wfPvHoverHex="";
    if(wfPvImg) wfPvDraw();
    const hp=document.getElementById("hover-pos"); if(hp) hp.textContent="—";
  });

  // The tap/swipe now happens on right-mouseup (short = tap, drag = swipe);
  // contextmenu only suppresses the browser menu + the graph's context handler.
  c.addEventListener("contextmenu", e=>{ e.preventDefault(); e.stopPropagation(); });

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
// Prefer the decoded image's natural size so the on-screen box always matches
// the real capture (ADB screencap / scrcpy), not a stale cached wm size.
window.__recvFrame = function(dataUrl, w, h){
  // Drop frames that arrive after the user left the tab (avoid needless work).
  if(!wfPvActive) return;
  const img = new Image();
  img.onload = ()=>{
    wfPvImg = img;
    // natural* is the ground truth of the JPEG we just decoded; fall back to
    // the backend's reported size only if the browser omits natural dims.
    const nw = img.naturalWidth || 0, nh = img.naturalHeight || 0;
    wfPvImgW = nw || (w|0) || 0;
    wfPvImgH = nh || (h|0) || 0;
    wfPvErr = "";
    wfPvPixDirty = true;   // hover-HUD pixel cache rebuilds lazily on next hover
    // Keep the canvas buffer sized to the wrap so letterboxing uses the true
    // device aspect (image box = device aspect ratio inside the dark panel).
    if(typeof wfPvResize==="function") wfPvResize();
    else wfPvDraw();
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
