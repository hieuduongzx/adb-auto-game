// ── Rendering ──────────────────────────────────────────────────────────────
function wfRenderAll(){
  wfRenderActivities(); wfRenderFunctions(); wfRenderPalette(); wfRenderCanvas(); wfRenderInspector();
  const t=wfEditTarget();
  $("wf-cur-act").textContent = !t ? "—" : (WF.edit.kind==="function" ? "ƒ "+t.name : t.name);
}

// ── Inline rename (double-click a row name) ──────────────────────────────────
// Swap the name label for an input; Enter/blur commits, Esc cancels.
function wfBeginRename(nameEl, obj){
  const inp=document.createElement("input");
  inp.type="text"; inp.value=obj.name; inp.className="wf-act-rename";
  nameEl.replaceWith(inp);
  inp.focus(); inp.select();
  let done=false;
  const commit=ok=>{ if(done) return; done=true;
    const v=(inp.value||"").trim();
    if(ok && v && v!==obj.name){ wfPushUndo(); obj.name=v; }
    wfRenderAll(); };
  inp.addEventListener("keydown",ev=>{ ev.stopPropagation();
    if(ev.key==="Enter") commit(true); else if(ev.key==="Escape") commit(false); });
  inp.addEventListener("blur",()=>commit(true));
  inp.addEventListener("mousedown",ev=>ev.stopPropagation());
  inp.addEventListener("click",ev=>ev.stopPropagation());
}
// Delegated on the list container (rows are rebuilt on every render, the
// container isn't) so the double-click survives the re-render the first
// click triggers via row selection.
function wfSetupRename(listEl, resolve){
  if(!listEl || listEl.__renameWired) return; listEl.__renameWired=true;
  listEl.addEventListener("dblclick",e=>{
    if(e.target.closest(".wf-act-cb,.wf-act-del,.wf-act-grip,.wf-act-rename")) return;
    const row=e.target.closest(".wf-act"); if(!row) return;
    const obj=resolve(row.dataset.id); if(!obj) return;
    const nameEl=row.querySelector(".wf-act-name"); if(!nameEl) return;
    e.stopPropagation();
    wfBeginRename(nameEl, obj);
  });
}

function wfRenderActivities(){
  // Two buckets of activities share one array but render into separate lists
  // (Sequent vs Background), each shown under its own tab.
  const seqWrap=$("wf-activities"), bgWrap=$("wf-activities-bg");
  const seqCnt=$("wf-act-count"), bgCnt=$("wf-bg-count");
  if(seqWrap) seqWrap.innerHTML="";
  if(bgWrap) bgWrap.innerHTML="";
  const seqActs=WF.activities.filter(a=>a.type!=="background");
  const bgActs =WF.activities.filter(a=>a.type==="background");
  if(seqCnt) seqCnt.textContent = seqActs.length? String(seqActs.length):"";
  if(bgCnt)  bgCnt.textContent = bgActs.length ? String(bgActs.length) :"";
  const check=`<svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>`;
  function rowInto(wrap, act){
    const sel = WF.edit.kind==="activity" && act.id===WF.edit.id;
    const el=document.createElement("div");
    // Apply run-status classes (running / done / errored) from the live tracker
    // so the row keeps its indicator across re-renders during a test run.
    const st=wfActStatus[act.id];
    el.className="wf-act"+(sel?" sel":"")+(st==="running"?" running":"")+(st==="done"?" done":"")+(st==="errored"?" errored":"");
    el.dataset.id=act.id;
    el.innerHTML=
      `<span class="wf-act-runbar"></span>
       <span class="wf-act-grip" title="Drag to reorder">${WF_GRIP}</span>
       <span class="wf-act-cb ${act.enabled?"checked":""}">${check}</span>
       <span class="wf-act-name" title="Double-click to rename">${escHtml(act.name)}</span>
       <button class="wf-act-del" title="Delete">${wfIco("x")}</button>`;
    el.querySelector(".wf-act-cb").addEventListener("click",e=>wfToggleActivity(act.id,e));
    el.querySelector(".wf-act-del").addEventListener("click",e=>wfDeleteActivity(act.id,e));
    el.addEventListener("click",e=>{ if(e.target.closest(".wf-act-cb,.wf-act-del,.wf-act-grip,.wf-act-rename"))return; wfSelectActivity(act.id); });
    wfAttachReorder(el, el.querySelector(".wf-act-grip"), wrap, WF.activities);
    wrap.appendChild(el);
  }
  if(seqWrap){
    if(!seqActs.length){ seqWrap.innerHTML='<div class="wf-insp-empty" style="padding:2px;">No sequence activities.</div>'; }
    else seqActs.forEach(a=>rowInto(seqWrap, a));
  }
  if(bgWrap){
    if(!bgActs.length){ bgWrap.innerHTML='<div class="wf-insp-empty" style="padding:2px;">No background tasks.</div>'; }
    else bgActs.forEach(a=>rowInto(bgWrap, a));
  }
  wfToggleActPanel();   // re-apply the persisted collapsed state on every render
}

function wfRenderFunctions(){
  const wrap=$("wf-functions"); if(!wrap) return; wrap.innerHTML="";
  const cnt=$("wf-fn-count"); if(cnt) cnt.textContent = WF.functions.length? String(WF.functions.length):"";
  if(!WF.functions.length){ wrap.innerHTML='<div class="wf-insp-empty">No functions. Click “+” to create one.</div>'; return; }
  WF.functions.forEach(fn=>{
    const sel = WF.edit.kind==="function" && fn.id===WF.edit.id;
    const el=document.createElement("div"); el.className="wf-act wf-fn"+(sel?" sel":""); el.dataset.id=fn.id;
    el.title="Drag to canvas to insert a call · click to edit function";
    el.innerHTML=
      `<span class="wf-act-grip" title="Drag to canvas to use / drag to reorder">${WF_GRIP}</span>
       <span class="wf-badge fn">ƒ</span>
       <span class="wf-act-name" title="Double-click to rename">${escHtml(fn.name)}</span>
       <button class="wf-act-del" title="Delete function">${wfIco("x")}</button>`;
    el.querySelector(".wf-act-del").addEventListener("click",e=>wfDeleteFunction(fn.id,e));
    el.addEventListener("click",e=>{ if(e.target.closest(".wf-act-del,.wf-act-grip,.wf-act-rename"))return; wfEditFunction(fn.id); });
    wfAttachReorder(el, el.querySelector(".wf-act-grip"), wrap, WF.functions, "call:"+fn.id);
    wrap.appendChild(el);
  });
}

