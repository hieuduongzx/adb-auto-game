// ── Groups (frames) ───────────────────────────────────────────────────────────
// A group is a named rectangle living in the graph (graph.groups). Membership is
// geometric: a node belongs to a group when its centre is inside the rectangle.
// Moving the group's header moves every node currently inside it. Groups are
// purely visual — the engine ignores them (it only runs nodes + edges).
// Colours read from the shared --cat-*/--group-red vars (base.css :root) — the
// same palette used for node category accents, so a group frame around, say,
// image-category nodes doesn't clash with a differently-tuned hardcoded hex.
const WF_GROUP_COLORS = (function(){
  const cs=getComputedStyle(document.documentElement);
  const v=name=>(cs.getPropertyValue(name)||"").trim();
  const hexToRgb=hex=>{ const m=/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    return m ? [parseInt(m[1],16),parseInt(m[2],16),parseInt(m[3],16)] : [0,0,0]; };
  const mk=(hex,alpha)=>{ const [r,g,b]=hexToRgb(hex); return {b:hex, bg:`rgba(${r},${g},${b},${alpha})`}; };
  return [
    mk(v("--cat-basic")||"#6f9be8", .07),
    mk(v("--cat-image")||"#2fb0a3", .08),
    mk(v("--cat-ocr")  ||"#e0954b", .09),
    mk(v("--cat-logic")||"#9a78e6", .08),
    mk(v("--group-red")||"#cf6b6b", .08),
  ];
})();
function wfGroups(){ const t=wfEditTarget(); if(!t) return []; if(!t.graph.groups) t.graph.groups=[]; return t.graph.groups; }
function wfGroupColor(gr){ return WF_GROUP_COLORS[(gr.color||0) % WF_GROUP_COLORS.length]; }
// Padding around member nodes when drawing/fitting a group frame, and extra
// headroom for the floating title tab above it — both on the 4pt spacing scale.
const WF_GROUP_PAD = 24;   // var(--s6)
const WF_GROUP_HD  = 24;   // var(--s6) — clears the group's title tab
function wfNodesInGroup(gr){
  const g=wfGraph(); if(!g) return [];
  return g.nodes.filter(n=>{
    const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
    const w=el?el.offsetWidth:156, h=el?el.offsetHeight:48;
    const cx=n.x+w/2, cy=n.y+h/2;
    return cx>=gr.x && cx<=gr.x+gr.w && cy>=gr.y && cy<=gr.y+gr.h;
  });
}
function wfAddGroup(x,y,w,h){
  const groups=wfGroups();
  const gr={ id:"g"+wfUid().slice(1), name:"Group "+(groups.length+1),
    x:Math.round(x), y:Math.round(y), w:Math.round(w), h:Math.round(h), color:groups.length%WF_GROUP_COLORS.length };
  groups.push(gr); wfRenderCanvas(); setStatus(`Created "${gr.name}" — drag the title to move the whole group`);
  return gr;
}
function wfDeleteGroup(id){ wfPushUndo(); const groups=wfGroups(); const i=groups.findIndex(x=>x.id===id); if(i>=0){ groups.splice(i,1); wfRenderCanvas(); setStatus("Group deleted (blocks kept) — Ctrl+Z to undo"); } }
function wfRenameGroup(gr){ uiPrompt({title:"Rename group", label:"Group name", value:gr.name||""}).then(nm=>{
  if(nm===null) return; nm=nm.trim(); if(!nm||nm===gr.name) return;
  wfPushUndo(); gr.name=nm; wfRenderCanvas();
}); }
// Create a group hugging the current multi-selection (toolbar button shortcut).
function wfGroupSelection(){
  const ids=WF.sel.slice(); if(ids.length<1) return false;
  wfPushUndo();
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  ids.forEach(id=>{ const n=wfNode(id); if(!n) return;
    const el=document.querySelector(`.wf-node[data-node="${id}"]`);
    const w=el?el.offsetWidth:158, h=el?el.offsetHeight:52;
    x0=Math.min(x0,n.x); y0=Math.min(y0,n.y); x1=Math.max(x1,n.x+w); y1=Math.max(y1,n.y+h);
  });
  if(!isFinite(x0)) return false;
  const pad=WF_GROUP_PAD;
  wfAddGroup(x0-pad, y0-pad-WF_GROUP_HD, (x1-x0)+pad*2, (y1-y0)+pad*2+WF_GROUP_HD);
  return true;
}
// Resize an existing group to tightly wrap all its current member nodes.
function wfFitGroup(gr){
  const members=wfNodesInGroup(gr);
  if(!members.length){ setStatus('Group "'+gr.name+'" contains no blocks'); return; }
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  members.forEach(n=>{
    const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
    const w=el?el.offsetWidth:158, h=el?el.offsetHeight:52;
    x0=Math.min(x0,n.x); y0=Math.min(y0,n.y); x1=Math.max(x1,n.x+w); y1=Math.max(y1,n.y+h);
  });
  if(!isFinite(x0)) return;
  const pad=WF_GROUP_PAD;
  gr.x=wfSnap(x0-pad); gr.y=wfSnap(y0-pad-WF_GROUP_HD);
  gr.w=wfSnap((x1-x0)+pad*2); gr.h=wfSnap((y1-y0)+pad*2+WF_GROUP_HD);
  wfRenderCanvas();
  setStatus(`Fit group bounds for "${gr.name}"`);
}
function wfRenderGroups(){
  const world=$("wf-world"), svg=$("wf-wires");
  [...world.querySelectorAll(".wf-group")].forEach(el=>el.remove());
  wfGroups().forEach(gr=>{
    const c=wfGroupColor(gr);
    const el=document.createElement("div"); el.className="wf-group"; el.dataset.group=gr.id;
    el.style.left=gr.x+"px"; el.style.top=gr.y+"px"; el.style.width=gr.w+"px"; el.style.height=gr.h+"px";
    el.style.borderColor=c.b; el.style.background=c.bg; el.style.color=c.b;
    el.innerHTML=`<div class="wf-group-hd" style="background:${c.b}"><span class="wf-group-name">${escHtml(gr.name)}</span><button class="wf-group-del" title="Delete group (keep nodes)">${wfIco("x")}</button></div><div class="wf-group-resize"></div>`;
    world.insertBefore(el, svg);   // behind the wires + nodes
    const hd=el.querySelector(".wf-group-hd");
    hd.addEventListener("mousedown",e=>wfStartGroupMove(e,gr));
    hd.addEventListener("dblclick",e=>{ e.stopPropagation(); wfRenameGroup(gr); });
    hd.addEventListener("contextmenu",e=>{ e.preventDefault(); e.stopPropagation(); wfShowGroupMenu(e.clientX, e.clientY, gr); });
    const del=el.querySelector(".wf-group-del");
    del.addEventListener("mousedown",e=>e.stopPropagation());
    del.addEventListener("click",e=>{ e.stopPropagation(); wfDeleteGroup(gr.id); });
    el.querySelector(".wf-group-resize").addEventListener("mousedown",e=>wfStartGroupResize(e,gr));
  });
}
function wfStartGroupMove(e,gr){
  if(e.button!==0 || e.target.closest(".wf-group-del")) return;
  e.stopPropagation();
  const members=wfNodesInGroup(gr).map(n=>({id:n.id, ox:n.x, oy:n.y}));
  wfGesture={mode:"groupmove", gr, gx:gr.x, gy:gr.y, sx:e.clientX, sy:e.clientY, members};
}
function wfStartGroupResize(e,gr){
  if(e.button!==0) return; e.stopPropagation();
  wfGesture={mode:"groupresize", gr, ow:gr.w, oh:gr.h, sx:e.clientX, sy:e.clientY};
}

