// ── Wires ────────────────────────────────────────────────────────────────────
// Wires paint below cards (they run under a block and re-emerge at its far
// edge), with an underlay at crossings. No mid-wire markers — direction reads
// from the port side. Selection highlights adjacent links without rebuilding
// paths or changing execution-state colours.
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
  const portsByNode=new Map(), positions=new Map();
  document.querySelectorAll("#wf-world .wf-node").forEach(el=>{
    const x=el.offsetLeft, y=el.offsetTop, ports=new Map();
    const right=x+el.offsetWidth;
    el.querySelectorAll(".wf-port").forEach(p=>{
      const side=p.classList.contains("out")?"out":"in";
      // `edge` = the card border this port hides behind. Dots sit INSIDE the
      // block, so a link has to swing past that edge to be seen at all — the
      // router solves for it below rather than guessing a handle length.
      const pt={ x:x+p.offsetLeft+p.offsetWidth/2, y:y+p.offsetTop+p.offsetHeight/2,
                 edge: side==="out" ? right : x, bottom:y+el.offsetHeight };
      ports.set(side+":"+p.dataset.port, pt);
      if(!ports.has(side)) ports.set(side, pt);   // first port of a side = fallback
    });
    portsByNode.set(el.dataset.node, ports);
    positions.set(el.dataset.node,{x,y});
  });
  wfWireIdx={ ports:portsByNode, positions };
}

// Card sizes and port offsets stay fixed during a drag. Translate the cached
// endpoints for its members without measuring every other card again.
function wfWireIndexMove(ids){
  if(!wfWireIdx.positions) return false;
  for(const id of ids){
    const el=wfNodeElById(id), prev=wfWireIdx.positions.get(id), ports=wfWireIdx.ports.get(id);
    if(!el||!prev||!ports) return false;
    const x=el.offsetLeft,y=el.offsetTop,dx=x-prev.x,dy=y-prev.y;
    for(const p of new Set(ports.values())){ p.x+=dx; p.y+=dy; p.edge+=dx; p.bottom+=dy; }
    prev.x=x; prev.y=y;
  }
  return true;
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
  b.title="Link style: "+WF_LINK_MODE_LBL[wfLinkMode]+" - click to cycle (spline → linear → straight)";
}

// ── Link shapes ──────────────────────────────────────────────────────────────
const WF_LINK_MIN=40, WF_LINK_MAX=380;
const WF_LINK_CLEAR=14;   // px of link that must show past each card's edge
const WF_LINK_STUB=14;    // shortest stub a linear/straight link leaves a port with
// The stub has the same job the spline's lobe has: a dot sits inside its card,
// so a stub that stops at the border shows nothing. Reach past the edge by the
// same clearance, and — for two blocks nose to nose, where there is no room —
// shrink rather than let the two stubs overshoot each other into a zigzag.
function wfStub(a,b){
  const s=Math.max(WF_LINK_STUB,
    (a.edge==null?a.x:a.edge)-a.x + WF_LINK_CLEAR,
    b.x-(b.edge==null?b.x:b.edge) + WF_LINK_CLEAR);
  return b.x>a.x ? Math.max(3, Math.min(s,(b.x-a.x)/3)) : s;
}