// ── Activities panel tabs (in-canvas corner) ─────────────────────────────────
// Two tabs: "seq" (sequence activities) and "bg" (background activities).
// Functions live in their own section at the bottom of the left sidebar.
let wfActTabCur="seq";
function wfActTab(which){
  if(which==="fns") which="seq";   // legacy callers — the fns tab moved to the sidebar
  wfActTabCur=which;
  document.querySelectorAll(".wf-act-tab").forEach(t=>t.classList.toggle("sel", t.dataset.tab===which));
  const acts=$("wf-activities"), bg=$("wf-activities-bg");
  if(acts) acts.style.display = which==="seq"?"":"none";
  if(bg)   bg.style.display   = which==="bg" ?"":"none";
  const add=$("wf-act-add");
  if(add) add.title = which==="bg"?"Add background task":"Add activity";
  const title=$("wf-act-hdr-title");
  if(title) title.textContent = which==="bg"?"Background tasks":"Activities";
}
function wfActAddCurrent(){
  if(wfActTabCur==="bg") wfAddActivity("background");
  else wfAddActivity("sequence");
}
function wfToggleActPanel(){
  const p=$("wf-act-panel"); if(p) p.classList.toggle("collapsed", wfActCollapsed);
  wfEqualizeCornerPanels();
}
// Both corner panels (Activities + Variables) are content-sized: each hugs its
// own list — the Variables panel grows row by row up to ~10 vars then scrolls
// (see .wf-vars-body max-height). The old behaviour stretched the shorter panel
// to match the taller one, which padded Variables with empty space; kept as a
// reset-only hook since renders still call it.
function wfEqualizeCornerPanels(){
  const a=$("wf-act-panel"), v=$("wf-vars-panel"); if(!a||!v) return;
  a.style.minHeight=""; v.style.minHeight="";            // natural (content) height
}
// Dragging is armed only while the grip handle is held, so checkbox / select /
// delete clicks keep working. Rows shuffle live during dragover; on drop the
// backing array (WF.activities or WF.functions) is reordered to match the DOM —
// for sequence activities this changes their run order.
const WF_GRIP = `<svg width="8" height="13" viewBox="0 0 9 14" fill="currentColor"><circle cx="2" cy="2" r="1.3"/><circle cx="7" cy="2" r="1.3"/><circle cx="2" cy="7" r="1.3"/><circle cx="7" cy="7" r="1.3"/><circle cx="2" cy="12" r="1.3"/><circle cx="7" cy="12" r="1.3"/></svg>`;

// `paletteType` (optional): if set, the row also acts like a palette chip — it's
// draggable from anywhere and dropping it on the canvas spawns that node (used by
// the Function list so a function can be dragged straight onto the graph).
function wfAttachReorder(el, handle, listEl, arr, paletteType){
  if(paletteType){ el.draggable=true; }                     // drag from anywhere
  else if(handle){
    handle.addEventListener("mousedown", ()=>{ el.draggable=true; });
    handle.addEventListener("mouseup",   ()=>{ el.draggable=false; });
  } else return;
  el.addEventListener("dragstart", e=>{
    el.classList.add("wf-dragging");
    if(paletteType){ wfPaletteDrag=paletteType; e.dataTransfer.effectAllowed="copyMove";
      try{ e.dataTransfer.setData("text/plain", paletteType); }catch{} }
    else { e.dataTransfer.effectAllowed="move";
      try{ e.dataTransfer.setData("text/plain", el.dataset.id); }catch{} }
  });
  el.addEventListener("dragend", ()=>{
    if(!paletteType) el.draggable=false;
    el.classList.remove("wf-dragging");
    if(paletteType) wfPaletteDrag=null;
    wfCommitReorder(listEl, arr);
  });
}

function wfDragAfter(listEl, y){
  const rows=[...listEl.querySelectorAll(".wf-act:not(.wf-dragging)")];
  let closest=null, closestOff=Number.NEGATIVE_INFINITY;
  for(const r of rows){
    const box=r.getBoundingClientRect();
    const off=y-box.top-box.height/2;
    if(off<0 && off>closestOff){ closestOff=off; closest=r; }
  }
  return closest;
}

function wfSetupSortable(listEl){
  listEl.addEventListener("dragover", e=>{
    const dragging=listEl.querySelector(".wf-dragging");
    if(!dragging) return;   // only react to a drag that started in THIS list
    e.preventDefault();
    e.dataTransfer.dropEffect="move";
    const after=wfDragAfter(listEl, e.clientY);
    if(after==null) listEl.appendChild(dragging);
    else listEl.insertBefore(dragging, after);
  });
}

function wfCommitReorder(listEl, arr){
  const ids=[...listEl.querySelectorAll(".wf-act")].map(e=>e.dataset.id);
  if(!ids.length){ wfRenderAll(); return; }
  if(ids.length>=arr.length){
    // The list holds the whole array (functions tab, or full activity list) — sort it.
    arr.sort((a,b)=> ids.indexOf(a.id) - ids.indexOf(b.id));
  } else {
    // Filtered subset (Sequent or Background tab): reorder only the matching
    // items in place, leaving the other bucket exactly where it was.
    const idSet=new Set(ids);
    const ord=new Map(ids.map((id,i)=>[id,i]));
    const matched=arr.filter(a=>idSet.has(a.id)).sort((a,b)=>ord.get(a.id)-ord.get(b.id));
    let mi=0;
    for(let i=0;i<arr.length;i++){ if(idSet.has(arr[i].id)) arr[i]=matched[mi++]; }
  }
  wfRenderAll();
}

