// ── Inspector ──────────────────────────────────────────────────────────────
function wfRenderInspector(){
  const body=$("wf-insp-body"); body.innerHTML="";
  wfRenderVarsPanel();

  // Multi-selection panel.
  if(WF.sel.length>1){
    const g=wfGraph();
    const selNodes=g?WF.sel.map(id=>g.nodes.find(n=>n.id===id)).filter(Boolean):[];

    const card=document.createElement("div"); card.className="wf-insp-card";
    const hdr=document.createElement("div"); hdr.className="wf-insp-hdr";
    hdr.innerHTML=`<span class="ico">${wfIco("box")}</span><span class="title">${WF.sel.length} block được chọn</span>`;
    card.appendChild(hdr);

    const list=document.createElement("div"); list.style.cssText="display:flex;flex-direction:column;gap:2px;";
    selNodes.slice(0,8).forEach(n=>{
      const def=WF_NODES[n.type]||{};
      const row=document.createElement("div");
      row.style.cssText="font-size:11px;color:var(--dim);padding:1px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
      row.textContent=(def.label||n.type)+(n.label?` · ${n.label}`:"");
      list.appendChild(row);
    });
    if(selNodes.length>8){
      const more=document.createElement("div");
      more.style.cssText="font-size:10px;color:var(--muted);padding:1px 4px;";
      more.textContent=`+${selNodes.length-8} nữa…`; list.appendChild(more);
    }
    card.appendChild(list);

    const alignSec=document.createElement("div"); alignSec.className="wf-insp-sec"; alignSec.textContent="Căn chỉnh"; card.appendChild(alignSec);
    const alignGrid=document.createElement("div"); alignGrid.className="wf-insp-grid";
    const mkAlign=(lbl,fn)=>{ const b=document.createElement("button"); b.className="btn sm"; b.textContent=lbl; b.title=lbl; b.onclick=fn; return b; };
    alignGrid.appendChild(mkAlign("← Trái", ()=>{ if(!g||!selNodes.length) return; const minX=Math.min(...selNodes.map(n=>n.x)); selNodes.forEach(n=>n.x=minX); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("→ Phải",()=>{ if(!g||!selNodes.length) return; const maxX=Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.x+(el?el.offsetWidth:158); })); selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.x=maxX-(el?el.offsetWidth:158); }); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↑ Trên", ()=>{ if(!g||!selNodes.length) return; const minY=Math.min(...selNodes.map(n=>n.y)); selNodes.forEach(n=>n.y=minY); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↓ Dưới",()=>{ if(!g||!selNodes.length) return; const maxY=Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.y+(el?el.offsetHeight:46); })); selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.y=maxY-(el?el.offsetHeight:46); }); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↔ Giữa X",()=>{ if(!g||!selNodes.length) return; const cx=(Math.min(...selNodes.map(n=>n.x))+Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.x+(el?el.offsetWidth:158); })))/2; selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.x=cx-(el?el.offsetWidth:158)/2; }); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↕ Giữa Y",()=>{ if(!g||!selNodes.length) return; const cy=(Math.min(...selNodes.map(n=>n.y))+Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.y+(el?el.offsetHeight:46); })))/2; selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.y=cy-(el?el.offsetHeight:46)/2; }); wfRenderCanvas(); }));
    card.appendChild(alignGrid);

    const actSec=document.createElement("div"); actSec.className="wf-insp-sec"; actSec.textContent="Thao tác"; card.appendChild(actSec);
    const actGrid=document.createElement("div"); actGrid.className="wf-insp-grid";
    const dupBtn=document.createElement("button"); dupBtn.className="btn sm"; dupBtn.textContent="Nhân bản"; dupBtn.title="Ctrl+D"; dupBtn.onclick=()=>wfDuplicate(); actGrid.appendChild(dupBtn);
    const grpBtn=document.createElement("button"); grpBtn.className="btn sm"; grpBtn.textContent="Tạo nhóm"; grpBtn.onclick=()=>wfGroupSelection(); actGrid.appendChild(grpBtn);
    const delBtn=document.createElement("button"); delBtn.className="btn sm err"; delBtn.textContent="Xoá"; delBtn.onclick=()=>wfDeleteSelected(); actGrid.appendChild(delBtn);
    card.appendChild(actGrid);

    const tip=document.createElement("div"); tip.className="wf-insp-tip";
    tip.textContent="Ctrl+click / Shift+click để thêm/bớt chọn. Phím ← → ↑ ↓ di chuyển (Shift = 10px).";
    card.appendChild(tip);
    body.appendChild(card);
    return;
  }

  const node=wfNode(WF.selectedNode), act=wfCurAct(), fn=wfCurFn();
  if(node){
    const def=WF_NODES[node.type]||{label:node.type,fields:[]};

    // Header card.
    const hdrCard=document.createElement("div"); hdrCard.className="wf-insp-card";
    const hdr=document.createElement("div"); hdr.className="wf-insp-hdr";
    hdr.innerHTML=`<span class="ico">${wfIco(def.ico||"box")}</span><span class="title">${def.label||node.type}</span>`;
    hdrCard.appendChild(hdr);
    body.appendChild(hdrCard);

    // Parameters.
    if(node.type==="call"){ body.appendChild(wfCallPicker(node)); }
    else if(node.type==="switch" || node.type==="try_chain"){ body.appendChild(wfBranchCountEditor(node)); }
    else {
      if(!(def.fields||[]).length){
        const d=document.createElement("div"); d.className="wf-insp-tip"; d.textContent="Node này không có tham số."; body.appendChild(d);
      }
      (def.fields||[]).forEach(f=>body.appendChild(wfFieldEl(node,f)));
    }

    // Note & Log cards.
    if(node.type!=="note") body.appendChild(wfNoteField(node));
    if(node.type!=="note" && node.type!=="start") body.appendChild(wfLogField(node));
    return;
  }

  if(fn){
    const card=document.createElement("div"); card.className="wf-insp-card";
    const hdr=document.createElement("div"); hdr.className="wf-insp-hdr";
    hdr.innerHTML=`<span class="ico">${wfIco("function")}</span><span class="title">ƒ Function</span>`;
    card.appendChild(hdr);
    card.appendChild(wfActField("Tên","text",fn.name,v=>{ fn.name=v; wfRenderFunctions(); wfRenderPalette(); $("wf-cur-act").textContent="ƒ "+v; }));
    const tip=document.createElement("div"); tip.className="wf-insp-tip"; tip.textContent="Xếp node cho function này. Nó dùng được như một node trong mọi hoạt động (kéo từ mục Function)."; card.appendChild(tip);
    body.appendChild(card);
    return;
  }

  if(act){
    const card=document.createElement("div"); card.className="wf-insp-card";
    const hdr=document.createElement("div"); hdr.className="wf-insp-hdr";
    const typeLabel=act.type==="background"?"Hoạt động nền":"Hoạt động tuần tự";
    hdr.innerHTML=`<span class="ico">${wfIco(act.type==="background"?"layers":"play")}</span><span class="title">${typeLabel}</span>`;
    card.appendChild(hdr);
    card.appendChild(wfActField("Tên","text",act.name,v=>{ act.name=v; wfRenderActivities(); $("wf-cur-act").textContent=v; }));
    if(act.type==="background") card.appendChild(wfActField("Chu kỳ (s)","num",act.pollInterval,v=>act.pollInterval=parseFloat(v)||1));
    else card.appendChild(wfActField("Số lần thử","num",act.maxRetries,v=>act.maxRetries=parseInt(v)||1));
    card.appendChild(wfVarsSection(act));
    const tip=document.createElement("div"); tip.className="wf-insp-tip"; tip.textContent="Bấm một node trên canvas để sửa tham số của nó."; card.appendChild(tip);
    body.appendChild(card);
    return;
  }
  body.innerHTML='<div class="wf-insp-empty">Chưa chọn hoạt động.</div>';
}

