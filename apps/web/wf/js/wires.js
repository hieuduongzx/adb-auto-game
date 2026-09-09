// ── Wires ────────────────────────────────────────────────────────────────────
// One DOM read pass per draw feeds everything below: node boxes AND port centres
// come from offsetLeft/offsetTop (already #wf-world layout coords). That makes
// the geometry zoom-independent, immune to the :hover scale on a port dot, and —
// because nothing is measured after an element has been appended — costs a
// single layout flush instead of one forced relayout per port.
const WF_WIRE_CELL = 256;      // row/column bucket size for the box lookups
let wfWireIdx = { boxes:[], ports:new Map(), rows:null, cols:null };
let _wfBandStamp = 0;          // per-query dedupe marker stamped onto the boxes

function wfWireIndexRebuild(){
  const boxes=[], portsByNode=new Map(), rows=new Map(), cols=new Map();
  const bucket=(map,key,b)=>{ let a=map.get(key); if(!a) map.set(key,a=[]); a.push(b); };
  document.querySelectorAll("#wf-world .wf-node").forEach(el=>{
    const x=el.offsetLeft, y=el.offsetTop;
    const box={ id:el.dataset.node, left:x, top:y,
                right:x+el.offsetWidth, bottom:y+el.offsetHeight, _s:0 };
    const ports=new Map();
    el.querySelectorAll(".wf-port").forEach(p=>{
      const side=p.classList.contains("out")?"out":"in";
      const pt={ x:x+p.offsetLeft+p.offsetWidth/2, y:y+p.offsetTop+p.offsetHeight/2 };
      ports.set(side+":"+p.dataset.port, pt);
      if(!ports.has(side)) ports.set(side, pt);   // first port of a side = fallback
    });
    portsByNode.set(box.id, ports);
    boxes.push(box);
    for(let c=Math.floor(box.top/WF_WIRE_CELL);  c<=Math.floor(box.bottom/WF_WIRE_CELL); c++) bucket(rows,c,box);
    for(let c=Math.floor(box.left/WF_WIRE_CELL); c<=Math.floor(box.right/WF_WIRE_CELL);  c++) bucket(cols,c,box);
  });
  wfWireIdx={ boxes, ports:portsByNode, rows, cols };
}

// Boxes meeting a horizontal (rows) or vertical (cols) band. Bucket lookups stop
// a 300-block graph from being rescanned for every riser/shelf probe; a band
// wider than the bucket sweep is cheaper to answer from the flat list.
function wfBandBoxes(map, lo, hi, keep){
  const idx=wfWireIdx;
  const c0=Math.floor(lo/WF_WIRE_CELL), c1=Math.floor(hi/WF_WIRE_CELL);
  if(!map || c1-c0>48) return idx.boxes.filter(keep);
  const out=[], s=++_wfBandStamp;
  for(let c=c0;c<=c1;c++){
    const a=map.get(c); if(!a) continue;
    for(const b of a){ if(b._s===s) continue; b._s=s; if(keep(b)) out.push(b); }
  }
  return out;
}
const wfBoxesBandY=(y0,y1)=>wfBandBoxes(wfWireIdx.rows,y0,y1,b=>b.bottom>=y0&&b.top<=y1);
const wfBoxesBandX=(x0,x1)=>wfBandBoxes(wfWireIdx.cols,x0,x1,b=>b.right>=x0&&b.left<=x1);

function wfPortPt(nodeId,port){
  if(!wfWireIdx.ports.size) wfWireIndexRebuild();
  const ports=wfWireIdx.ports.get(nodeId); if(!ports) return null;
  const side=(port==="in"||port==="loop")?"in":"out";
  return ports.get(side+":"+port) || ports.get(side) || null;
}