// Per-category collapse state, persisted locally so the sidebar reopens the
// way the user left it. A live search always shows matches (collapse ignored).
let wfPalCollapsed={};
try{ wfPalCollapsed=JSON.parse(localStorage.getItem("wfPalCollapsed")||"{}")||{}; }catch{}
function wfPalToggleCat(key){
  wfPalCollapsed[key]=!wfPalCollapsed[key];
  try{ localStorage.setItem("wfPalCollapsed", JSON.stringify(wfPalCollapsed)); }catch{}
  wfRenderPalette();
}
const WF_PAL_CHEV = `<svg class="wf-pal-chev" width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4.5L6 8l3.5-3.5"/></svg>`;
function wfRenderPalette(){
  const pal=$("wf-palette"); pal.innerHTML="";
  const q=(wfPaletteQuery||"").trim().toLowerCase();
  let shown=0;
  // Node types grouped by category. When a query is active, only matching
  // types render and their category header shows a live hit count.
  const ctrl = WF.controller||"adb";
  WF_CATS.forEach(cat=>{
    // Controller-specific categories only appear in their matching project mode
    // (Device/emulator = ADB, Win32 window nodes = PC).
    if(cat.ctrl && cat.ctrl!==ctrl) return;
    let types=Object.keys(WF_NODES).filter(t=>WF_NODES[t].cat===cat.key);
    if(q) types=types.filter(t=>(WF_NODES[t].label+" "+t).toLowerCase().includes(q));
    if(!types.length) return;
    shown+=types.length;
    const closed = !q && !!wfPalCollapsed[cat.key];
    const hdr=document.createElement("div"); hdr.className="wf-pal-cat cat-"+cat.key+(closed?" closed":"");
    hdr.title=closed?"Expand category":"Collapse category";
    hdr.innerHTML=`<span>${escHtml(cat.label)}</span><span class="wf-pal-cat-n">${types.length}</span>${WF_PAL_CHEV}`;
    hdr.addEventListener("click",()=>{ if(!q) wfPalToggleCat(cat.key); });
    pal.appendChild(hdr);
    if(closed) return;
    const grid=document.createElement("div"); grid.className="wf-pal-grid";
    types.forEach(type=>grid.appendChild(wfChip(WF_NODES[type].ico, WF_NODES[type].label, type, cat.key)));
    pal.appendChild(grid);
  });
  if(!shown){
    const none=document.createElement("div"); none.className="wf-pal-none";
    none.textContent=q?`No nodes match “${wfPaletteQuery.trim()}”`:"No nodes.";
    pal.appendChild(none);
  }
  // Function calls live in the Function list at the top of the sidebar — drag a
  // row from there straight onto the canvas to insert a call node.
}
// Palette search — filter node chips by label/type as the user types.
let wfPaletteQuery="";
function wfPaletteFilter(v){
  wfPaletteQuery=v||"";
  const clr=$("wf-pal-search-clr"); if(clr) clr.style.display=wfPaletteQuery?"flex":"none";
  wfRenderPalette();
}
function wfPaletteFilterClear(){
  wfPaletteQuery=""; const inp=$("wf-pal-search-inp"); if(inp){ inp.value=""; inp.focus(); }
  const clr=$("wf-pal-search-clr"); if(clr) clr.style.display="none";
  wfRenderPalette();
}
function wfChip(ico,label,dragType,catKey){
  const chip=document.createElement("div");
  chip.className="wf-chip"+(catKey?" cat-"+catKey:""); chip.draggable=true;
  chip.innerHTML=`<span class="ico">${wfIco(ico)}</span>${escHtml(label)}`;
  chip.addEventListener("dragstart",e=>{ wfPaletteDrag=dragType; e.dataTransfer.effectAllowed="copy"; try{e.dataTransfer.setData("text/plain",dragType);}catch{} });
  chip.addEventListener("dragend",()=>{ wfPaletteDrag=null; });
  return chip;
}

function wfRenderCanvas(){
  const world=$("wf-world"), empty=$("wf-canvas-empty"), g=wfGraph();
  [...world.querySelectorAll(".wf-node,.wf-group")].forEach(n=>n.remove());
  wfApplyTransform();
  if(!g){ empty.style.display="flex"; $("wf-wires").innerHTML=""; return; }
  empty.style.display="none";
  wfRenderGroups();   // frames behind the nodes
  g.nodes.forEach(n=>world.appendChild(wfNodeEl(n)));
  wfReflowStacks();   // snap merged blocks flush (needs nodes in the DOM)
  wfDrawWires();
  wfMarkDefaultEntry();  // pill above the block that start.out points to
  if(wfRunning||wfRunStopped) wfReapplyRunViz();   // keep the run-trail across redraws (live + after stop)
  wfRenderVarsPanel();
}

