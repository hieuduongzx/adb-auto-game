// ── Wires ────────────────────────────────────────────────────────────────────
function wfPortPt(nodeId,port){
  let el;
  if(port==="in"||port==="loop"){
    el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.in[data-port="${port}"]`);
    if(!el) el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.in`);
  } else {
    el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.out[data-port="${port}"]`);
    if(!el) el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.out`);
  }
  if(!el) return null;
  const wr=$("wf-world").getBoundingClientRect(), r=el.getBoundingClientRect();
  return { x:(r.left+r.width/2-wr.left)/wfZoom, y:(r.top+r.height/2-wr.top)/wfZoom };
}

// Arrowhead markers — colours read from the shared CSS vars (base.css :root) so
// wires/ports/canvas overlays never drift onto a second hex for the same role.
const WF_WIRE_DEFS = (function(){
  const cs=getComputedStyle(document.documentElement);
  const v=(name,fallback)=>(cs.getPropertyValue(name)||fallback).trim();
  const mk=(id,c)=>`<marker id="${id}" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L6,3 L0,6 Z" fill="${c}"/></marker>`;
  return "<defs>"+
    mk("wf-ah",v("--wire-arrow","#94a6ba"))+
    mk("wf-ah-t",v("--branch-t","#1f9d57"))+
    mk("wf-ah-f",v("--branch-f","#e0792e"))+
    mk("wf-ah-switch",v("--wire-switch","#9a78e6"))+
    mk("wf-ah-loop",v("--branch-loop-line","#d09030"))+
    mk("wf-ah-run-ok",v("--run-ok","#1f9d57"))+
    mk("wf-ah-run-fail",v("--run-fail","#d6483f"))+
    mk("wf-ah-hover",v("--accent","#2f6fed"))+
    mk("wf-ah-temp",v("--accent","#2f6fed"))+
  "</defs>";
})();

// ── Wire shape ────────────────────────────────────────────────────────────────
// Two shapes only, like a normal node editor:
//   direct  → straight line when level, otherwise one soft cubic — used
//             whenever that shape doesn't slice through a node it skips over;
//   detour  → stub → riser → shelf → riser → stub. The shelf travels the
//             nearest clear horizontal band (a gap between node rows, or just
//             outside the first/last row), each riser slides sideways until it
//             clears every node box, and a new detour nudges a few px away
//             from any detour already placed this pass — so wires never cut
//             through blocks and never overdraw each other's shelf.

// Node boxes snapshot for the current draw pass (world coords).
let wfWireBoxes=[];
function wfWireBoxesRebuild(){
  wfWireBoxes=[];
  document.querySelectorAll("#wf-world .wf-node").forEach(el=>{
    wfWireBoxes.push({ left:el.offsetLeft, top:el.offsetTop,
                       right:el.offsetLeft+el.offsetWidth, bottom:el.offsetTop+el.offsetHeight });
  });
}

// Sampled obstruction test: true when the cubic a → (c1x,a.y) → (c2x,b.y) → b
// passes through a node box other than the endpoints' own nodes. A straight
// level line is the degenerate case of the same cubic, so one test covers both.
function wfWireBlocked(a,b,c1x,c2x){
  const pad=4;
  const near=(p,bx)=>p.x>=bx.left-8&&p.x<=bx.right+8&&p.y>=bx.top-8&&p.y<=bx.bottom+8;
  const minX=Math.min(a.x,b.x,c1x,c2x)-pad, maxX=Math.max(a.x,b.x,c1x,c2x)+pad;
  const minY=Math.min(a.y,b.y)-pad, maxY=Math.max(a.y,b.y)+pad;
  // Broad phase: only sample against boxes overlapping the curve's bounds.
  const boxes=wfWireBoxes.filter(bx=>!near(a,bx)&&!near(b,bx) &&
    bx.right>=minX&&bx.left<=maxX&&bx.bottom>=minY&&bx.top<=maxY);
  if(!boxes.length) return false;
  // Adaptive sampling: long/high-curvature splines need more probes than a
  // short local hop. Roughly one sample per 10 world px, capped for large maps.
  const approx=Math.hypot(c1x-a.x,0)+Math.hypot(c2x-c1x,b.y-a.y)+Math.hypot(b.x-c2x,0);
  const steps=Math.max(24,Math.min(128,Math.ceil(approx/10)));
  for(let i=1;i<steps;i++){
    const t=i/steps, u=1-t;
    const x=u*u*u*a.x + 3*u*u*t*c1x + 3*u*t*t*c2x + t*t*t*b.x;
    const y=(u*u*u+3*u*u*t)*a.y + (3*u*t*t+t*t*t)*b.y;
    for(const bx of boxes)
      if(x>bx.left-pad && x<bx.right+pad && y>bx.top-pad && y<bx.bottom+pad) return true;
  }
  return false;
}
function wfFwdPull(dx,dy){ return Math.min(130, Math.max(24, Math.abs(dx)*0.45 + Math.abs(dy)*0.12)); }