// Vertical port-alignment snap. Given the dragged block id and a proposed top
// (world Y), return an adjusted top so that — if any of the block's port dots
// falls within WF_PORT_SNAP px of another block's port dot — the two dots line
// up exactly. Ports are measured from the live DOM (offsetTop within the node),
// so this works for every kind: it lets a start/end triangle's lone dot (which
// sits at the triangle centre, higher than a full block's body-centred dot)
// snap level with the neighbour it's wiring to. Single-node drags only.
const WF_PORT_SNAP = 7;   // world px pull range
let wfPortSnapHit=null;   // {otherId, y} of the port line last snapped to (for the guide)
function wfPortAlignSnapY(dragId, topY){
  wfPortSnapHit=null;
  const dEl=wfNodeElById(dragId); if(!dEl) return topY;
  const dOff=[...dEl.querySelectorAll(".wf-port")].map(p=>p.offsetTop+p.offsetHeight/2);
  if(!dOff.length) return topY;
  const g=wfGraph(); if(!g) return topY;
  let bestTop=topY, bestDist=WF_PORT_SNAP+0.001, found=false;
  for(const other of g.nodes){
    if(other.id===dragId) continue;
    const oEl=wfNodeElById(other.id); if(!oEl) continue;
    const oAbs=[...oEl.querySelectorAll(".wf-port")].map(p=>other.y+p.offsetTop+p.offsetHeight/2);
    for(const off of dOff){
      for(const oy of oAbs){
        const need=oy-off;                 // the top that would align this pair
        const dist=Math.abs(need-topY);
        if(dist<bestDist){ bestDist=dist; bestTop=need; found=true;
          wfPortSnapHit={otherId:other.id, y:oy}; }
      }
    }
  }
  return found ? Math.round(bestTop) : topY;
}

// ── Smart alignment (Figma-style) ─────────────────────────────────────────────
// While dragging a single block, its edges and centre lines pull onto the
// edges/centres of every other block within WF_ALIGN_SNAP world px, and a thin
// accent guide shows exactly what got aligned to what. The Y axis defers to the
// port snap above (a straight wire beats a straight border); holding Alt
// disables all magnetism for free-hand placement.
const WF_ALIGN_SNAP = 6;
function wfAlignSnap(dragId, x, y, skipY){
  const out={x, y, v:null, h:null};
  const dEl=wfNodeElById(dragId), g=wfGraph();
  if(!dEl||!g) return out;
  const dw=dEl.offsetWidth, dh=dEl.offsetHeight;
  let bx=WF_ALIGN_SNAP+.001, by=WF_ALIGN_SNAP+.001;
  for(const o of g.nodes){
    if(o.id===dragId) continue;
    const oEl=wfNodeElById(o.id); if(!oEl) continue;
    const ow=oEl.offsetWidth, oh=oEl.offsetHeight;
    const oxs=[o.x, o.x+ow/2, o.x+ow], dxs=[0, dw/2, dw];
    for(const ox of oxs) for(const dxo of dxs){
      const d=Math.abs((x+dxo)-ox);
      if(d<bx){ bx=d; out.x=Math.round(ox-dxo); out.v={x:ox, o, ow, oh}; }
    }
    if(skipY) continue;
    const oys=[o.y, o.y+oh/2, o.y+oh], dys=[0, dh/2, dh];
    for(const oy of oys) for(const dyo of dys){
      const d=Math.abs((y+dyo)-oy);
      if(d<by){ by=d; out.y=Math.round(oy-dyo); out.h={y:oy, o, ow, oh}; }
    }
  }
  return out;
}
function wfGuideEl(id, cls){
  let el=document.getElementById(id);
  if(!el){ el=document.createElement("div"); el.id=id; el.className="wf-align-guide "+cls;
    $("wf-world").appendChild(el); }
  return el;
}
function wfHideAlignGuides(){
  ["wf-guide-v","wf-guide-h"].forEach(id=>{ const el=document.getElementById(id); if(el) el.remove(); });
}
// Draw the guides against the node's FINAL (snapped, applied) position.
function wfShowAlignGuides(dragId, al, portSnapped){
  const dEl=wfNodeElById(dragId), n=wfNode(dragId);
  if(!dEl||!n){ wfHideAlignGuides(); return; }
  const dw=dEl.offsetWidth, dh=dEl.offsetHeight;
  if(al && al.v){
    const y0=Math.min(al.v.o.y, n.y)-14, y1=Math.max(al.v.o.y+al.v.oh, n.y+dh)+14;
    const el=wfGuideEl("wf-guide-v","v");
    el.style.left=(al.v.x-0.5)+"px"; el.style.top=y0+"px"; el.style.height=(y1-y0)+"px";
  } else { const el=document.getElementById("wf-guide-v"); if(el) el.remove(); }
  let h=al && al.h ? {y:al.h.y, o:al.h.o, ow:al.h.ow} : null;
  // The port snap owns Y — surface ITS line so the user sees why the block stuck.
  if(!h && portSnapped && wfPortSnapHit){
    const o=wfNode(wfPortSnapHit.otherId), oEl=wfNodeElById(wfPortSnapHit.otherId);
    if(o&&oEl) h={y:wfPortSnapHit.y, o, ow:oEl.offsetWidth};
  }
  if(h){
    const x0=Math.min(h.o.x, n.x)-14, x1=Math.max(h.o.x+h.ow, n.x+dw)+14;
    const el=wfGuideEl("wf-guide-h","h");
    el.style.top=(h.y-0.5)+"px"; el.style.left=x0+"px"; el.style.width=(x1-x0)+"px";
  } else { const el=document.getElementById("wf-guide-h"); if(el) el.remove(); }
}