// LiteGraph's spline: horizontal handles set a quarter of the port-to-port
// distance out from each dot. Level ports therefore give a dead-straight line
// for free and a short hop stays nearly straight.
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
// wfSplineOff bisects; the path and its flow marker both want the same answer,
// so memoise the last one rather than solve it twice per link per frame.
let _wfOffKey="", _wfOffVal=0;
function wfSplineOffCached(a,b){
  const key=a.x+","+a.y+","+a.edge+","+b.x+","+b.y+","+b.edge;
  if(key!==_wfOffKey){ _wfOffKey=key; _wfOffVal=wfSplineOff(a,b); }
  return _wfOffVal;
}
function wfSplinePath(a,b){
  const off=wfSplineOffCached(a,b), lift=wfSplineLift(b.x-a.x, b.y-a.y);
  return `M${a.x},${a.y} C${a.x+off},${a.y-lift} ${b.x-off},${b.y-lift} ${b.x},${b.y}`;
}
function wfLinearPath(a,b){
  const s=wfStub(a,b);
  return `M${a.x},${a.y} L${a.x+s},${a.y} L${b.x-s},${b.y} L${b.x},${b.y}`;
}
function wfStraightPath(a,b){
  const pts=wfOrthogonalPoints(a,b);
  let d=`M${a.x},${a.y}`;
  for(let i=1;i<pts.length-1;i++){
    const p=pts[i-1],q=pts[i],r=pts[i+1];
    const before=Math.hypot(q.x-p.x,q.y-p.y),after=Math.hypot(r.x-q.x,r.y-q.y);
    const radius=Math.min(10,before/2,after/2);
    if(!radius){ d+=` L${q.x},${q.y}`; continue; }
    d+=` L${q.x-(q.x-p.x)/before*radius},${q.y-(q.y-p.y)/before*radius}`+
       ` Q${q.x},${q.y} ${q.x+(r.x-q.x)/after*radius},${q.y+(r.y-q.y)/after*radius}`;
  }
  return d+` L${b.x},${b.y}`;
}
function wfOrthogonalPoints(a,b){
  const s=wfStub(a,b);
  if(b.x-a.x>s*2){
    if(Math.abs(b.y-a.y)<1) return [a,b];
    const mx=(a.x+b.x)/2;
    return [a,{x:mx,y:a.y},{x:mx,y:b.y},b];
  }
  // A return edge must leave the source to the right, travel below both
  // cards, then approach the destination from the left (including self-links).
  const right=Math.max(a.x,a.edge??a.x)+s;
  const left=Math.min(b.x,b.edge??b.x)-s;
  const y=Math.max(a.bottom??a.y,b.bottom??b.y)+28;
  return [a,{x:right,y:a.y},{x:right,y},{x:left,y},{x:left,y:b.y},b];
}
function wfWirePath(a,b){
  if(wfLinkMode==="linear")   return wfLinearPath(a,b);
  if(wfLinkMode==="straight") return wfStraightPath(a,b);
  return wfSplinePath(a,b);
}