function wfInspHdr(iconName,title,sub){
  const hdr=document.createElement("div"); hdr.className="wf-insp-hdr";
  let html=`<span class="ico">${wfIco(iconName)}</span><span class="title">${title}</span>`;
  if(sub) html+=`<span class="badge">${sub}</span>`;
  hdr.innerHTML=html;
  return hdr;
}

function wfCallPicker(node){
  const row=document.createElement("div"); row.className="wf-field";
  const l=document.createElement("label"); l.textContent="function"; row.appendChild(l);
  const sel=document.createElement("select");
  if(!WF.functions.length){ const o=document.createElement("option"); o.value=""; o.textContent="(chưa có function)"; sel.appendChild(o); }
  WF.functions.forEach(fn=>{ const o=document.createElement("option"); o.value=fn.id; o.textContent=fn.name; if(fn.id===node.params.fn)o.selected=true; sel.appendChild(o); });
  sel.onchange=()=>{ node.params.fn=sel.value; wfRenderCanvas(); };
  row.appendChild(sel); return row;
}

function wfNoteField(node){
  const card=document.createElement("div"); card.className="wf-insp-card";
  card.appendChild(wfInspHdr("edit","Ghi chú"));
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-insp-input";
  inp.placeholder="ghi chú cho node này…"; inp.value=node.note||"";
  inp.oninput=()=>{ node.note=inp.value; wfUpdNodeNote(node); };
  card.appendChild(inp);
  return card;
}
function wfUpdNodeNote(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  let n=el.querySelector(".wf-node-note");
  if(node.note){
    if(!n){ n=document.createElement("div"); n.className="wf-node-note"; el.appendChild(n); el.classList.remove("collapsed"); }
    n.innerHTML=wfIco("edit")+`<span>${escHtml(node.note)}</span>`;
  } else if(n){ n.remove(); }
}