function wfStartMove(e,n){
  if(e.button!==0||e.target.closest(".wf-port,.wf-node-eye")) return;
  e.stopPropagation();
  if(e.shiftKey||e.ctrlKey){ wfToggleSel(n.id); wfMarkSel(); wfRenderInspector(); return; }
  let ids;
  if(WF.sel.length>1 && WF.sel.includes(n.id)){
    ids=WF.sel.slice();              // move the whole multi-selection together
  } else if(n.stack){
    ids=wfStackMembers(n.stack).map(m=>m.id); wfSelectOne(n.id);  // drag a merged block as one
  } else {
    ids=[n.id]; wfSelectOne(n.id);   // single node
  }
  wfMarkSel(); wfRenderInspector();
  const g=wfGraph(); if(!g) return;
  const items=ids.map(id=>{ const nn=g.nodes.find(x=>x.id===id); return nn?{id,ox:nn.x,oy:nn.y}:null; }).filter(Boolean);
  wfGesture={mode:"move",items,sx:e.clientX,sy:e.clientY,dragId:n.id,mergeOk:e.ctrlKey};
}
function wfStartConnect(e,nodeId,port){
  if(e.button!==0) return; e.stopPropagation(); e.preventDefault();
  wfGesture={mode:"connect",from:nodeId,port};
  $("wf-canvas").classList.add("wf-connecting");   // let drops land on nodes, not wires
}
// Loose connect: the drop only has to land *anywhere on the target node*, not
// exactly on its input dot. The node under the pointer becomes the target.
function wfNodeUnderPointer(x,y){
  const el=document.elementFromPoint(x,y); if(!el) return null;
  const node=el.closest(".wf-node"); return node?node.dataset.node:null;
}
function wfHighlightTarget(id){
  document.querySelectorAll(".wf-node").forEach(el=>el.classList.toggle("conn-target", !!id && el.dataset.node===id));
}
// When a node has >1 input (the loop), pick the input port nearest the drop
// point so dropping low on a loop wires into its 'loop' (loop-back) port.
function wfNearestInPort(nodeId, clientX, clientY){
  const ports=[...document.querySelectorAll(`.wf-node[data-node="${nodeId}"] .wf-port.in`)];
  if(ports.length<=1) return "in";
  let best="in", bestD=Infinity;
  ports.forEach(p=>{ const r=p.getBoundingClientRect();
    const dx=clientX-(r.left+r.width/2), dy=clientY-(r.top+r.height/2), d=dx*dx+dy*dy;
    if(d<bestD){ bestD=d; best=p.dataset.port||"in"; } });
  return best;
}
function wfConnectTo(toNodeId, clientX, clientY){
  const g=wfGraph();
  if(g && wfGesture && wfGesture.from!==toNodeId){
    // Dropping onto any block of a merged stack wires into the stack's head.
    const tn=wfNode(toNodeId);
    if(tn && tn.stack){ const chain=wfStackChain(tn.stack); if(chain.length) toNodeId=chain[0].id; }
    if(wfGesture.from===toNodeId) return false;
    const toPort=wfNearestInPort(toNodeId, clientX, clientY);
    g.edges=g.edges.filter(ed=>!(ed.from===wfGesture.from && ed.fromPort===wfGesture.port)); // one wire per output port
    g.edges.push({from:wfGesture.from,fromPort:wfGesture.port,to:toNodeId,toPort});
    return true;
  }
  return false;
}
// ── Insert-on-wire (palette drop) ─────────────────────────────────────────────
// While dragging a chip from the palette, the wire under the cursor lights up;
// dropping the chip there splices the new block into that wire: old from→to
// becomes from→new (in) and new (primary out)→to. Saves the delete-two-wires-
// reconnect dance when adding a step to the middle of a chain.
let wfInsWireGrp=null;
function wfWireInsertHover(x,y){
  const el=document.elementFromPoint(x,y);
  const grp=el && el.closest ? el.closest("g.wire-grp") : null;
  if(wfInsWireGrp && wfInsWireGrp!==grp) wfInsWireGrp.classList.remove("wire-insert");
  wfInsWireGrp=grp||null;
  if(grp) grp.classList.add("wire-insert");
}
function wfWireInsertClear(){
  if(wfInsWireGrp){ wfInsWireGrp.classList.remove("wire-insert"); wfInsWireGrp=null; }
}
// Primary sequential-out port for a spliced-in node (mirrors wfMergeOutPort).
function wfSpliceOutPort(node){
  const def=WF_NODES[node.type]||{};
  if(def.kind==="condition"||def.kind==="call") return "true";
  return (def.outs&&def.outs.length) ? def.outs[0] : null;
}
function wfWireInsertSplice(g, edge, node){
  if(!g||!edge||!node) return false;
  if(!g.edges.includes(edge)) return false;          // stale reference — wire was redrawn
  const def=WF_NODES[node.type]||{};
  if(def.kind==="start"||def.kind==="note") return false;   // nothing to wire into
  const outPort=wfSpliceOutPort(node);
  const toId=edge.to, toPort=edge.toPort||"in";
  edge.to=node.id; edge.toPort="in";
  if(outPort) g.edges.push({from:node.id, fromPort:outPort, to:toId, toPort:toPort});
  setStatus("Block spliced into the wire");
  return true;
}

