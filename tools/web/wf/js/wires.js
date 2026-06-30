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
  const mk=(id,c)=>`<marker id="${id}" markerWidth="8" markerHeight="8" refX="1" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L7,3.5 L0,7 Z" fill="${c}"/></marker>`;
  return "<defs>"+
    mk("wf-ah","#94a6ba")+
    mk("wf-ah-t","#1f9d57")+
    mk("wf-ah-f","#e0792e")+
    mk("wf-ah-loop","#d09030")+
    mk("wf-ah-temp","#2f6fed")+
  "</defs>";
})();

// ── Wire routing ──────────────────────────────────────────────────────────────
// Hybrid node-editor routing: soft splines for simple left-to-right flow,
// rounded orthogonal bends for tall/backward routes. This keeps dense graphs
// tidy like n8n/ComfyUI without making every connection look identical.
function wfWireKey(ed){ return [ed.from,ed.fromPort||"out",ed.to,ed.toPort||"in"].join("|"); }
function wfWirePairKey(ed){ return [ed.from,ed.to].sort().join("|"); }
function wfWireClamp(v,min,max){ return Math.max(min, Math.min(max, v)); }
function wfWireLayer(ed,a,b){
  if((ed.toPort||"in")==="loop") return 0;
  if(a&&b&&b.x<a.x) return 2;
  return 1;
}
function wfWireAddLaneBuckets(buckets,key,ed){ (buckets[key]||(buckets[key]=[])).push(ed); }
function wfWireLaneOrder(ed,pts){
  const p=pts.get(wfWireKey(ed));
  return p ? p.a.y*100000+p.b.y*100+p.a.x+p.b.x/1000 : 0;
}
function wfLaneMap(edges,pts){
  const buckets={};
  edges.forEach(ed=>{
    const p=pts.get(wfWireKey(ed)); if(!p) return;
    const layer=wfWireLayer(ed,p.a,p.b);
    wfWireAddLaneBuckets(buckets,"pair|"+wfWirePairKey(ed)+"|"+layer,ed);
    wfWireAddLaneBuckets(buckets,"from|"+ed.from+"|"+(ed.fromPort||"out")+"|"+layer,ed);
    wfWireAddLaneBuckets(buckets,"to|"+ed.to+"|"+(ed.toPort||"in")+"|"+layer,ed);
  });
  const lanes=new Map();
  Object.keys(buckets).forEach(k=>{
    const bucket=buckets[k].slice().sort((a,b)=>wfWireLaneOrder(a,pts)-wfWireLaneOrder(b,pts));
    if(bucket.length<2) return;
    const kind=k.slice(0,k.indexOf("|"));
    const step=kind==="pair"?14:6;
    bucket.forEach((ed,i)=>{
      const key=wfWireKey(ed);
      lanes.set(key, (lanes.get(key)||0) + (i-(bucket.length-1)/2)*step);
    });
  });
  lanes.forEach((v,k)=>lanes.set(k,wfWireClamp(v,-24,24)));
  return lanes;
}
function wfWireRoundedPath(points,r){
  if(points.length<2) return "";
  let d=`M${points[0].x},${points[0].y}`;
  for(let i=1;i<points.length-1;i++){
    const p0=points[i-1], p=points[i], p1=points[i+1];
    const v0={x:p.x-p0.x,y:p.y-p0.y}, v1={x:p1.x-p.x,y:p1.y-p.y};
    const l0=Math.hypot(v0.x,v0.y), l1=Math.hypot(v1.x,v1.y);
    if(l0<1||l1<1){ d+=` L${p.x},${p.y}`; continue; }
    const rr=Math.min(r,l0/2,l1/2);
    const a={x:p.x-v0.x/l0*rr,y:p.y-v0.y/l0*rr};
    const b={x:p.x+v1.x/l1*rr,y:p.y+v1.y/l1*rr};
    d+=` L${a.x},${a.y} Q${p.x},${p.y} ${b.x},${b.y}`;
  }
  const last=points[points.length-1];
  return d+` L${last.x},${last.y}`;
}
function wfWireSoftPath(a,b,ao,bo,dx,laneShift){
  const pull=Math.max(44, Math.min(Math.abs(dx)*0.52+Math.abs(laneShift)*0.25, 190));
  const c1={x:ao.x+pull,y:ao.y};
  const c2={x:bo.x-pull,y:bo.y};
  if(Math.abs(laneShift)<0.1) return `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`;
  const pad=Math.max(22, Math.min(34, Math.abs(dx)*0.18));
  return `M${a.x},${a.y} C${a.x+pad},${a.y} ${ao.x-pad},${ao.y} ${ao.x},${ao.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${bo.x},${bo.y} C${bo.x+pad},${bo.y} ${b.x-pad},${b.y} ${b.x},${b.y}`;
}
function wfWireStepPath(a,b,dx,dy,laneShift){
  const offset=Math.max(12, Math.min(Math.abs(dx)*0.08+14, 26));
  const midY=a.y+dy*0.5+laneShift;
  return wfWireRoundedPath([
    a,
    {x:a.x+offset,y:a.y},
    {x:a.x+offset,y:midY},
    {x:b.x-offset,y:midY},
    {x:b.x-offset,y:b.y},
    b
  ],10);
}
function wfWireBackPath(a,b,dx,dy,loop,laneShift){
  const side=loop?1:(dy>=0?1:-1);
  const out=Math.max(26, Math.min(Math.abs(dx)*0.12+42, 66));
  const clearY=a.y+side*(Math.max(42, Math.min(Math.abs(dy)*0.24+48, 104))+Math.abs(laneShift)*0.16)+laneShift;
  return wfWireRoundedPath([
    a,
    {x:a.x+out,y:a.y},
    {x:a.x+out,y:clearY},
    {x:b.x-out,y:clearY},
    {x:b.x-out,y:b.y},
    b
  ],14);
}
function wfWirePath(a,b,ed,lane){
  const dx=b.x-a.x, dy=b.y-a.y, back=dx<0, loop=(ed.toPort||"in")==="loop";
  const dist=Math.hypot(dx,dy)||1;
  const laneShift=lane||0;
  const nx=-dy/dist, ny=dx/dist;
  const ao={x:a.x+nx*laneShift,y:a.y+ny*laneShift};
  const bo={x:b.x+nx*laneShift,y:b.y+ny*laneShift};

  if(loop||back) return wfWireBackPath(a,b,dx,dy,loop,laneShift);
  if(dx>150&&Math.abs(dy)>Math.max(100,Math.abs(dx)*0.85)) return wfWireStepPath(a,b,dx,dy,laneShift);
  return wfWireSoftPath(a,b,ao,bo,dx,laneShift);
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
    const tt=document.createElementNS(NS,"title"); tt.textContent="Chuột phải để xoá dây nối"; hit.appendChild(tt);
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
