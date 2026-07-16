// ── Auto-layout strategies ────────────────────────────────────────────────────
// Each rearranges every node in the current graph into a tidy arrangement, then
// fits the result to view. Notes are excluded (they float free). Nodes keep their
// x/y in world coords; stacks/groups are not touched (members follow their head).
const WF_LAY_NODE_W=168, WF_LAY_NODE_H=64, WF_LAY_GAP_X=36, WF_LAY_GAP_Y=30;
// Approximate node height: real DOM height when available, else the default.
function wfNodeH(n){
  const el=wfNodeElById(n.id); return el?el.offsetHeight:WF_LAY_NODE_H;
}
function wfNodeW(n){
  const el=wfNodeElById(n.id); return el?el.offsetWidth:WF_LAY_NODE_W;
}
// Arrange from real wire topology. Loop-back inputs are excluded from ranking so
// a retry edge cannot pull its ancestor below itself; disconnected islands and
// malformed cycles are still laid out deterministically instead of overlapping.
function wfLayEdges(g){
  const ids=new Set((g.nodes||[]).filter(n=>n.type!=="note").map(n=>n.id));
  return (g.edges||[]).filter(e=>ids.has(e.from)&&ids.has(e.to)&&e.from!==e.to&&(e.toPort||"in")!=="loop");
}
function wfLayPortRank(port){
  port=String(port||"out");
  if(port==="out"||port==="true") return 0;
  if(port==="false") return 100;
  if(port==="default") return 90;
  const m=/^c(\d+)$/.exec(port); return m?10+parseInt(m[1],10):50;
}
function wfAdjForward(g){
  const adj={}; (g.nodes||[]).forEach(n=>adj[n.id]=[]);
  wfLayEdges(g).slice().sort((a,b)=>wfLayPortRank(a.fromPort)-wfLayPortRank(b.fromPort))
    .forEach(e=>{ if(!adj[e.from].includes(e.to)) adj[e.from].push(e.to); });
  return adj;
}
// Longest-path topological layering keeps every forward wire moving to a later
// row/column. A small barycentric pass then orders siblings by their parent wires
// (and true/case/false port order), reducing crossings at branches and joins.
function wfTopoLayers(g){
  const nodes=(g.nodes||[]).filter(n=>n.type!=="note"), byId=new Map(nodes.map(n=>[n.id,n]));
  if(!nodes.length) return [];
  const edges=wfLayEdges(g), adj={}, pred={}, indeg={}, layer={}, original={};
  nodes.forEach((n,i)=>{ adj[n.id]=[]; pred[n.id]=[]; indeg[n.id]=0; layer[n.id]=0; original[n.id]=i; });
  edges.forEach(e=>{ adj[e.from].push(e); pred[e.to].push(e); indeg[e.to]++; });
  const start=nodes.find(n=>n.type==="start");
  const startId=start&&start.id;
  const cmpSeed=(a,b)=>(a===b?0:a===startId?-1:b===startId?1:
    ((byId.get(a).y||0)-(byId.get(b).y||0))||((byId.get(a).x||0)-(byId.get(b).x||0))||original[a]-original[b]);
  const queue=nodes.filter(n=>indeg[n.id]===0).map(n=>n.id).sort(cmpSeed), seen=new Set();
  // Break cycles one node at a time when Kahn's queue drains. Incoming wires
  // from already-ranked nodes still determine the new seed's minimum layer.
  while(seen.size<nodes.length){
    if(!queue.length){
      const id=nodes.map(n=>n.id).filter(id=>!seen.has(id)).sort(cmpSeed)[0];
      const fromSeen=pred[id].filter(e=>seen.has(e.from));
      layer[id]=fromSeen.length?Math.max(...fromSeen.map(e=>layer[e.from]+1)):0;
      queue.push(id);
    }
    const id=queue.shift(); if(seen.has(id)) continue; seen.add(id);
    adj[id].forEach(e=>{
      if(seen.has(e.to)) return; // cycle/back-edge: keep the earlier node above
      layer[e.to]=Math.max(layer[e.to],layer[id]+1);
      indeg[e.to]=Math.max(0,indeg[e.to]-1);
      if(indeg[e.to]===0) queue.push(e.to);
    });
  }
  const layers=[];
  nodes.forEach(n=>{ const d=layer[n.id]||0; (layers[d]||(layers[d]=[])).push(n.id); });
  const pos={};
  layers.forEach((row,depth)=>{
    row.sort((a,b)=>{
      const score=id=>{
        const incoming=pred[id].filter(e=>(layer[e.from]||0)<depth&&pos[e.from]!==undefined);
        if(!incoming.length) return [Number.MAX_SAFE_INTEGER,50,original[id]];
        return [incoming.reduce((s,e)=>s+pos[e.from],0)/incoming.length,
          Math.min(...incoming.map(e=>wfLayPortRank(e.fromPort))),original[id]];
      };
      const aa=score(a), bb=score(b); return aa[0]-bb[0]||aa[1]-bb[1]||aa[2]-bb[2];
    });
    row.forEach((id,i)=>pos[id]=i);
  });
  return layers.filter(Boolean);
}
// Layout: vertical columns (top-to-bottom flow), one row per topo layer, each
// layer centred on a shared axis so a linear chain forms a straight vertical
// line and forks fan out symmetrically.
function wfLayoutVertical(g){
  const layers=wfTopoLayers(g);
  // Pre-measure each layer's total width so we can centre them all on one axis.
  const rows=layers.map(layer=>{
    const items=layer.map(id=>g.nodes.find(n=>n.id===id)).filter(n=>n&&n.type!=="note");
    const w=items.reduce((s,n)=>s+wfNodeW(n),0)+Math.max(0,items.length-1)*WF_LAY_GAP_X;
    const h=items.length?Math.max(...items.map(wfNodeH)):WF_LAY_NODE_H;
    return {items,w,h};
  });
  const axis=Math.max(...rows.map(r=>r.w), WF_LAY_NODE_W)/2 + 40;
  let y=40;
  rows.forEach(row=>{
    let x=axis-row.w/2;
    row.items.forEach(n=>{ n.x=wfSnap(x); n.y=wfSnap(y); x+=wfNodeW(n)+WF_LAY_GAP_X; });
    y+=row.h+WF_LAY_GAP_Y;
  });
}
// Layout: horizontal rows (left-to-right flow), one column per topo layer, each
// column centred vertically on a shared axis.
function wfLayoutHorizontal(g){
  const layers=wfTopoLayers(g);
  const cols=layers.map(layer=>{
    const items=layer.map(id=>g.nodes.find(n=>n.id===id)).filter(n=>n&&n.type!=="note");
    const h=items.reduce((s,n)=>s+wfNodeH(n),0)+Math.max(0,items.length-1)*WF_LAY_GAP_Y;
    const w=items.length?Math.max(...items.map(wfNodeW)):WF_LAY_NODE_W;
    return {items,w,h};
  });
  const axis=Math.max(...cols.map(c=>c.h), WF_LAY_NODE_H)/2 + 40;
  let x=40;
  cols.forEach(col=>{
    let y=axis-col.h/2;
    col.items.forEach(n=>{ n.x=wfSnap(x); n.y=wfSnap(y); y+=wfNodeH(n)+WF_LAY_GAP_Y; });
    x+=col.w+WF_LAY_GAP_X;
  });
}
// Layout: tidy wire tree. Each node is claimed by its first forward parent;
// shared joins stay in the longest-path layer but count toward only one subtree,
// preventing exponential width. Real DOM sizes keep siblings from overlapping.
function wfLayoutTree(g){
  const layers=wfTopoLayers(g); if(!layers.length) return;
  const byId=new Map((g.nodes||[]).map(n=>[n.id,n])), depth={}, order={};
  layers.forEach((row,d)=>row.forEach((id,i)=>{ depth[id]=d; order[id]=i; }));
  const adj=wfAdjForward(g), claimed=new Set(), kidsOf={};
  layers.flat().forEach(id=>{
    kidsOf[id]=(adj[id]||[]).filter(t=>depth[t]>depth[id]&&!claimed.has(t))
      .sort((a,b)=>(depth[a]-depth[b])||(order[a]-order[b]));
    kidsOf[id].forEach(t=>claimed.add(t));
  });
  const rowY=[]; let y=40;
  layers.forEach((row,d)=>{ rowY[d]=y; y+=Math.max(WF_LAY_NODE_H,...row.map(id=>wfNodeH(byId.get(id))))+WF_LAY_GAP_Y; });
  const widths={};
  function widthOf(id){
    if(widths[id]!==undefined) return widths[id];
    const n=byId.get(id), own=n?wfNodeW(n):WF_LAY_NODE_W, kids=kidsOf[id]||[];
    if(!kids.length) return widths[id]=own;
    const childW=kids.reduce((s,k)=>s+widthOf(k),0)+Math.max(0,kids.length-1)*WF_LAY_GAP_X;
    return widths[id]=Math.max(own,childW);
  }
  const placed=new Set();
  function place(id,left){
    if(placed.has(id)) return; placed.add(id);
    const n=byId.get(id), span=widthOf(id), own=wfNodeW(n);
    n.x=wfSnap(left+(span-own)/2); n.y=wfSnap(rowY[depth[id]]);
    const kids=kidsOf[id]||[];
    let childLeft=left+(span-(kids.reduce((s,k)=>s+widthOf(k),0)+Math.max(0,kids.length-1)*WF_LAY_GAP_X))/2;
    kids.forEach(k=>{ place(k,childLeft); childLeft+=widthOf(k)+WF_LAY_GAP_X; });
  }
  let left=40;
  const roots=layers.flat().filter(id=>!claimed.has(id));
  roots.forEach(id=>{ place(id,left); left+=widthOf(id)+WF_LAY_GAP_X*2; });
  // Defensive fallback for malformed cyclic graphs whose forced seed was claimed.
  layers.flat().forEach(id=>{ if(!placed.has(id)){ place(id,left); left+=widthOf(id)+WF_LAY_GAP_X*2; } });
}
// Layout: compact — vertical columns but with tight gaps and nodes packed by
// topo order into a near-square grid (good for many small blocks).
function wfLayoutCompact(g){
  const layers=wfTopoLayers(g);
  const cols=Math.max(1, Math.ceil(Math.sqrt(g.nodes.filter(n=>n.type!=="note").length)));
  let y=40, col=0, x=40, rowMaxH=0;
  layers.forEach(layer=>{
    layer.forEach(id=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      n.x=wfSnap(x); n.y=wfSnap(y);
      const h=wfNodeH(n); if(h>rowMaxH) rowMaxH=h;
      col++;
      if(col>=cols){ col=0; x=40; y+=rowMaxH+28; rowMaxH=0; }
      else x+=WF_LAY_NODE_W+28;
    });
  });
}
function wfLayoutCaptureGroups(g){
  return (g.groups||[]).map(gr=>({gr, old:{x:gr.x,y:gr.y,w:gr.w,h:gr.h}, ids:(g.nodes||[]).filter(n=>{
    const w=wfNodeW(n), h=wfNodeH(n), cx=n.x+w/2, cy=n.y+h/2;
    return cx>=gr.x&&cx<=gr.x+gr.w&&cy>=gr.y&&cy<=gr.y+gr.h;
  }).map(n=>n.id)}));
}
function wfLayoutRefitGroups(captured,g){
  const byId=new Map((g.nodes||[]).map(n=>[n.id,n]));
  captured.forEach(({gr,ids})=>{
    const members=ids.map(id=>byId.get(id)).filter(Boolean); if(!members.length) return;
    const x0=Math.min(...members.map(n=>n.x)), y0=Math.min(...members.map(n=>n.y));
    const x1=Math.max(...members.map(n=>n.x+wfNodeW(n))), y1=Math.max(...members.map(n=>n.y+wfNodeH(n)));
    const pad=typeof WF_GROUP_PAD!=="undefined"?WF_GROUP_PAD:24;
    const hd=typeof WF_GROUP_HD!=="undefined"?WF_GROUP_HD:24;
    gr.x=wfSnap(x0-pad); gr.y=wfSnap(y0-pad-hd);
    gr.w=wfSnap(x1-x0+pad*2); gr.h=wfSnap(y1-y0+pad*2+hd);
  });
}
function wfAutoLayout(kind){
  const g=wfGraph(); if(!g) return;
  wfPushUndo();
  // Snapshot positions and positional group membership before wires rearrange
  // the nodes; group frames are rebuilt around those same members afterward.
  const from={}, capturedGroups=wfLayoutCaptureGroups(g);
  g.nodes.forEach(n=>{ from[n.id]={x:n.x,y:n.y}; });
  if(kind==="vertical")   wfLayoutVertical(g);
  else if(kind==="horizontal") wfLayoutHorizontal(g);
  else if(kind==="tree")  wfLayoutTree(g);
  else if(kind==="compact") wfLayoutCompact(g);
  else if(kind==="zigzag") wfLayoutZigzag(g);
  else if(kind==="radial") wfLayoutRadial(g);
  wfLayoutRefitGroups(capturedGroups,g);
  wfAnimateLayout(g, from, capturedGroups);
  const wireCount=wfLayEdges(g).length;
  setStatus("Arranged "+g.nodes.filter(n=>n.type!=="note").length+" blocks from "+wireCount+" wire"+(wireCount===1?"":"s")+" · "+kind);
}
// Animate every node from its previous position to the freshly-computed one,
// redrawing wires on each frame, then fit the view. Respects reduced-motion:
// falls back to an instant render+fit. Uses a single rAF loop with an ease-out
// curve so the rearrange reads as one smooth settle instead of a hard jump.
function wfAnimateLayout(g, from, capturedGroups){
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nodes=g.nodes.filter(n=>from[n.id] && (from[n.id].x!==n.x || from[n.id].y!==n.y));
  if(reduce || !nodes.length || (typeof wfPvActive!=="undefined" && wfPvActive)){ wfRenderCanvas(); wfFit(false); return; }
  // Pre-fit to the FINAL layout so the camera is already framed; we then animate
  // nodes inside that stable frame (no simultaneous pan/zoom + node motion).
  wfRenderCanvas();
  wfFit(false);
  const els=new Map();
  nodes.forEach(n=>{ const el=wfNodeElById(n.id); if(el) els.set(n, {el, x0:from[n.id].x, y0:from[n.id].y, x1:n.x, y1:n.y}); });
  const groupEls=(capturedGroups||[]).map(({gr,old})=>{
    const el=document.querySelector(`.wf-group[data-group="${gr.id}"]`);
    return el?{el,old,fin:{x:gr.x,y:gr.y,w:gr.w,h:gr.h}}:null;
  }).filter(Boolean);
  const dur=380, t0=performance.now();
  const ease=t=>1-Math.pow(1-t,3);   // cubic ease-out
  function frame(now){
    const t=Math.min(1,(now-t0)/dur), k=ease(t);
    els.forEach(({el,x0,y0,x1,y1})=>{
      const cx=x0+(x1-x0)*k, cy=y0+(y1-y0)*k;
      el.style.left=cx+"px"; el.style.top=cy+"px";
    });
    groupEls.forEach(({el,old,fin})=>{
      el.style.left=(old.x+(fin.x-old.x)*k)+"px"; el.style.top=(old.y+(fin.y-old.y)*k)+"px";
      el.style.width=(old.w+(fin.w-old.w)*k)+"px"; el.style.height=(old.h+(fin.h-old.h)*k)+"px";
    });
    wfDrawWires();
    if(t<1) requestAnimationFrame(frame);
    else { wfRenderCanvas(); }   // final authoritative render (ports/wires exact)
  }
  requestAnimationFrame(frame);
}
// Layout menu — toggle open/closed; click outside to close (wired in wfInitCanvas).
function wfToggleLayoutMenu(e){
  if(e) e.stopPropagation();
  const bar=document.getElementById("wf-layout-bar");
  if(bar) bar.classList.toggle("open");
}
function wfCloseLayoutMenu(){
  const bar=document.getElementById("wf-layout-bar");
  if(bar) bar.classList.remove("open");
}
// Layout: zigzag — vertical columns that alternate left/right per layer, so a
// long sequential flow reads as a boustrophedon (snake) instead of one tall tower.
function wfLayoutZigzag(g){
  const layers=wfTopoLayers(g);
  let y=40;
  const cw=WF_LAY_NODE_W;
  layers.forEach((layer,i)=>{
    // Odd layers sit one column to the right; even to the left, giving the snake.
    const xBase=40 + (i%2?cw+WF_LAY_GAP_X:0);
    let x=xBase, rowMaxH=0;
    layer.forEach(id=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      n.x=wfSnap(x); n.y=wfSnap(y);
      const h=wfNodeH(n); if(h>rowMaxH) rowMaxH=h;
      x+=wfNodeW(n)+20;
    });
    y+=rowMaxH+28;
  });
}
// Layout: radial — start node at the centre, each topo layer on a ring whose
// radius grows with depth. Nice for hub-and-spoke graphs (many branches).
function wfLayoutRadial(g){
  const layers=wfTopoLayers(g);
  const cx=400, cy=350;
  const ringGap=210;
  layers.forEach((layer,depth)=>{
    if(!depth){ // centre
      layer.forEach(id=>{ const n=g.nodes.find(n=>n.id===id); if(n&&n.type!=="note"){ n.x=wfSnap(cx-wfNodeW(n)/2); n.y=wfSnap(cy-20); } });
      return;
    }
    const r=depth*ringGap;
    const step=layer.length;
    layer.forEach((id,i)=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      // spread the ring evenly; offset so depth-1 starts at top.
      const ang=(i/Math.max(1,step))*Math.PI*2 - Math.PI/2;
      n.x=wfSnap(cx + Math.cos(ang)*r - wfNodeW(n)/2);
      n.y=wfSnap(cy + Math.sin(ang)*r - 15);
    });
  });
}
let wfGesture=null;     // {mode:'pan'|'move'|'connect', ...}
let wfPaletteDrag=null; // node type being dragged from palette
let wfCanvasReady=false;
const wfUid=()=>"n"+Math.random().toString(36).slice(2,9);
const wfBase=p=>{ if(!p)return"(image)"; const s=String(p).replace(/\\/g,"/").split("/").pop(); return s.length>14?"…"+s.slice(-13):s; };
// Summary for a multi-image ("…_any") node: list up to 2 names, else a count.
const wfBaseAny=t=>{ const a=(Array.isArray(t)?t:[]).filter(Boolean); if(!a.length)return"(no image)"; return a.length<=2?a.map(wfBase).join(" / "):a.length+" images"; };

// Top-level mode switch: Tools (helper) ↔ Workflow (node-graph).
/* (mode switching removed — the designer is its own standalone window) */

// Condition types a switch case may use — instant checks only (no wait_* timeout,
// no tap_* side-effect). Kept in sync with SWITCH_CASE_TYPES in engine.py.
const WF_SWITCH_CASE_TYPES = ["if_image","if_image_any","if_text","if_var","if_time","if_color"];
function wfDefaults(type){
  const def=WF_NODES[type]||{fields:[]}; const p={};
  (def.fields||[]).forEach(f=>{
    if(f.k && f.k.startsWith("_")) return;  // UI-only field (e.g. "_region" group)
    if(f.t==="tpls"){ p[f.k]= Array.isArray(f.d)?f.d.slice():[]; return; }  // fresh array per node
    if(f.t==="points"){ p[f.k]=Array.isArray(f.d)?f.d.map(pt=>({...pt})):[]; return; }
    p[f.k]= f.d!==undefined?f.d : (f.t==="num"?0 : f.t==="bool"?false : "");
  });
  if(type==="switch") p.cases=[];   // multi-branch starts with no cases
  return p;
}