// A detour's vertical riser at x spanning yA..yB must not pass through a node
// box. Try sliding toward the port (the sliver before the first blocker), or
// pushing outward past the blockers — pick the clear option nearer the start.
// `stubY` is the horizontal stub's row: pushing outward past a box that also
// covers that row would drag the stub through it, so such a push is rejected.
function wfRiserX(x0, yA, yB, dir, limit, stubY){
  const pad=6, y0=Math.min(yA,yB)-2, y1=Math.max(yA,yB)+2;
  const hit=x=>{ for(const bx of wfWireBoxes)
      if(x>bx.left-pad && x<bx.right+pad && y1>bx.top-pad && y0<bx.bottom+pad) return bx;
    return null; };
  if(!hit(x0)) return x0;
  let xs=x0, g=0, bs;                        // slide toward the port
  while((bs=hit(xs)) && g++<8) xs = dir>0 ? bs.left-pad : bs.right+pad;
  const slideOk = !bs && (dir>0 ? xs>=limit : xs<=limit);
  let xp=x0, g2=0, bp, pushOk=true;          // push outward past the blockers
  while((bp=hit(xp)) && g2++<8){
    if(stubY>bp.top-pad && stubY<bp.bottom+pad){ pushOk=false; break; }
    xp = dir>0 ? bp.right+pad : bp.left-pad;
  }
  pushOk = pushOk && !hit(xp);
  if(slideOk && (!pushOk || Math.abs(xs-x0)<=Math.abs(xp-x0))) return xs;
  if(pushOk) return xp;
  return x0;
}

// Nearest clear horizontal band to the wire's midpoint for the shelf leg:
// merge the (padded) y-extents of every box the shelf passes over, then pick
// among the gaps between those bands plus the outside of the first/last band.
// This lets a long back-run travel BETWEEN node rows instead of always boxing
// around the whole graph.
function wfShelfY(xLo,xHi,a,b){
  const pad=12, MIN=18;
  const iv=[];
  for(const bx of wfWireBoxes){
    if(bx.right<xLo || bx.left>xHi) continue;
    iv.push([bx.top-pad, bx.bottom+pad]);
  }
  const mid=(a.y+b.y)/2;
  if(!iv.length) return mid;
  iv.sort((p,q)=>p[0]-q[0]);
  const bands=[iv[0].slice()];
  for(let i=1;i<iv.length;i++){
    const m=bands[bands.length-1];
    if(iv[i][0]<=m[1]+MIN) m[1]=Math.max(m[1],iv[i][1]); else bands.push(iv[i].slice());
  }
  let best=bands[0][0]-12;
  const consider=y=>{ if(Math.abs(y-mid)<Math.abs(best-mid)) best=y; };
  for(let i=0;i<bands.length-1;i++) consider((bands[i][1]+bands[i+1][0])/2);
  consider(bands[bands.length-1][1]+12);
  return best;
}
// Vertical clearance from y to the nearest box the shelf passes over (0 = inside one).
function wfShelfClearance(x0,x1,y){
  let d=1e9;
  for(const bx of wfWireBoxes){
    if(bx.right<x0 || bx.left>x1) continue;
    if(y>=bx.top && y<=bx.bottom) return 0;
    d=Math.min(d, y<bx.top ? bx.top-y : y-bx.bottom);
  }
  return d;
}

