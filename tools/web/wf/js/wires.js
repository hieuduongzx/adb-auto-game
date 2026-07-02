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

// ── Wire shape ────────────────────────────────────────────────────────────────
// Two shapes only, like a normal node editor:
//   forward  → straight line when level, otherwise one soft cubic;
//   backward → one smooth U-detour that arcs around the node rows (above or
//              below, whichever is nearer) instead of slicing through them.
// The only geometry the router knows is the bounding box of the nodes the wire
// spans — no channel search, no lanes, no per-leg dodging.

// Node boxes snapshot for the current draw pass (world coords).
let wfWireBoxes=[];
function wfWireBoxesRebuild(){
  wfWireBoxes=[];
  document.querySelectorAll("#wf-world .wf-node").forEach(el=>{
    wfWireBoxes.push({ left:el.offsetLeft, top:el.offsetTop,
                       right:el.offsetLeft+el.offsetWidth, bottom:el.offsetTop+el.offsetHeight });
  });
}
// Vertical extent of everything a backward wire passes over in [x0, x1].
function wfSpanBounds(x0,x1,a,b){
  let top=Math.min(a.y,b.y), bot=Math.max(a.y,b.y);
  for(const bx of wfWireBoxes){
    if(bx.right<x0 || bx.left>x1) continue;
    if(bx.top<top) top=bx.top;
    if(bx.bottom>bot) bot=bx.bottom;
  }
  return {top,bot};
}

// `lane` (0,1,2…) fans stacked backward wires apart so they don't overdraw.
function wfWirePath(a,b,lane){
  const dx=b.x-a.x, dy=b.y-a.y;

  // Forward flow: straight when level, one calm spline otherwise.
  if(dx>=-20){
    if(dx>=0 && Math.abs(dy)<5) return `M${a.x},${a.y} L${b.x},${b.y}`;
    const pull=Math.min(130, Math.max(24, Math.abs(dx)*0.45 + Math.abs(dy)*0.12));
    return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
  }

  // Short backward hop with a real vertical offset (e.g. into the row below):
  // the classic S-curve is lighter and reads naturally — it travels the gap
  // between rows instead of boxing around them.
  if(Math.abs(dy)>=40 && dx>-400){
    const pull=Math.min(180, 40+Math.abs(dx)*0.35+Math.abs(dy)*0.10);
    return `M${a.x},${a.y} C${a.x+pull},${a.y} ${b.x-pull},${b.y} ${b.x},${b.y}`;
  }

  // Long or level back-run: out right → around the spanned rows → in from left.
  const k=lane||0, stub=16+k*8, r=10;
  const xOut=a.x+stub, xIn=b.x-stub;
  const {top,bot}=wfSpanBounds(xIn,xOut,a,b);
  const mid=(a.y+b.y)/2;
  const above=(mid-top)<=(bot-mid);
  const routeY=above ? top-24-k*14 : bot+24+k*14;

  const s1=routeY>=a.y?1:-1, s2=b.y>=routeY?1:-1;
  const r1=Math.min(r, Math.abs(routeY-a.y)/2, Math.abs(xOut-a.x)/2);
  const r2=Math.min(r, Math.abs(routeY-b.y)/2, Math.abs(b.x-xIn)/2);
  return `M${a.x},${a.y} L${xOut-r1},${a.y} Q${xOut},${a.y} ${xOut},${a.y+s1*r1}`+
         ` L${xOut},${routeY-s1*r1} Q${xOut},${routeY} ${xOut-r1},${routeY}`+
         ` L${xIn+r2},${routeY} Q${xIn},${routeY} ${xIn},${routeY+s2*r2}`+
         ` L${xIn},${b.y-s2*r2} Q${xIn},${b.y} ${xIn+r2},${b.y} L${b.x},${b.y}`;
}

function wfDrawWires(){
  const svg=$("wf-wires"), g=wfGraph();
  const temp=svg.querySelector(".temp");
  svg.innerHTML=WF_WIRE_DEFS; if(temp) svg.appendChild(temp);
  if(!g) return;
  const NS="http://www.w3.org/2000/svg";
  wfWireBoxesRebuild();
  let back=0;   // backward-wire counter → fan lanes apart

  (g.edges||[]).forEach(ed=>{
    if(wfSameStack(ed.from,ed.to)) return;
    const toPort=ed.toPort||"in";
    const a=wfPortPt(ed.from,ed.fromPort), b=wfPortPt(ed.to,toPort);
    if(!a||!b) return;
    const d=wfWirePath(a,b, (b.x-a.x < -20) ? back++ : 0);
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
  t.setAttribute("d",wfWirePath(a,b,0));
}

function wfClearTemp(){ const t=$("wf-wires").querySelector(".temp"); if(t)t.remove(); }
