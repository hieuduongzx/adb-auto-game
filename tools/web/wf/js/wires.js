// ── Wires ────────────────────────────────────────────────────────────────────
function wfPortPt(nodeId,port){
  let el;
  if(port==="in"||port==="loop"){
    el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.in[data-port="${port}"]`);
    // Fall back to the node's first input (e.g. a 'loop' edge whose target is no
    // longer a loop node) so the wire still anchors somewhere sensible.
    if(!el) el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.in`);
  }
  else{
    el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.out[data-port="${port}"]`);
    // Legacy/loose: if that exact out port is gone (e.g. a node that became a
    // condition), anchor on the node's first output port so the wire still shows.
    if(!el) el=document.querySelector(`.wf-node[data-node="${nodeId}"] .wf-port.out`);
  }
  if(!el) return null;
  const wr=$("wf-world").getBoundingClientRect(), r=el.getBoundingClientRect();
  // Wires are drawn inside the (scaled) world → convert screen delta to world units.
  return { x:(r.left+r.width/2-wr.left)/wfZoom, y:(r.top+r.height/2-wr.top)/wfZoom };
}
// Arrowhead markers, one per wire colour (CSS picks the right one via marker-end).
// Compact chevrons — for orthogonal wires, marker orients on the last segment.
const WF_WIRE_DEFS = (function(){
  const mk=(id,c)=>`<marker id="${id}" markerWidth="7" markerHeight="7" refX="0" refY="2.6" orient="auto" markerUnits="userSpaceOnUse"><path d="M5.6,0.4 L0,2.6 L5.6,4.8 L4.3,2.6 Z" fill="${c}" fill-opacity="0.95"/></marker>`;
  return "<defs>"+mk("wf-ah","#94a6ba")+mk("wf-ah-h","#bb3a33")+mk("wf-ah-t","#1f9d57")
    +mk("wf-ah-f","#e0792e")+mk("wf-ah-nottook","#d6483f")+mk("wf-ah-loop","#d09030")+mk("wf-ah-temp","#2f6fed")+"</defs>";
})();
// ── Wire routing ──────────────────────────────────────────────────────────────
// Hybrid: bezier for forward horizontal flow (soft, natural), orthogonal
// right-angle bends when the target is above/below or behind — no more
// looping curves that cross over themselves.
//
//   • Straight / near-horizontal: bezier S-curve.
//   • Target directly below/above (small dx, large dy): orthogonal L-shape.
//   • Backward (dx < 0): orthogonal U-turn via a vertical leg.
function wfBezier(a,b){
  const dx=b.x-a.x, dy=b.y-a.y, adx=Math.abs(dx), ady=Math.abs(dy);

  // ── Backward ngang (dy nhỏ): U-turn gọn — ra phải, xuống dưới, sang trái, vào ─
  if(dx < -10 && ady < 40){
    const h=Math.max(15, Math.min(adx*0.25, 30));
    const outX=a.x+h, inX=b.x-h;
    const vOff=45;
    const midY=(a.y+b.y)/2 + vOff;
    return `M${a.x},${a.y} L${outX},${a.y} L${outX},${midY} L${inX},${midY} L${inX},${b.y} L${b.x},${b.y}`;
  }

  // ── Near-vertical: target is mostly below/above — orthogonal L-shape.
  // Covers cases where the horizontal gap is within ~1 node width and the
  // vertical span dominates, so the wire doesn't sweep in a wide bezier arc.
  if(adx < 160 && ady > adx * 1.2){
    const h=Math.max(20, Math.min(adx*0.55, 50));
    const midX=a.x+h;
    return `M${a.x},${a.y} L${midX},${a.y} L${midX},${b.y} L${b.x},${b.y}`;
  }

  // ── Forward / diagonal: soft bezier S-curve ─────────────────────────────────
  const hx=Math.min(dx/2, 150);
  return `M${a.x},${a.y} C${a.x+hx},${a.y} ${b.x-hx},${b.y} ${b.x},${b.y}`;
}
function wfDrawWires(){
  const svg=$("wf-wires"), g=wfGraph();
  const temp=svg.querySelector(".temp");
  svg.innerHTML=WF_WIRE_DEFS; if(temp) svg.appendChild(temp);
  if(!g) return;
  const NS="http://www.w3.org/2000/svg";
  // Draw order: loop-backs first (underneath), then forward flow on top, so a
  // backward arc never visually crosses over a forward branch.
  const edges=(g.edges||[]).slice().filter(ed=>!wfSameStack(ed.from, ed.to));
  edges.sort((x,y)=>{
    const lx=(x.toPort||"in")==="loop"?0:1, ly=(y.toPort||"in")==="loop"?0:1;
    return lx-ly;
  });
  edges.forEach(ed=>{
    const toPort = ed.toPort||"in";
    const a=wfPortPt(ed.from,ed.fromPort), b=wfPortPt(ed.to,toPort);
    if(!a||!b) return;
    const d=wfBezier(a,b);
    // Group a fat invisible hit-path with the visible wire: the group carries the
    // edge ref (right-click to delete) and widens the hover target generously.
    const grp=document.createElementNS(NS,"g"); grp.setAttribute("class","wire-grp"); grp.__edge=ed;
    const hit=document.createElementNS(NS,"path"); hit.setAttribute("class","wire-hit"); hit.setAttribute("d",d);
    const tt=document.createElementNS(NS,"title"); tt.textContent="Chuột phải để xoá dây nối"; hit.appendChild(tt);
    const p=document.createElementNS(NS,"path");
    p.setAttribute("class","wire"+(ed.fromPort==="true"?" t":ed.fromPort==="false"?" f":"")+(toPort==="loop"?" loopback":""));
    p.dataset.from=ed.from; p.dataset.fromport=ed.fromPort; p.dataset.to=ed.to;  // for run-trail branch colouring
    p.setAttribute("d", d);
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
  t.setAttribute("d",wfBezier(a,b));
}
function wfClearTemp(){ const t=$("wf-wires").querySelector(".temp"); if(t)t.remove(); }
