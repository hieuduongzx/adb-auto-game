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
// Build an adjacency map: out-edges only (forward flow), ignoring loop-backs.
function wfAdjForward(g){
  const adj={}; (g.nodes||[]).forEach(n=>adj[n.id]=[]);
  (g.edges||[]).forEach(e=>{ if(e.to!==e.from && (e.toPort||"in")!=="loop") adj[e.from].push(e.to); });
  return adj;
}
// Topological layers via BFS from the start node (or any node with no in-edges).
// Returns an array of layers; each layer is an array of node ids.
function wfTopoLayers(g){
  const nodes=g.nodes||[];
  const adj=wfAdjForward(g);
  // in-degree
  const indeg={}; nodes.forEach(n=>indeg[n.id]=0);
  (g.edges||[]).forEach(e=>{ if(e.to!==e.from && (e.toPort||"in")!=="loop") indeg[e.to]=(indeg[e.to]||0)+1; });
  const start=nodes.find(n=>n.type==="start") || nodes.find(n=>(indeg[n.id]||0)===0);
  let layer0=start?[start.id]:nodes.filter(n=>(indeg[n.id]||0)===0).map(n=>n.id);
  if(!layer0.length && nodes.length) layer0=[nodes[0].id];
  const layers=[layer0];
  const seen=new Set(layer0);
  // For a clean visual, every successor enters the NEXT layer (so siblings in the
  // same fork share a column) — breadth-first.
  let cur=layer0;
  while(cur.length){
    const nxt=[];
    cur.forEach(id=>{
      (adj[id]||[]).forEach(t=>{ if(!seen.has(t)){ seen.add(t); nxt.push(t); } });
    });
    // Also pull in any unseen zero-in-degree nodes (disconnected islands).
    nodes.forEach(n=>{ if(!seen.has(n.id) && (indeg[n.id]||0)===0){ seen.add(n.id); nxt.push(n.id); } });
    if(nxt.length) layers.push(nxt);
    cur=nxt;
  }
  // Any leftover (cyclic / unreached) → one more layer.
  const left=nodes.filter(n=>!seen.has(n.id)).map(n=>n.id);
  if(left.length) layers.push(left);
  return layers;
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
    row.items.forEach(n=>{ n.x=Math.round(x); n.y=Math.round(y); x+=wfNodeW(n)+WF_LAY_GAP_X; });
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
    col.items.forEach(n=>{ n.x=Math.round(x); n.y=Math.round(y); y+=wfNodeH(n)+WF_LAY_GAP_Y; });
    x+=col.w+WF_LAY_GAP_X;
  });
}
// Layout: tree — layers as rows, each branch's children centred under their
// parent. Subtree width counts each node once (first parent wins) so shared
// children don't inflate the span.
function wfLayoutTree(g){
  const layers=wfTopoLayers(g);
  const adj=wfAdjForward(g);
  const inLayers=id=>layers.some(l=>l.includes(id));
  // Assign each node to a single parent (the first that reaches it) so the tree
  // is a true tree — shared descendants aren't counted under every parent.
  const claimed=new Set();
  const kidsOf={};
  layers.forEach(layer=>layer.forEach(id=>{
    kidsOf[id]=(adj[id]||[]).filter(t=>inLayers(t)&&!claimed.has(t));
    kidsOf[id].forEach(t=>claimed.add(t));
  }));
  const widths={};
  function wOf(id){ if(widths[id]!==undefined) return widths[id];
    const kids=kidsOf[id]||[];
    if(!kids.length) return widths[id]=1;
    return widths[id]=kids.reduce((s,k)=>s+wOf(k),0); }
  const colW=WF_LAY_NODE_W+WF_LAY_GAP_X;
  let x=40;
  layers.forEach((layer,i)=>{
    let cursor=x;
    layer.forEach(id=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      const w=wOf(id);
      n.x=Math.round(cursor+(w*colW-WF_LAY_NODE_W)/2);
      n.y=40+i*(WF_LAY_NODE_H+WF_LAY_GAP_Y);
      cursor+=w*colW;
    });
    const span=layer.reduce((s,id)=>s+wOf(id),0);
    x=40+Math.max(span*colW, colW);
  });
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
      n.x=x; n.y=y;
      const h=wfNodeH(n); if(h>rowMaxH) rowMaxH=h;
      col++;
      if(col>=cols){ col=0; x=40; y+=rowMaxH+28; rowMaxH=0; }
      else x+=WF_LAY_NODE_W+28;
    });
  });
}
function wfAutoLayout(kind){
  const g=wfGraph(); if(!g) return;
  wfPushUndo();
  // Snapshot current positions so we can animate from old → new.
  const from={}; g.nodes.forEach(n=>{ from[n.id]={x:n.x,y:n.y}; });
  if(kind==="vertical")   wfLayoutVertical(g);
  else if(kind==="horizontal") wfLayoutHorizontal(g);
  else if(kind==="tree")  wfLayoutTree(g);
  else if(kind==="compact") wfLayoutCompact(g);
  else if(kind==="zigzag") wfLayoutZigzag(g);
  else if(kind==="radial") wfLayoutRadial(g);
  wfAnimateLayout(g, from);
  setStatus("Layout applied: "+kind);
}
// Animate every node from its previous position to the freshly-computed one,
// redrawing wires on each frame, then fit the view. Respects reduced-motion:
// falls back to an instant render+fit. Uses a single rAF loop with an ease-out
// curve so the rearrange reads as one smooth settle instead of a hard jump.
function wfAnimateLayout(g, from){
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nodes=g.nodes.filter(n=>from[n.id] && (from[n.id].x!==n.x || from[n.id].y!==n.y));
  if(reduce || !nodes.length || (typeof wfPvActive!=="undefined" && wfPvActive)){ wfRenderCanvas(); wfFit(false); return; }
  // Pre-fit to the FINAL layout so the camera is already framed; we then animate
  // nodes inside that stable frame (no simultaneous pan/zoom + node motion).
  wfRenderCanvas();
  wfFit(false);
  const els=new Map();
  nodes.forEach(n=>{ const el=wfNodeElById(n.id); if(el) els.set(n, {el, x0:from[n.id].x, y0:from[n.id].y, x1:n.x, y1:n.y}); });
  const dur=380, t0=performance.now();
  const ease=t=>1-Math.pow(1-t,3);   // cubic ease-out
  function frame(now){
    const t=Math.min(1,(now-t0)/dur), k=ease(t);
    els.forEach(({el,x0,y0,x1,y1},n)=>{
      const cx=x0+(x1-x0)*k, cy=y0+(y1-y0)*k;
      el.style.left=cx+"px"; el.style.top=cy+"px";
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
      n.x=x; n.y=y;
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
      layer.forEach(id=>{ const n=g.nodes.find(n=>n.id===id); if(n&&n.type!=="note"){ n.x=cx-wfNodeW(n)/2; n.y=cy-20; } });
      return;
    }
    const r=depth*ringGap;
    const step=layer.length;
    layer.forEach((id,i)=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      // spread the ring evenly; offset so depth-1 starts at top.
      const ang=(i/Math.max(1,step))*Math.PI*2 - Math.PI/2;
      n.x=cx + Math.cos(ang)*r - wfNodeW(n)/2;
      n.y=cy + Math.sin(ang)*r - 15;
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