// Detours placed earlier in the current draw pass — a new detour nudges its
// shelf/risers a few px away from any it would overdraw. Overlap is resolved
// pairwise on real geometry, so unrelated wires never fan apart.
let wfPlacedDetours=[];
function wfShelfLaneY(x0,x1,preferred,mid){
  const occupied=wfPlacedDetours.filter(o=>Math.min(x1,o.x1)>Math.max(x0,o.x0)).map(o=>o.routeY);
  const ok=y=>wfShelfClearance(x0,x1,y)>=10 && occupied.every(oy=>Math.abs(y-oy)>=10);
  if(ok(preferred)) return preferred;
  // Search symmetric 10px lanes and choose the valid one nearest the endpoint
  // midpoint. Unlike a one-step nudge, this cannot settle inside a node band.
  for(let step=1;step<=20;step++){
    const candidates=[preferred-step*10,preferred+step*10].filter(ok);
    if(candidates.length) return candidates.sort((p,q)=>Math.abs(p-mid)-Math.abs(q-mid))[0];
  }
  return preferred;
}
function wfDetourGeom(a,b){
  let routeY=(a.y+b.y)/2, xOut=a.x+16, xIn=b.x-16;
  for(let i=0;i<2;i++){                       // risers ↔ shelf settle in 2 passes
    xOut=wfRiserX(a.x+16, a.y, routeY, +1, a.x+6, a.y);
    xIn =wfRiserX(b.x-16, routeY, b.y, -1, b.x-6, b.y);
    routeY=wfShelfY(Math.min(xOut,xIn), Math.max(xOut,xIn), a, b);
  }
  let x0=Math.min(xOut,xIn), x1=Math.max(xOut,xIn);
  routeY=wfShelfLaneY(x0,x1,routeY,(a.y+b.y)/2);
  // The shelf may have moved to avoid another wire. Recompute both risers for
  // that FINAL shelf, otherwise a previously-clear riser can cross a node.
  for(let i=0;i<2;i++){
    xOut=wfRiserX(a.x+16,a.y,routeY,+1,a.x+6,a.y);
    xIn =wfRiserX(b.x-16,routeY,b.y,-1,b.x-6,b.y);
  }
  // Separate coincident risers only when the nudged lane is also node-clear.
  const yr=(y0,y1,o0,o1)=>Math.min(Math.max(y0,y1),Math.max(o0,o1))>Math.max(Math.min(y0,y1),Math.min(o0,o1));
  for(const o of wfPlacedDetours){
    if(Math.abs(xOut-o.xOut)<8 && yr(a.y,routeY,o.ya,o.routeY)){
      const cand=xOut+8, clear=wfRiserX(cand,a.y,routeY,+1,a.x+6,a.y);
      if(Math.abs(clear-cand)<.1) xOut=cand;
    }
    if(Math.abs(xIn-o.xIn)<8 && yr(routeY,b.y,o.routeY,o.yb)){
      const cand=xIn-8, clear=wfRiserX(cand,routeY,b.y,-1,b.x-6,b.y);
      if(Math.abs(clear-cand)<.1) xIn=cand;
    }
  }
  x0=Math.min(xOut,xIn); x1=Math.max(xOut,xIn);
  return {xOut,xIn,routeY,x0,x1,ya:a.y,yb:b.y};
}

// `register` — wfDrawWires passes true so the wire's detour geometry joins
// wfPlacedDetours (what later wires dodge). The temp wire doesn't register.
function wfWirePath(a,b,register){
  const dx=b.x-a.x, dy=b.y-a.y;

  // Forward flow: straight when level, one calm spline otherwise — as long as
  // the direct shape doesn't cut through a node it skips over.
  if(dx>=-20){
    const pull=wfFwdPull(dx,dy);
    if(!wfWireBlocked(a,b,a.x+pull,b.x-pull)){
      if(dx>=0 && Math.abs(dy)<5) return `M${a.x},${a.y} L${b.x},${b.y}`;
      return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
    }
  }
  // Short backward hop with a real vertical offset (e.g. into the row below):
  // the classic S-curve is lighter and reads naturally — it travels the gap
  // between rows instead of boxing around them. Only when the gap is clear.
  else if(Math.abs(dy)>=40 && dx>-400){
    const pull=Math.min(180, 40+Math.abs(dx)*0.35+Math.abs(dy)*0.10);
    if(!wfWireBlocked(a,b,a.x+pull,b.x-pull))
      return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
  }

  // Detour: out right → riser → clear shelf band → riser → in from the left.
  // The shelf runs rightwards for blocked forward wires and leftwards for
  // back-runs (h flips the middle corners).
  const geom=wfDetourGeom(a,b);
  if(register) wfPlacedDetours.push(geom);
  const {xOut,xIn,routeY}=geom, r=10;
  const h=xIn>=xOut?1:-1, s1=routeY>=a.y?1:-1, s2=b.y>=routeY?1:-1;
  const room=Math.abs(xIn-xOut)/2;
  const r1=Math.min(r, Math.abs(routeY-a.y)/2, Math.abs(xOut-a.x)/2, room);
  const r2=Math.min(r, Math.abs(routeY-b.y)/2, Math.abs(b.x-xIn)/2, room);
  return `M${a.x},${a.y} L${xOut-r1},${a.y} Q${xOut},${a.y} ${xOut},${a.y+s1*r1}`+
         ` L${xOut},${routeY-s1*r1} Q${xOut},${routeY} ${xOut+h*r1},${routeY}`+
         ` L${xIn-h*r2},${routeY} Q${xIn},${routeY} ${xIn},${routeY+s2*r2}`+
         ` L${xIn},${b.y-s2*r2} Q${xIn},${b.y} ${xIn+r2},${b.y} L${b.x},${b.y}`;
}