function wfLogField(node){
  const card=document.createElement("div"); card.className="wf-insp-card";
  card.appendChild(wfInspHdr("log","Log khi chạy"));
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-insp-input";
  inp.placeholder="tự ghi log mỗi lần chạy node…"; inp.value=node.log||"";
  inp.oninput=()=>{ node.log=inp.value; wfUpdNodeLog(node); };
  card.appendChild(inp);
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.innerHTML='Có thể chèn biến: <code style="background:var(--alt);padding:1px 4px;border-radius:4px;">{tên_biến}</code>';
  card.appendChild(hint);
  return card;
}
function wfUpdNodeLog(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  let n=el.querySelector(".wf-node-log");
  if(node.log){
    if(!n){ n=document.createElement("div"); n.className="wf-node-log";
      const note=el.querySelector(".wf-node-note"), thumb=el.querySelector(".wf-node-thumb");
      if(thumb) el.insertBefore(n, thumb); else el.appendChild(n);
      el.classList.remove("collapsed"); }
    n.textContent=node.log;
  } else if(n){ n.remove(); }
}

function wfActField(label,t,val,onset){
  const row=document.createElement("div"); row.className="wf-field";
  const l=document.createElement("label"); l.textContent=label; row.appendChild(l);
  const inp=document.createElement("input"); inp.type=t==="num"?"number":"text"; inp.value=val;
  inp.oninput=()=>onset(inp.value); row.appendChild(inp); return row;
}

