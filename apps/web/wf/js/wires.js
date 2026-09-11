// ── Wires ────────────────────────────────────────────────────────────────────
// Links are drawn the way ComfyUI/LiteGraph (and Blender's node editor) draw
// them: a single curve from the output dot to the input dot and nothing else.
// There is no obstacle avoidance and no lane allocation — a link that passes a
// block simply runs behind it, because the wire layer paints under the cards.
// That is the whole trick those editors use: the graph reads from where the
// blocks sit, so the wires are allowed to stay dumb, calm and predictable.
//
// Three render modes, the same three ComfyUI ships (rail button cycles them):
//   spline   (default) — cubic bezier, horizontal handles ¼ of the port distance
//   linear             — one straight run with a short stub off each port
//   straight           — orthogonal Z: stub → vertical at the midpoint → stub
//
// One DOM read pass per draw feeds the geometry: port centres come from
// offsetLeft/offsetTop (already #wf-world layout coords), so it is zoom-
// independent, immune to the :hover scale on a port dot, and costs a single
// layout flush instead of one forced relayout per port.
let wfWireIdx = { ports:new Map() };

function wfWireIndexRebuild(){
  const portsByNode=new Map();
  document.querySelectorAll("#wf-world .wf-node").forEach(el=>{
    const x=el.offsetLeft, y=el.offsetTop, ports=new Map();
    const right=x+el.offsetWidth;
    el.querySelectorAll(".wf-port").forEach(p=>{
      const side=p.classList.contains("out")?"out":"in";
      // `edge` = the card border this port hides behind. Dots sit INSIDE the
      // block, so a link has to swing past that edge to be seen at all — the
      // router solves for it below rather than guessing a handle length.
      const pt={ x:x+p.offsetLeft+p.offsetWidth/2, y:y+p.offsetTop+p.offsetHeight/2,
                 edge: side==="out" ? right : x };
      ports.set(side+":"+p.dataset.port, pt);
      if(!ports.has(side)) ports.set(side, pt);   // first port of a side = fallback
    });
    portsByNode.set(el.dataset.node, ports);
  });
  wfWireIdx={ ports:portsByNode };
}

function wfPortPt(nodeId,port){
  if(!wfWireIdx.ports.size) wfWireIndexRebuild();
  const ports=wfWireIdx.ports.get(nodeId); if(!ports) return null;
  const side=(port==="in"||port==="loop")?"in":"out";
  return ports.get(side+":"+port) || ports.get(side) || null;
}

// ── Link render mode ─────────────────────────────────────────────────────────
const WF_LINK_MODES=["spline","linear","straight"];
const WF_LINK_MODE_LBL={ spline:"Spline", linear:"Linear", straight:"Straight" };
let wfLinkMode="spline";
try{ const m=localStorage.getItem("wfLinkMode"); if(WF_LINK_MODES.includes(m)) wfLinkMode=m; }catch{}

function wfSetLinkMode(mode){
  if(!WF_LINK_MODES.includes(mode)) return;
  wfLinkMode=mode;
  try{ localStorage.setItem("wfLinkMode",mode); }catch{}
  wfSyncLinkModeBtn();
  wfDrawWires();
}
function wfCycleLinkMode(){
  wfSetLinkMode(WF_LINK_MODES[(WF_LINK_MODES.indexOf(wfLinkMode)+1)%WF_LINK_MODES.length]);
  if(typeof setStatus==="function") setStatus("Link style: "+WF_LINK_MODE_LBL[wfLinkMode]);
}
// The rail button shows which of the three shapes is live (icon swaps with it).
function wfSyncLinkModeBtn(){
  const b=document.getElementById("wf-link-btn"); if(!b) return;
  b.dataset.mode=wfLinkMode;
  b.title="Link style: "+WF_LINK_MODE_LBL[wfLinkMode]+" — click to cycle (spline → linear → straight)";
}

// ── Link shapes ──────────────────────────────────────────────────────────────
const WF_LINK_STUB=14;    // how far a linear/straight link leaves the port before it turns
// Two blocks nose-to-nose have no room for a full stub — shrink it rather than
// let the two stubs overshoot each other into a zigzag.
function wfStub(a,b){ return Math.max(3, Math.min(WF_LINK_STUB, Math.abs(b.x-a.x)/3)); }

