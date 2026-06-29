// ── Groups (frames) ───────────────────────────────────────────────────────────
// A group is a named rectangle living in the graph (graph.groups). Membership is
// geometric: a node belongs to a group when its centre is inside the rectangle.
// Moving the group's header moves every node currently inside it. Groups are
// purely visual — the engine ignores them (it only runs nodes + edges).
const WF_GROUP_COLORS = [
  {b:"#6f9be8", bg:"rgba(111,155,232,.07)"},
  {b:"#2fb0a3", bg:"rgba(47,176,163,.08)"},
  {b:"#e0954b", bg:"rgba(224,149,75,.09)"},
  {b:"#9a78e6", bg:"rgba(154,120,230,.08)"},
  {b:"#cf6b6b", bg:"rgba(207,107,107,.08)"},
];
function wfGroups(){ const t=wfEditTarget(); if(!t) return []; if(!t.graph.groups) t.graph.groups=[]; return t.graph.groups; }
function wfGroupColor(gr){ return WF_GROUP_COLORS[(gr.color||0) % WF_GROUP_COLORS.length]; }
function wfNodesInGroup(gr){
  const g=wfGraph(); if(!g) return [];
  return g.nodes.filter(n=>{
    const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
    const w=el?el.offsetWidth:158, h=el?el.offsetHeight:52;
    const cx=n.x+w/2, cy=n.y+h/2;
    return cx>=gr.x && cx<=gr.x+gr.w && cy>=gr.y && cy<=gr.y+gr.h;
  });
}
function wfAddGroup(x,y,w,h){
  const groups=wfGroups();
  const gr={ id:"g"+wfUid().slice(1), name:"Nhóm "+(groups.length+1),
    x:Math.round(x), y:Math.round(y), w:Math.round(w), h:Math.round(h), color:groups.length%WF_GROUP_COLORS.length };
  groups.push(gr); wfRenderCanvas(); setStatus(`Đã tạo "${gr.name}" — kéo tiêu đề để di chuyển cả nhóm`);
  return gr;
}
function wfDeleteGroup(id){ const groups=wfGroups(); const i=groups.findIndex(x=>x.id===id); if(i>=0){ groups.splice(i,1); wfRenderCanvas(); } }
function wfRenameGroup(gr){ const nm=prompt("Tên nhóm:", gr.name||""); if(nm!==null){ gr.name=(nm.trim()||gr.name); wfRenderCanvas(); } }
// Create a group hugging the current multi-selection (toolbar button shortcut).
function wfGroupSelection(){
  const ids=WF.sel.slice(); if(ids.length<1) return false;
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  ids.forEach(id=>{ const n=wfNode(id); if(!n) return;
    const el=document.querySelector(`.wf-node[data-node="${id}"]`);
    const w=el?el.offsetWidth:158, h=el?el.offsetHeight:52;
    x0=Math.min(x0,n.x); y0=Math.min(y0,n.y); x1=Math.max(x1,n.x+w); y1=Math.max(y1,n.y+h);
  });
  if(!isFinite(x0)) return false;
  const pad=22;
  wfAddGroup(x0-pad, y0-pad-22, (x1-x0)+pad*2, (y1-y0)+pad*2+22);
  return true;
}
// Resize an existing group to tightly wrap all its current member nodes.
function wfFitGroup(gr){
  const members=wfNodesInGroup(gr);
  if(!members.length){ setStatus('Nhóm "'+gr.name+'" không chứa block nào'); return; }
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  members.forEach(n=>{
    const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
    const w=el?el.offsetWidth:158, h=el?el.offsetHeight:52;
    x0=Math.min(x0,n.x); y0=Math.min(y0,n.y); x1=Math.max(x1,n.x+w); y1=Math.max(y1,n.y+h);
  });
  if(!isFinite(x0)) return;
  const pad=22;
  gr.x=wfSnap(x0-pad); gr.y=wfSnap(y0-pad-22);
  gr.w=wfSnap((x1-x0)+pad*2); gr.h=wfSnap((y1-y0)+pad*2+22);
  wfRenderCanvas();
  setStatus(`Đã khớp viền nhóm "${gr.name}"`);
}
function wfRenderGroups(){
  const world=$("wf-world"), svg=$("wf-wires");
  [...world.querySelectorAll(".wf-group")].forEach(el=>el.remove());
  wfGroups().forEach(gr=>{
    const c=wfGroupColor(gr);
    const el=document.createElement("div"); el.className="wf-group"; el.dataset.group=gr.id;
    el.style.left=gr.x+"px"; el.style.top=gr.y+"px"; el.style.width=gr.w+"px"; el.style.height=gr.h+"px";
    el.style.borderColor=c.b; el.style.background=c.bg; el.style.color=c.b;
    el.innerHTML=`<div class="wf-group-hd" style="background:${c.b}"><span class="wf-group-name">${escHtml(gr.name)}</span><button class="wf-group-del" title="Xoá nhóm (giữ lại các node)">${wfIco("x")}</button></div><div class="wf-group-resize"></div>`;
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
// point so dropping low on a loop wires into its 'lặp' (loop-back) port.
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
function wfCanvasMouseDown(e){
  if(e.target.closest(".wf-node")||e.target.closest(".wf-group")) return;
  // Middle mouse, or Space+left → pan.
  if(e.button===1 || (e.button===0 && wfSpace)){
    e.preventDefault();
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
  const b=$("wf-group-btn"); if(b){ b.classList.toggle("on",wfGroupMode); b.title="Tạo nhóm: "+(wfGroupMode?"đang bật — kéo để vẽ khung":"Tắt"); }
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
  const g=wfGraph(); if(!g) return;
  const n=wfNode(nodeId); if(!n||n.type==="start") return;
  const startNode=g.nodes.find(nd=>nd.type==="start"); if(!startNode) return;
  g.edges=g.edges.filter(e=>!(e.from===startNode.id&&(e.fromPort||"out")==="out"));
  g.edges.push({from:startNode.id,fromPort:"out",to:nodeId,toPort:"in"});
  wfRenderCanvas();
  setStatus("Đã đặt làm block mặc định");
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
// Run one block in isolation — the engine executes it on the calling thread
// (no graph walk), firing the same on_node/on_node_done callbacks a real run
// does, so the canvas paints it amber→green/red and the log streams its output.
function wfRunSingleNode(node){
  if(!node) return;
  if(wfRunning){ setStatus("Workflow đang chạy — dừng trước khi chạy 1 block"); return; }
  // Serialize just this node (id/type/params + note/log) and the current flow
  // so the engine can resolve templates against the right templates dir.
  const clean={ id:node.id, type:node.type, params:Object.assign({}, node.params||{}) };
  if(node.note) clean.note=node.note;
  if(node.log)  clean.log=node.log;
  setStatus("Đang chạy block…");
  api().workflow_run_node(JSON.stringify(clean), JSON.stringify(wfSerialize())).then(ok=>{
    if(!ok) setStatus("Chạy block thất bại");
  });
}
function wfHideMenu(){ const m=$("wf-ctxmenu"); if(m) m.style.display="none"; }
function wfShowMenu(clientX, clientY){
  const m=$("wf-ctxmenu"); if(!m) return;
  const items=[];
  const copyable=WF.sel.filter(id=>{ const n=wfNode(id); return n && n.type!=="start"; }).length;
  const stackSids=[...new Set(WF.sel.map(id=>{ const n=wfNode(id); return n&&n.stack; }).filter(Boolean))];
  if(WF.sel.length===1){
    const _n=wfNode(WF.sel[0]);
    if(_n&&_n.type!=="start") items.push({ico:"play",label:"Đặt làm mặc định", fn:()=>wfSetAsDefault(WF.sel[0])});
    // Run a single block in isolation (no graph walk). Structural nodes (loop,
    // parallel, switch, call) and terminals don't make sense standalone, so the
    // entry only shows on executable action/condition kinds.
    if(_n){
      const _def=WF_NODES[_n.type]||{};
      const _kind=_def.kind;
      if(_kind==="action"||_kind==="condition"){
        items.push({ico:"play",label:"Chạy block này", fn:()=>wfRunSingleNode(_n)});
      }
    }
  }
  if(stackSids.length) items.push({ico:"link_off",label:"Bỏ merge", fn:()=>stackSids.forEach(wfUnmerge)});
  if(WF.sel.length>=1) items.push({ico:"box",label:"Tạo nhóm quanh ("+WF.sel.length+")", fn:wfGroupSelection});
  if(copyable){ items.push({ico:"copy",label:"Sao chép ("+copyable+")", fn:wfCopy});
    items.push({ico:"scissors",label:"Cắt ("+copyable+")", fn:wfCut});
    items.push({ico:"copy",label:"Nhân đôi ("+copyable+")", fn:wfDuplicate}); }
  if(wfClipboard&&wfClipboard.nodes.length) items.push({ico:"clipboard",label:"Dán ("+wfClipboard.nodes.length+")", fn:()=>wfPaste({clientX,clientY})});
  if(WF.sel.length) items.push({ico:"trash",label:"Xoá ("+WF.sel.length+")", fn:()=>wfDeleteSelected()});
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
  const d=document.createElement("div"); d.className="wf-ctx-item"; d.innerHTML=`<span class="wf-ctx-ico">${wfIco("trash")}</span>Xoá dây nối`;
  d.onclick=()=>{ wfHideMenu(); wfDeleteWire(ed); }; m.appendChild(d);
  m.style.left=clientX+"px"; m.style.top=clientY+"px"; m.style.display="block";
}
function wfShowGroupMenu(clientX, clientY, gr){
  const m=$("wf-ctxmenu"); if(!m) return;
  m.innerHTML="";
  const items=[
    {ico:"expand", label:"Khớp viền", fn:()=>wfFitGroup(gr)},
    {ico:"edit",   label:"Đổi tên",   fn:()=>wfRenameGroup(gr)},
    {ico:"trash",  label:"Xoá nhóm",  fn:()=>wfDeleteGroup(gr.id)},
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
  document.addEventListener("mousedown",e=>{ if(!e.target.closest("#wf-ctxmenu")) wfHideMenu(); if(!e.target.closest("#wf-globs-pop") && !e.target.closest("#wf-vars-mgr") && !e.target.closest("#wf-vars-add")) wfHideGlobsEditor(); }, true);
  // Vars panel header toggles collapse (click-through to drag is fine on body).
  const vhdr=document.querySelector("#wf-vars-panel .wf-vars-hdr");
  if(vhdr) vhdr.onclick=(e)=>{ if(e.target.closest(".wf-vars-actions")) return; wfVarsCollapsed=!wfVarsCollapsed; wfRenderVarsPanel(); };
  const vadd=$("wf-vars-add");
  if(vadd) vadd.onclick=(e)=>{ e.stopPropagation(); wfAddQuickGlobal(); };
  const vmgr=$("wf-vars-mgr");
  if(vmgr) vmgr.onclick=(e)=>{ e.stopPropagation(); wfToggleGlobsEditor(); };
  // Activities/Functions panel: tab switching + "+" add button + collapse.
  document.querySelectorAll(".wf-act-tab").forEach(tab=>{
    tab.onclick=(e)=>{ e.stopPropagation(); wfActTab(tab.dataset.tab); };
  });
  const aadd=$("wf-act-add");
  if(aadd) aadd.onclick=(e)=>{ e.stopPropagation(); wfActAddCurrent(); };
  // Only the title row (not the tab bar) is the collapse trigger.
  const ahdr=document.querySelector("#wf-act-hdr-row");
  if(ahdr) ahdr.onclick=(e)=>{ if(e.target.closest(".wf-act-hdr-add")) return; wfActCollapsed=!wfActCollapsed; wfToggleActPanel(); };
  // Auto-layout buttons (bottom-left toolbar).
  document.querySelectorAll(".wf-layout-btn").forEach(btn=>{
    btn.onclick=(e)=>{ e.stopPropagation(); wfAutoLayout(btn.dataset.layout); };
  });
  canvas.addEventListener("wheel",e=>{
    e.preventDefault();
    const r=canvas.getBoundingClientRect();
    wfSetZoom(wfZoom*(e.deltaY<0?1.1:1/1.1), e.clientX-r.left, e.clientY-r.top);
  }, {passive:false});
  canvas.addEventListener("dragover",e=>{ if(wfPaletteDrag){ e.preventDefault(); e.dataTransfer.dropEffect="copy"; } });
  canvas.addEventListener("drop",e=>{
    if(!wfPaletteDrag) return; e.preventDefault();
    const g=wfGraph(); if(!g){ alert("Chọn hoặc thêm một hoạt động/function trước."); wfPaletteDrag=null; return; }
    const wr=$("wf-world").getBoundingClientRect();
    const x=wfSnap((e.clientX-wr.left)/wfZoom-70), y=wfSnap((e.clientY-wr.top)/wfZoom-14);
    let node;
    if(wfPaletteDrag.startsWith("call:")){ node=wfNewNode("call",x,y); node.params={fn:wfPaletteDrag.slice(5)}; }
    else if(wfPaletteDrag.startsWith("var:")){ const p=wfPaletteDrag.split(":"); const vtype=p[1], vname=p.slice(2).join(":");
      node=wfNewNode("if_var",x,y); node.params={name:vname, op:"==", value: vtype==="bool"?"true":""}; }
    else node=wfNewNode(wfPaletteDrag,x,y);
    g.nodes.push(node); wfSelectOne(node.id); wfPaletteDrag=null;
    wfRenderCanvas(); wfRenderInspector();
  });
  document.addEventListener("mousemove",e=>{
    if(!wfGesture) return;
    if(wfGesture.mode==="move"){
      // Snap the lead node, then shift the whole selection by the SAME delta.
      const lead=wfGesture.items.find(it=>it.id===wfGesture.dragId)||wfGesture.items[0];
      if(!lead) return;
      const sx=wfSnap(lead.ox+(e.clientX-wfGesture.sx)/wfZoom);
      const sy=wfSnap(lead.oy+(e.clientY-wfGesture.sy)/wfZoom);
      const dx=sx-lead.ox, dy=sy-lead.oy;
      wfGesture.items.forEach(it=>{
        const n=wfNode(it.id); if(!n) return;
        n.x=it.ox+dx; n.y=it.oy+dy;
        const el=document.querySelector(`.wf-node[data-node="${n.id}"]`);
        if(el){ el.style.left=n.x+"px"; el.style.top=n.y+"px"; }
      });
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
      if(connected) wfRenderCanvas(); else wfDrawWires();
    } else if(wfGesture.mode==="groupresize"){
      wfRenderCanvas();
    } else if(wfGesture.mode==="groupdraw"){
      const box=$("wf-selbox"); const gst=wfGesture;
      if(box) box.remove();
      const wr=$("wf-world").getBoundingClientRect();
      const cx=(e.clientX-wr.left)/wfZoom, cy=(e.clientY-wr.top)/wfZoom;
      const x=Math.min(cx,gst.sx), y=Math.min(cy,gst.sy), w=Math.abs(cx-gst.sx), h=Math.abs(cy-gst.sy);
      if(w>40 && h>40) wfAddGroup(x,y,w,h);   // ignore tiny accidental drags
      wfSetGroupMode(false);
    } else if(wfGesture.mode==="box"){
      const box=$("wf-selbox"); if(box) box.remove();
      WF.selectedNode = WF.sel.length===1 ? WF.sel[0] : null;
      wfRenderInspector();
    } else if(wfGesture.mode==="move"){
      // Dropping a single lone block flush above/below another merges them.
      wfClearMergeHint();
      const moved=Math.abs(e.clientX-wfGesture.sx)+Math.abs(e.clientY-wfGesture.sy)>3;
      if(moved && wfGesture.items.length===1 && wfGesture.mergeOk) wfTryMerge(wfGesture.dragId);
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
