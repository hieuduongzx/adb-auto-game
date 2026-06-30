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
// Compact chevrons (not chunky triangles) so they read as direction hints, not
// dots. Re-inserted on every full redraw because wfDrawWires clears the <svg>.
const WF_WIRE_DEFS = (function(){
  // Elongated filled chevron: 8×7.5 in userspace, notch at 22% depth.
  // refX=8 aligns the sharp tip exactly to the path endpoint.
  const mk=(id,c)=>`<marker id="${id}" markerWidth="7" markerHeight="7" refX="5.6" refY="2.6" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0,0.4 L5.6,2.6 L0,4.8 L1.3,2.6 Z" fill="${c}" fill-opacity="0.95"/></marker>`;
  return "<defs>"+mk("wf-ah","#94a6ba")+mk("wf-ah-h","#bb3a33")+mk("wf-ah-t","#1f9d57")
    +mk("wf-ah-f","#e0792e")+mk("wf-ah-nottook","#d6483f")+mk("wf-ah-loop","#d09030")+mk("wf-ah-temp","#2f6fed")+"</defs>";
})();
// ── Wire routing ──────────────────────────────────────────────────────────────
// Three regimes ordered by a single invariant:
//   • Forward (dx ≥ 0): horizontal S-curve.
//       KEY RULE: hx ≤ dx/2. When this is violated the two control points cross
//       each other → the bezier folds back on itself → the "spiral" artefact.
//       At small dx the wire becomes a nearly-straight line, which is correct.
//   • Near-vertical (|dx| < 55 AND dy is the dominant dimension): vertical
//       S-curve so the wire exits/arrives straight down instead of diagonal.
//       Only fires when ady > adx*1.8 to avoid false-triggering on diagonal wires.
//   • Backward (dx < 0, not near-vertical): U-bow sized by the actual span
//       between the two ports so close nodes get a tight arc and far nodes a
//       wide one — avoids the "huge arch over two adjacent blocks" problem.
function wfBezier(a,b){
  const dx=b.x-a.x, dy=b.y-a.y, adx=Math.abs(dx), ady=Math.abs(dy);

  // ── Near-vertical (applies to both forward and slightly-backward) ───────────
  // Condition: small horizontal gap AND vertical is the dominant direction.
  if(adx < 55 && ady > adx * 1.8){
    const h=Math.max(48, ady * 0.44);
    const ys=Math.sign(dy)||1;
    return `M${a.x},${a.y} C${a.x},${a.y+ys*h} ${b.x},${b.y-ys*h} ${b.x},${b.y}`;
  }

  // ── Backward: U-bow ─────────────────────────────────────────────────────────
  if(dx < 0){
    // hx: horizontal kick from each port before the bow starts.
    const hx=Math.min(155, Math.max(42, adx * 0.38 + 28));
    // bow: perpendicular offset, scaled by the diagonal span so adjacent nodes
    // get a tight arc and far-apart nodes get a wide, comfortable arc.
    const span=Math.hypot(adx, ady);
    const bow=Math.min(195, Math.max(48, span * 0.44 + 36));
    // Bow away from the midline: downward when target is above, upward when below.
    const bowSign=dy < 0 ? 1 : -1;
    return `M${a.x},${a.y} C${a.x+hx},${a.y+bowSign*bow} ${b.x-hx},${b.y+bowSign*bow} ${b.x},${b.y}`;
  }

  // ── Forward S-curve ─────────────────────────────────────────────────────────
  // A firmer, symmetric S that reads like pro node editors: each end leaves/arrives
  // dead-horizontal ("cứng" — stiff), then eases through the middle ("mềm" — soft).
  // hx stays ≤ dx/2 (hard invariant: prevents the control points crossing = no
  // spiral) and is capped so far-apart nodes don't sweep into a loose, lazy arc.
  const hx=Math.min(dx / 2, 150);
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