// Arrow position and tangent are computed from the route rather than reading
// SVG path geometry on every drag frame.
function wfLinkMid(a,b){
  if(wfLinkMode==="linear"){
    const s=wfStub(a,b), p={x:a.x+s,y:a.y}, q={x:b.x-s,y:b.y};
    return { x:(p.x+q.x)/2, y:(p.y+q.y)/2, ang:Math.atan2(q.y-p.y,q.x-p.x) };
  }
  if(wfLinkMode==="straight"){
    const pts=wfOrthogonalPoints(a,b);
    const lengths=pts.slice(1).map((p,i)=>Math.hypot(p.x-pts[i].x,p.y-pts[i].y));
    let remaining=lengths.reduce((sum,n)=>sum+n,0)/2;
    for(let i=0;i<lengths.length;i++){
      if(remaining<=lengths[i]){
        const p=pts[i],q=pts[i+1],t=lengths[i]?remaining/lengths[i]:0;
        return {x:p.x+(q.x-p.x)*t,y:p.y+(q.y-p.y)*t,ang:Math.atan2(q.y-p.y,q.x-p.x)};
      }
      remaining-=lengths[i];
    }
    return {x:a.x,y:a.y,ang:0};
  }
  const off=wfSplineOffCached(a,b), lift=wfSplineLift(b.x-a.x, b.y-a.y);
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
const wfWireGroups=new Map(), wfWireGroupsByFrom=new Map();
let wfWireRoutes=[], wfWireGraph=null;
const wfWireRoutesByNode=new Map();
function wfWireRouteCompare(p,q){ return p.span-q.span || (p.key<q.key?-1:p.key>q.key?1:0); }
function wfOrderWireGroups(svg,routes){
  let cursor=svg.firstChild;
  for(const {ed} of routes){
    const grp=wfWireGroups.get(ed);
    if(grp!==cursor) svg.insertBefore(grp,cursor);
    cursor=grp.nextSibling;
  }
}
function wfDrawMovedWires(svg,g,ids){
  if(wfWireGraph!==g || !wfWireIndexMove(ids)) return false;
  const changed=new Set();
  for(const id of ids) for(const route of wfWireRoutesByNode.get(id)||[]) changed.add(route);
  for(const route of changed){
    const {ed,a,b}=route,grp=wfWireGroups.get(ed);
    if(!grp||grp.parentNode!==svg) return false;
    const d=wfWirePath(a,b);
    if(grp.__path!==d){
      const {halo,hit,p}=grp.__parts;
      halo.setAttribute("d",d); hit.setAttribute("d",d); p.setAttribute("d",d); grp.__path=d;
    }
    route.span=Math.abs(b.x-a.x)+Math.abs(b.y-a.y);
  }
  // Preserve shortest-first paint order even when a drag changes link spans.
  if(changed.size){ wfWireRoutes.sort(wfWireRouteCompare); wfOrderWireGroups(svg,wfWireRoutes); }
  return true;
}

function wfDrawWires(movedIds){
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();   // node moves redraw wires → keep the map live
  const svg=$("wf-wires"), g=wfGraph();
  const world=$("wf-world");
  if(!g){
    svg.innerHTML=""; wfWireGroups.clear(); wfWireGroupsByFrom.clear();
    wfWireRoutes=[]; wfWireGraph=null; wfWireRoutesByNode.clear();
    wfWireIdx={ports:new Map()}; wfWiresStale=false; return;
  }
  if(world && world.offsetParent===null){ wfWiresStale=true; return; }   // canvas hidden — measurements would be 0
  const wasStale=wfWiresStale; wfWiresStale=false;
  if(g && !wasStale && movedIds && wfDrawMovedWires(svg,g,movedIds)) return;
  // Keep the dashed preview only while a connect drag is still in progress.
  // A finished drop used to redraw the canvas before clearing the gesture, so
  // this pass glued the preview back on top of the real wire.
  const connecting=wfGesture?.mode==="connect" || wfGesture?.connection?.mode==="connect";
  const temp=connecting ? svg.querySelector(".temp") : null;
  if(!connecting) wfClearTemp();
  wfWireIndexRebuild();

  // Resolve endpoints first, then sort shortest-first so a long run paints over
  // the local hops rather than under them. Ties break on a stable key, so paint
  // order no longer changes merely because JSON import/delete/undo reordered the
  // edge array.
  const routes=[];
  (g.edges||[]).forEach(ed=>{
    const toPort=ed.toPort||"in";
    const a=wfPortPt(ed.from,ed.fromPort), b=wfPortPt(ed.to,toPort);
    if(!a||!b) return;
    routes.push({ ed, a, b, toPort,
      span:Math.abs(b.x-a.x)+Math.abs(b.y-a.y),
      key:`${ed.from}\u0000${ed.fromPort||"out"}\u0000${ed.to}\u0000${toPort}` });
  });
  routes.sort(wfWireRouteCompare);
  wfWireRoutes=routes; wfWireGraph=g; wfWireRoutesByNode.clear();
  for(const route of routes){
    for(const id of new Set([route.ed.from,route.ed.to])){
      let adjacent=wfWireRoutesByNode.get(id);
      if(!adjacent) wfWireRoutesByNode.set(id,adjacent=[]);
      adjacent.push(route);
    }
  }

  const index=typeof wfBuildRenderIndex==="function" ? wfBuildRenderIndex(g) : null;
  const byId=index ? index.byId : new Map((g.nodes||[]).map(n=>[n.id,n]));
  const live=new Set(); wfWireGroupsByFrom.clear();
  // Keep path elements, focus and execution colours alive during node moves.
  // Only changed paths need attributes written; untouched links do no DOM work.
  let cursor=svg.firstChild;
  routes.forEach(({ed,a,b,toPort})=>{
    const d=wfWirePath(a,b);
    let grp=wfWireGroups.get(ed);
    if(!grp || grp.parentNode!==svg){
      grp=document.createElementNS(WF_NS,"g");
      grp.setAttribute("class","wire-grp"); grp.__edge=ed;
      const halo=document.createElementNS(WF_NS,"path"); halo.setAttribute("class","wire-halo");
      const hit=document.createElementNS(WF_NS,"path"); hit.setAttribute("class","wire-hit");
      hit.setAttribute("tabindex","0"); hit.setAttribute("role","button");
      const tt=document.createElementNS(WF_NS,"title"); hit.appendChild(tt);
      const p=document.createElementNS(WF_NS,"path");
      grp.appendChild(halo); grp.appendChild(hit); grp.appendChild(p);
      grp.__parts={halo,hit,tt,p}; wfWireGroups.set(ed,grp);
    }
    live.add(ed);
    let fromGroups=wfWireGroupsByFrom.get(ed.from);
    if(!fromGroups) wfWireGroupsByFrom.set(ed.from,fromGroups=[]);
    fromGroups.push(grp);
    const {halo,hit,tt,p}=grp.__parts;
    if(grp.__path!==d){
      halo.setAttribute("d",d); hit.setAttribute("d",d); p.setAttribute("d",d); grp.__path=d;
    }
    const fromLabel=WF_PORT_LBL[ed.fromPort]||ed.fromPort||"out";
    const nodeLabel=id=>{ const n=byId.get(id); return n&&(WF_NODES[n.type]?.label||n.type)||id; };
    const description=`${nodeLabel(ed.from)} → ${nodeLabel(ed.to)} (${fromLabel})`;
    if(grp.__description!==description){
      hit.setAttribute("aria-label",description+"; press Delete to remove");
      tt.textContent=description+" · Right-click or Delete to remove";
      grp.__description=description;
    }
    const src=byId.get(ed.from);
    const tone=typeof wfWireTone==="function" ? wfWireTone(ed.fromPort, toPort, src, ed, index) : "";
    const wireClass="wire"+(toPort==="loop"?" loopback":"")+(tone?" tone-"+tone:"");
    if(grp.__wireClass!==wireClass){
      p.setAttribute("class",wireClass); grp.__wireClass=wireClass;
    }
    if(p.dataset.from!==ed.from) p.dataset.from=ed.from;
    if(p.dataset.fromport!==(ed.fromPort||"out")) p.dataset.fromport=ed.fromPort||"out";
    if(p.dataset.to!==ed.to) p.dataset.to=ed.to;
    const taken=typeof wfRanPort!=="undefined" ? wfRanPort[ed.from] : null;
    p.classList.toggle("took-wire",taken!=null && String(taken)===(ed.fromPort||"out"));
    p.classList.toggle("nottook-wire",taken!=null && String(taken)!==(ed.fromPort||"out") &&
      typeof wfIsBranchPort==="function" && wfIsBranchPort(ed.fromPort));
    // No mid-wire direction marker: the flow reads from the port side and the
    // run-trail dash animation — a floating arrowhead was just visual noise.
    if(grp!==cursor) svg.insertBefore(grp,cursor);
    cursor=grp.nextSibling;
  });
  for(const [ed,grp] of wfWireGroups){
    if(!live.has(ed)){ grp.remove(); wfWireGroups.delete(ed); }
  }
  if(temp) svg.appendChild(temp);
  wfSyncWireSelection();
}
function wfSyncWireSelection(){
  const svg=$("wf-wires"); if(!svg) return;
  const selected=new Set(WF.sel||[]);
  svg.classList.toggle("has-selection",selected.size>0);
  svg.querySelectorAll(".wire-grp").forEach(grp=>{
    const e=grp.__edge;
    grp.classList.toggle("related",!!e&&(selected.has(e.from)||selected.has(e.to)));
  });
  const button=$("wf-fit-selection"); if(button) button.disabled=!selected.size;
  const stats=$("wf-graph-stats"),g=wfGraph();
  if(stats) stats.textContent=g?`${g.nodes.length} nodes · ${(g.edges||[]).length} links`+
    (selected.size?` · ${selected.size} selected`:""):"";
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

// Hover a wire → light up its two endpoint sockets so the eye traces the link
// from block to block. Delegated like the Delete handler: one listener serves
// every wire, and leaving clears whatever is lit (one hover at a time).
document.addEventListener("mouseover",e=>{
  const t=e.target;
  if(!t||!t.classList||!t.classList.contains("wire-hit")) return;
  const grp=t.parentNode, ed=grp&&grp.__edge; if(!ed) return;
  const from=document.querySelector(`.wf-node[data-node="${ed.from}"] .wf-port[data-port="${ed.fromPort||"out"}"]`);
  const to=document.querySelector(`.wf-node[data-node="${ed.to}"] .wf-port[data-port="${ed.toPort||"in"}"]`);
  if(from) from.classList.add("hover-end");
  if(to) to.classList.add("hover-end");
});
document.addEventListener("mouseout",e=>{
  const t=e.target;
  if(!t||!t.classList||!t.classList.contains("wire-hit")) return;
  document.querySelectorAll(".wf-port.hover-end").forEach(p=>p.classList.remove("hover-end"));
});

function wfDeleteWire(ed){
  const g=wfGraph(); if(!g||!ed) return;
  wfPushUndo();
  const i=g.edges.indexOf(ed); if(i>=0) g.edges.splice(i,1);
  wfRenderCanvas();
  setStatus("Wire deleted - Ctrl+Z to undo");
}

function wfDrawTempWire(mx,my){
  const s=wfGesture?.connection || wfGesture;
  if(!s || s.mode!=="connect") return;
  s.mx=mx; s.my=my;
  const a=wfPortPt(s.from,s.port); if(!a) return;
  const wr=$("wf-world").getBoundingClientRect();
  const b={ x:(mx-wr.left)/wfZoom, y:(my-wr.top)/wfZoom };
  const svg=$("wf-wires"); let t=svg.querySelector(".temp");
  if(!t){ t=document.createElementNS(WF_NS,"path"); t.setAttribute("class","temp"); svg.appendChild(t); }
  if(!wfWireIdx.ports.size) wfWireIndexRebuild();
  t.setAttribute("d",s.direction==="in" ? wfWirePath(b,a) : wfWirePath(a,b));
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