function wfCanvasMouseDown(e){
  if(e.target.closest(".wf-node")||e.target.closest(".wf-group")) return;
  wfCancelCamAnim();   // a press on the canvas takes the camera back by hand
  // Floating overlays (Activities/Variables corner stack, layout menu, minimap,
  // empty-state card) sit above the canvas — a press there must not clear the
  // selection or start a rubber-band box (the re-render it triggers would also
  // swallow the click).
  if(e.target.closest("#wf-corner-stack,.wf-layout-bar,.wf-minimap,.wf-empty-card")) return;
  // Middle mouse, or Space+left → pan.
  if(e.button===1 || (e.button===0 && wfSpace)){
    e.preventDefault();
    wfCancelCamAnim();   // direct manipulation beats any camera tween in flight
    $("wf-canvas").classList.add("panning");
    wfGesture={mode:"pan",sx:e.clientX,sy:e.clientY,ox:wfPan.x,oy:wfPan.y};
    return;
  }
  if(e.button!==0) return;
  const wr=$("wf-world").getBoundingClientRect();
  // Group-draw mode: left-drag on empty canvas draws a new group rectangle.
  if(wfGroupMode){
    const box=document.createElement("div"); box.id="wf-selbox"; box.className="wf-selbox";
    $("wf-world").appendChild(box);
    wfGesture={mode:"groupdraw", sx:(e.clientX-wr.left)/wfZoom, sy:(e.clientY-wr.top)/wfZoom};
    return;
  }
  // Plain left on empty → rubber-band select.
  if(!e.shiftKey) wfClearSel();
  const box=document.createElement("div"); box.id="wf-selbox"; box.className="wf-selbox";
  $("wf-world").appendChild(box);
  wfGesture={mode:"box", sx:(e.clientX-wr.left)/wfZoom, sy:(e.clientY-wr.top)/wfZoom, base:WF.sel.slice()};
  wfMarkSel(); wfRenderInspector();
}
// Group-draw arm state (toolbar ⊞ button). One-shot: drawing a group disarms it.
let wfGroupMode=false;
function wfSetGroupMode(on){
  wfGroupMode=!!on;
  const b=$("wf-group-btn"); if(b){ b.classList.toggle("on",wfGroupMode); b.title="Create group: "+(wfGroupMode?"on — drag to draw a frame":"Off"); }
  const c=$("wf-canvas"); if(c) c.style.cursor=wfGroupMode?"crosshair":"";
}
function wfToggleGroupMode(){
  // If blocks are selected, wrap them in a group right away; else arm draw mode.
  if(!wfGroupMode && WF.sel.length>0){ wfGroupSelection(); return; }
  wfSetGroupMode(!wfGroupMode);
}
// ── Default entry block ───────────────────────────────────────────────────────
// "Set as default" rewires start.out to point at the chosen block.
// The visual pill (::before) is applied after every canvas render.
function wfSetAsDefault(nodeId){
  wfPushUndo();
  const g=wfGraph(); if(!g) return;
  const n=wfNode(nodeId); if(!n||n.type==="start") return;
  const startNode=g.nodes.find(nd=>nd.type==="start"); if(!startNode) return;
  g.edges=g.edges.filter(e=>!(e.from===startNode.id&&(e.fromPort||"out")==="out"));
  g.edges.push({from:startNode.id,fromPort:"out",to:nodeId,toPort:"in"});
  wfRenderCanvas();
  setStatus("Set as default block");
}
function wfMarkDefaultEntry(){
  document.querySelectorAll(".wf-node.wf-entry").forEach(el=>el.classList.remove("wf-entry"));
  const g=wfGraph(); if(!g) return;
  const startNode=g.nodes.find(nd=>nd.type==="start"); if(!startNode) return;
  const e=g.edges.find(ed=>ed.from===startNode.id&&(ed.fromPort||"out")==="out");
  if(!e||!e.to) return;
  const target=wfNodeElById(e.to); if(target) target.classList.add("wf-entry");
}

// ── Right-click context menu (group / copy / delete) ──────────────────────────
// Can this node type be tested in isolation? Structural nodes (loop / call /
// parallel / switch…) need a graph walk — only action + condition make sense.
function wfCanTestNode(node){
  if(!node) return false;
  const def=WF_NODES[node.type]||{};
  return def.kind==="action" || def.kind==="condition";
}