// LiteGraph's spline: horizontal handles set a quarter of the port-to-port
// distance out from each dot. Level ports therefore give a dead-straight line
// for free and a short hop stays nearly straight.
const WF_LINK_MIN=40, WF_LINK_MAX=380;
const WF_LINK_CLEAR=14;   // px of link that must show past each card's edge

// How far a handle of length k throws the curve beyond its own endpoints.
// x(t) is a cubic with both handles horizontal, so x'(t)=0 is a quadratic:
//   (6k−2D)t² − (6k−2D)t + k = 0,  D = b.x − a.x
// giving the two extrema in closed form — no sampling, no per-frame path
// measurement. A forward link with a short handle is monotonic (no lobe at all).
function wfSplineExtent(ax,bx,k){
  const flat={ max:Math.max(ax,bx), min:Math.min(ax,bx) };
  const S=6*k-2*(bx-ax);
  if(S<=0) return flat;
  const disc=1-4*k/S;
  if(disc<=0) return flat;
  const r=Math.sqrt(disc), c1=ax+k, c2=bx-k;
  const at=t=>{ const u=1-t; return u*u*u*ax+3*u*u*t*c1+3*u*t*t*c2+t*t*t*bx; };
  const x1=at((1-r)/2), x2=at((1+r)/2);
  return { max:Math.max(flat.max,x1,x2), min:Math.min(flat.min,x1,x2) };
}
// Handle length. Forward links keep LiteGraph's quarter-distance and are done.
// A back-run is the case that needs care: both of its ends are tucked inside a
// card, so a short handle leaves nothing on screen but the bare diagonal across
// the gap — two blocks stacked one above the other showed a link that seemed to
// come from nowhere. Solve for the shortest handle whose lobes clear both cards.
function wfSplineOff(a,b){
  const dx=b.x-a.x, dy=b.y-a.y;
  const base=Math.min(Math.hypot(dx,dy)*0.25, WF_LINK_MAX);
  if(dx>=0) return Math.max(base, Math.min(WF_LINK_MIN, dx*0.6));
  const needR=(a.edge==null?a.x:a.edge)+WF_LINK_CLEAR;
  const needL=(b.edge==null?b.x:b.edge)-WF_LINK_CLEAR;
  const ok=k=>{ const e=wfSplineExtent(a.x,b.x,k); return e.max>=needR && e.min<=needL; };
  let lo=Math.max(base, WF_LINK_MIN);
  if(ok(lo)) return lo;
  if(!ok(WF_LINK_MAX)) return WF_LINK_MAX;
  let hi=WF_LINK_MAX;
  for(let i=0;i<14;i++){ const mid=(lo+hi)/2; if(ok(mid)) hi=mid; else lo=mid; }
  return hi;
}
function wfSplineLift(dx,dy){
  // A back-run between near-level ports would fold flat onto itself — lift both
  // handles so the loop stays readable instead of collapsing into the line.
  return (dx<0 && Math.abs(dy)<28) ? 30 : 0;
}
function wfSplinePath(a,b){
  const off=wfSplineOff(a,b), lift=wfSplineLift(b.x-a.x, b.y-a.y);
  return `M${a.x},${a.y} C${a.x+off},${a.y-lift} ${b.x-off},${b.y-lift} ${b.x},${b.y}`;
}
function wfLinearPath(a,b){
  const s=wfStub(a,b);
  return `M${a.x},${a.y} L${a.x+s},${a.y} L${b.x-s},${b.y} L${b.x},${b.y}`;
}
function wfStraightPath(a,b){
  const s=wfStub(a,b), dy=b.y-a.y;
  // Forward links turn at the halfway column; a back-run has no halfway column
  // to use, so it turns just past its own stub and runs the vertical there.
  const mx=(b.x-a.x > s*2+20) ? (a.x+b.x)/2 : a.x+s+10;
  if(Math.abs(dy)<1) return `M${a.x},${a.y} L${b.x},${b.y}`;
  const sy=dy>0?1:-1;
  const d1=mx-a.x, d2=b.x-mx;
  const r=Math.max(0, Math.min(9, Math.abs(dy)/2, Math.abs(d1), Math.abs(d2)));
  const h1=d1>=0?1:-1, h2=d2>=0?1:-1;
  return `M${a.x},${a.y} L${mx-h1*r},${a.y} Q${mx},${a.y} ${mx},${a.y+sy*r}`+
         ` L${mx},${b.y-sy*r} Q${mx},${b.y} ${mx+h2*r},${b.y} L${b.x},${b.y}`;
}
function wfWirePath(a,b){
  if(wfLinkMode==="linear")   return wfLinearPath(a,b);
  if(wfLinkMode==="straight") return wfStraightPath(a,b);
  return wfSplinePath(a,b);
}

