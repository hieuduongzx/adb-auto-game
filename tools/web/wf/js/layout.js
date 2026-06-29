// ── Auto-layout strategies ────────────────────────────────────────────────────
// Each rearranges every node in the current graph into a tidy arrangement, then
// fits the result to view. Notes are excluded (they float free). Nodes keep their
// x/y in world coords; stacks/groups are not touched (members follow their head).
const WF_LAY_NODE_W=158, WF_LAY_NODE_H=52, WF_LAY_GAP_X=36, WF_LAY_GAP_Y=36;
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
// Layout: vertical columns (top-to-bottom flow), one column per topo layer.
function wfLayoutVertical(g){
  const layers=wfTopoLayers(g);
  let y=40;
  layers.forEach(layer=>{
    let x=40;
    let maxW=0;
    layer.forEach(id=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      n.x=x; n.y=y;
      const w=wfNodeW(n); if(w>maxW) maxW=w;
      x+=w+WF_LAY_GAP_X;
    });
    // tallest node in this row → advance y
    const maxH=Math.max(...layer.map(id=>{ const n=g.nodes.find(n=>n.id===id); return n?wfNodeH(n):WF_LAY_NODE_H; }));
    y+=maxH+WF_LAY_GAP_Y;
  });
}
// Layout: horizontal rows (left-to-right flow), one row per topo layer.
function wfLayoutHorizontal(g){
  const layers=wfTopoLayers(g);
  let x=40;
  layers.forEach(layer=>{
    let y=40;
    layer.forEach(id=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      n.x=x; n.y=y;
      y+=wfNodeH(n)+WF_LAY_GAP_Y;
    });
    const maxW=Math.max(...layer.map(id=>{ const n=g.nodes.find(n=>n.id===id); return n?wfNodeW(n):WF_LAY_NODE_W; }));
    x+=maxW+WF_LAY_GAP_X;
  });
}
// Layout: tree — layers as columns, but each branch's children centered under
// their parent, so forks fan out like a tree.
function wfLayoutTree(g){
  const layers=wfTopoLayers(g);
  const adj=wfAdjForward(g);
  // Compute subtree width (leaf count) per node.
  const widths={};
  function wOf(id){ if(widths[id]!==undefined) return widths[id];
    const kids=(adj[id]||[]).filter(t=>layers.some(l=>l.includes(t)));
    if(!kids.length) return widths[id]=1;
    return widths[id]=kids.reduce((s,k)=>s+wOf(k),0); }
  const colW=WF_LAY_NODE_W+WF_LAY_GAP_X;
  let x=40;
  layers.forEach((layer,i)=>{
    let cursor=x;
    // Position each node, reserving subtree width; center it over its span.
    layer.forEach(id=>{
      const n=g.nodes.find(n=>n.id===id); if(!n||n.type==="note") return;
      const w=wOf(id);
      n.x=cursor+(w*colW-WF_LAY_NODE_W)/2;
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
  if(kind==="vertical")   wfLayoutVertical(g);
  else if(kind==="horizontal") wfLayoutHorizontal(g);
  else if(kind==="tree")  wfLayoutTree(g);
  else if(kind==="compact") wfLayoutCompact(g);
  wfRenderCanvas();
  wfFit();
  setStatus("Đã sắp xếp: "+kind);
}
let wfGesture=null;     // {mode:'pan'|'move'|'connect', ...}
let wfPaletteDrag=null; // node type being dragged from palette
let wfCanvasReady=false;
const wfUid=()=>"n"+Math.random().toString(36).slice(2,9);
const wfBase=p=>{ if(!p)return"(ảnh)"; const s=String(p).replace(/\\/g,"/").split("/").pop(); return s.length>14?"…"+s.slice(-13):s; };
// Summary for a multi-image ("…_any") node: list up to 2 names, else a count.
const wfBaseAny=t=>{ const a=(Array.isArray(t)?t:[]).filter(Boolean); if(!a.length)return"(chưa có ảnh)"; return a.length<=2?a.map(wfBase).join(" / "):a.length+" ảnh"; };

// Top-level mode switch: Công cụ (helper) ↔ Workflow (node-graph).
/* (mode switching removed — the designer is its own standalone window) */

// Condition types a switch case may use — instant checks only (no wait_* timeout,
// no tap_* side-effect). Kept in sync with SWITCH_CASE_TYPES in engine.py.
const WF_SWITCH_CASE_TYPES = ["if_image","if_image_any","if_text","if_var"];
function wfDefaults(type){
  const def=WF_NODES[type]||{fields:[]}; const p={};
  (def.fields||[]).forEach(f=>{
    if(f.k && f.k.startsWith("_")) return;  // UI-only field (e.g. "_region" group)
    if(f.t==="tpls"){ p[f.k]= Array.isArray(f.d)?f.d.slice():[]; return; }  // fresh array per node
    p[f.k]= f.d!==undefined?f.d : (f.t==="num"?0 : f.t==="bool"?false : "");
  });
  if(type==="switch") p.cases=[];   // multi-branch starts with no cases
  return p;
}
