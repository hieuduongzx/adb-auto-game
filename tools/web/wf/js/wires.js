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
// Backward arcs paint on top of forward flow so a loop-back is never buried.
function wfWireLayer(ed,a,b){ return (b.x-a.x > -20) ? 1 : 2; }
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
// Registry of horizontal channels already claimed this draw pass — parallel
// back-runs consult it so two wires never travel the exact same corridor.
let wfWireChannels=[];
function wfWireBoxesRebuild(){
  const g=wfGraph(); wfWireBoxes=[]; wfWireChannels=[];
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
// Vertical twin of the channel test: does a riser x=riserX spanning [y0,y1]
// cut through any block?
function wfRiserBlocked(riserX, y0, y1, pad){
  const lo=Math.min(y0,y1)-pad, hi=Math.max(y0,y1)+pad;
  for(const box of wfWireBoxes){
    if(box.bottom<lo || box.top>hi) continue;                    // no y-overlap
    if(riserX>=box.left-pad && riserX<=box.right+pad) return box;
  }
  return null;
}
// Slide a vertical riser sideways (dir +1 right / -1 left) until it clears
// every block in its span — mirrors wfClearChannel for the two vertical legs.
function wfClearRiser(riserX, y0, y1, dir, pad){
  let x=riserX;
  for(let i=0;i<40;i++){
    const hit=wfRiserBlocked(x, y0, y1, pad);
    if(!hit) return x;
    x = dir>0 ? hit.right+pad+6 : hit.left-pad-6;
  }
  return x;
}
// Nudge a channel away from corridors other wires already claimed this pass,
// so stacked back-runs fan out into parallel lanes instead of overdrawing.
const WF_CHAN_GAP=9;
function wfChannelSeparate(chanY, x0, x1, dir){
  let y=chanY;
  for(let guard=0;guard<20;guard++){
    const clash=wfWireChannels.find(c=> Math.max(x0,c.x0)<=Math.min(x1,c.x1)
                                     && Math.abs(y-c.y)<WF_CHAN_GAP);
    if(!clash) return y;
    y = clash.y + dir*WF_CHAN_GAP;
  }
  return y;
}
function wfWirePath(a,b,ed,lane){
  const dx=b.x-a.x, dy=b.y-a.y;

  // ── Forward flow: one calm spline ──────────────────────────────────────────
  if (dx > -20) {
    if (Math.abs(dy) < 5) {
        // Almost horizontal, draw a straight line
        return `M${a.x},${a.y} L${b.x},${b.y}`;
    }
    // Tension grows with distance but is clamped: long jumps stay taut instead
    // of ballooning, and short drops still leave the port horizontally.
    const pull = wfWireClamp(Math.abs(dx)*0.45 + Math.abs(dy)*0.12, 24, 130);
    return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
  }

  // ── Backward / loop: orthogonal detour, fully obstacle-aware ───────────────
  // Route plan: exit RIGHT of the source to a vertical riser, travel a clear
  // horizontal channel above or below everything in the way, then a second
  // riser drops LEFT of the target and drives straight into its port. Every
  // one of those three legs is pushed until it clears ALL blocks, and the
  // channel additionally dodges corridors other wires claimed this pass.
  const isTemp = !ed || ed.to==="__temp";
  const stub = 16 + (lane || 0) * 10;  // riser distance out from each port
  const pad  = 7;                      // breathing room kept from block edges
  const r    = 8;                      // corner radius

  const sBox = ed ? wfNodeBox(ed.from) : null;
  const tBox = isTemp ? null : wfNodeBox(ed.to);
  let xOut = a.x + stub, xIn = b.x - stub;

  // Candidate channels just past the union of both endpoint boxes, then pushed
  // outward until they clear every intermediate block in the span.
  let topY = Math.min(sBox?sBox.top:a.y,    tBox?tBox.top:b.y)    - 25;
  let botY = Math.max(sBox?sBox.bottom:a.y, tBox?tBox.bottom:b.y) + 25;
  topY = wfClearChannel(topY, xIn, xOut, -1, pad);
  botY = wfClearChannel(botY, xIn, xOut, +1, pad);

  // Side choice: prefer a channel that sits between the two endpoints
  // (the "gap" between rows) if clear — it produces a shorter total path
  // and keeps the wire visually tighter to its nodes. Fall back to the
  // classic shortest-approach-to-target heuristic when the mid-gap is blocked.
  const midY   = (a.y + b.y) / 2;
  const midLow = Math.min(a.y, b.y);
  const midHigh = Math.max(a.y, b.y);
  let below;
  let routeY;

  // Check if a horizontal span at midY is clear (inside the y-range of both endpoints).
  if (midY > midLow + 12 && midY < midHigh - 12 && !wfChannelBlocked(midY, xIn, xOut, pad)) {
    routeY = midY;
    below = routeY > b.y;  // drive the riser toward the target for corner direction
  } else {
    below  = Math.abs(botY - b.y) <= Math.abs(b.y - topY);
    routeY = below ? botY : topY;
  }
  const dir = below ? +1 : -1;

  // Fan out from corridors already taken, then re-verify the nudged channel.
  routeY = wfChannelSeparate(routeY, xIn, xOut, dir);
  routeY = wfClearChannel(routeY, xIn, xOut, dir, pad);

  // Risers: slide each vertical leg sideways until it cuts no block — the
  // source leg escapes rightward, the target leg leftward. Widening a riser
  // stretches the channel span, so settle the channel once more after.
  xOut = wfClearRiser(xOut, a.y, routeY, +1, pad);
  xIn  = wfClearRiser(xIn,  routeY, b.y, -1, pad);
  routeY = wfClearChannel(routeY, xIn, xOut, dir, pad);

  if(!isTemp) wfWireChannels.push({ y:routeY, x0:Math.min(xIn,xOut), x1:Math.max(xIn,xOut) });

  // Corner radii shrink when a leg is too short for the full curve.
  const s1 = routeY >= a.y ? 1 : -1;   // travel direction of the source leg
  const s2 = b.y >= routeY ? 1 : -1;   // travel direction of the target leg
  const safeR1 = Math.min(r, Math.abs(routeY - a.y) / 2, Math.abs(xOut - a.x) / 2);
  const safeR2 = Math.min(r, Math.abs(routeY - b.y) / 2, Math.abs(b.x - xIn) / 2);

  return `M${a.x},${a.y}
          L${xOut-safeR1},${a.y}
          Q${xOut},${a.y} ${xOut},${a.y+s1*safeR1}
          L${xOut},${routeY-s1*safeR1}
          Q${xOut},${routeY} ${xOut-safeR1},${routeY}
          L${xIn+safeR2},${routeY}
          Q${xIn},${routeY} ${xIn},${routeY+s2*safeR2}
          L${xIn},${b.y-s2*safeR2}
          Q${xIn},${b.y} ${xIn+safeR2},${b.y}
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
  if(!confirm("Remove this wire?")) return;
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
