// ── Node finder (Ctrl+F) ──────────────────────────────────────────────────────
// A quick-jump palette over EVERY node in EVERY activity/function: type a piece
// of the node's label, summary, template filename, note or id, arrow through
// the hits, Enter to jump — switching graphs if needed and gliding the camera
// onto the block. Esc closes. Built for the real graphs this tool edits
// (hundreds of nodes across a dozen activities).
let wfFindEl=null, wfFindHits=[], wfFindSel=0;

function wfFindIndex(){
  const items=[];
  const scan=(kind,owner)=>{
    ((owner.graph&&owner.graph.nodes)||[]).forEach(n=>{
      const def=WF_NODES[n.type]||{};
      let title=def.label||n.type;
      if(n.type==="call"){ const fn=wfFnById(n.params&&n.params.fn); if(fn) title="ƒ "+fn.name; }
      let sum=""; try{ sum=def.sum?String(def.sum(n.params||{})):""; }catch{}
      let tpl="";
      const tf=(typeof wfTplField==="function")?wfTplField(n.type):null;
      if(tf){ const v=(n.params||{})[tf.k]; tpl=Array.isArray(v)?v.join(" "):String(v||""); }
      items.push({kind, owner, node:n, title, sum,
        where:(kind==="function"?"ƒ ":"")+(owner.name||owner.id),
        hay:(title+" "+sum+" "+tpl+" "+(n.note||"")+" "+n.type+" "+n.id).toLowerCase()});
    });
  };
  (WF.activities||[]).forEach(a=>scan("activity",a));
  (WF.functions||[]).forEach(f=>{
    // The function ITSELF is a hit too (not just its call blocks): searching
    // "collect" must offer "go edit Collect rewards", the same way an activity
    // name does — otherwise a function's blocks could be found but not the
    // function you'd actually want to open.
    const name=f.name||f.id;
    items.push({ kind:"fn", fn:f, title:"ƒ "+name, sum:"function",
      where:"Function", hay:("ƒ "+name+" function call "+f.id).toLowerCase() });
    scan("function",f);
  });
  return items;
}

function wfFindClose(){
  if(wfFindEl){ wfFindEl.remove(); wfFindEl=null; wfFindHits=[]; wfFindSel=0; }
}
function wfFindJump(it){
  if(!it) return;
  if(it.kind==="fn"){          // the function itself → open it for editing
    if(typeof wfEditFunction==="function") wfEditFunction(it.fn.id);
    wfFindClose();
    return;
  }
  if(it.kind==="activity"){ if(typeof wfSelectActivity==="function") wfSelectActivity(it.owner.id); }
  else { if(typeof wfEditFunction==="function") wfEditFunction(it.owner.id); }
  wfSelectOne(it.node.id); wfMarkSel(); wfRenderInspector();
  wfCenterOnNode(it.node);
  wfFindClose();
}
// Which activity/function owns a node id. The log panel only ever has the id
// (the engine cannot know the graph layout), so this is the bridge back to a
// block on the canvas.
function wfOwnerOfNode(id){
  if(!id) return null;
  let hit=null;
  const scan=(kind,owner)=>{
    if(hit) return;
    const n=((owner.graph&&owner.graph.nodes)||[]).find(x=>x.id===id);
    if(n) hit={kind, owner, node:n};
  };
  (WF.activities||[]).forEach(a=>scan("activity",a));
  if(!hit) (WF.functions||[]).forEach(f=>scan("function",f));
  return hit;
}
// Jump the canvas to a block by id, switching activity/function and view as
// needed. Returns false when the block no longer exists (workflow edited since
// the run was captured).
function wfJumpToNode(id){
  const it=wfOwnerOfNode(id);
  if(!it) return false;
  if(typeof wfSwitchView==="function" && typeof wfCurView==="function" && wfCurView()!=="canvas"){
    wfSwitchView("canvas");   // the graph is hidden behind Library/Preview
  }
  wfFindJump(it);
  return true;
}

function wfFindRender(listEl, q){
  const all=wfFindIndex();
  const terms=(q||"").trim().toLowerCase().split(/\s+/).filter(Boolean);
  wfFindHits = terms.length ? all.filter(it=>terms.every(t=>it.hay.includes(t))) : all;
  wfFindSel=Math.min(wfFindSel, Math.max(0,wfFindHits.length-1));
  listEl.innerHTML="";
  if(!wfFindHits.length){
    const e=document.createElement("div"); e.className="wf-find-empty";
     e.textContent=terms.length?"No nodes match.":"No nodes yet.";
    listEl.appendChild(e); return;
  }
  const cur=wfEditTarget();
  wfFindHits.slice(0,30).forEach((it,i)=>{
    const row=document.createElement("button"); row.type="button";
    row.className="wf-find-item"+(i===wfFindSel?" sel":"");
    const here = cur && it.owner===cur;
    row.innerHTML=
      `<span class="t">${escHtml(it.title)}</span>`+
      (it.sum?`<span class="s">${escHtml(it.sum)}</span>`:"")+
      `<span class="w${here?" here":""}">${escHtml(it.where)}</span>`;
    row.addEventListener("mousedown",e=>e.preventDefault());   // keep input focus
    row.addEventListener("click",()=>wfFindJump(it));
    listEl.appendChild(row);
  });
  if(wfFindHits.length>30){
    const more=document.createElement("div"); more.className="wf-find-empty";
    more.textContent=`+${wfFindHits.length-30} more results — type to narrow down`;
    listEl.appendChild(more);
  }
}
function wfFindShow(){
  if(wfFindEl){ const inp=wfFindEl.querySelector("input"); if(inp){ inp.focus(); inp.select(); } return; }
  const canvas=$("wf-canvas"); if(!canvas) return;
  const box=document.createElement("div"); box.className="wf-find"; wfFindEl=box;
  box.innerHTML=
    `<div class="wf-find-bar">
       <svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/></svg>
       <input type="text" placeholder="Find node or function… (name, image, note)" spellcheck="false" autocomplete="off">
       <span class="k">Esc</span>
     </div>
     <div class="wf-find-list"></div>`;
  canvas.appendChild(box);
  const inp=box.querySelector("input"), list=box.querySelector(".wf-find-list");
  const move=d=>{ if(!wfFindHits.length) return; wfFindSel=(wfFindSel+d+Math.min(30,wfFindHits.length))%Math.min(30,wfFindHits.length); wfFindRender(list, inp.value); };
  inp.addEventListener("input",()=>{ wfFindSel=0; wfFindRender(list, inp.value); });
  inp.addEventListener("keydown",e=>{
    e.stopPropagation();
    if(e.key==="Escape"){ wfFindClose(); }
    else if(e.key==="ArrowDown"){ e.preventDefault(); move(1); }
    else if(e.key==="ArrowUp"){ e.preventDefault(); move(-1); }
    else if(e.key==="Enter"){ e.preventDefault(); wfFindJump(wfFindHits[wfFindSel]); }
  });
  box.addEventListener("mousedown",e=>e.stopPropagation());   // don't box-select under it
  inp.addEventListener("blur",()=>{ setTimeout(()=>{ if(wfFindEl && !wfFindEl.contains(document.activeElement)) wfFindClose(); },120); });
  wfFindRender(list,"");
  inp.focus();
}