// ── Variables panel (bottom-right of canvas) ──────────────────────────────────
// Collect every variable the user can reference: declared on the current
// activity (with their declared default), plus any live values the engine has
// pushed during a test run. Live values override declared defaults.
function wfDeclaredVars(){
  const out={};
  const walk=(vars,prefix)=>{ (vars||[]).forEach(v=>{ const nm=(v.name||"").trim(); if(!nm) return; const full=prefix?prefix+"."+nm:nm; out[full]=v.value; walk(v.children,full); }); };
  walk(WF.globals,"");
  const act=wfCurAct();
  if(act) walk(act.vars,"");
  return out;
}
// All known variable names across the whole flow (every activity + functions),
// so a dropdown in any graph can offer vars declared elsewhere too. Sources:
//   1. Global vars (declared at flow top level — visible in every activity).
//   2. Vars explicitly declared on an activity (the "Variables" section).
//   3. Vars produced by nodes — set_var / calc_var / read_var / parse_var each
//      write a var via their "name" field, so we treat those names as known
//      defaults every other block can reference. Sort alphabetically.
const WF_VAR_PRODUCERS = {"set_var":"name","calc_var":"name","read_var":"name","parse_var":"name"};
function wfGraphVarNames(g){
  const s=new Set();
  (g && g.nodes || []).forEach(n=>{
    const k=WF_VAR_PRODUCERS[n.type];
    if(k){ const nm=String((n.params||{})[k]||"").trim(); if(nm) s.add(nm); }
  });
  return s;
}
function wfAllVarNames(){
  const s=new Set();
  const walk=(vars,prefix)=>{ (vars||[]).forEach(v=>{ const n=(v.name||"").trim(); if(!n) return; const full=prefix?prefix+"."+n:n; s.add(full); walk(v.children,full); }); };
  walk(WF.globals,"");
  (WF.activities||[]).forEach(a=>{ walk(a.vars,""); });
  // Vars produced by nodes anywhere in the flow count as defaults too.
  (WF.activities||[]).forEach(a=>{ wfGraphVarNames(a.graph).forEach(n=>s.add(n)); });
  (WF.functions||[]).forEach(fn=>{ wfGraphVarNames(fn.graph).forEach(n=>s.add(n)); });
  return [...s].sort();
}
function wfRenderVarsPanel(){
  const panel=$("wf-vars-panel"); if(!panel) return;
  const body=$("wf-vars-body"); if(!body) return;
  panel.classList.toggle("collapsed", wfVarsCollapsed);
  panel.classList.toggle("live", Object.keys(wfLiveVars).length>0);
  const declared=wfDeclaredVars();
  // Buckets: globals → activity-declared → node-produced → live-only extras.
  // Walk nested vars to collect all names (dotted for children).
  const globalNames=[];
  const walkNames=(vars,prefix)=>{ (vars||[]).forEach(v=>{ const n=(v.name||"").trim(); if(!n) return; const full=prefix?prefix+"."+n:n; globalNames.push(full); walkNames(v.children,full); }); };
  walkNames(WF.globals,"");
  const actDeclared={}; const act=wfCurAct(); const actNames=[];
  const walkAct=(vars,prefix)=>{ (vars||[]).forEach(v=>{ const n=(v.name||"").trim(); if(!n) return; const full=prefix?prefix+"."+n:n; if(!globalNames.includes(full)){ actDeclared[full]=v.value; actNames.push(full); } walkAct(v.children,full); }); };
  if(act) walkAct(act.vars,"");
  const g=wfGraph();
  const nodeNames=[]; wfGraphVarNames(g).forEach(n=>{ if(!globalNames.includes(n)&&!actNames.includes(n)) nodeNames.push(n); });
  const liveExtra=[]; Object.keys(wfLiveVars).forEach(n=>{ if(!globalNames.includes(n)&&!actNames.includes(n)&&!nodeNames.includes(n)) liveExtra.push(n); });
  const allNames=[...globalNames,...actNames,...nodeNames,...liveExtra];
  // Update count badge in header.
  const countEl=$("wf-vars-count"); if(countEl) countEl.textContent=allNames.length?String(allNames.length):"";
  body.innerHTML="";
  if(!allNames.length){
    const e=document.createElement("div"); e.className="wf-vars-empty";
    e.textContent="No variables. Click + to add a global variable.";
    body.appendChild(e); wfEqualizeCornerPanels(); return;
  }
  function mkSep(label){ const s=document.createElement("span"); s.className="wf-vars-sep"; s.textContent=label; return s; }
  function mkRow(n, isGlobal){
    const row=document.createElement("div"); row.className="wf-var-row-live";
    // Global rows are a shortcut into the globals editor — one click to edit.
    if(isGlobal){ row.classList.add("clickable");
      row.addEventListener("click",()=>{ wfGlobsOpen=true; wfShowGlobsEditor(); }); }
    const nm=document.createElement("span"); nm.className="vn";
    nm.title=n+(isGlobal?" · global · click to edit":"");
    if(isGlobal){
      nm.style.color="var(--accent)";
      nm.innerHTML='<svg viewBox="0 0 24 24" width="9" height="9" style="vertical-align:middle;margin-right:3px"><circle cx="12" cy="12" r="6" fill="currentColor"/></svg>'+n;
    } else { nm.textContent=n; }
    const live=wfLiveVars[n];
    const hasDeclared=declared.hasOwnProperty(n);
    const val=(live!==undefined)?live:(hasDeclared?declared[n]:undefined);
    const vv=document.createElement("span"); vv.className="vv"+(n===wfFreshVar?" fresh":"");
    vv.textContent=(val===undefined||val===null||val==="")?(hasDeclared?"∅":"(generated)"):String(val);
    vv.title=(live!==undefined)?"runtime value":(hasDeclared?"declared value":"created by node");
    row.appendChild(nm); row.appendChild(vv);
    return row;
  }
  if(globalNames.length){ body.appendChild(mkSep("Global")); globalNames.forEach(n=>body.appendChild(mkRow(n,true))); }
  if(actNames.length){ body.appendChild(mkSep("Activities")); actNames.forEach(n=>body.appendChild(mkRow(n,false))); }
  if(nodeNames.length){ body.appendChild(mkSep("Node")); nodeNames.forEach(n=>body.appendChild(mkRow(n,false))); }
  if(liveExtra.length){ body.appendChild(mkSep("Live")); liveExtra.forEach(n=>body.appendChild(mkRow(n,false))); }
  wfEqualizeCornerPanels();
}