// Per-activity variables.
function wfVarsSection(act){
  if(!act.vars) act.vars=[];
  const wrap=document.createElement("div");
  wrap.appendChild(wfInspHdr("pin","Biến hoạt động", String(act.vars.length)));
  act.vars.forEach((v,idx)=>wrap.appendChild(wfVarRow(act,v,idx)));
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Biến"; add.style.marginTop="4px";
  add.onclick=()=>{ const n=act.vars.length+1; act.vars.push({name:"var"+n, label:"Setting "+n, type:"bool", value:false}); wfRenderInspector(); };
  wrap.appendChild(add);
  return wrap;
}
function wfVarRow(act,v,idx){
  const card=document.createElement("div"); card.className="wf-var-card";
  // Line 1: drag-chip + title + delete.
  const r1=document.createElement("div"); r1.className="wf-var-row";
  const chip=document.createElement("span"); chip.className="wf-var-chip"; chip.draggable=true;
  chip.textContent="🔖"; chip.title="Kéo vào canvas để tạo node kiểm tra";
  chip.addEventListener("dragstart",e=>{ wfPaletteDrag="var:"+(v.type||"bool")+":"+(v.name||""); e.dataTransfer.effectAllowed="copy"; try{e.dataTransfer.setData("text/plain",v.name||"");}catch{} });
  chip.addEventListener("dragend",()=>{ wfPaletteDrag=null; });
  r1.appendChild(chip);
  const lbl=document.createElement("input"); lbl.type="text"; lbl.value=v.label||""; lbl.placeholder="Tiêu đề (hiện trong settings)"; lbl.style.cssText="flex:1;min-width:0;font-weight:600;";
  lbl.oninput=()=>{ v.label=lbl.value; };
  r1.appendChild(lbl);
  const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Xoá biến";
  del.onclick=()=>{ act.vars.splice(idx,1); wfRenderInspector(); };
  r1.appendChild(del);
  // Line 2: name + type + default value.
  const r2=document.createElement("div"); r2.className="wf-var-row";
  const nm=document.createElement("input"); nm.type="text"; nm.value=v.name||""; nm.placeholder="biến (vd isClaim)"; nm.style.cssText="flex:1;min-width:0;font-size:10.5px;font-family:var(--mono);";
  nm.oninput=()=>{ v.name=nm.value; };
  r2.appendChild(nm);
  const ty=document.createElement("select");
  [["bool","bool"],["number","số"],["text","chữ"],["select","chọn"]].forEach(([val,lab])=>{ const o=document.createElement("option"); o.value=val; o.textContent=lab; if((v.type||"bool")===val)o.selected=true; ty.appendChild(o); });
  ty.onchange=()=>{
    v.type=ty.value;
    if(ty.value==="select"){ if(!v.options||!v.options.length) v.options=["A","B"]; v.value=v.options[0]; }
    else v.value = ty.value==="bool"?false : ty.value==="number"?0 : "";
    wfRenderInspector();
  };
  r2.appendChild(ty);
  r2.appendChild(wfVarValue(v));
  card.appendChild(r1); card.appendChild(r2);
  // Line 3 (select only): options.
  if(v.type==="select"){
    const r3=document.createElement("div"); r3.className="wf-var-row";
    const opt=document.createElement("input"); opt.type="text"; opt.placeholder="lựa chọn: A, B, C"; opt.value=(v.options||[]).join(", ");
    opt.style.cssText="flex:1;min-width:0;font-size:10.5px;";
    opt.onchange=()=>{ v.options=opt.value.split(",").map(s=>s.trim()).filter(Boolean); if(!v.options.includes(v.value)) v.value=v.options[0]||""; wfRenderInspector(); };
    r3.appendChild(opt); card.appendChild(r3);
  }
  return card;
}
function wfVarValue(v){
  if((v.type||"bool")==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(v.value?" checked":""); cb.title="Giá trị mặc định";
    cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
    cb.onclick=()=>{ v.value=!v.value; cb.classList.toggle("checked",v.value); };
    return cb;
  }
  if(v.type==="select"){
    const sel=document.createElement("select"); sel.style.maxWidth="86px";
    (v.options||[]).forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; if(String(v.value)===String(o))op.selected=true; sel.appendChild(op); });
    sel.onchange=()=>{ v.value=sel.value; };
    return sel;
  }
  const inp=document.createElement("input"); inp.type=v.type==="number"?"number":"text";
  inp.value=v.value!==undefined&&v.value!==null?v.value:""; inp.style.width="58px";
  inp.oninput=()=>{ v.value = v.type==="number"?(parseFloat(inp.value)||0):inp.value; };
  return inp;
}