// Test one block: switch to Preview, run the node on the device, paint match
// overlay (image/color/OCR) + green/red trail. Timeout for wait_* is capped to
// 1s server-side so a miss returns quickly with the best-score box.
async function wfRunSingleNode(node){
  if(!node){
    // Toolbar / shortcut with no arg → use the primary selection.
    node = WF.selectedNode ? wfNode(WF.selectedNode) : null;
  }
  if(!node){ uiToast("Select a block to test.","warning"); return; }
  if(wfRunning){ uiToast("A workflow is running — stop it before testing a single block.","warning"); return; }
  if(wfNodeTesting){ setStatus("Testing block…"); return; }
  if(!wfCanTestNode(node)){
    uiToast("Structural blocks (loop/call/…) can't be tested alone — use Run from selected.","warning");
    return;
  }
  const def=WF_NODES[node.type]||{};
  // Show the live screen + match boxes (Test always paints overlay even if
  // Debug overlay toggle is off — see wfWantMatchOverlay).
  if(typeof wfSwitchView==="function") wfSwitchView("preview");
  // Clear prior trail colours on this node so amber→result is obvious.
  const el=typeof wfNodeElById==="function"?wfNodeElById(node.id):null;
  if(el) el.classList.remove("ran-ok","ran-fail","ran-skip");
  if(typeof wfPvOverlay!=="undefined"){ wfPvOverlay=[]; wfPvMatchRegion=null; wfPvOverlayMeta=null; }
  if(typeof wfPvDraw==="function") wfPvDraw();

  const clean={ id:node.id, type:node.type, params:Object.assign({}, node.params||{}) };
  if(node.note) clean.note=node.note;
  if(node.log)  clean.log=node.log;
  // Per-node timing/retry used by the engine for real runs — include so test
  // matches production behaviour (except wait timeout which is capped).
  if(node.delayBefore) clean.delayBefore=node.delayBefore;
  if(node.delayAfter)  clean.delayAfter=node.delayAfter;
  if(node.retryCount)  clean.retryCount=node.retryCount;
  if(node.retryDelay)  clean.retryDelay=node.retryDelay;
  if(node.screenshotOnFail) clean.screenshotOnFail=node.screenshotOnFail;

  wfNodeTesting=true;
  if(typeof wfNoteNodeStart==="function") wfNoteNodeStart(node.id);
  if(typeof wfSetRunningNode==="function") wfSetRunningNode(node.id);
  setStatus("Test «"+(def.label||node.type)+"»…");
  try{
    const r=await api().workflow_run_node(JSON.stringify(clean), JSON.stringify(wfSerialize()));
    const status=(r && r.status) ? r.status : (r ? "ok" : "fail");
    const port=r && r.port;
    if(typeof wfNoteNodeDone==="function") wfNoteNodeDone(node.id);
    if(typeof wfMarkNodeResult==="function") wfMarkNodeResult(node.id, status, port);
    if(typeof wfSetRunningNode==="function") wfSetRunningNode(null);
    const failish = status==="fail" || port==="false";
    const branch = port!=null ? " → "+port : "";
    setStatus("Test «"+(def.label||node.type)+"»: "+status+branch);
    if(typeof uiToast==="function"){
      uiToast((def.label||node.type)+": "+(failish?"no match / fail":"ok")+branch,
              failish?"warning":"success");
    }
  }catch(e){
    if(typeof wfSetRunningNode==="function") wfSetRunningNode(null);
    setStatus("Test block failed");
    if(typeof uiToast==="function") uiToast("Test block error","error");
  }finally{
    wfNodeTesting=false;
  }
}
function wfHideMenu(){ const m=$("wf-ctxmenu"); if(m) m.style.display="none"; }
function wfShowMenu(clientX, clientY){
  const m=$("wf-ctxmenu"); if(!m) return;
  const items=[];
  const copyable=WF.sel.filter(id=>{ const n=wfNode(id); return n && n.type!=="start"; }).length;
  const stackSids=[...new Set(WF.sel.map(id=>{ const n=wfNode(id); return n&&n.stack; }).filter(Boolean))];
  if(WF.sel.length===1){
    const _n=wfNode(WF.sel[0]);
    if(_n&&_n.type!=="start") items.push({ico:"play",label:"Set as default", fn:()=>wfSetAsDefault(WF.sel[0])});
    // Test one block: runs on device, paints match overlay on Preview.
    if(_n && wfCanTestNode(_n)){
      items.push({ico:"target",label:"Test block (Ctrl+Enter)", fn:()=>wfRunSingleNode(_n)});
    }
  }
  if(stackSids.length) items.push({ico:"link_off",label:"Unmerge", fn:()=>stackSids.forEach(wfUnmerge)});
  if(WF.sel.length>=1) items.push({ico:"box",label:"Create group around ("+WF.sel.length+")", fn:wfGroupSelection});
  if(copyable){ items.push({ico:"copy",label:"Copy ("+copyable+")", fn:wfCopy});
    items.push({ico:"scissors",label:"Cut ("+copyable+")", fn:wfCut});
    items.push({ico:"copy",label:"Duplicate ("+copyable+")", fn:wfDuplicate}); }
  if(wfClipboard&&wfClipboard.nodes.length) items.push({ico:"clipboard",label:"Paste ("+wfClipboard.nodes.length+")", fn:()=>wfPaste({clientX,clientY})});
  if(WF.sel.length) items.push({ico:"trash",label:"Delete ("+WF.sel.length+")", fn:()=>wfDeleteSelected()});
  if(!items.length){ wfHideMenu(); return; }
  m.innerHTML="";
  items.forEach(it=>{ const d=document.createElement("div"); d.className="wf-ctx-item";
    d.innerHTML=`<span class="wf-ctx-ico">${wfIco(it.ico||"help")}</span>${escHtml(it.label)}`;
    d.onclick=()=>{ wfHideMenu(); it.fn(); }; m.appendChild(d); });
  const cr=$("wf-canvas").getBoundingClientRect();
  m.style.left=(clientX)+"px"; m.style.top=(clientY)+"px"; m.style.display="block";
}

function wfShowWireMenu(clientX, clientY, ed){
  const m=$("wf-ctxmenu"); if(!m) return;
  m.innerHTML="";
  const d=document.createElement("div"); d.className="wf-ctx-item"; d.innerHTML=`<span class="wf-ctx-ico">${wfIco("trash")}</span>Delete wire`;
  d.onclick=()=>{ wfHideMenu(); wfDeleteWire(ed); }; m.appendChild(d);
  m.style.left=clientX+"px"; m.style.top=clientY+"px"; m.style.display="block";
}
// Activities visible on the current tab (sequence vs background).
function wfActTabList(){
  const isBg = (typeof wfActTabCur!=="undefined" && wfActTabCur==="bg");
  return WF.activities.filter(a=>(a.type==="background")===isBg);
}
// Enable/disable every activity on the current tab at once.
function wfSetAllActivitiesEnabled(on){
  const list = wfActTabList();
  if(!list.length) return;
  const what = (typeof wfActTabCur!=="undefined" && wfActTabCur==="bg")?"background tasks":"activities";
  wfPushUndo(); list.forEach(a=>a.enabled=on); wfRenderActivities();
  setStatus((on?"Enabled all ":"Disabled all ")+what);
}
// Shared renderer for activity context-menu rows (optionally with a separator).
function wfAppendActMenuItems(m, items){
  items.forEach(it=>{
    if(it.sep){ const s=document.createElement("div"); s.className="wf-ctx-sep"; m.appendChild(s); return; }
    const d=document.createElement("div"); d.className="wf-ctx-item";
    d.innerHTML=`<span class="wf-ctx-ico">${wfIco(it.ico)}</span>${escHtml(it.label)}`;
    d.onclick=()=>{ wfHideMenu(); it.fn(); }; m.appendChild(d);
  });
}
// Select-all / deselect-all items for the current tab (shared by row + empty menus).
function wfActSelectAllItems(){
  const n = wfActTabList().length;
  return [
    {ico:"check", label:"Select all ("+n+")",   fn:()=>wfSetAllActivitiesEnabled(true)},
    {ico:"x",     label:"Deselect all ("+n+")", fn:()=>wfSetAllActivitiesEnabled(false)},
  ];
}
// Right-click menu on a single activity row.
function wfShowActRowMenu(clientX, clientY, act){
  const m=$("wf-ctxmenu"); if(!m||!act) return;
  m.innerHTML="";
  const items=[
    {ico:"play",  label:"Run this activity only", fn:()=>{ if(typeof wfRunOneActivity==="function") wfRunOneActivity(act.id); }},
    {ico:"check", label: act.enabled?"Disable":"Enable", fn:()=>wfToggleActivity(act.id)},
    {ico:"trash", label:"Delete activity", fn:()=>wfDeleteActivity(act.id)},
    {sep:true},
    ...wfActSelectAllItems(),
  ];
  wfAppendActMenuItems(m, items);
  m.style.left=clientX+"px"; m.style.top=clientY+"px"; m.style.display="block";
}
// Right-click empty area of the Activities panel: tick / untick every activity
// in the visible tab (sequence or background) at once.
function wfShowActAllMenu(clientX, clientY){
  const m=$("wf-ctxmenu"); if(!m) return;
  if(!wfActTabList().length){ wfHideMenu(); return; }
  m.innerHTML="";
  wfAppendActMenuItems(m, wfActSelectAllItems());
  m.style.left=clientX+"px"; m.style.top=clientY+"px"; m.style.display="block";
}