// ── Global variables editor (popover from the vars panel "+") ─────────────────
let wfGlobsOpen=false;
function wfAddQuickGlobal(){
  if(!Array.isArray(WF.globals)) WF.globals=[];
  wfPushUndoDebounced();
  const n=WF.globals.length+1;
  WF.globals.push({name:"g"+n, label:"Global "+n, type:"bool", value:false});
  wfRenderVarsPanel();
  wfShowGlobsEditor();
}
function wfToggleGlobsEditor(){
  wfGlobsOpen=!wfGlobsOpen;
  if(wfGlobsOpen) wfShowGlobsEditor(); else wfHideGlobsEditor();
}
function wfHideGlobsEditor(){ const p=document.getElementById("wf-globs-pop"); if(p) p.remove(); wfGlobsOpen=false; }
function wfShowGlobsEditor(){
  wfHideGlobsEditor();
  if(!Array.isArray(WF.globals)) WF.globals=[];
  const pop=document.createElement("div"); pop.id="wf-globs-pop"; pop.className="wf-globs-pop";
  const hdr=document.createElement("div"); hdr.className="wf-vars-hdr";
  hdr.innerHTML='<span>Global variables</span><span class="wf-vars-close" style="cursor:pointer" title="Close">'+wfIco("x")+'</span>';
  hdr.querySelector(".wf-vars-close").onclick=wfHideGlobsEditor;
  pop.appendChild(hdr);
  const body=document.createElement("div"); body.className="wf-globs-pop-body";
  function render(){
    body.innerHTML="";
    if(!WF.globals.length){
      const e=document.createElement("div"); e.className="wf-vars-empty";
      e.textContent="No global variables. Click \"+ Add\".";
      body.appendChild(e);
    }
    WF.globals.forEach((v,idx)=> { body.appendChild(wfGlobRow(v,idx,render)); wfBuildGlobChildren(v,body,render); });
    const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Add";
    add.style.marginTop="2px";
    add.onclick=()=>{ wfPushUndoDebounced(); const n=WF.globals.length+1; WF.globals.push({name:"g"+n, label:"Global "+n, type:"bool", value:false, children:[]}); render(); wfRenderVarsPanel(); };
    body.appendChild(add);
  }
  render();
  pop.appendChild(body);
  document.body.appendChild(pop);
  // Anchor below the "+" button (vars panel is now top-right).
  const btn=$("wf-vars-add");
  if(btn){
    const r=btn.getBoundingClientRect();
    let left=r.right-250, top=r.bottom+6;
    pop.style.top=Math.max(8, top)+"px";
    pop.style.left=Math.max(8, Math.min(window.innerWidth-250, left))+"px";
  }
}
function wfGlobRow(v,idx,render){
  const card=document.createElement("div"); card.className="wf-glob-card";
  const r1=document.createElement("div"); r1.className="wf-var-row";
  r1.style.alignItems="center";
  const tag=document.createElement("span"); tag.className="wf-glob-tag"; tag.innerHTML='<svg viewBox="0 0 24 24" width="9" height="9" style="vertical-align:middle;margin-right:3px"><circle cx="12" cy="12" r="6" fill="currentColor"/></svg>GLOBAL';
  const addChild=document.createElement("button"); addChild.className="btn sm"; addChild.textContent="+ Child"; addChild.title="Add child variable";
  addChild.onclick=(e)=>{ e.stopPropagation(); wfPushUndoDebounced(); v.children=v.children||[]; const n=v.children.length+1; v.children.push({name:v.name+"_sub"+n, label:"Sub "+n, type:"bool", value:false, children:[]}); render(); wfRenderVarsPanel(); };
  const del=document.createElement("button"); del.className="wf-glob-del"; del.textContent="−"; del.title="Delete global variable";
  del.onclick=(e)=>{ e.stopPropagation(); wfPushUndoDebounced(); WF.globals.splice(idx,1); render(); wfRenderVarsPanel(); };
  const sp=document.createElement("span"); sp.style.flex="1";
  r1.appendChild(tag); r1.appendChild(sp); r1.appendChild(addChild); r1.appendChild(del);
  card.appendChild(r1);
  const r1b=document.createElement("div"); r1b.className="wf-var-row";
  const lbl=document.createElement("input"); lbl.type="text"; lbl.value=v.label||""; lbl.placeholder="Title"; lbl.style.flex="1"; lbl.style.minWidth="0"; lbl.style.fontWeight="600";
  lbl.oninput=()=>{ wfPushUndoDebounced(); v.label=lbl.value; };
  r1b.appendChild(lbl);
  card.appendChild(r1b);
  const r2=document.createElement("div"); r2.className="wf-var-row";
  const nm=document.createElement("input"); nm.type="text"; nm.value=v.name||""; nm.placeholder="variable"; nm.style.flex="1"; nm.style.minWidth="0"; nm.style.fontSize="10.5px"; nm.style.fontFamily="var(--mono)";
  nm.oninput=()=>{ wfPushUndoDebounced(); v.name=nm.value; wfRenderVarsPanel(); };
  r2.appendChild(nm);
  const ty=document.createElement("select");
  [["bool","bool"],["number","number"],["text","text"],["select","select"]].forEach(([val,lab])=>{ const o=document.createElement("option"); o.value=val; o.textContent=lab; if((v.type||"bool")===val)o.selected=true; ty.appendChild(o); });
  ty.onchange=()=>{
    wfPushUndoDebounced();
    v.type=ty.value;
    if(ty.value==="select"){ if(!v.options||!v.options.length) v.options=["A","B"]; v.value=v.options[0]; }
    else v.value = ty.value==="bool"?false : ty.value==="number"?0 : "";
    render(); wfRenderVarsPanel();
  };
  r2.appendChild(ty);
  card.appendChild(r2);
  card.appendChild(wfVarValue(v));
  if(v.type==="select"){
    const r3=document.createElement("div"); r3.className="wf-var-row";
    const l=document.createElement("label"); l.textContent="options"; l.style.fontSize="10px"; r3.appendChild(l);
    const opt=document.createElement("input"); opt.type="text"; opt.value=(v.options||[]).join(", "); opt.placeholder="A, B, C"; opt.style.flex="1"; opt.style.minWidth="0"; opt.style.fontSize="10px";
    opt.onchange=()=>{ wfPushUndoDebounced(); v.options=opt.value.split(",").map(s=>s.trim()).filter(Boolean); if(!v.options.includes(v.value)) v.value=v.options[0]||""; render(); wfRenderVarsPanel(); };
    r3.appendChild(opt); card.appendChild(r3);
  }
  return card;
}
function wfBuildGlobChildren(v,container,render,depth){
  depth=depth||0;
  v.children=v.children||[];
  v.children.forEach((cv,ci)=>{
    const childCard=wfGlobRow(cv,ci,render);
    childCard.style.marginLeft=((depth+1)*WF_VAR_INDENT)+"px";
    container.appendChild(childCard);
    if(cv.children&&cv.children.length) wfBuildGlobChildren(cv,container,render,depth+1);
  });
}