// Arrowhead markers — colours read from the shared CSS vars (base.css :root) so
// wires/ports/canvas overlays never drift onto a second hex for the same role.
// Rebuilt after a theme switch: every var below resolves to a different hex per
// theme, and a once-computed <defs> would keep painting the old arrowheads.
let _wfWireDefs=null;
function wfWireDefs(){
  if(_wfWireDefs) return _wfWireDefs;
  const cs=getComputedStyle(document.documentElement);
  const v=(name,fallback)=>(cs.getPropertyValue(name)||fallback).trim();
  const mk=(id,c)=>`<marker id="${id}" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L6,3 L0,6 Z" fill="${c}"/></marker>`;
  return _wfWireDefs="<defs>"+
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
}
window.addEventListener("m2k-theme",()=>{ _wfWireDefs=null; });
// ── Wire shape ────────────────────────────────────────────────────────────────
// Three shapes, tried in order — the first one that doesn't cut through a block
// it skips over wins:
//   1. direct  → a straight line when the ports are level, otherwise one soft
//                cubic with horizontal handles (the normal node-editor look);
//   2. bypass  → the same cubic with its handles lifted into the nearest clear
//                horizontal band, so a single obstacle is arced around instead
//                of forcing a boxy detour;
//   3. detour  → stub → riser → shelf → riser → stub. The shelf travels the
//                nearest clear horizontal band (a gap between node rows, or just
//                outside the first/last row), each riser slides sideways until it
//                clears every node box, and a new detour takes a free 10px lane
//                so detours never overdraw each other's shelf.