function wfShowGroupMenu(clientX, clientY, gr){
  const m=$("wf-ctxmenu"); if(!m) return;
  m.innerHTML="";
  const items=[
    {ico:"expand", label:"Fit bounds", fn:()=>wfFitGroup(gr)},
    {ico:"edit",   label:"Rename",   fn:()=>wfRenameGroup(gr)},
    {ico:"trash",  label:"Delete group",  fn:()=>wfDeleteGroup(gr.id)},
  ];
  items.forEach(it=>{
    const d=document.createElement("div"); d.className="wf-ctx-item";
    d.innerHTML=`<span class="wf-ctx-ico">${wfIco(it.ico)}</span>${escHtml(it.label)}`;
    d.onclick=()=>{ wfHideMenu(); it.fn(); }; m.appendChild(d);
  });
  m.style.left=clientX+"px"; m.style.top=clientY+"px"; m.style.display="block";
}
function wfInitCanvas(){
  if(wfCanvasReady) return; wfCanvasReady=true;
  const canvas=$("wf-canvas");
  canvas.addEventListener("mousedown",wfCanvasMouseDown);
  // Track the pointer over the canvas so Ctrl+V pastes under the cursor.
  canvas.addEventListener("mousemove",e=>{ wfPointer.x=e.clientX; wfPointer.y=e.clientY; wfPointer.inside=true; });
  canvas.addEventListener("mouseleave",()=>{ wfPointer.inside=false; });
  canvas.addEventListener("contextmenu",e=>{
    // Preview tab owns its own right-click (tap device); skip the graph menu.
    if(wfPvActive) return;
    e.preventDefault();
    // Right-click on a wire → offer to delete just that wire.
    const wireGrp=e.target.closest("g.wire-grp");
    if(wireGrp && wireGrp.__edge){ wfShowWireMenu(e.clientX, e.clientY, wireGrp.__edge); return; }
    // Right-click on a group header → group menu (handled by its own listener via stopPropagation).
    if(e.target.closest(".wf-group-hd")) return;
    const ne=e.target.closest(".wf-node");
    if(ne && !WF.sel.includes(ne.dataset.node)){ wfSelectOne(ne.dataset.node); wfMarkSel(); wfRenderInspector(); }
    wfShowMenu(e.clientX, e.clientY);
  });
  document.addEventListener("mousedown",e=>{ if(!e.target.closest("#wf-ctxmenu")) wfHideMenu(); if(!e.target.closest("#wf-globs-pop") && !e.target.closest("#wf-vars-mgr") && !e.target.closest("#wf-vars-add") && !e.target.closest("#wf-var-scope-menu")) wfHideGlobsEditor(); if(!e.target.closest("#wf-layout-bar")) wfCloseLayoutMenu(); }, true);
  // Vars panel header toggles collapse (click-through to drag is fine on body).
  const vhdr=document.querySelector("#wf-vars-panel .wf-vars-hdr");
  if(vhdr) vhdr.onclick=(e)=>{ if(e.target.closest(".wf-vars-actions")) return; wfVarsCollapsed=!wfVarsCollapsed; wfPersistPanelState(); wfRenderVarsPanel(); };
  const vadd=$("wf-vars-add");
  if(vadd) vadd.onclick=(e)=>{ e.stopPropagation(); if(typeof wfShowAddVarMenu==="function") wfShowAddVarMenu(); };
  const vmgr=$("wf-vars-mgr");
  if(vmgr) vmgr.onclick=(e)=>{ e.stopPropagation(); wfToggleGlobsEditor(); };
  // Activities panel: tab switching + "+" add button + collapse.
  document.querySelectorAll(".wf-act-tab").forEach(tab=>{
    tab.onclick=(e)=>{ e.stopPropagation(); wfActTab(tab.dataset.tab); };
  });
  const aadd=$("wf-act-add");
  if(aadd) aadd.onclick=(e)=>{ e.stopPropagation(); wfActAddCurrent(); };
  const afocus=$("wf-act-focus");
  if(afocus) afocus.onclick=(e)=>{ e.stopPropagation(); wfToggleFocus(); };
  const adbg=$("wf-act-dbg");
  if(adbg) adbg.onclick=(e)=>{ e.stopPropagation(); if(typeof wfToggleDebugOverlay==="function") wfToggleDebugOverlay(); };
  // Only the title row (not the tab bar / header buttons) is the collapse trigger.
  const ahdr=document.querySelector("#wf-act-hdr-row");
  if(ahdr) ahdr.onclick=(e)=>{ if(e.target.closest(".wf-act-hdr-add,.wf-act-hdr-tog,.wf-act-hdr-focus")) return; wfActCollapsed=!wfActCollapsed; wfPersistPanelState(); wfToggleActPanel(); };
  // Functions section (bottom of the left sidebar): "+" creates, header collapses.
  const fadd=$("wf-fn-add");
  if(fadd) fadd.onclick=(e)=>{ e.stopPropagation(); wfAddFunction(); };
  const fhdr=$("wf-fns-hdr"), fsec=$("wf-side-fns-sec");
  if(fhdr && fsec){
    try{ if(localStorage.getItem("wfFnsCollapsed")==="1") fsec.classList.add("collapsed"); }catch{}
    fhdr.onclick=(e)=>{ if(e.target.closest(".wf-act-hdr-add")) return;
      const c=fsec.classList.toggle("collapsed");
      try{ localStorage.setItem("wfFnsCollapsed", c?"1":"0"); }catch{} };
  }
  // Auto-layout menu (bottom-left): toggle open/closed + run a strategy on pick.
  document.querySelectorAll(".wf-layout-item").forEach(btn=>{
    btn.onclick=(e)=>{ e.stopPropagation(); wfAutoLayout(btn.dataset.layout); wfCloseLayoutMenu(); };
  });
  // ── Activity panel: stop wheel from zooming the canvas ──────────────────
  const actBody=document.querySelector(".wf-act-panel-body");
  if(actBody) actBody.addEventListener("wheel", e=>e.stopPropagation(), {passive:true});
  // Right-click empty area of the activity list → select/deselect-all menu.
  // (Row-level contextmenu is handled on each .wf-act and stops propagation.)
  if(actBody) actBody.addEventListener("contextmenu", e=>{
    if(e.target.closest(".wf-act")) return;  // row menu owns this click
    e.preventDefault(); e.stopPropagation();
    wfShowActAllMenu(e.clientX, e.clientY);
  });
  // ── Inspector body: stop wheel from zooming the canvas ──────────────────
  const inspBody=$("wf-insp-body");
  if(inspBody) inspBody.addEventListener("wheel", e=>e.stopPropagation(), {passive:true});
  // ── Vars panel body: stop wheel from zooming the canvas ─────────────────
  const varsBody=$("wf-vars-body");
  if(varsBody) varsBody.addEventListener("wheel", e=>e.stopPropagation(), {passive:true});
  // ── Side palette: stop wheel from zooming the canvas ────────────────────
  const palette=$("wf-palette");
  if(palette) palette.addEventListener("wheel", e=>e.stopPropagation(), {passive:true});
  canvas.addEventListener("wheel",e=>{
    e.preventDefault();
    const r=canvas.getBoundingClientRect();
    // Snap zoom to 1% steps so we don't settle on ugly fractions that force a
    // soft GPU resample of every node (e.g. 87.3% after many wheel ticks).
    let z=wfZoom*(e.deltaY<0?1.1:1/1.1);
    z=Math.round(z*100)/100;
    if(Math.abs(z-1)<0.02) z=1;   // stick to 100% when close
    wfSetZoom(z, e.clientX-r.left, e.clientY-r.top);
  }, {passive:false});
  canvas.addEventListener("dragover",e=>{ if(wfPaletteDrag){ e.preventDefault(); e.dataTransfer.dropEffect="copy"; wfWireInsertHover(e.clientX,e.clientY); } });
  canvas.addEventListener("dragleave",e=>{ if(!e.relatedTarget || !canvas.contains(e.relatedTarget)) wfWireInsertClear(); });
  canvas.addEventListener("drop",e=>{
    if(!wfPaletteDrag) return; e.preventDefault();
    // Dropped straight onto a wire? Capture its edge so the new block splices in.
    const insEdge = wfInsWireGrp ? wfInsWireGrp.__edge : null;
    wfWireInsertClear();
    const g=wfGraph(); if(!g){ uiToast("Select or create an activity/function first.","warning"); wfPaletteDrag=null; return; }
    const wr=$("wf-world").getBoundingClientRect();
    const x=wfSnap((e.clientX-wr.left)/wfZoom-70), y=wfSnap((e.clientY-wr.top)/wfZoom-14);
    wfPushUndo();
    let node;
    if(wfPaletteDrag.startsWith("call:")){ node=wfNewNode("call",x,y); node.params={fn:wfPaletteDrag.slice(5)}; }
    else if(wfPaletteDrag.startsWith("var:")){ const p=wfPaletteDrag.split(":"); const vtype=p[1], vname=p.slice(2).join(":");
      node=wfNewNode("if_var",x,y); node.params={name:vname, op:"==", value: vtype==="bool"?"true":""}; }
    else node=wfNewNode(wfPaletteDrag,x,y);
    g.nodes.push(node);
    wfWireInsertSplice(g, insEdge, node);
    wfSelectOne(node.id); wfPaletteDrag=null;
    wfRenderCanvas(); wfRenderInspector();
    wfPopNodes([node.id]);   // brief arrival fade on the fresh block
  });
  document.addEventListener("mousemove",e=>{
    if(!wfGesture) return;
    if(wfGesture.mode==="move"){
      // Snap the lead node, then shift the whole selection by the SAME delta.
      const lead=wfGesture.items.find(it=>it.id===wfGesture.dragId)||wfGesture.items[0];
      if(!lead) return;
      const dx0=(e.clientX-wfGesture.sx)/wfZoom, dy0=(e.clientY-wfGesture.sy)/wfZoom;
      // Only flag as dragging after a real move (not just a click).
      if(!wfGesture._moving && (Math.abs(dx0)>1||Math.abs(dy0)>1)){
        wfGesture._moving=true;
        wfGesture.items.forEach(it=>{ const el=document.querySelector(`.wf-node[data-node="${it.id}"]`); if(el) el.classList.add("wf-dragging"); });
      }
      if(!wfGesture._moving) return;
      const rawX=lead.ox+(e.clientX-wfGesture.sx)/wfZoom;
      const rawY=lead.oy+(e.clientY-wfGesture.sy)/wfZoom;
      // Grid is the baseline. Smart align is evaluated from the unsnapped pointer
      // position, then overrides the grid only on an axis that actually matched.
      // This prevents a 20px grid from skipping a nearby 6px alignment target,
      // while the untouched axis remains cleanly on-grid.
      let sx=e.altKey?Math.round(rawX):wfSnap(rawX);
      let sy=e.altKey?Math.round(rawY):wfSnap(rawY);
      // Port/edge/centre alignment belongs to Smart align. Exact alignment wins
      // over the grid on its axis; a straight port wire is more useful than an
      // arbitrary grid coordinate. Alt bypasses both grid and Smart align.
      let alignHit=null, portSnapped=false;
      if(wfGesture.items.length===1 && !e.altKey && wfAlignOn){
        const py=wfPortAlignSnapY(wfGesture.dragId, rawY);
        portSnapped = py!==rawY;
        const alignY=portSnapped?py:rawY;
        alignHit=wfAlignSnap(wfGesture.dragId, rawX, alignY, portSnapped);
        if(alignHit.v) sx=alignHit.x;
        if(portSnapped) sy=py;
        else if(alignHit.h) sy=alignHit.y;
      }
      const dx=sx-lead.ox, dy=sy-lead.oy;
      wfGesture.items.forEach(it=>{
        const n=wfNode(it.id); if(!n) return;
        n.x=it.ox+dx; n.y=it.oy+dy;
        const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
        if(el){ el.style.left=n.x+"px"; el.style.top=n.y+"px"; }
      });
      if(wfGesture.items.length===1 && !e.altKey && wfAlignOn) wfShowAlignGuides(wfGesture.dragId, alignHit, portSnapped);
      else wfHideAlignGuides();
      wfDrawWires();
      wfGesture.mergeOk=e.ctrlKey;  // live-track Ctrl so user can press it mid-drag
      if(wfGesture.items.length===1 && wfGesture.mergeOk) wfShowMergeHint(wfGesture.dragId);
      else wfClearMergeHint();
    } else if(wfGesture.mode==="groupmove"){
      // Move the frame + every node that was inside it when the drag began.
      // Snap the group frame first, then apply the same snapped delta to members
      // so the whole group moves on-grid when snapping is on.
      const gr=wfGesture.gr;
      gr.x=wfSnap(wfGesture.gx+(e.clientX-wfGesture.sx)/wfZoom);
      gr.y=wfSnap(wfGesture.gy+(e.clientY-wfGesture.sy)/wfZoom);
      const sdx=gr.x-wfGesture.gx, sdy=gr.y-wfGesture.gy;
      const gel=document.querySelector(`.wf-group[data-group="${gr.id}"]`);
      if(gel){ gel.style.left=gr.x+"px"; gel.style.top=gr.y+"px"; }
      wfGesture.members.forEach(m=>{ const n=wfNode(m.id); if(!n) return; n.x=m.ox+sdx; n.y=m.oy+sdy;
        const el=document.querySelector(`.wf-node[data-node="${m.id}"]`); if(el){ el.style.left=n.x+"px"; el.style.top=n.y+"px"; } });
      wfDrawWires();
    } else if(wfGesture.mode==="groupresize"){
      const gr=wfGesture.gr;
      gr.w=Math.max(80, wfSnap(wfGesture.ow+(e.clientX-wfGesture.sx)/wfZoom));
      gr.h=Math.max(60, wfSnap(wfGesture.oh+(e.clientY-wfGesture.sy)/wfZoom));
      const el=document.querySelector(`.wf-group[data-group="${gr.id}"]`);
      if(el){ el.style.width=gr.w+"px"; el.style.height=gr.h+"px"; }
    } else if(wfGesture.mode==="groupdraw"){
      const wr=$("wf-world").getBoundingClientRect();
      const cx=(e.clientX-wr.left)/wfZoom, cy=(e.clientY-wr.top)/wfZoom;
      const x=Math.min(cx,wfGesture.sx), y=Math.min(cy,wfGesture.sy);
      const w=Math.abs(cx-wfGesture.sx), h=Math.abs(cy-wfGesture.sy);
      const box=$("wf-selbox"); if(box){ box.style.left=x+"px"; box.style.top=y+"px"; box.style.width=w+"px"; box.style.height=h+"px"; }
    } else if(wfGesture.mode==="box"){
      wfBoxSelectMove(e);
    } else if(wfGesture.mode==="pan"){
      wfPan.x=wfGesture.ox+(e.clientX-wfGesture.sx);
      wfPan.y=wfGesture.oy+(e.clientY-wfGesture.sy);
      wfWorldMotionHint();
      wfApplyTransform();
    } else if(wfGesture.mode==="connect"){
      wfDrawTempWire(e.clientX,e.clientY);
      const tid=wfNodeUnderPointer(e.clientX,e.clientY);
      wfHighlightTarget(tid && tid!==wfGesture.from ? tid : null);
    }
  });
  document.addEventListener("mouseup",e=>{
    if(!wfGesture) return;
    if(wfGesture.mode==="connect"){
      const tid=wfNodeUnderPointer(e.clientX,e.clientY);
      const connected = tid ? wfConnectTo(tid, e.clientX, e.clientY) : false;
      wfClearTemp(); wfHighlightTarget(null);
      // A new wire changes which nodes are "wired in" → rebuild so the warning
      // badges refresh; otherwise just redraw the wires (cheaper, no node change).
      if(connected){ wfPushUndo(); wfRenderCanvas(); } else wfDrawWires();
    } else if(wfGesture.mode==="groupresize"){
      wfPushUndo(); wfRenderCanvas();
    } else if(wfGesture.mode==="groupdraw"){
      const box=$("wf-selbox"); const gst=wfGesture;
      if(box) box.remove();
      const wr=$("wf-world").getBoundingClientRect();
      const cx=(e.clientX-wr.left)/wfZoom, cy=(e.clientY-wr.top)/wfZoom;
      const x=Math.min(cx,gst.sx), y=Math.min(cy,gst.sy), w=Math.abs(cx-gst.sx), h=Math.abs(cy-gst.sy);
      if(w>40 && h>40){ wfPushUndo(); wfAddGroup(x,y,w,h); }   // ignore tiny accidental drags
      wfSetGroupMode(false);
    } else if(wfGesture.mode==="box"){
      const box=$("wf-selbox"); if(box) box.remove();
      WF.selectedNode = WF.sel.length===1 ? WF.sel[0] : null;
      wfRenderInspector();
    } else if(wfGesture.mode==="move"){
      // Dropping a single lone block flush above/below another merges them.
      wfClearMergeHint();
      wfHideAlignGuides();
      document.querySelectorAll(".wf-node.wf-dragging").forEach(el=>el.classList.remove("wf-dragging"));
      const moved=Math.abs(e.clientX-wfGesture.sx)+Math.abs(e.clientY-wfGesture.sy)>3;
      // Only a real drag suppresses the action bar (wf-dragdone). A plain click
      // must leave the bar visible on the freshly selected block.
      if(moved) wfGesture.items.forEach(it=>{ const el=document.querySelector(`.wf-node[data-node="${it.id}"]`); if(el) el.classList.add("wf-dragdone"); });
      if(moved && wfGesture.items.length===1 && wfGesture.mergeOk){ wfPushUndo(); wfTryMerge(wfGesture.dragId); }
      else if(moved) wfPushUndo();  // plain move — push before the final render
    } else if(wfGesture.mode==="pan"){
      $("wf-canvas").classList.remove("panning");
    }
    $("wf-canvas").classList.remove("wf-connecting");
    wfGesture=null;
  });
}
function wfBoxSelectMove(e){
  const wr=$("wf-world").getBoundingClientRect();
  const cx=(e.clientX-wr.left)/wfZoom, cy=(e.clientY-wr.top)/wfZoom;
  const x=Math.min(cx,wfGesture.sx), y=Math.min(cy,wfGesture.sy);
  const w=Math.abs(cx-wfGesture.sx), h=Math.abs(cy-wfGesture.sy);
  const box=$("wf-selbox");
  if(box){ box.style.left=x+"px"; box.style.top=y+"px"; box.style.width=w+"px"; box.style.height=h+"px"; }
  const g=wfGraph(); if(!g) return;
  const hit=[];
  g.nodes.forEach(n=>{
    const el=document.querySelector(`.wf-node[data-node="${n.id}"]`); if(!el) return;
    const nw=el.offsetWidth, nh=el.offsetHeight;
    if(n.x < x+w && n.x+nw > x && n.y < y+h && n.y+nh > y) hit.push(n.id);
  });
  WF.sel = wfGesture.base.concat(hit.filter(id=>!wfGesture.base.includes(id)));
  wfMarkSel();
}
