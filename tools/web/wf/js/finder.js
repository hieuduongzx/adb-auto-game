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
  (WF.functions||[]).forEach(f=>scan("function",f));
  return items;
}

function wfFindClose(){
  if(wfFindEl){ wfFindEl.remove(); wfFindEl=null; wfFindHits=[]; wfFindSel=0; }
}
function wfFindJump(it){
  if(!it) return;
  if(it.kind==="activity"){ if(typeof wfSelectActivity==="function") wfSelectActivity(it.owner.id); }
  else { if(typeof wfEditFunction==="function") wfEditFunction(it.owner.id); }
  wfSelectOne(it.node.id); wfMarkSel(); wfRenderInspector();
  wfCenterOnNode(it.node);
  wfFindClose();
}
function wfFindRender(listEl, q){
  const all=wfFindIndex();
  const terms=(q||"").trim().toLowerCase().split(/\s+/).filter(Boolean);
  wfFindHits = terms.length ? all.filter(it=>terms.every(t=>it.hay.includes(t))) : all;
  wfFindSel=Math.min(wfFindSel, Math.max(0,wfFindHits.length-1));
  listEl.innerHTML="";
  if(!wfFindHits.length){
    const e=document.createElement("div"); e.className="wf-find-empty";
    e.textContent=terms.length?"Không khớp block nào.":"Chưa có block.";
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
    more.textContent=`+${wfFindHits.length-30} kết quả nữa — gõ thêm để lọc`;
    listEl.appendChild(more);
  }
}
function wfFindShow(){
  if(wfFindEl){ const inp=wfFindEl.querySelector("input"); if(inp){ inp.focus(); inp.select(); } return; }
  const canvas=$("wf-canvas"); if(!canvas) return;
  const box=document.createElement("div"); box.className="wf-find"; wfFindEl=box;
  box.innerHTML=
    `<div class="wf-find-bar">
       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></svg>
       <input type="text" placeholder="Tìm block… (tên, ảnh, ghi chú)" spellcheck="false" autocomplete="off">
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
