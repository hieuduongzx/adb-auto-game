// ── Inspector ──────────────────────────────────────────────────────────────
function wfRenderInspector(){
  const body=$("wf-insp-body"); body.innerHTML="";
  wfRenderVarsPanel();   // the vars list depends on the current activity
  // Multi-selection: show count, node list, alignment tools, and bulk actions.
  if(WF.sel.length>1){
    const g=wfGraph();
    const selNodes=g?WF.sel.map(id=>g.nodes.find(n=>n.id===id)).filter(Boolean):[];
    // Header
    const h=document.createElement("div"); h.className="wf-insp-sec";
    h.textContent=`${WF.sel.length} block được chọn`; body.appendChild(h);
    // Selected node name list (truncated at 6)
    const list=document.createElement("div"); list.style.cssText="display:flex;flex-direction:column;gap:2px;margin:4px 0 8px;";
    selNodes.slice(0,6).forEach(n=>{ const def=WF_NODES[n.type]||{}; const row=document.createElement("div"); row.style.cssText="font-size:11px;color:var(--muted);padding:1px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"; row.textContent=(def.label||n.type)+(n.label?` · ${n.label}`:""); list.appendChild(row); });
    if(selNodes.length>6){ const more=document.createElement("div"); more.style.cssText="font-size:10px;color:var(--muted);padding:1px 4px;"; more.textContent=`+${selNodes.length-6} nữa…`; list.appendChild(more); }
    body.appendChild(list);
    // Align buttons
    const alignSec=document.createElement("div"); alignSec.className="wf-insp-sec"; alignSec.textContent="Căn chỉnh"; body.appendChild(alignSec);
    const alignRow=document.createElement("div"); alignRow.style.cssText="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;";
    const mkAlign=(lbl,fn)=>{ const b=document.createElement("button"); b.className="btn sm"; b.textContent=lbl; b.title=lbl; b.onclick=fn; return b; };
    alignRow.appendChild(mkAlign("← Trái", ()=>{ if(!g||!selNodes.length) return; const minX=Math.min(...selNodes.map(n=>n.x)); selNodes.forEach(n=>n.x=minX); wfRenderCanvas(); }));
    alignRow.appendChild(mkAlign("→ Phải",()=>{ if(!g||!selNodes.length) return; const maxX=Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.x+(el?el.offsetWidth:158); })); selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.x=maxX-(el?el.offsetWidth:158); }); wfRenderCanvas(); }));
    alignRow.appendChild(mkAlign("↑ Trên", ()=>{ if(!g||!selNodes.length) return; const minY=Math.min(...selNodes.map(n=>n.y)); selNodes.forEach(n=>n.y=minY); wfRenderCanvas(); }));
    alignRow.appendChild(mkAlign("↓ Dưới",()=>{ if(!g||!selNodes.length) return; const maxY=Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.y+(el?el.offsetHeight:46); })); selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.y=maxY-(el?el.offsetHeight:46); }); wfRenderCanvas(); }));
    alignRow.appendChild(mkAlign("↔ Giữa X",()=>{ if(!g||!selNodes.length) return; const cx=(Math.min(...selNodes.map(n=>n.x))+Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.x+(el?el.offsetWidth:158); })))/2; selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.x=cx-(el?el.offsetWidth:158)/2; }); wfRenderCanvas(); }));
    alignRow.appendChild(mkAlign("↕ Giữa Y",()=>{ if(!g||!selNodes.length) return; const cy=(Math.min(...selNodes.map(n=>n.y))+Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.y+(el?el.offsetHeight:46); })))/2; selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.y=cy-(el?el.offsetHeight:46)/2; }); wfRenderCanvas(); }));
    body.appendChild(alignRow);
    // Bulk actions
    const actSec=document.createElement("div"); actSec.className="wf-insp-sec"; actSec.textContent="Thao tác"; body.appendChild(actSec);
    const actRow=document.createElement("div"); actRow.style.cssText="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px;";
    const dupBtn=document.createElement("button"); dupBtn.className="btn sm"; dupBtn.textContent="Nhân bản (Ctrl+D)"; dupBtn.onclick=()=>wfDuplicate(); actRow.appendChild(dupBtn);
    const grpBtn=document.createElement("button"); grpBtn.className="btn sm"; grpBtn.textContent="Tạo nhóm"; grpBtn.onclick=()=>wfGroupSelection(); actRow.appendChild(grpBtn);
    const delBtn=document.createElement("button"); delBtn.className="btn sm err"; delBtn.textContent="Xoá (Delete)"; delBtn.onclick=()=>wfDeleteSelected(); actRow.appendChild(delBtn);
    body.appendChild(actRow);
    const tip=document.createElement("div"); tip.className="wf-insp-empty"; tip.textContent="Ctrl+click / Shift+click để thêm/bớt chọn. Phím ← → ↑ ↓ để di chuyển (Shift+mũi tên = 10px)."; body.appendChild(tip);
    return;
  }
  const node=wfNode(WF.selectedNode), act=wfCurAct(), fn=wfCurFn();
  if(node){
    const def=WF_NODES[node.type]||{label:node.type,fields:[]};
    const h=document.createElement("div"); h.className="wf-insp-sec"; h.innerHTML=`<span class="ico" style="width:15px;height:15px;display:inline-flex;vertical-align:middle">${wfIco(def.ico)}</span> ${def.label}`; body.appendChild(h);
    if(node.type==="call"){ body.appendChild(wfCallPicker(node)); }
    else if(node.type==="switch"){ body.appendChild(wfSwitchCasesEditor(node)); }
    else {
      if(!(def.fields||[]).length){ const d=document.createElement("div"); d.className="wf-insp-empty"; d.textContent="Node này không có tham số."; body.appendChild(d); }
      (def.fields||[]).forEach(f=>body.appendChild(wfFieldEl(node,f)));
    }
    // A free-text note for any node (the standalone "note" node carries its own text).
    if(node.type!=="note") body.appendChild(wfNoteField(node));
    // A runtime log line: auto-emitted to the log panel every time this block runs.
    // 'start' never executes, and the "note" node isn't run, so skip both.
    if(node.type!=="note" && node.type!=="start") body.appendChild(wfLogField(node));
    return;
  }
  if(fn){
    const h=document.createElement("div"); h.className="wf-insp-sec"; h.textContent="ƒ Function"; body.appendChild(h);
    body.appendChild(wfActField("Tên","text",fn.name,v=>{ fn.name=v; wfRenderFunctions(); wfRenderPalette(); $("wf-cur-act").textContent="ƒ "+v; }));
    const tip=document.createElement("div"); tip.className="wf-insp-empty"; tip.textContent="Xếp node cho function này. Nó dùng được như một node trong mọi hoạt động (kéo từ mục Function)."; body.appendChild(tip);
    return;
  }
  if(act){
    const h=document.createElement("div"); h.className="wf-insp-sec"; h.textContent=act.type==="background"?"Hoạt động nền":"Hoạt động tuần tự"; body.appendChild(h);
    body.appendChild(wfActField("Tên","text",act.name,v=>{ act.name=v; wfRenderActivities(); $("wf-cur-act").textContent=v; }));
    if(act.type==="background") body.appendChild(wfActField("Chu kỳ (s)","num",act.pollInterval,v=>act.pollInterval=parseFloat(v)||1));
    else body.appendChild(wfActField("Số lần thử","num",act.maxRetries,v=>act.maxRetries=parseInt(v)||1));
    body.appendChild(wfVarsSection(act));
    const tip=document.createElement("div"); tip.className="wf-insp-empty"; tip.textContent="Bấm một node trên canvas để sửa tham số của nó."; body.appendChild(tip);
    return;
  }
  body.innerHTML='<div class="wf-insp-empty">Chưa chọn hoạt động.</div>';
}
function wfCallPicker(node){
  const row=document.createElement("div"); row.className="wf-field";
  const l=document.createElement("label"); l.textContent="function"; row.appendChild(l);
  const sel=document.createElement("select"); sel.style.flex="1"; sel.style.minWidth="0";
  if(!WF.functions.length){ const o=document.createElement("option"); o.value=""; o.textContent="(chưa có function)"; sel.appendChild(o); }
  WF.functions.forEach(fn=>{ const o=document.createElement("option"); o.value=fn.id; o.textContent=fn.name; if(fn.id===node.params.fn)o.selected=true; sel.appendChild(o); });
  sel.onchange=()=>{ node.params.fn=sel.value; wfRenderCanvas(); };
  row.appendChild(sel); return row;
}
function wfNoteField(node){
  const wrap=document.createElement("div");
  const sec=document.createElement("div"); sec.className="wf-insp-sec"; sec.textContent="Ghi chú"; sec.style.marginTop="8px"; wrap.appendChild(sec);
  const inp=document.createElement("input"); inp.type="text"; inp.placeholder="ghi chú cho node này…"; inp.value=node.note||"";
  inp.style.width="100%";
  inp.oninput=()=>{ node.note=inp.value; wfUpdNodeNote(node); };
  wrap.appendChild(inp); return wrap;
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
  const wrap=document.createElement("div");
  const sec=document.createElement("div"); sec.className="wf-insp-sec"; sec.textContent="Log khi chạy"; sec.style.marginTop="8px"; wrap.appendChild(sec);
  const inp=document.createElement("input"); inp.type="text"; inp.placeholder="tự ghi log mỗi lần chạy node…"; inp.value=node.log||"";
  inp.style.width="100%";
  inp.oninput=()=>{ node.log=inp.value; wfUpdNodeLog(node); };
  wrap.appendChild(inp);
  const hint=document.createElement("div"); hint.className="wf-insp-empty"; hint.style.padding="2px 0 0";
  hint.innerHTML='Có thể chèn biến: <code>{tên_biến}</code>';
  wrap.appendChild(hint);
  return wrap;
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
// Per-activity variables (e.g. a bool "isClaim"). Each is seeded into the
// engine at activity start; drag a var's chip onto the canvas to make a check.
function wfVarsSection(act){
  if(!act.vars) act.vars=[];
  const wrap=document.createElement("div");
  const sec=document.createElement("div"); sec.className="wf-insp-sec"; sec.style.marginTop="8px";
  sec.innerHTML=`Biến <span style="font-weight:400;text-transform:none;letter-spacing:0;color:var(--muted)">(kéo vào canvas để kiểm tra)</span>`;
  wrap.appendChild(sec);
  act.vars.forEach((v,idx)=>wrap.appendChild(wfVarRow(act,v,idx)));
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Biến"; add.style.marginTop="4px";
  add.onclick=()=>{ const n=act.vars.length+1; act.vars.push({name:"var"+n, label:"Setting "+n, type:"bool", value:false}); wfRenderInspector(); };
  wrap.appendChild(add);
  return wrap;
}
function wfVarRow(act,v,idx){
  const card=document.createElement("div"); card.className="wf-var-card";
  // Line 1: drag-chip + title (display label) + delete.
  const r1=document.createElement("div"); r1.className="wf-var-row";
  const chip=document.createElement("span"); chip.className="wf-var-chip"; chip.draggable=true;
  chip.textContent="🔖"; chip.title="Kéo vào canvas để tạo node kiểm tra";
  chip.addEventListener("dragstart",e=>{ wfPaletteDrag="var:"+(v.type||"bool")+":"+(v.name||""); e.dataTransfer.effectAllowed="copy"; try{e.dataTransfer.setData("text/plain",v.name||"");}catch{} });
  chip.addEventListener("dragend",()=>{ wfPaletteDrag=null; });
  r1.appendChild(chip);
  const lbl=document.createElement("input"); lbl.type="text"; lbl.value=v.label||""; lbl.placeholder="Tiêu đề (hiện trong settings)"; lbl.style.flex="1"; lbl.style.minWidth="0"; lbl.style.fontWeight="600";
  lbl.oninput=()=>{ v.label=lbl.value; };
  r1.appendChild(lbl);
  const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Xoá biến";
  del.onclick=()=>{ act.vars.splice(idx,1); wfRenderInspector(); };
  r1.appendChild(del);
  // Line 2: variable name (key) + type + default value.
  const r2=document.createElement("div"); r2.className="wf-var-row";
  const nm=document.createElement("input"); nm.type="text"; nm.value=v.name||""; nm.placeholder="biến (vd isClaim)"; nm.style.flex="1"; nm.style.minWidth="0"; nm.style.fontSize="10.5px"; nm.style.fontFamily="var(--mono)";
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
  // Line 3 (select only): editable comma-separated option list.
  if(v.type==="select"){
    const r3=document.createElement("div"); r3.className="wf-var-row";
    const opt=document.createElement("input"); opt.type="text"; opt.placeholder="lựa chọn: A, B, C"; opt.value=(v.options||[]).join(", ");
    opt.style.flex="1"; opt.style.minWidth="0"; opt.style.fontSize="10.5px";
    opt.onchange=()=>{ v.options=opt.value.split(",").map(s=>s.trim()).filter(Boolean); if(!v.options.includes(v.value)) v.value=v.options[0]||""; wfRenderInspector(); };
    const l=document.createElement("label"); l.textContent="opts"; l.style.fontSize="10px"; l.style.color="var(--muted)"; l.style.flexShrink="0";
    r3.appendChild(l); r3.appendChild(opt); card.appendChild(r3);
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
// When the user pastes into an x/y/w/h input, detect a tuple on the clipboard
// ("548, 1536" or "(327, 887, 394, 234)") and distribute the numbers across the
// node's sibling fields in [x,y,w,h] order — so pasting a region fills all four
// boxes at once. Only fires for number fields whose key is a coordinate.
const WF_COORD_KEYS = ["x","y","w","h"];
function wfAttachCoordPaste(node, f, inp){
  if(f.t!=="num" || !WF_COORD_KEYS.includes(f.k)) return;
  inp.addEventListener("paste", e=>{
    const txt=(e.clipboardData||{}).getData("text") || "";
    // Match 2-4 comma/space separated numbers, optionally wrapped in parens.
    const m=txt.match(/^\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)\s*(?:[, ]+\s*(-?\d+(?:\.\d+)?)\s*(?:[, ]+\s*(-?\d+(?:\.\d+)?)\s*)?)?\)?\s*$/);
    if(!m) return;   // single number or non-numeric → let the native paste happen
    e.preventDefault();
    const nums=[m[1],m[2],m[3],m[4]].filter(v=>v!==undefined).map(parseFloat);
    // Map numbers to coordinate keys by canonical order, only setting fields the
    // node actually has (a tap node has x,y; an OCR node has x,y,w,h).
    const def=WF_NODES[node.type];
    const have=new Set((def&&def.fields||[]).filter(ff=>ff.t==="num"&&WF_COORD_KEYS.includes(ff.k)).map(ff=>ff.k));
    nums.forEach((val,i)=>{ const key=WF_COORD_KEYS[i]; if(have.has(key)) node.params[key]=val; });
    wfUpdNodeSum(node);
    if(f.refresh) wfRenderCanvas();
    // Refresh the visible inputs in the inspector so the pasted values show.
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
  const row=document.createElement("div"); row.className="wf-field";
  const lab=document.createElement("label"); lab.textContent=f.lbl||f.k; lab.title=f.k; row.appendChild(lab);
  if(f.t==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(node.params[f.k]?" checked":"");
    cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
    cb.onclick=()=>{ node.params[f.k]=!node.params[f.k]; cb.classList.toggle("checked",node.params[f.k]); wfUpdNodeSum(node); };
    row.appendChild(cb); return row;
  }
  if(f.t==="select"){
    const sel=document.createElement("select"); sel.style.flex="1"; sel.style.minWidth="0";
    (f.opts||[]).forEach(o=>{ const v=(o&&o.v!==undefined)?o.v:o, t=(o&&o.t!==undefined)?o.t:o;
      const op=document.createElement("option"); op.value=v; op.textContent=t; if(node.params[f.k]===v)op.selected=true; sel.appendChild(op); });
    sel.onchange=()=>{ node.params[f.k]=sel.value; wfUpdNodeSum(node); };
    row.appendChild(sel); return row;
  }
  if(f.t==="region"){
    // Optional search-region crop (regionX/Y/W/H). A single bordered panel
    // contains a title row on top and a 2×2 grid of inputs underneath.
    // W=0/H=0 means "no restriction" (engine treats it as full-screen).
    const wrap=document.createElement("div");
    wrap.style.cssText="display:flex;flex-direction:column;gap:5px;padding:5px 0;";
    // Title row: label + checkbox toggle.
    const hdr=document.createElement("div"); hdr.className="wf-field"; hdr.style.margin="0";
    const lab=document.createElement("label"); lab.textContent="Vùng tìm"; lab.title="Giới hạn khớp ảnh trong 1 vùng màn hình (tuỳ chọn)"; hdr.appendChild(lab);
    const cb=document.createElement("span"); cb.className="cb";
    const enabled=()=> !!(node.params.regionX||node.params.regionY||node.params.regionW||node.params.regionH);
    cb.classList.toggle("checked", enabled());
    cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
    cb.style.cursor="pointer";
    hdr.appendChild(cb);
    // Single panel wrapping the 2×2 inputs.
    const panel=document.createElement("div"); panel.className="wf-region-panel";
    const makeCell=(key,ph)=>{
      const i=document.createElement("input"); i.type="number"; i.min="0"; i.placeholder=ph;
      i.value=node.params[key]!==undefined?node.params[key]:"";
      i.oninput=()=>{ node.params[key]=parseFloat(i.value)||0; };
      return {input:i};
    };
    const x=makeCell("regionX","X"), y=makeCell("regionY","Y"),
          w=makeCell("regionW","W"), h=makeCell("regionH","H");
    panel.appendChild(x.input); panel.appendChild(y.input);
    panel.appendChild(w.input); panel.appendChild(h.input);
    const sync=()=>{ const on=enabled(); cb.classList.toggle("checked",on); panel.style.display=on?"":"none"; };
    sync();
    cb.onclick=()=>{
      if(enabled()){ // turning off → clear
        node.params.regionX=0; node.params.regionY=0; node.params.regionW=0; node.params.regionH=0;
        x.value=y.value=w.value=h.value="";
      } else {                       // turning on → seed with a sensible default region
        if(!node.params.regionW) node.params.regionW=540;
        if(!node.params.regionH) node.params.regionH=960;
        w.value=node.params.regionW; h.value=node.params.regionH;
      }
      sync();
    };
    wrap.appendChild(hdr); wrap.appendChild(panel);
    return wrap;
  }
  if(f.t==="tpls"){
    // A vertical list of templates (OR-set): each row = path + pick + remove + thumb.
    row.style.flexDirection="column"; row.style.alignItems="stretch"; row.style.gap="5px";
    const arr=()=> Array.isArray(node.params[f.k])?node.params[f.k]:(node.params[f.k]=[]);
    const list=document.createElement("div"); list.style.display="flex"; list.style.flexDirection="column"; list.style.gap="6px";
    function renderList(){
      list.innerHTML="";
      arr().forEach((path,idx)=>{
        const item=document.createElement("div");
        item.style.cssText="border:1px solid var(--border2);border-radius:6px;padding:5px;display:flex;flex-direction:column;gap:4px;";
        const r=document.createElement("div"); r.style.cssText="display:flex;align-items:center;gap:4px;";
        const num=document.createElement("span"); num.textContent=(idx+1)+"."; num.style.cssText="font-size:10px;color:var(--muted);flex-shrink:0;";
        const inp=document.createElement("input"); inp.type="text"; inp.value=path||""; inp.style.cssText="flex:1;min-width:0;font-size:10px;";
        const pick=document.createElement("button"); pick.className="btn sm"; pick.textContent="Chọn…";
        const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Xoá ảnh";
        const img=document.createElement("img"); img.className="wf-tpl-preview"; wfLoadThumb(img, path);
        const commit=v=>{ arr()[idx]=v; wfUpdNodeSum(node); wfUpdNodePreview(node); wfLoadThumb(img,v); };
        inp.oninput=()=>commit(inp.value);
        pick.onclick=async()=>{ const pp=await api().pick_template(); if(pp){ inp.value=pp; commit(pp); } };
        del.onclick=()=>{ arr().splice(idx,1); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); };
        r.appendChild(num); r.appendChild(inp); r.appendChild(pick); r.appendChild(del);
        item.appendChild(r); item.appendChild(img); list.appendChild(item);
      });
      if(!arr().length){ const e=document.createElement("div"); e.className="wf-tpl-empty"; e.textContent="Chưa có ảnh — thêm ít nhất 2 để dùng \"hoặc\"."; list.appendChild(e); }
    }
    renderList();
    const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Ảnh";
    add.onclick=async()=>{ const pp=await api().pick_template(); arr().push(pp||""); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); };
    row.appendChild(list); row.appendChild(add);
    return row;
  }
  // Variable-picker field: a text input backed by a <datalist> of every
  // variable declared anywhere in the flow, so the user can pick an existing
  // var from a dropdown OR type a new name. Falls through to the plain input
  // when no vars exist yet.
  if(f.var && f.t!=="num"){
    const names=wfAllVarNames();
    const inp=document.createElement("input"); inp.type="text";
    inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
    inp.setAttribute("list","wf-varlist"); inp.style.flex="1"; inp.style.minWidth="0";
    inp.oninput=()=>{ node.params[f.k]=inp.value; wfUpdNodeSum(node); wfRenderVarsPanel(); };
    row.appendChild(inp);
    if(names.length){
      let dl=document.getElementById("wf-varlist");
      if(!dl){ dl=document.createElement("datalist"); dl.id="wf-varlist"; document.body.appendChild(dl); }
      // Rebuild each render so newly-declared vars appear.
      dl.innerHTML=""; names.forEach(n=>{ const o=document.createElement("option"); o.value=n; dl.appendChild(o); });
    }
    return row;
  }
  const inp=document.createElement("input");
  inp.type=f.t==="num"?"number":"text"; if(f.t==="num"&&f.step) inp.step=f.step;
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.oninput=()=>{ node.params[f.k]= f.t==="num"?(parseFloat(inp.value)||0):inp.value; wfUpdNodeSum(node); if(f.refresh) wfRenderCanvas(); };
  // Smart paste on coordinate fields (x/y/w/h): if the clipboard holds a tuple
  // like "548, 1536" or "(327, 887, 394, 234)", split it across the sibling
  // fields in canonical order [x,y,w,h] so pasting a region fills all four at
  // once instead of dumping garbage into one box.
  wfAttachCoordPaste(node, f, inp);
  row.appendChild(inp);
  if(f.t==="tpl"){
    inp.style.fontSize="10px";
    const btn=document.createElement("button"); btn.className="btn sm"; btn.textContent="Chọn…";
    row.appendChild(btn);
    // Wrap the row + a live preview thumbnail of the chosen image.
    const wrap=document.createElement("div"); wrap.appendChild(row);
    const img=document.createElement("img"); img.className="wf-tpl-preview"; wrap.appendChild(img);
    wfLoadThumb(img, node.params[f.k]);
    const refresh=v=>{ node.params[f.k]=v; wfUpdNodeSum(node); wfLoadThumb(img,v); wfUpdNodePreview(node); };
    inp.oninput=()=>refresh(inp.value);
    btn.onclick=async()=>{ const p=await api().pick_template(); if(p){ inp.value=p; refresh(p); } };
    return wrap;
  }
  return row;
}
// Editor for the "Rẽ nhánh" (switch) node: a list of cases, each a condition of a
// chosen type whose own fields are edited (reusing wfFieldEl via a throwaway proxy
// so its DOM-refresh helpers no-op on the switch node). Add/remove/reorder go
// through the edge-remap helpers so wires stay attached to the right case.
function wfSwitchCasesEditor(node){
  const wrap=document.createElement("div");
  const cases=()=> Array.isArray(node.params.cases)?node.params.cases:(node.params.cases=[]);
  const list=document.createElement("div"); list.style.cssText="display:flex;flex-direction:column;gap:8px;";
  function render(){
    list.innerHTML="";
    cases().forEach((c,idx)=>{
      const item=document.createElement("div");
      item.style.cssText="border:1px solid var(--border2);border-radius:7px;padding:6px;display:flex;flex-direction:column;gap:5px;";
      const hd=document.createElement("div"); hd.style.cssText="display:flex;align-items:center;gap:4px;";
      const num=document.createElement("span"); num.textContent="#"+(idx+1);
      num.style.cssText="font-size:10.5px;font-weight:700;color:var(--accent);flex-shrink:0;";
      const sel=document.createElement("select"); sel.style.cssText="flex:1;min-width:0;font-size:11px;";
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
      // Render the chosen condition's fields, edited against c.params. The proxy id
      // doesn't match any DOM node, so wfFieldEl's wfUpdNodeSum/Preview no-op safely.
      const proxy={ id:node.id+"__c"+idx, type:c.type, params:c.params };
      (WF_NODES[c.type].fields||[]).forEach(f=> item.appendChild(wfFieldEl(proxy,f)));
      list.appendChild(item);
    });
    if(!cases().length){ const e=document.createElement("div"); e.className="wf-insp-empty"; e.textContent='Chưa có nhánh. Bấm "+ Nhánh".'; list.appendChild(e); }
  }
  render();
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Nhánh";
  add.onclick=()=>{ cases().push({type:"if_image", params:wfDefaults("if_image")}); render(); wfRenderCanvas(); wfUpdNodeSum(node); };
  const hint=document.createElement("div"); hint.className="wf-insp-empty"; hint.style.marginTop="2px";
  hint.textContent="Kiểm lần lượt từ trên xuống: đúng nhánh nào đi cổng đó (#1..#n), không khớp đi cổng 'khác'.";
  wrap.appendChild(list); wrap.appendChild(add); wrap.appendChild(hint);
  return wrap;
}
function wfUpdNodeSum(node){
  const def=WF_NODES[node.type]; if(!def||!def.sum) return;
  const el=document.querySelector(`.wf-node[data-node="${node.id}"] .wf-node-sum`);
  let s=""; try{ s=def.sum(node.params); }catch{}
  if(el) el.textContent=s;
}
// Image-template helpers (which nodes carry a template, and its current path).
function wfTplField(type){ const def=WF_NODES[type]; return def&&(def.fields||[]).find(f=>f.t==="tpl"||f.t==="tpls"); }
function wfTplOf(node){ const f=wfTplField(node.type); if(!f) return ""; const v=node.params[f.k];
  return Array.isArray(v)?(v.find(Boolean)||""):(v||""); }   // tpls → first set image
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
  if(img) wfLoadThumb(img, wfTplOf(node));   // refresh single in-node thumbnail if shown
}