// Flow marker — ComfyUI puts a dot at each link's midpoint; here it is a small
// triangle turned along the curve, so the same glyph also says which way the
// flow runs (this graph is control flow: direction is load-bearing). Computed
// analytically per shape, never via getPointAtLength — that would force a
// layout flush per wire on every drag frame.
function wfLinkMid(a,b){
  if(wfLinkMode==="linear"){
    const s=wfStub(a,b), p={x:a.x+s,y:a.y}, q={x:b.x-s,y:b.y};
    return { x:(p.x+q.x)/2, y:(p.y+q.y)/2, ang:Math.atan2(q.y-p.y,q.x-p.x) };
  }
  if(wfLinkMode==="straight"){
    const s=wfStub(a,b), dy=b.y-a.y;
    const mx=(b.x-a.x > s*2+20) ? (a.x+b.x)/2 : a.x+s+10;
    if(Math.abs(dy)<1) return { x:(a.x+b.x)/2, y:a.y, ang:b.x>=a.x?0:Math.PI };
    return { x:mx, y:(a.y+b.y)/2, ang:dy>0?Math.PI/2:-Math.PI/2 };
  }
  const off=wfSplineOff(a,b), lift=wfSplineLift(b.x-a.x, b.y-a.y);
  const c1={x:a.x+off,y:a.y-lift}, c2={x:b.x-off,y:b.y-lift};
  return {                                   // B(½) and B′(½) of the cubic
    x:(a.x+3*c1.x+3*c2.x+b.x)/8,
    y:(a.y+3*c1.y+3*c2.y+b.y)/8,
    ang:Math.atan2((b.y+c2.y-c1.y-a.y), (b.x+c2.x-c1.x-a.x)),
  };
}

// Wires draw "blind" while #wf-world is display:none (Preview tab): every
// measurement returns 0 → paths become an invisible M0,0. The guard below skips
// that draw pass and sets a stale flag; wfSwitchView("canvas") redraws once the
// canvas is visible again.
let wfWiresStale=false;
const WF_NS="http://www.w3.org/2000/svg";
const WF_FLOW_TRI="M-2.5,-2.8 L3.2,0 L-2.5,2.8 Z";

