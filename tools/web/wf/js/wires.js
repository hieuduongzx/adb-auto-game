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
  const mk=(id,c)=>`<marker id="${id}" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L7,3.5 L0,7 Z" fill="${c}"/></marker>`;
  return "<defs>"+
    mk("wf-ah","#94a6ba")+
    mk("wf-ah-t",v("--branch-t","#1f9d57"))+
    mk("wf-ah-f",v("--branch-f","#e0792e"))+
    mk("wf-ah-loop",v("--branch-loop-line","#d09030"))+
    mk("wf-ah-temp",v("--accent","#2f6fed"))+
  "</defs>";
})();

// ── Wire routing ──────────────────────────────────────────────────────────────
// Keep wires simple: one soft cubic curve from output dot to input dot.
function wfWireKey(ed){ return [ed.from,ed.fromPort||"out",ed.to,ed.toPort||"in"].join("|"); }
function wfWireClamp(v,min,max){ return Math.max(min, Math.min(max, v)); }
function wfWireLayer(ed,a,b){ return 1; }
function wfLaneMap(edges,pts){
  const lanes = new Map();
  const backEdges = edges.filter(ed => {
    const p = pts.get(wfWireKey(ed));
    return p && p.b.x < p.a.x;
  });
  backEdges.sort((x,y) => {
    const px = pts.get(wfWireKey(x)), py = pts.get(wfWireKey(y));
    return Math.abs(px.b.x - px.a.x) - Math.abs(py.b.x - py.a.x);
  });
  backEdges.forEach((ed, i) => lanes.set(wfWireKey(ed), i));
  return lanes;
}
// Bounding box of a node in world coords (left/top/right/bottom), or null.
function wfNodeBox(id){
  const el=wfNodeElById(id);
  if(!el) return null;
  return { left:el.offsetLeft, top:el.offsetTop,
           right:el.offsetLeft+el.offsetWidth, bottom:el.offsetTop+el.offsetHeight };
}
// Cache of every node box for the current draw pass — so the router can test a
// candidate horizontal channel against ALL blocks, not just the two endpoints.
// Rebuilt once per wfDrawWires() call (wfWireBoxesRebuild) to stay cheap.
let wfWireBoxes=[];
function wfWireBoxesRebuild(){
  const g=wfGraph(); wfWireBoxes=[];
  if(!g) return;
  (g.nodes||[]).forEach(n=>{ const b=wfNodeBox(n.id); if(b) wfWireBoxes.push(b); });
}
// Given a horizontal segment y=chanY spanning [x0,x1], is any node in the way?
// pad keeps a little breathing room so wires don't kiss a block's edge.
function wfChannelBlocked(chanY, x0, x1, pad){
  const lo=Math.min(x0,x1)-pad, hi=Math.max(x0,x1)+pad;
  for(const box of wfWireBoxes){
    if(box.right<lo || box.left>hi) continue;                 // no x-overlap
    if(chanY>=box.top-pad && chanY<=box.bottom+pad) return box; // channel cuts this box
  }
  return null;
}
// Find a clear horizontal channel starting at chanY and stepping in `dir`
// (+1 down / -1 up) until no node blocks the span, or we give up after a few
// tries (then just return the last candidate — better a drawn wire than none).
function wfClearChannel(chanY, x0, x1, dir, pad){
  let y=chanY;
  for(let i=0;i<40;i++){
    const hit=wfChannelBlocked(y, x0, x1, pad);
    if(!hit) return y;
    // Jump just past the blocking box in the travel direction, plus padding.
    y = dir>0 ? hit.bottom+pad+6 : hit.top-pad-6;
  }
  return y;
}
function wfWirePath(a,b,ed,lane){
  const dx=b.x-a.x, dy=b.y-a.y;
  
  // Straight/forward connection
  if (dx > -20) {
    if (Math.abs(dy) < 5) {
        // Almost horizontal, draw a straight line
        return `M${a.x},${a.y} L${b.x},${b.y}`;
    }
    const pull = Math.max(Math.abs(dx) * 0.4, Math.abs(dy) * 0.2, 20);
    return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
  } 
  
  // Backward / Loop connection - Hybrid orthogonal + curves
  const pullX = 16 + (lane || 0) * 10; // Tighter extend out from output/input
  const pullY = 25 + (lane || 0) * 12; // Tighter vertical offset
  const r = 8; // Corner radius
  
  // Geometry-aware side choice: the horizontal channel (routeY) must clear the
  // union of BOTH involved node boxes so it never cuts across a block. We then
  // pick the side (above/below) whose approach INTO the target port is shortest
  // — this steers the wire toward the target and stops it climbing the full
  // height beside a block or looping back over the source node.
  const sBox = ed ? wfNodeBox(ed.from) : null;
  const tBox = ed ? wfNodeBox(ed.to)   : null;
  let topClear    = Math.min(sBox?sBox.top:a.y,    tBox?tBox.top:b.y)    - pullY;
  let bottomClear = Math.max(sBox?sBox.bottom:a.y, tBox?tBox.bottom:b.y) + pullY;

  // Upgrade: the horizontal run travels between the two vertical risers at
  // x = a.x+pullX and x = b.x-pullX. Push each candidate channel out until it
  // clears EVERY node in that x-span (not just the endpoints), so the wire
  // routes around intermediate blocks instead of slicing through them.
  const runX0 = a.x + pullX, runX1 = b.x - pullX;
  const pad = 7;
  topClear    = wfClearChannel(topClear,    runX0, runX1, -1, pad);
  bottomClear = wfClearChannel(bottomClear, runX0, runX1, +1, pad);
  
  let routeY, signY1, signY2;
  const approachUp   = Math.abs(b.y - topClear);      // vertical run into target if routed above
  const approachDown = Math.abs(bottomClear - b.y);   // …if routed below
  if (approachDown <= approachUp) {
    // Route BELOW both nodes: a goes DOWN to routeY, then UP into b.
    routeY = bottomClear;
    signY1 = 1;
    signY2 = -1;
  } else {
    // Route ABOVE both nodes: a goes UP to routeY, then DOWN into b.
    routeY = topClear;
    signY1 = -1;
    signY2 = 1;
  }
  
  // Handle edge cases where dy is too small for the corner radius
  const safeR1 = Math.min(r, Math.abs(routeY - a.y) / 2, Math.abs(pullX) / 2);
  const safeR2 = Math.min(r, Math.abs(routeY - b.y) / 2, Math.abs(pullX) / 2);

  return `M${a.x},${a.y} 
          L${a.x+pullX-safeR1},${a.y}
          Q${a.x+pullX},${a.y} ${a.x+pullX},${a.y+signY1*safeR1}
          L${a.x+pullX},${routeY-signY1*safeR1}
          Q${a.x+pullX},${routeY} ${a.x+pullX-safeR1},${routeY}
          L${b.x-pullX+safeR2},${routeY}
          Q${b.x-pullX},${routeY} ${b.x-pullX},${routeY+signY2*safeR2}
          L${b.x-pullX},${b.y-signY2*safeR2}
          Q${b.x-pullX},${b.y} ${b.x-pullX+safeR2},${b.y}
          L${b.x},${b.y}`;
}