// ── Smart paste on coordinate fields ─────────────────────────────────────────
const WF_COORD_KEYS = ["x","y","w","h"];
function wfAttachCoordPaste(node, f, inp){
  if(f.t!=="num" || !WF_COORD_KEYS.includes(f.k)) return;
  inp.addEventListener("paste", e=>{
    const txt=(e.clipboardData||{}).getData("text") || "";
    const m=txt.match(/^\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)\s*(?:[, ]+\s*(-?\d+(?:\.\d+)?)\s*(?:[, ]+\s*(-?\d+(?:\.\d+)?)\s*)?)?\)?\s*$/);
    if(!m) return;
    e.preventDefault();
    const nums=[m[1],m[2],m[3],m[4]].filter(v=>v!==undefined).map(parseFloat);
    const def=WF_NODES[node.type];
    const have=new Set((def&&def.fields||[]).filter(ff=>ff.t==="num"&&WF_COORD_KEYS.includes(ff.k)).map(ff=>ff.k));
    nums.forEach((val,i)=>{ const key=WF_COORD_KEYS[i]; if(have.has(key)) node.params[key]=val; });
    wfUpdNodeSum(node);
    if(f.refresh) wfRenderCanvas();
    const body=$("wf-insp-body");
    if(body){
      WF_COORD_KEYS.forEach(key=>{
        if(!have.has(key)) return;
        const labEl=body.querySelector(`.wf-field > label[title="${key}"]`);
        const inpEl=labEl&&labEl.parentNode.querySelector("input");
        if(inpEl) inpEl.value=node.params[key];
      });
    }
  });
}

function wfFieldEl(node,f){
  // Region is a special block (already styled as a panel).
  if(f.t==="region") return wfRegionField(node,f);

  const row=document.createElement("div"); row.className="wf-field";
  const lab=document.createElement("label"); lab.textContent=f.lbl||f.k; lab.title=f.k; row.appendChild(lab);

  if(f.t==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(node.params[f.k]?" checked":"");
    cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
    cb.onclick=()=>{ node.params[f.k]=!node.params[f.k]; cb.classList.toggle("checked",node.params[f.k]); wfUpdNodeSum(node); };
    row.appendChild(cb); return row;
  }
  if(f.t==="select"){
    const sel=document.createElement("select");
    (f.opts||[]).forEach(o=>{ const v=(o&&o.v!==undefined)?o.v:o, t=(o&&o.t!==undefined)?o.t:o;
      const op=document.createElement("option"); op.value=v; op.textContent=t; if(node.params[f.k]===v)op.selected=true; sel.appendChild(op); });
    sel.onchange=()=>{ node.params[f.k]=sel.value; wfUpdNodeSum(node); };
    row.appendChild(sel); return row;
  }
  if(f.t==="tpls") return wfTplsField(node,f,row);

  // Variable-picker text field backed by datalist.
  if(f.var && f.t!=="num"){
    const names=wfAllVarNames();
    const inp=document.createElement("input"); inp.type="text";
    inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
    inp.setAttribute("list","wf-varlist");
    inp.oninput=()=>{ node.params[f.k]=inp.value; wfUpdNodeSum(node); wfRenderVarsPanel(); };
    row.appendChild(inp);
    if(names.length){
      let dl=document.getElementById("wf-varlist");
      if(!dl){ dl=document.createElement("datalist"); dl.id="wf-varlist"; document.body.appendChild(dl); }
      dl.innerHTML=""; names.forEach(n=>{ const o=document.createElement("option"); o.value=n; dl.appendChild(o); });
    }
    return row;
  }

  const inp=document.createElement("input");
  inp.type=f.t==="num"?"number":"text"; if(f.t==="num"&&f.step) inp.step=f.step;
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.oninput=()=>{ node.params[f.k]= f.t==="num"?(parseFloat(inp.value)||0):inp.value; wfUpdNodeSum(node); if(f.refresh) wfRenderCanvas(); };
  wfAttachCoordPaste(node, f, inp);
  row.appendChild(inp);

  if(f.t==="tpl"){
    inp.style.fontSize="10px";
    const btn=document.createElement("button"); btn.className="btn sm"; btn.textContent="Chọn…";
    row.appendChild(btn);
    const wrap=document.createElement("div"); wrap.appendChild(row);
    const img=document.createElement("img"); img.className="wf-tpl-preview"; wrap.appendChild(img);
    wfLoadThumb(img, node.params[f.k]);
      const refresh=v=>{ node.params[f.k]=v; wfUpdNodeSum(node); wfLoadThumb(img,v); wfUpdNodePreview(node); wfRenderCanvas(); };
    inp.oninput=()=>refresh(inp.value);
    btn.onclick=async()=>{ const p=await api().pick_template(); if(p){ inp.value=p; refresh(p); } };
    return wrap;
  }
  return row;
}