// Wires draw "blind" while #wf-world is display:none (Preview tab): every
// getBoundingClientRect() returns 0 → paths become an invisible M0,0. The guard
// below skips that draw pass and sets a stale flag; wfSwitchView("canvas")
// redraws once the canvas is visible again.
let wfWiresStale=false;
function wfDrawWires(){
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();   // node moves redraw wires → keep the map live
  const svg=$("wf-wires"), g=wfGraph();
  const world=$("wf-world");
  if(world && world.offsetParent===null){ wfWiresStale=true; return; }   // canvas hidden — measurements would be 0
  wfWiresStale=false;
  const temp=svg.querySelector(".temp");
  svg.innerHTML=WF_WIRE_DEFS; if(temp) svg.appendChild(temp);
  if(!g) return;
  const NS="http://www.w3.org/2000/svg";
  wfWireBoxesRebuild();
  wfPlacedDetours=[];

  // Route in a deterministic order. Geometry no longer changes merely because
  // JSON import/delete/undo happened to reorder the edge array.
  const edges=[...(g.edges||[])].sort((a,b)=>{
    const ka=`${a.from}\u0000${a.fromPort||"out"}\u0000${a.to}\u0000${a.toPort||"in"}`;
    const kb=`${b.from}\u0000${b.fromPort||"out"}\u0000${b.to}\u0000${b.toPort||"in"}`;
    return ka<kb?-1:ka>kb?1:0;
  });
  edges.forEach(ed=>{
    if(wfSameStack(ed.from,ed.to)) return;
    const toPort=ed.toPort||"in";
    const a=wfPortPt(ed.from,ed.fromPort), b=wfPortPt(ed.to,toPort);
    if(!a||!b) return;
    const d=wfWirePath(a,b,true);
    const cls="wire"+(toPort==="loop"?" loopback":"");
    const grp=document.createElementNS(NS,"g"); grp.setAttribute("class","wire-grp"); grp.__edge=ed;
    const hit=document.createElementNS(NS,"path"); hit.setAttribute("class","wire-hit"); hit.setAttribute("d",d);
    hit.setAttribute("tabindex","0"); hit.setAttribute("role","button");
    const fromLabel=WF_PORT_LBL[ed.fromPort]||ed.fromPort||"out";
    hit.setAttribute("aria-label",`Wire ${fromLabel||"out"}; press Delete to remove`);
    const tt=document.createElementNS(NS,"title"); tt.textContent="Right-click or press Delete to remove wire"; hit.appendChild(tt);
    hit.addEventListener("keydown",e=>{
      if(e.key==="Delete"||e.key==="Backspace"){
        e.preventDefault(); e.stopPropagation(); wfDeleteWire(ed);
      }
    });
    const p=document.createElementNS(NS,"path");
    p.setAttribute("class",cls);
    p.dataset.from=ed.from; p.dataset.fromport=ed.fromPort; p.dataset.to=ed.to;
    p.setAttribute("d",d);
    grp.appendChild(hit); grp.appendChild(p);
    svg.appendChild(grp);
  });
}

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
  if(!t){ t=document.createElementNS("http://www.w3.org/2000/svg","path"); t.setAttribute("class","temp"); svg.appendChild(t); }
  if(!wfWireBoxes.length) wfWireBoxesRebuild();
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
