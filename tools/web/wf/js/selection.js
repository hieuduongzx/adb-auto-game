// ── Selection ────────────────────────────────────────────────────────────────
function wfMarkSel(){ document.querySelectorAll(".wf-node").forEach(el=>el.classList.toggle("sel",WF.sel.includes(el.dataset.node)));
  if(typeof wfMinimapQueue==="function") wfMinimapQueue(); }
// Brief arrival fade on freshly created blocks (palette drop / paste) so new
// material registers without moving any geometry (opacity only — wires stay put).
function wfPopNodes(ids){
  (ids||[]).forEach(id=>{ const el=wfNodeElById(id); if(!el) return;
    el.classList.add("wf-node-new");
    el.addEventListener("animationend",()=>el.classList.remove("wf-node-new"),{once:true});
    setTimeout(()=>el.classList.remove("wf-node-new"),400);   // reduced-motion fallback
  });
}
function wfSelectOne(id){ WF.sel=id?[id]:[]; WF.selectedNode=id||null; document.querySelectorAll(".wf-node.wf-dragdone").forEach(el=>el.classList.remove("wf-dragdone")); }
function wfToggleSel(id){ const i=WF.sel.indexOf(id); if(i>=0)WF.sel.splice(i,1); else WF.sel.push(id); WF.selectedNode=WF.sel.length?id:null; }
function wfClearSel(){ WF.sel=[]; WF.selectedNode=null; }
function wfDeleteNode(id){ wfDeleteNodes([id]); }
function wfDeleteSelected(){ if(WF.sel.length) wfDeleteNodes(WF.sel.slice()); }
function wfDeleteNodes(ids){
  const g=wfGraph(); if(!g) return;
  const del=ids.filter(id=>{ const n=g.nodes.find(x=>x.id===id); return n && n.type!=="start"; });
  if(!del.length) return;
  wfPushUndo();
  g.nodes=g.nodes.filter(n=>!del.includes(n.id));
  g.edges=g.edges.filter(e=>!del.includes(e.from)&&!del.includes(e.to));
  // A merge with only one block left is no longer a stack — dissolve it.
  const stackCount={}; g.nodes.forEach(n=>{ if(n.stack) stackCount[n.stack]=(stackCount[n.stack]||0)+1; });
  g.nodes.forEach(n=>{ if(n.stack && stackCount[n.stack]<2) n.stack=null; });
  WF.sel=WF.sel.filter(id=>!del.includes(id));
  if(del.includes(WF.selectedNode)) WF.selectedNode=null;
  wfRenderCanvas(); wfRenderInspector();
  // Không hỏi xác nhận — Ctrl+Z hoàn tác được; nhắc khi xóa nhiều block một lúc.
  if(del.length>2) uiToast(`Đã xóa ${del.length} block — Ctrl+Z để hoàn tác`,"info");
  else setStatus(`Đã xóa ${del.length} block — Ctrl+Z để hoàn tác`);
}

// ── Copy / paste ──────────────────────────────────────────────────────────────
// Clipboard holds detached clones of the copied nodes (params, note, stacking)
// plus the edges *internal* to the selection, referenced by array index so they
// survive id remapping. Works across activities/functions (it's not tied to the
// current graph). The 'start' node is never copyable.
let wfClipboard=null;
let wfPasteShift=0;            // cascade offset for repeated Ctrl+V at no cursor
let wfPointer={x:0,y:0,inside:false};   // last pointer pos over the canvas
function wfCopy(){
  const g=wfGraph(); if(!g) return false;
  const ids=WF.sel.filter(id=>{ const n=g.nodes.find(x=>x.id===id); return n && n.type!=="start"; });
  if(!ids.length) return false;
  const idset=new Set(ids);
  const nodes=ids.map(id=>{ const n=g.nodes.find(x=>x.id===id);
    return { type:n.type, x:n.x, y:n.y, note:n.note||"", log:n.log||"", showPreview:!!n.showPreview,
      stack:n.stack||null, params:JSON.parse(JSON.stringify(n.params||{})) }; });
  const edges=g.edges.filter(e=>idset.has(e.from)&&idset.has(e.to))
    .map(e=>({fromIdx:ids.indexOf(e.from), fromPort:e.fromPort, toIdx:ids.indexOf(e.to), toPort:e.toPort||"in"}));
  const minX=Math.min(...nodes.map(n=>n.x)), minY=Math.min(...nodes.map(n=>n.y));
  wfClipboard={nodes,edges,minX,minY};
  wfPasteShift=0;
  setStatus(`Copied ${nodes.length} node`);
  return true;
}
function wfCut(){ if(wfCopy()) wfDeleteSelected(); }
function wfDuplicate(){ if(wfCopy()) wfPaste(); }   // copy + cascade-offset paste
function wfPaste(opts){
  const g=wfGraph(); if(!g){ uiToast("Chọn hoặc tạo một activity trước.","warning"); return; }
  if(!wfClipboard||!wfClipboard.nodes.length) return;
  wfPushUndo();
  const clip=wfClipboard;
  let dx, dy;
  if(opts && opts.clientX!==undefined){
    const wr=$("wf-world").getBoundingClientRect();
    dx=wfSnap((opts.clientX-wr.left)/wfZoom - clip.minX - 70);
    dy=wfSnap((opts.clientY-wr.top)/wfZoom - clip.minY - 14);
  } else { wfPasteShift+=24; dx=wfPasteShift; dy=wfPasteShift; }
  const newIds=clip.nodes.map(()=>wfUid());
  const stackMap={};   // remap copied stack ids → fresh ids so paste stays its own merge
  clip.nodes.forEach((n,i)=>{
    const node=wfNewNode(n.type, n.x+dx, n.y+dy);
    node.id=newIds[i];
    node.params=JSON.parse(JSON.stringify(n.params||{}));
    node.note=n.note||""; node.log=n.log||""; node.showPreview=!!n.showPreview;
    if(n.stack){ stackMap[n.stack]=stackMap[n.stack]||wfStackId(); node.stack=stackMap[n.stack]; }
    g.nodes.push(node);
  });
  clip.edges.forEach(e=>g.edges.push({from:newIds[e.fromIdx], fromPort:e.fromPort, to:newIds[e.toIdx], toPort:e.toPort||"in"}));
  // A partially-copied stack (only some members) can leave a lone tagged node —
  // drop the tag so it isn't a one-block "merge".
  const stkCnt={}; g.nodes.forEach(n=>{ if(n.stack) stkCnt[n.stack]=(stkCnt[n.stack]||0)+1; });
  g.nodes.forEach(n=>{ if(n.stack && stkCnt[n.stack]<2) n.stack=null; });
  WF.sel=newIds.slice(); WF.selectedNode=newIds.length===1?newIds[0]:null;
  wfRenderCanvas(); wfMarkSel(); wfRenderInspector();
  wfPopNodes(newIds);
  setStatus(`Pasted ${newIds.length} node`);
}