function wfDrawWires(){
  const svg=$("wf-wires"), g=wfGraph();
  const temp=svg.querySelector(".temp");
  svg.innerHTML=WF_WIRE_DEFS; if(temp) svg.appendChild(temp);
  if(!g) return;
  const NS="http://www.w3.org/2000/svg";
  wfWireBoxesRebuild();   // snapshot node boxes so the router can dodge intermediates

  // Layers: 1) loop-backs under, 2) normal/branch, 3) backward arcs on top.
  const edges=(g.edges||[]).slice().filter(ed=>!wfSameStack(ed.from,ed.to));
  const pts=new Map();
  edges.forEach(ed=>{
    const toPort=ed.toPort||"in";
    const a=wfPortPt(ed.from,ed.fromPort), b=wfPortPt(ed.to,toPort);
    if(a&&b) pts.set(wfWireKey(ed), {a,b});
  });
  const lanes=wfLaneMap(edges,pts);
  edges.sort((x,y)=>{
    const px=pts.get(wfWireKey(x)), py=pts.get(wfWireKey(y));
    const lx=px?wfWireLayer(x,px.a,px.b):1;
    const ly=py?wfWireLayer(y,py.a,py.b):1;
    return lx-ly;
  });

  edges.forEach(ed=>{
    const toPort=ed.toPort||"in";
    const p0=pts.get(wfWireKey(ed));
    if(!p0) return;
    const d=wfWirePath(p0.a,p0.b,ed,lanes.get(wfWireKey(ed))||0);
    const cls="wire"+(toPort==="loop"?" loopback":"");
    const grp=document.createElementNS(NS,"g"); grp.setAttribute("class","wire-grp"); grp.__edge=ed;
    const hit=document.createElementNS(NS,"path"); hit.setAttribute("class","wire-hit"); hit.setAttribute("d",d);
    const tt=document.createElementNS(NS,"title"); tt.textContent="Right-click to delete wire"; hit.appendChild(tt);
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
}

function wfDrawTempWire(mx,my){
  const a=wfPortPt(wfGesture.from,wfGesture.port); if(!a) return;
  const wr=$("wf-world").getBoundingClientRect();
  const b={ x:(mx-wr.left)/wfZoom, y:(my-wr.top)/wfZoom };
  const svg=$("wf-wires"); let t=svg.querySelector(".temp");
  if(!t){ t=document.createElementNS("http://www.w3.org/2000/svg","path"); t.setAttribute("class","temp"); svg.appendChild(t); }
  if(!wfWireBoxes.length) wfWireBoxesRebuild();
  t.setAttribute("d",wfWirePath(a,b,{from:wfGesture.from,fromPort:wfGesture.port,to:"__temp",toPort:"in"},0));
}

function wfClearTemp(){ const t=$("wf-wires").querySelector(".temp"); if(t)t.remove(); }
