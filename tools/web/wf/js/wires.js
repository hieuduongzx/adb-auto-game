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

// Arrowhead markers
const WF_WIRE_DEFS = (function(){
  const mk=(id,c)=>`<marker id="${id}" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L7,3.5 L0,7 Z" fill="${c}"/></marker>`;
  return "<defs>"+
    mk("wf-ah","#94a6ba")+
    mk("wf-ah-t","#1f9d57")+
    mk("wf-ah-f","#e0792e")+
    mk("wf-ah-loop","#d09030")+
    mk("wf-ah-temp","#2f6fed")+
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
  const pullX = 30 + (lane || 0) * 15; // Extend out from output
  const pullY = 40 + (lane || 0) * 15; // Vertical offset
  const r = 10; // Corner radius
  
  // Decide if we route above or below based on the higher/lower node
  const minY = Math.min(a.y, b.y);
  const maxY = Math.max(a.y, b.y);
  
  // Try to route smartly: if 'a' is below 'b', going up might be better, else down.
  // We'll calculate a unified Y routing line.
  let routeY, signY1, signY2;
  
  if (a.y >= b.y) {
    // Route BELOW the bottom-most node
    routeY = maxY + pullY;
    signY1 = 1;  // 'a' goes DOWN to routeY
    signY2 = -1; // routeY goes UP to 'b'
  } else {
    // Route ABOVE the top-most node
    routeY = minY - pullY;
    signY1 = -1; // 'a' goes UP to routeY
    signY2 = 1;  // routeY goes DOWN to 'b'
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
  t.setAttribute("d",wfWirePath(a,b,{from:wfGesture.from,fromPort:wfGesture.port,to:"__temp",toPort:"in"},0));
}

function wfClearTemp(){ const t=$("wf-wires").querySelector(".temp"); if(t)t.remove(); }