// Lightweight static checks surfaced as a "!" badge on the node — catches the two
// mistakes that silently break a flow: an image node with no template picked, and
// a block that has no incoming wire (so the run never reaches it).
function wfNodeWarnings(n, def, g){
  const w=[];
  for(const f of (def.fields||[])){
    if(f.t==="tpl" && !String(n.params[f.k]||"").trim()) w.push("No template image selected");
    if(f.t==="tpls"){ const a=n.params[f.k]; if(!Array.isArray(a)||!a.filter(x=>String(x||"").trim()).length) w.push("No images in the list"); }
    if(f.t==="color" && !/^#[0-9a-fA-F]{6}$/.test(String(n.params[f.k]||""))) w.push("Invalid color — need #RRGGBB");
  }
  if(n.type==="switch"){
    const cs=(n.params&&n.params.cases)||[];
    if(!cs.length) w.push("No branches");
    cs.forEach((c,i)=>{ const cd=WF_NODES[c.type]; (cd&&cd.fields||[]).forEach(f=>{
      if(f.t==="tpl" && !String((c.params||{})[f.k]||"").trim()) w.push(`Branch #${i+1}: no image selected`); }); });
  }
  if(n.type==="and" && g){
    const expected=Math.max(1,parseInt(n.params&&n.params.count)||2);
    const incoming=(g.edges||[]).filter(ed=>ed.to===n.id).length;
    if(!incoming) w.push("No incoming wire — this block will never run");
    else if(incoming!==expected) w.push(`Expected ${expected} incoming branches, found ${incoming}`);
  }
  if(def.kind!=="start" && def.kind!=="note" && n.type!=="and" && g && !(g.edges||[]).some(ed=>ed.to===n.id))
    w.push("No incoming wire — this block will never run");
  return w;
}
// Swatch dot for the node summary of color nodes (t:"color" field) — shows the
// picked colour itself, so the block reads at a glance without parsing hex.
function wfColorDotHtml(n,def){
  const cf=(def.fields||[]).find(f=>f.t==="color");
  if(!cf) return "";
  const v=String((n.params||{})[cf.k]||"");
  return /^#[0-9a-fA-F]{6}$/.test(v) ? `<span class="wf-node-colordot" style="background:${v}"></span>` : "";
}

// Timing badges (delayBefore / delayAfter) — floating chips anchored under the
// block's bottom-left corner (absolute), so a delay never stretches the
// standardized card. Shared by wfNodeEl and the inspector's live update.
function wfDelayChipsHtml(n){
  const dp=[];
  if(n.delayBefore) dp.push(`<span class="wf-delay-chip">${wfIco("clock")}Before ${n.delayBefore}s</span>`);
  if(n.delayAfter)  dp.push(`<span class="wf-delay-chip">${wfIco("timer")}After ${n.delayAfter}s</span>`);
  return dp.length ? `<div class="wf-node-delay">${dp.join("")}</div>` : "";
}
function wfNodeEl(n){
  const def=WF_NODES[n.type]||{label:n.type,ico:"help",kind:"action",outs:["out"],fields:[]};
  const g=wfGraph();
  const el=document.createElement("div");
  // Category tint (only for the bulk action/condition blocks — structural kinds
  // start/end/stop/loop/call/note keep their own distinct styling).
  const catCls = (def.kind==="action"||def.kind==="condition") && def.cat ? " cat-"+def.cat : "";
  // Nodes with true/false outputs show "T"/"F" labels in the top-right corner;
  // flag them so the header reserves room and the title can't slide under the labels.
  const tfCls = ((def.outs||[]).includes("true") || n.type==="switch") ? " has-tf" : "";
  el.className="wf-node "+def.kind+catCls+tfCls+(WF.sel.includes(n.id)?" sel":"")+(n.id===wfRunNode?" running":"");
  el.style.left=n.x+"px"; el.style.top=n.y+"px"; el.dataset.node=n.id;
  // Dynamic output ports — grow the card so they all sit inside it. Multi-port
  // blocks stack their ports in the body starting at top=26, 16px apart; the last
  // port needs room below it. Never shorter than the standard 60px block.
  let dynOutCount=0;
  if(n.type==="switch") dynOutCount=((n.params&&n.params.cases)||[]).length+1;
  else if(n.type==="try_chain") dynOutCount=Math.max(1,parseInt(n.params&&n.params.count)||3)+1;
  else if(n.type==="parallel") dynOutCount=Math.max(1,parseInt(n.params&&n.params.count)||3);
  else if(n.type==="random_branch") dynOutCount=Math.max(1,parseInt(n.params&&n.params.count)||2);
  else if(n.type==="loop_until_image") dynOutCount=3;   // body/found/fail — grow the card
  if(dynOutCount>2) el.style.minHeight=Math.max(60, 26 + (dynOutCount-1)*16 + 14)+"px";
  // Merged-block membership: hide the join port at the joined edge and flatten
  // that corner so the stack reads as one block.
  const intIn = n.stack ? wfHasInternalIn(n) : false;
  const intOut = n.stack ? wfHasInternalOut(n) : false;
  if(n.stack){ el.classList.add("wf-stacked");
    if(intIn) el.classList.add("wf-stk-jtop"); if(intOut) el.classList.add("wf-stk-jbot"); }
  // A call node shows the referenced function's name as its title.
  let title=def.label, sum="";
  if(n.type==="call"){ const fn=wfFnById(n.params.fn); title=fn?fn.name:"(no function selected)";
    sum=fn?"ƒ call function":"double-click to pick"; }
  else { try{ sum=def.sum?def.sum(n.params):""; }catch{} }
  const tplField = wfTplField(n.type);
  const isTpls = tplField && tplField.t==="tpls";
  const hasTpl = !!tplField;
  const showThumb = hasTpl && (wfPreviewAll || n.showPreview);
  const eyeBtn = ""; // eye moved to hover action bar
  // Action bar above the node (hover-only): delete, toggle preview, copy.
  const delSvg = '<svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  const copySvg = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const actEyeSvg = '<svg viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  const actBar = `<div class="wf-node-actions">
    <button class="wf-act-del" title="Delete">${delSvg}</button>
    <span class="wf-node-act-spacer"></span>
    ${hasTpl ? `<button class="wf-act-eye${n.showPreview?" on":""}" title="Toggle preview">${actEyeSvg}</button>` : ""}
    <button class="wf-act-copy" title="Copy">${copySvg}</button>
  </div>`;
  const noteHtml = n.note ? `<div class="wf-node-note">${wfIco("edit")}<span>${escHtml(n.note)}</span></div>` : "";
  const logHtml = n.log ? `<div class="wf-node-log">${escHtml(n.log)}</div>` : "";
  const delayHtml = wfDelayChipsHtml(n);
  const rp=[];
  if(n.retryCount) rp.push(`${wfIco("loop")}<span>Retry ${n.retryCount}×</span>`);
  if(n.screenshotOnFail) rp.push(`${wfIco("camera")}<span>Screenshot on fail</span>`);
  const retryHtml = rp.length ? `<div class="wf-node-retry">${rp.join("")}</div>` : "";
  // tpls → a strip of small thumbnails (one per listed image); single tpl → one.
  // The preview row is always rendered (so block height is stable) but the image
  // is hidden via CSS until showPreview / wfPreviewAll turns it on.
  const hasRealThumb = hasTpl && (wfPreviewAll || n.showPreview);
  const thumbHtml = hasTpl ? (isTpls
    ? `<div class="wf-node-thumbs"></div>`
    : `<img class="wf-node-thumb">`) : "";
  // start/end render as a small play/stop triangle, not a header+body card.
  const isTerminal = def.kind==="start"||def.kind==="end";
  // Color nodes get a live swatch dot in front of the summary text.
  const sumHtml = sum?`<div class="wf-node-sum">${wfColorDotHtml(n,def)}${escHtml(sum)}</div>`:"";
  const topRow = hasTpl ? `<div class="wf-node-prevrow">${thumbHtml}${sumHtml}</div>` : sumHtml;
  el.classList.toggle("showing-thumb", hasRealThumb);
  el.classList.toggle("has-thumb", hasTpl);
  if(isTerminal){
    const termIco = def.kind==="end" ? '<rect x="7" y="7" width="10" height="10" rx="2"/>' : '<polygon points="8 5 19 12 8 19 8 5"/>';
    el.innerHTML = `<span class="wf-node-tri"><svg viewBox="0 0 24 24" fill="currentColor" stroke="none">${termIco}</svg></span><span class="wf-node-tri-lbl">${escHtml(def.label)}</span>`;
  } else {
    el.innerHTML=
      actBar+
      `<div class="wf-node-hd"><span class="ico">${wfIco(def.ico)}</span>${eyeBtn}<span class="wf-node-title">${escHtml(title)}</span></div>`+
      topRow+delayHtml+retryHtml+noteHtml+logHtml;
  }
  // Output ports are placed first; input ports mirror the output row of the
  // same index so a block's in/out wires start level. Switch builds its ports
  // from the case list: c0..c{n-1} (one per case, including "else") + the
  // shared "default" fallback port.
  let outs;
  if(intOut) outs=[];
  else if(n.type==="switch") outs=((n.params&&n.params.cases)||[]).map((_,i)=>"c"+i).concat(["default"]);
  else if(n.type==="try_chain") outs=Array.from({length:Math.max(1,parseInt(n.params&&n.params.count)||3)},(_,i)=>String(i+1)).concat(["fail"]);
  else if(n.type==="parallel"||n.type==="random_branch") outs=Array.from({length:Math.max(1,parseInt(n.params&&n.params.count)||(n.type==="parallel"?3:2))},(_,i)=>String(i+1));
  else outs=(def.outs||[]);
  // Primary port row — the single input and the first output share this y, so a
  // block's in/out sit on one straight horizontal line and chaining any block's
  // primary output into the next block's input stays perfectly level. For a full
  // block it's row 26 (the card's vertical centre, below the 20px header); a
  // terminal centres in its 30px chip.
  // Extra ports (branch outputs true/false…, the loop's second "loop" input)
  // stack 16px below this row; the card grows when there are many outputs.
  const rowTop = isTerminal ? Math.round(30/2-4.5) : 26;
  const outTop = i => rowTop + (outs.length>1 ? i*16 : 0);
  // Single input → the shared primary row (level with the first output). The
  // loop's in/loop pair stacks from that row downward.
  const nIns = wfIns(n.type).length;
  const inTop = i => rowTop + (nIns>1 ? i*16 : 0);
  if(hasTpl){
    if(isTpls){
      const strip=el.querySelector(".wf-node-thumbs");
      const arr=Array.isArray(n.params[tplField.k])?n.params[tplField.k].filter(p=>String(p||"").trim()):[];
      if(!arr.length){ const e=document.createElement("span"); e.className="wf-tpl-empty"; e.textContent="(no image)"; strip.appendChild(e); }
      arr.forEach(p=>{ const im=document.createElement("img"); im.className="wf-node-thumb-sm"; strip.appendChild(im); wfLoadThumb(im,p); });
    } else {
      wfLoadThumb(el.querySelector(".wf-node-thumb"), wfTplOf(n));
    }
  }
  // input ports (start has none; note floats).
  // Most nodes have a single 'in'; the loop also exposes a 'loop' (loop-back)
  // input below it so the wire that re-enters the loop lands on its own port.
  if(def.kind!=="start" && def.kind!=="note" && !intIn){
    const ins=wfIns(n.type);
    ins.forEach((port,i)=>{
      const top = inTop(i);
      const ip=document.createElement("span");
      // Color the destination input to match the source port's semantic colour.
      const incoming = g && (g.edges||[]).find(e=>e.to===n.id && (e.toPort||"in")===port);
      const srcPort = incoming ? incoming.fromPort : null;
      const isConnected = !!incoming;
      ip.className="wf-port in"+(port==="loop"?" loop":"")+
        (srcPort==="true"?" t":srcPort==="false"?" f":"")+
        (isConnected?" connected":"");
      ip.dataset.node=n.id; ip.dataset.port=port; ip.style.top=top+"px";
      el.appendChild(ip);
      if(ins.length>1){ const lbl=document.createElement("span"); lbl.className="wf-port-lbl in"+(port==="loop"?" loop":"");
        lbl.style.top=(top+0)+"px"; lbl.textContent=WF_IN_LBL[port]||port; el.appendChild(lbl); }
    });
  }
  // output ports (hidden when this member feeds the next block in its stack).
  outs.forEach((port,i)=>{
    const top = outTop(i);
    const op=document.createElement("span");
    const isConnected = g && (g.edges||[]).some(e=>e.from===n.id && e.fromPort===port);
    op.className="wf-port out"+(port==="true"?" t":port==="false"?" f":"")+(isConnected?" connected":"");
    op.dataset.node=n.id; op.dataset.port=port; op.style.top=top+"px";
    el.appendChild(op);
    let lblTxt;
    if(n.type==="switch") lblTxt = (port==="default") ? "else" : "#"+(i+1);
    else if(n.type==="parallel"||n.type==="random_branch"||n.type==="try_chain") lblTxt = port;
    else lblTxt = WF_PORT_LBL[port];
    if(lblTxt){ const lbl=document.createElement("span"); lbl.className="wf-port-lbl"; lbl.style.top=(top+0)+"px"; lbl.textContent=lblTxt; el.appendChild(lbl); }
  });
  // Validation badge (missing template / not wired in) so broken flows show before a run.
  const warns=wfNodeWarnings(n,def,wfGraph());
  if(warns.length){ el.classList.add("has-warn");
    const b=document.createElement("span"); b.className="wf-node-warn"; b.textContent="!"; b.title=warns.join("\n"); el.appendChild(b); }
  // interactions — the whole node body is a drag handle (ports excluded inside wfStartMove).
  // Deletion is via Delete/Backspace or the right-click menu — no per-node × button.
  el.addEventListener("mousedown",e=>wfStartMove(e,n));
  // Double-click a call node → jump into that function's graph.
  if(n.type==="call"){ el.addEventListener("dblclick",e=>{ e.stopPropagation(); if(n.params&&n.params.fn&&wfFnById(n.params.fn)) wfEditFunction(n.params.fn); }); }
  // Double-click any image-related block to pick its template(s) directly.
  if(hasTpl){
    el.addEventListener("dblclick",async e=>{
      if(e.target.closest(".wf-port,.wf-node-eye")) return;
      e.stopPropagation();
      const f=wfTplField(n.type);
      if(!f) return;
      if(f.t==="tpls"){
        const pp=await api().pick_template(); if(!pp) return;
        wfPushUndoDebounced();
        const arr=Array.isArray(n.params[f.k])?n.params[f.k]:(n.params[f.k]=[]);
        arr.push(pp);
      } else {
        const pp=await api().pick_template(); if(!pp) return;
        wfPushUndoDebounced();
        n.params[f.k]=pp;
      }
      wfUpdNodeSum(n); wfUpdNodePreview(n); wfRenderCanvas(); wfRenderInspector();
    });
  }
  const eye=el.querySelector(".wf-node-eye");
  // Action bar buttons (hover toolbar above node)
  const actDel=el.querySelector(".wf-act-del");
  if(actDel){ actDel.addEventListener("mousedown",e=>e.stopPropagation()); actDel.addEventListener("click",e=>{ e.stopPropagation(); wfDeleteNode(n.id); }); }
  const actEye=el.querySelector(".wf-act-eye");
  if(actEye){ actEye.addEventListener("mousedown",e=>e.stopPropagation()); actEye.addEventListener("click",e=>{ e.stopPropagation(); wfPushUndoDebounced(); n.showPreview=!n.showPreview; wfRenderCanvas(); }); }
  const actCopy=el.querySelector(".wf-act-copy");
  if(actCopy){ actCopy.addEventListener("mousedown",e=>e.stopPropagation()); actCopy.addEventListener("click",e=>{ e.stopPropagation(); wfSelectOne(n.id); wfMarkSel(); wfCopy(); wfPaste({clientX:event.clientX+20,clientY:event.clientY+20}); }); }
  el.querySelectorAll(".wf-port.out").forEach(p=>p.addEventListener("mousedown",e=>wfStartConnect(e,n.id,p.dataset.port)));
  // Connection completion is handled globally (drop anywhere on a node = connect).
  return el;
}

// ── Switch-node case edits: keep outgoing wires attached as ports c0.. shift ──
function wfRemoveSwitchCase(node, idx){
  const g=wfGraph(); if(!g) return;
  node.params.cases.splice(idx,1);
  g.edges = g.edges.filter(e=>!(e.from===node.id && e.fromPort==="c"+idx));   // drop the removed case's wire
  g.edges.forEach(e=>{ if(e.from===node.id && /^c\d+$/.test(e.fromPort)){
    const j=parseInt(e.fromPort.slice(1)); if(j>idx) e.fromPort="c"+(j-1); } });   // shift higher cases down
}
function wfReorderSwitchCase(node, from, to){
  const cs=node.params.cases, n=cs.length;
  if(from<0||from>=n||to<0||to>=n||from===to) return;
  // Derive old→new index map by applying the same move to an index array.
  const ord=[]; for(let i=0;i<n;i++) ord.push(i);
  const [m]=ord.splice(from,1); ord.splice(to,0,m);
  const newIndexOf={}; ord.forEach((oldIdx,newIdx)=>{ newIndexOf[oldIdx]=newIdx; });
  const [moved]=cs.splice(from,1); cs.splice(to,0,moved);
  const g=wfGraph(); if(!g) return;
  g.edges.forEach(e=>{ if(e.from===node.id && /^c\d+$/.test(e.fromPort)){
    const old=parseInt(e.fromPort.slice(1));
    if(newIndexOf[old]!==undefined) e.fromPort="c"+newIndexOf[old]; } });
}
