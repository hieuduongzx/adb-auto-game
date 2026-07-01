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
function wfWireLayer(ed,a,b){ return (a&&b&&b.x<a.x) ? 0 : 1; }
function wfLaneMap(edges,pts){
  const lanes=new Map();
  // Build a conflict graph: count how many backward edges share the same
  // source or target node, then assign each edge a unique lane offset so
  // no two wires ever run on top of each other.
  const srcCnt=new Map(), tgtCnt=new Map();
  const backEdges=[];
  edges.forEach(ed=>{
    const p=pts.get(wfWireKey(ed));
    if(!p) return;
    if(p.b.x < p.a.x){
      backEdges.push(ed);
      srcCnt.set(ed.from, (srcCnt.get(ed.from)||0)+1);
      tgtCnt.set(ed.to, (tgtCnt.get(ed.to)||0)+1);
    }
  });
  // Sort by source + target conflict count so edges with more shared nodes
  // (higher chance of overlapping segments) get lower lane numbers.
  backEdges.sort((a,b)=>{
    const sa=(srcCnt.get(a.from)||0)+(tgtCnt.get(a.to)||0);
    const sb=(srcCnt.get(b.from)||0)+(tgtCnt.get(b.to)||0);
    return sb-sa;
  });
  // Assign lanes: track used lanes per source AND per target node so no
  // two edges sharing either endpoint get the same lane.
  const usedSrc=new Map(), usedTgt=new Map();
  for(const ed of backEdges){
    let lane=0;
    while(
      (usedSrc.get(ed.from)||new Set()).has(lane) ||
      (usedTgt.get(ed.to)||new Set()).has(lane)
    ) lane++;
    if(!usedSrc.has(ed.from)) usedSrc.set(ed.from, new Set());
    if(!usedTgt.has(ed.to)) usedTgt.set(ed.to, new Set());
    usedSrc.get(ed.from).add(lane);
    usedTgt.get(ed.to).add(lane);
    lanes.set(wfWireKey(ed), lane);
  }
  return lanes;
}
function wfWirePath(a,b,ed,lane){
  const dx=b.x-a.x, dy=b.y-a.y;
  // Backward wires: gấp khúc gọn, lane offset chống trùng triệt để.
  if(dx < 0){
    const n=lane||0;
    if(dy===0){
      // Perfectly horizontal backward: route below with a single lane step.
      const step=30+n*20;
      return `M${a.x},${a.y}`+
        ` L${a.x+8},${a.y}`+
        ` L${a.x+8},${a.y+step}`+
        ` L${b.x-8},${b.y+step}`+
        ` L${b.x-8},${b.y}`+
        ` L${b.x},${b.y}`;
    }
    const step=wfWireClamp(Math.abs(dy)+24+n*22, 24, 120);
    const midY=Math.max(a.y,b.y)+step;
    const bendR=a.x+wfWireClamp(Math.abs(dx)*0.28+28+n*8, 36, 100);
    const bendL=b.x-wfWireClamp(Math.abs(dx)*0.12+22+n*6, 26, 72);
    return `M${a.x},${a.y}`+
      ` L${bendR},${a.y}`+
      ` L${bendR},${midY}`+
      ` L${bendL},${midY}`+
      ` L${bendL},${b.y}`+
      ` L${b.x},${b.y}`;
  }
  const pull=wfWireClamp(Math.abs(dx)*0.5+Math.abs(dy)*0.08, 48, 180);
  return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
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
    const cls="wire"+
      (ed.fromPort==="true"?" t":ed.fromPort==="false"?" f":"")+
      (toPort==="loop"?" loopback":"");
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