function wfDrawWires(){
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();   // node moves redraw wires → keep the map live
  const svg=$("wf-wires"), g=wfGraph();
  const world=$("wf-world");
  if(world && world.offsetParent===null){ wfWiresStale=true; return; }   // canvas hidden — measurements would be 0
  wfWiresStale=false;
  const temp=svg.querySelector(".temp");
  svg.innerHTML=""; if(temp) svg.appendChild(temp);
  if(!g) return;
  wfWireIndexRebuild();

  // Resolve endpoints first, then sort shortest-first so a long run paints over
  // the local hops rather than under them. Ties break on a stable key, so paint
  // order no longer changes merely because JSON import/delete/undo reordered the
  // edge array.
  const routes=[];
  (g.edges||[]).forEach(ed=>{
    if(wfSameStack(ed.from,ed.to)) return;
    const toPort=ed.toPort||"in";
    const a=wfPortPt(ed.from,ed.fromPort), b=wfPortPt(ed.to,toPort);
    if(!a||!b) return;
    routes.push({ ed, a, b, toPort,
      span:Math.abs(b.x-a.x)+Math.abs(b.y-a.y),
      key:`${ed.from}\u0000${ed.fromPort||"out"}\u0000${ed.to}\u0000${toPort}` });
  });
  routes.sort((p,q)=>p.span-q.span || (p.key<q.key?-1:p.key>q.key?1:0));

  const frag=document.createDocumentFragment();
  routes.forEach(({ed,a,b,toPort})=>{
    const d=wfWirePath(a,b);
    const grp=document.createElementNS(WF_NS,"g");
    grp.setAttribute("class","wire-grp"); grp.__edge=ed;
    const hit=document.createElementNS(WF_NS,"path");
    hit.setAttribute("class","wire-hit"); hit.setAttribute("d",d);
    hit.setAttribute("tabindex","0"); hit.setAttribute("role","button");
    const fromLabel=WF_PORT_LBL[ed.fromPort]||ed.fromPort||"out";
    hit.setAttribute("aria-label",`Wire ${fromLabel||"out"}; press Delete to remove`);
    const tt=document.createElementNS(WF_NS,"title");
    tt.textContent="Right-click or press Delete to remove wire"; hit.appendChild(tt);
    const p=document.createElementNS(WF_NS,"path");
    p.setAttribute("class","wire"+(toPort==="loop"?" loopback":""));
    p.dataset.from=ed.from; p.dataset.fromport=ed.fromPort; p.dataset.to=ed.to;
    p.setAttribute("d",d);
    const m=wfLinkMid(a,b);
    const tri=document.createElementNS(WF_NS,"path");
    tri.setAttribute("class","wire-flow"+(toPort==="loop"?" loopback":""));
    tri.dataset.fromport=ed.fromPort;
    tri.setAttribute("d",WF_FLOW_TRI);
    tri.setAttribute("transform",`translate(${m.x.toFixed(1)},${m.y.toFixed(1)}) rotate(${(m.ang*180/Math.PI).toFixed(1)})`);
    grp.appendChild(hit); grp.appendChild(p); grp.appendChild(tri);
    frag.appendChild(grp);
  });
  svg.appendChild(frag);
}
// One delegated key handler for every wire hit-path — 200 wires no longer mean
// 200 listeners rebuilt on each draw.
document.addEventListener("keydown",e=>{
  if(e.key!=="Delete"&&e.key!=="Backspace") return;
  const t=e.target;
  if(!t||!t.classList||!t.classList.contains("wire-hit")) return;
  const grp=t.parentNode;
  if(!grp||!grp.__edge) return;
  e.preventDefault(); e.stopPropagation();
  wfDeleteWire(grp.__edge);
});

function wfDeleteWire(ed){
  const g=wfGraph(); if(!g||!ed) return;
  wfPushUndo();
  const i=g.edges.indexOf(ed); if(i>=0) g.edges.splice(i,1);
  wfRenderCanvas();
  setStatus("Wire deleted — Ctrl+Z to undo");
}

function wfDrawTempWire(mx,my){
  const a=wfPortPt(wfGesture.from,wfGesture.port); if(!a) return;
  const wr=$("wf-world").getBoundingClientRect();
  const b={ x:(mx-wr.left)/wfZoom, y:(my-wr.top)/wfZoom };
  const svg=$("wf-wires"); let t=svg.querySelector(".temp");
  if(!t){ t=document.createElementNS(WF_NS,"path"); t.setAttribute("class","temp"); svg.appendChild(t); }
  if(!wfWireIdx.ports.size) wfWireIndexRebuild();
  t.setAttribute("d",wfWirePath(a,b));
}

function wfClearTemp(){ const t=$("wf-wires").querySelector(".temp"); if(t)t.remove(); }

// Last-resort insurance: WebView2/Chromium occasionally mis-culls the large SVG
// inside a transformed container (wires stay in the DOM but aren't painted —
// resizing the window brings them back). Redraw the wires once a resize settles
// so the user never has to "jiggle" the window; 150ms debounce for resize bursts.
let _wfWireResizeT=null;
window.addEventListener("resize", ()=>{
  clearTimeout(_wfWireResizeT);
  _wfWireResizeT=setTimeout(()=>{ if(typeof wfPvActive==="undefined"||!wfPvActive) wfDrawWires(); },150);
});