function wfTplsField(node,f,row){
  const arr=()=> Array.isArray(node.params[f.k])?node.params[f.k]:(node.params[f.k]=[]);
  const list=document.createElement("div"); list.className="wf-tpls-list";
  function renderList(){
    list.innerHTML="";
    arr().forEach((path,idx)=>{
      const item=document.createElement("div"); item.className="wf-tpls-item";
      const r=document.createElement("div"); r.className="wf-tpls-hdr";
      const num=document.createElement("span"); num.className="num"; num.textContent=(idx+1)+".";
      const inp=document.createElement("input"); inp.type="text"; inp.value=path||"";
      const pick=document.createElement("button"); pick.className="btn sm"; pick.textContent="Chọn…";
      const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Xoá ảnh";
      const img=document.createElement("img"); img.className="wf-tpl-preview"; wfLoadThumb(img, path);
      const commit=v=>{ arr()[idx]=v; wfUpdNodeSum(node); wfUpdNodePreview(node); wfLoadThumb(img,v); wfRenderCanvas(); };
      inp.oninput=()=>commit(inp.value);
      pick.onclick=async()=>{ const pp=await api().pick_template(); if(pp){ inp.value=pp; commit(pp); } };
      del.onclick=()=>{ arr().splice(idx,1); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
      r.appendChild(num); r.appendChild(inp); r.appendChild(pick); r.appendChild(del);
      item.appendChild(r); item.appendChild(img); list.appendChild(item);
    });
    if(!arr().length){ const e=document.createElement("div"); e.className="wf-tpls-empty"; e.textContent="Chưa có ảnh — thêm ít nhất 2 để dùng \"hoặc\"."; list.appendChild(e); }
  }
  renderList();
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Ảnh";
  add.onclick=async()=>{ const pp=await api().pick_template(); arr().push(pp||""); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
  row.appendChild(list); row.appendChild(add);
  return row;
}

function wfRegionField(node,f){
  const wrap=document.createElement("div");
  wrap.style.cssText="display:flex;flex-direction:column;gap:5px;padding:5px 0;";
  const hdr=document.createElement("div"); hdr.className="wf-field"; hdr.style.margin="0";
  const lab=document.createElement("label"); lab.textContent="Vùng tìm"; lab.title="Giới hạn khớp ảnh trong 1 vùng màn hình (tuỳ chọn)"; hdr.appendChild(lab);
  const cb=document.createElement("span"); cb.className="cb";
  const enabled=()=> !!(node.params.regionX||node.params.regionY||node.params.regionW||node.params.regionH);
  cb.classList.toggle("checked", enabled());
  cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
  cb.style.cursor="pointer";
  hdr.appendChild(cb);
  const panel=document.createElement("div"); panel.className="wf-region-panel";
  const makeCell=(key,ph)=>{
    const i=document.createElement("input"); i.type="number"; i.min="0"; i.placeholder=ph;
    i.value=node.params[key]!==undefined?node.params[key]:"";
    i.oninput=()=>{ node.params[key]=parseFloat(i.value)||0; };
    return {input:i};
  };
  const x=makeCell("regionX","X"), y=makeCell("regionY","Y"),
        w=makeCell("regionW","W"), h=makeCell("regionH","H");
  const appendCell=(inp)=>{ const c=document.createElement("div"); c.className="wf-region-cell"; c.appendChild(inp); panel.appendChild(c); };
  appendCell(x.input); appendCell(y.input);
  appendCell(w.input); appendCell(h.input);
  const sync=()=>{ const on=enabled(); cb.classList.toggle("checked",on); panel.style.display=on?"":"none"; };
  sync();
  cb.onclick=()=>{
    if(enabled()){
      node.params.regionX=0; node.params.regionY=0; node.params.regionW=0; node.params.regionH=0;
      x.input.value=y.input.value=w.input.value=h.input.value="";
    } else {
      wfApplyRegionFromTplName(node, wfTemplatePathForRegion(node));
      if(!node.params.regionW) node.params.regionW=540;
      if(!node.params.regionH) node.params.regionH=960;
      x.input.value=node.params.regionX||""; y.input.value=node.params.regionY||"";
      w.input.value=node.params.regionW; h.input.value=node.params.regionH;
    }
    sync();
  };
  wrap.appendChild(hdr); wrap.appendChild(panel);
  return wrap;
}

// Shared branch-count editor for dynamic branch blocks. Switch keeps detailed
// per-branch conditions; try_chain only needs numbered output ports.
function wfBranchCountEditor(node){
  return node.type==="switch" ? wfSwitchCasesEditor(node) : wfCountBranchesEditor(node);
}

function wfNormalizeCount(v, fallback, min=1){
  const n=parseInt(v,10);
  return Math.max(min, Number.isFinite(n)?n:fallback);
}

function wfBranchCountControl(label, count, onSet, onAdd, min=1){
  const row=document.createElement("div"); row.className="wf-field wf-branch-count";
  const lab=document.createElement("label"); lab.textContent=label; row.appendChild(lab);
  const inp=document.createElement("input"); inp.type="number"; inp.min=String(min); inp.step="1"; inp.value=count;
  inp.title="Nhập số nhánh để thêm/xoá nhanh";
  inp.onchange=()=>{ const n=wfNormalizeCount(inp.value, count, min); inp.value=n; onSet(n); };
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Nhánh"; add.title="Thêm một nhánh";
  add.onclick=()=>onAdd();
  row.appendChild(inp); row.appendChild(add);
  return row;
}

function wfSetTryChainCount(node, nextCount){
  const prev=wfNormalizeCount(node.params.count, 3);
  node.params.count=nextCount;
  if(nextCount<prev){
    const g=wfGraph();
    if(g) g.edges=(g.edges||[]).filter(e=>!(e.from===node.id && /^\d+$/.test(e.fromPort) && parseInt(e.fromPort,10)>nextCount));
  }
  wfUpdNodeSum(node); wfRenderCanvas();
}

function wfCountBranchesEditor(node){
  const wrap=document.createElement("div");
  const count=()=>wfNormalizeCount(node.params.count, 3);
  const render=()=>{ wrap.innerHTML="";
    wrap.appendChild(wfBranchCountControl("Số nhánh", count(), n=>{ wfSetTryChainCount(node,n); render(); }, ()=>{ wfSetTryChainCount(node,count()+1); render(); }));
    const hint=document.createElement("div"); hint.className="wf-insp-tip";
    hint.textContent="Chạy nhánh #1 trước; nếu fail thì thử #2…#n. Khi tất cả fail sẽ đi cổng 'fail'.";
    wrap.appendChild(hint);
  };
  render();
  return wrap;
}

// Switch case editor.
function wfSwitchCasesEditor(node){
  const wrap=document.createElement("div");
  const cases=()=> Array.isArray(node.params.cases)?node.params.cases:(node.params.cases=[]);
  const addCase=()=>cases().push({type:"if_image", params:wfDefaults("if_image")});
  const setCaseCount=n=>{
    const cs=cases();
    while(cs.length<n) addCase();
    while(cs.length>n) wfRemoveSwitchCase(node, cs.length-1);
    wfUpdNodeSum(node); wfRenderCanvas();
  };
  const list=document.createElement("div"); list.style.cssText="display:flex;flex-direction:column;gap:8px;";
  function render(){
    const countCtl=wrap.querySelector(".wf-branch-count input");
    if(countCtl) countCtl.value=cases().length;
    list.innerHTML="";
    cases().forEach((c,idx)=>{
      const item=document.createElement("div"); item.className="wf-case";
      const hd=document.createElement("div"); hd.className="wf-case-hdr";
      const num=document.createElement("span"); num.className="wf-case-num"; num.textContent="#"+(idx+1);
      const sel=document.createElement("select");
      WF_SWITCH_CASE_TYPES.forEach(t=>{ const op=document.createElement("option"); op.value=t;
        op.textContent=WF_NODES[t].label; if(c.type===t)op.selected=true; sel.appendChild(op); });
      sel.onchange=()=>{ c.type=sel.value; c.params=wfDefaults(sel.value); render(); wfUpdNodeSum(node); };
      const up=document.createElement("button"); up.className="btn sm ico"; up.innerHTML=wfIco("chevron_up"); up.title="Lên"; up.disabled=idx===0;
      up.onclick=()=>{ wfReorderSwitchCase(node, idx, idx-1); render(); wfRenderCanvas(); };
      const dn=document.createElement("button"); dn.className="btn sm ico"; dn.innerHTML=wfIco("chevron_dn"); dn.title="Xuống"; dn.disabled=idx===cases().length-1;
      dn.onclick=()=>{ wfReorderSwitchCase(node, idx, idx+1); render(); wfRenderCanvas(); };
      const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Xoá nhánh";
      del.onclick=()=>{ wfRemoveSwitchCase(node, idx); render(); wfRenderCanvas(); };
      hd.appendChild(num); hd.appendChild(sel); hd.appendChild(up); hd.appendChild(dn); hd.appendChild(del);
      item.appendChild(hd);
      const proxy={ id:node.id+"__c"+idx, type:c.type, params:c.params };
      (WF_NODES[c.type].fields||[]).forEach(f=> item.appendChild(wfFieldEl(proxy,f)));
      list.appendChild(item);
    });
    if(!cases().length){ const e=document.createElement("div"); e.className="wf-insp-tip"; e.textContent='Chưa có nhánh. Bấm "+ Nhánh" hoặc nhập số nhánh.'; list.appendChild(e); }
  }
  const countCtl=wfBranchCountControl("Số nhánh", cases().length, n=>{ setCaseCount(n); render(); }, ()=>{ addCase(); render(); wfRenderCanvas(); wfUpdNodeSum(node); }, 0);
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.textContent="Kiểm lần lượt từ trên xuống: đúng nhánh nào đi cổng đó (#1..#n), không khớp đi cổng 'khác'.";
  wrap.appendChild(countCtl); wrap.appendChild(list); wrap.appendChild(hint);
  render();
  return wrap;
}

function wfUpdNodeSum(node){
  const def=WF_NODES[node.type]; if(!def||!def.sum) return;
  const el=document.querySelector(`.wf-node[data-node="${node.id}"] .wf-node-sum`);
  let s=""; try{ s=def.sum(node.params); }catch{}
  if(el) el.textContent=s;
}

// Image-template helpers.
function wfTplField(type){ const def=WF_NODES[type]; return def&&(def.fields||[]).find(f=>f.t==="tpl"||f.t==="tpls"); }
function wfTplOf(node){ const f=wfTplField(node.type); if(!f) return ""; const v=node.params[f.k];
  return Array.isArray(v)?(v.find(Boolean)||""):(v||""); }
function wfUpdNodePreview(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`);
  if(!el) return;
  const strip=el.querySelector(".wf-node-thumbs");
  if(strip){
    const f=wfTplField(node.type);
    const arr=Array.isArray(node.params[f.k])?node.params[f.k].filter(p=>String(p||"").trim()):[];
    strip.innerHTML="";
    if(!arr.length){ const e=document.createElement("span"); e.className="wf-tpl-empty"; e.textContent="(chưa có ảnh)"; strip.appendChild(e); return; }
    arr.forEach(p=>{ const im=document.createElement("img"); im.className="wf-node-thumb-sm"; strip.appendChild(im); wfLoadThumb(im,p); });
    return;
  }
  const img=el.querySelector(".wf-node-thumb");
  if(img) wfLoadThumb(img, wfTplOf(node));
}