// Exact segment-vs-box rejection for the straight/level case.
function wfSegBlocked(a,b,skip){
  const pad=4;
  const y0=Math.min(a.y,b.y)-pad, y1=Math.max(a.y,b.y)+pad;
  const x0=Math.min(a.x,b.x)-pad, x1=Math.max(a.x,b.x)+pad;
  for(const bx of wfBoxesBandY(y0,y1)){
    if(skip&&skip.has(bx.id)) continue;
    if(bx.right<x0||bx.left>x1) continue;
    return true;                      // level segment inside the box's y-band
  }
  return false;
}
// Sampled obstruction test for an arbitrary cubic a → c1 → c2 → b: true when it
// passes through a node box other than the ones owning its endpoints.
function wfCubicBlocked(a,c1,c2,b,skip){
  const pad=4;
  const minX=Math.min(a.x,b.x,c1.x,c2.x)-pad, maxX=Math.max(a.x,b.x,c1.x,c2.x)+pad;
  const minY=Math.min(a.y,b.y,c1.y,c2.y)-pad, maxY=Math.max(a.y,b.y,c1.y,c2.y)+pad;
  const boxes=wfBoxesBandY(minY,maxY).filter(bx=>
    !(skip&&skip.has(bx.id)) && bx.right>=minX && bx.left<=maxX);
  if(!boxes.length) return false;
  // Adaptive sampling: long/high-curvature splines need more probes than a short
  // local hop. Roughly one sample per 10 world px, capped for large maps.
  const approx=Math.hypot(c1.x-a.x,c1.y-a.y)+Math.hypot(c2.x-c1.x,c2.y-c1.y)+Math.hypot(b.x-c2.x,b.y-c2.y);
  const steps=Math.max(24,Math.min(128,Math.ceil(approx/10)));
  for(let i=1;i<steps;i++){
    const t=i/steps, u=1-t;
    const w0=u*u*u, w1=3*u*u*t, w2=3*u*t*t, w3=t*t*t;
    const x=w0*a.x+w1*c1.x+w2*c2.x+w3*b.x;
    const y=w0*a.y+w1*c1.y+w2*c2.y+w3*b.y;
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
  const band=wfBoxesBandY(y0-pad,y1+pad);
  const hit=x=>{ for(const bx of band)
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

// Nearest clear horizontal band to `mid` for a leg crossing xLo..xHi: merge the
// (padded) y-extents of every box in that column range, then pick among the gaps
// between those bands plus the outside of the first/last band. This lets a long
// run travel BETWEEN node rows instead of always boxing around the whole graph.
function wfClearBandY(xLo,xHi,mid,skip){
  const pad=12, MIN=18, iv=[];
  for(const bx of wfBoxesBandX(xLo,xHi)){
    if(skip&&skip.has(bx.id)) continue;
    iv.push([bx.top-pad, bx.bottom+pad]);
  }
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
function wfShelfY(xLo,xHi,a,b){ return wfClearBandY(xLo,xHi,(a.y+b.y)/2); }
// Vertical clearance from y to the nearest box the shelf passes over (0 = inside one).
function wfShelfClearance(x0,x1,y){
  let d=1e9;
  for(const bx of wfBoxesBandX(x0,x1)){
    if(y>=bx.top && y<=bx.bottom) return 0;
    d=Math.min(d, y<bx.top ? bx.top-y : y-bx.bottom);
  }
  return d;
}
// Detours placed earlier in the current draw pass — a new detour takes a lane
// clear of any it would overdraw. Overlap is resolved pairwise on real geometry,
// so unrelated wires never fan apart.
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
// `skip` — ids of the endpoint nodes, whose own boxes never count as blockers
// (a port sits ON its node's edge, so proximity tests would always trip).
function wfWirePath(a,b,register,skip){
  const dx=b.x-a.x, dy=b.y-a.y;

  // 1. Forward flow: straight when level, one calm spline otherwise — as long as
  //    the direct shape doesn't cut through a node it skips over.
  if(dx>=-20){
    if(dx>=0 && Math.abs(dy)<5){
      if(!wfSegBlocked(a,b,skip)) return `M${a.x},${a.y} L${b.x},${b.y}`;
    } else {
      const pull=wfFwdPull(dx,dy);
      const c1={x:a.x+pull,y:a.y}, c2={x:b.x-pull,y:b.y};
      if(!wfCubicBlocked(a,c1,c2,b,skip))
        return `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`;
    }
  }
  // Short backward hop with a real vertical offset (e.g. into the row below):
  // the classic S-curve is lighter and reads naturally — it travels the gap
  // between rows instead of boxing around them. Only when the gap is clear.
  else if(Math.abs(dy)>=40 && dx>-400){
    const pull=Math.min(180, 40+Math.abs(dx)*0.35+Math.abs(dy)*0.10);
    const c1={x:a.x+pull,y:a.y}, c2={x:b.x-pull,y:b.y};
    if(!wfCubicBlocked(a,c1,c2,b,skip))
      return `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`;
  }

  // 2. Bypass arc: keep the single-curve look but lift both handles into the
  //    nearest clear horizontal band. One block standing between two level ports
  //    is the common case, and an arc over it reads far better than a detour.
  if(dx>=-20){
    const lo=Math.min(a.x,b.x), hi=Math.max(a.x,b.x);
    const band=wfClearBandY(lo,hi,(a.y+b.y)/2,skip);
    const lift=Math.abs(band-(a.y+b.y)/2);
    if(lift>2 && lift<=260){
      const pull=Math.max(34, Math.min(150, Math.abs(dx)*0.42+lift*0.30));
      // Handles are pulled to the band, so the curve's apex lands ≈ 3/4 of the
      // way there — overshoot slightly so the crest actually clears the row.
      const hy=(a.y+b.y)/2 + (band-(a.y+b.y)/2)*1.34;
      const c1={x:a.x+pull,y:hy}, c2={x:b.x-pull,y:hy};
      if(!wfCubicBlocked(a,c1,c2,b,skip))
        return `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`;
    }
  }

  // 3. Detour: out right → riser → clear shelf band → riser → in from the left.
  //    The shelf runs rightwards for blocked forward wires and leftwards for
  //    back-runs (h flips the middle corners).
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
// measurement returns 0 → paths become an invisible M0,0. The guard below skips
// that draw pass and sets a stale flag; wfSwitchView("canvas") redraws once the
// canvas is visible again.
let wfWiresStale=false;
const WF_NS="http://www.w3.org/2000/svg";
function wfDrawWires(){
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();   // node moves redraw wires → keep the map live
  const svg=$("wf-wires"), g=wfGraph();
  const world=$("wf-world");
  if(world && world.offsetParent===null){ wfWiresStale=true; return; }   // canvas hidden — measurements would be 0
  wfWiresStale=false;
  const temp=svg.querySelector(".temp");
  svg.innerHTML=wfWireDefs(); if(temp) svg.appendChild(temp);
  if(!g) return;
  wfWireIndexRebuild();
  wfPlacedDetours=[];

  // Resolve endpoints first, then route. Shorter wires claim their lanes before
  // long ones, so a local hop keeps its clean shape and the long back-run is the
  // one that detours around it. Ties break on a stable key, so geometry no longer
  // changes merely because JSON import/delete/undo reordered the edge array.
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
    const skip=new Set([ed.from,ed.to]);
    const d=wfWirePath(a,b,true,skip);
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
    grp.appendChild(hit); grp.appendChild(p);
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
  if(!wfWireIdx.boxes.length) wfWireIndexRebuild();
  t.setAttribute("d",wfWirePath(a,b,false,new Set([wfGesture.from])));
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
