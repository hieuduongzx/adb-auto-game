// ── Inspector ──────────────────────────────────────────────────────────────
// Flat, sectioned layout: a sticky identity header names the selection, then
// hairline-separated blocks group its parameters / note / log. No nested cards.

// Sticky identity header — icon chip + title + optional sublabel / count badge.
function wfInspId(iconName,title,sub,count){
  const id=document.createElement("div"); id.className="wf-insp-id";
  let html=`<span class="ic">${wfIco(iconName||"box")}</span>`
         + `<span class="meta"><span class="title">${escHtml(title||"")}</span>`;
  if(sub) html+=`<span class="sub">${escHtml(sub)}</span>`;
  html+="</span>";
  if(count!==undefined&&count!==null&&count!=="") html+=`<span class="count">${escHtml(String(count))}</span>`;
  id.innerHTML=html;
  return id;
}

// One flat section: optional uppercase label (+ count) then its content rows.
// An optional right-aligned action button (e.g. the Timing ▸ gear) can be
// passed in; the header becomes a flex row with the action on the far right.
function wfInspBlock(label,count,action){
  const b=document.createElement("div"); b.className="wf-insp-block";
  if(label){
    const s=document.createElement("div"); s.className="wf-insp-sec";
    s.innerHTML=`<span>${escHtml(label)}</span>`;
    if(count!==undefined&&count!==null&&count!=="") s.innerHTML+=`<span class="sec-count">${escHtml(String(count))}</span>`;
    if(action){
      const sp=document.createElement("span"); sp.className="wf-insp-sec-spacer";
      s.appendChild(sp); s.appendChild(action);
    }
    b.appendChild(s);
  }
  return b;
}

// Debug block: collapsible JSON preview + Copy, and optional Import (paste JSON
// into the textarea then apply). `getObj` is lazy so the JSON is current when
// the user copies / expands. `applyObj(parsed)` receives the parsed object and
// mutates the live entity; omit it to hide Import.
function wfInspJsonBlock(label, getObj, applyObj){
  const b=wfInspBlock("Debug JSON");
  const wrap=document.createElement("div"); wrap.className="wf-json-tool";

  const bar=document.createElement("div"); bar.className="wf-json-bar";
  const toggle=document.createElement("button"); toggle.className="wf-json-toggle"; toggle.type="button";
  toggle.innerHTML=`<svg class="wf-json-chev uico uico-0" aria-hidden="true" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg><span>Preview</span>`;
  toggle.title=`Show or edit this ${label}'s JSON`;
  const copyBtn=document.createElement("button"); copyBtn.className="btn sm"; copyBtn.type="button";
  copyBtn.innerHTML=`${wfIco("clipboard")}<span>Copy</span>`;
  copyBtn.title="Copy this "+label+"'s JSON to the clipboard";
  bar.appendChild(toggle); bar.appendChild(copyBtn);

  let importBtn=null;
  if(typeof applyObj==="function"){
    importBtn=document.createElement("button"); importBtn.className="btn sm"; importBtn.type="button";
    importBtn.innerHTML=`${wfIco("edit")}<span>Import</span>`;
    importBtn.title="Paste JSON into the box below, then click Import to apply it to this "+label;
    bar.appendChild(importBtn);
  }

  // Editable so the user can paste / tweak JSON before Import.
  const pre=document.createElement("textarea"); pre.className="wf-json-pre"; pre.spellcheck=false;
  pre.placeholder="Paste "+label+" JSON here, then click Import…";
  pre.style.display="none";

  const json=()=>{ try{ return JSON.stringify(getObj(),null,2); }catch{ return "// (unavailable)"; } };
  const openPre=(seed)=>{
    if(pre.style.display==="none"){
      if(seed!==false) pre.value=json();
      pre.style.display="block"; wrap.classList.add("open");
    }
  };
  const flashBtn=(btn, ok, msg)=>{
    if(!btn) return;
    btn.classList.remove("flash","flash-err");
    btn.classList.add(ok?"flash":"flash-err");
    const lbl=btn.querySelector("span"); const old=lbl?lbl.textContent:"";
    if(lbl&&msg) lbl.textContent=msg;
    setTimeout(()=>{ btn.classList.remove("flash","flash-err"); if(lbl&&msg) lbl.textContent=old; }, ok?900:1600);
  };
  toggle.onclick=()=>{
    const open=pre.style.display==="none";
    if(open) openPre(true);
    else { pre.style.display="none"; wrap.classList.remove("open"); }
  };
  copyBtn.onclick=async()=>{
    const txt=json();
    try{ await navigator.clipboard.writeText(txt); }
    catch{ openPre(false); pre.value=txt; pre.select(); document.execCommand&&document.execCommand("copy"); }
    flashBtn(copyBtn, true, "Copied!");
  };
  if(importBtn){
    importBtn.onclick=()=>{
      // First click with panel closed: open for paste (keep empty if blank, else seed).
      if(pre.style.display==="none"){
        openPre(true);
        pre.focus(); pre.select();
        flashBtn(importBtn, true, "Paste…");
        return;
      }
      const txt=(pre.value||"").trim();
      if(!txt){
        pre.focus();
        flashBtn(importBtn, false, "Empty");
        if(typeof uiToast==="function") uiToast("Paste "+label+" JSON into the box, then Import.","warning");
        return;
      }
      let parsed;
      try{ parsed=JSON.parse(txt); }
      catch(e){
        flashBtn(importBtn, false, "Invalid");
        if(typeof uiToast==="function") uiToast("Invalid JSON: "+e.message,"error");
        return;
      }
      try{
        if(typeof wfPushUndo==="function") wfPushUndo();
        applyObj(parsed);
        // Drop selection entries whose nodes vanished after a graph replace;
        // keep a still-valid node selection (node-level import).
        const g=typeof wfGraph==="function"?wfGraph():null;
        if(g){
          const ids=new Set((g.nodes||[]).map(n=>n.id));
          if(Array.isArray(WF.sel)) WF.sel=WF.sel.filter(id=>ids.has(id));
          if(WF.selectedNode && !ids.has(WF.selectedNode)) WF.selectedNode=null;
        }
        if(typeof wfRenderAll==="function") wfRenderAll();
        else {
          if(typeof wfRenderActivities==="function") wfRenderActivities();
          if(typeof wfRenderFunctions==="function") wfRenderFunctions();
          if(typeof wfRenderCanvas==="function") wfRenderCanvas();
          if(typeof wfRenderInspector==="function") wfRenderInspector();
        }
        if(typeof setStatus==="function") setStatus(label+" imported from JSON");
        if(typeof uiToast==="function") uiToast("Imported "+label+" JSON","success");
      }catch(e){
        flashBtn(importBtn, false, "Failed");
        if(typeof uiToast==="function") uiToast(String(e.message||e),"error");
      }
    };
  }

  wrap.appendChild(bar); wrap.appendChild(pre);
  if(importBtn){
    const hint=document.createElement("div"); hint.className="wf-json-hint";
    hint.textContent="Paste JSON above → Import applies it to this "+label+" (undoable).";
    hint.style.display="none";
    const syncHint=()=>{ hint.style.display=wrap.classList.contains("open")?"":"none"; };
    toggle.addEventListener("click", ()=>setTimeout(syncHint,0));
    importBtn.addEventListener("click", ()=>setTimeout(syncHint,0));
    wrap.appendChild(hint);
  }
  b.appendChild(wrap);
  return b;
}

function wfRenderInspector(){
  const body=$("wf-insp-body"); body.innerHTML="";
  wfRenderVarsPanel();

  // Multi-selection panel.
  if(WF.sel.length>1){
    const g=wfGraph();
    const selNodes=g?WF.sel.map(id=>g.nodes.find(n=>n.id===id)).filter(Boolean):[];

    body.appendChild(wfInspId("box", WF.sel.length+" blocks selected", null, WF.sel.length));

    const listBlock=wfInspBlock();
    const list=document.createElement("div"); list.className="wf-msel-list";
    selNodes.slice(0,8).forEach(n=>{
      const def=WF_NODES[n.type]||{};
      const row=document.createElement("div"); row.className="wf-msel-row";
      row.innerHTML=`<span class="dot"></span><span class="lbl">${escHtml((def.label||n.type)+(n.label?` · ${n.label}`:""))}</span>`;
      list.appendChild(row);
    });
    if(selNodes.length>8){
      const more=document.createElement("div"); more.className="wf-msel-more";
      more.textContent=`+${selNodes.length-8} more…`; list.appendChild(more);
    }
    listBlock.appendChild(list); body.appendChild(listBlock);

    const alignBlock=wfInspBlock("Align");
    const alignGrid=document.createElement("div"); alignGrid.className="wf-insp-grid";
    const mkAlign=(lbl,fn)=>{ const b=document.createElement("button"); b.className="btn sm"; b.textContent=lbl; b.title=lbl; b.onclick=fn; return b; };
    alignGrid.appendChild(mkAlign("← Left", ()=>{ if(!g||!selNodes.length) return; wfPushUndo(); const minX=Math.min(...selNodes.map(n=>n.x)); selNodes.forEach(n=>n.x=minX); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("→ Right",()=>{ if(!g||!selNodes.length) return; wfPushUndo(); const maxX=Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.x+(el?el.offsetWidth:158); })); selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.x=maxX-(el?el.offsetWidth:158); }); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↑ Top", ()=>{ if(!g||!selNodes.length) return; wfPushUndo(); const minY=Math.min(...selNodes.map(n=>n.y)); selNodes.forEach(n=>n.y=minY); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↓ Bottom",()=>{ if(!g||!selNodes.length) return; wfPushUndo(); const maxY=Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.y+(el?el.offsetHeight:46); })); selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.y=maxY-(el?el.offsetHeight:46); }); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↔ Center X",()=>{ if(!g||!selNodes.length) return; wfPushUndo(); const cx=(Math.min(...selNodes.map(n=>n.x))+Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.x+(el?el.offsetWidth:158); })))/2; selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.x=cx-(el?el.offsetWidth:158)/2; }); wfRenderCanvas(); }));
    alignGrid.appendChild(mkAlign("↕ Center Y",()=>{ if(!g||!selNodes.length) return; wfPushUndo(); const cy=(Math.min(...selNodes.map(n=>n.y))+Math.max(...selNodes.map(n=>{ const el=wfNodeElById(n.id); return n.y+(el?el.offsetHeight:46); })))/2; selNodes.forEach(n=>{ const el=wfNodeElById(n.id); n.y=cy-(el?el.offsetHeight:46)/2; }); wfRenderCanvas(); }));
    alignBlock.appendChild(alignGrid); body.appendChild(alignBlock);

    const actBlock=wfInspBlock("Actions");
    const actGrid=document.createElement("div"); actGrid.className="wf-insp-grid";
    const dupBtn=document.createElement("button"); dupBtn.className="btn sm"; dupBtn.textContent="Duplicate"; dupBtn.title="Ctrl+D"; dupBtn.onclick=()=>wfDuplicate(); actGrid.appendChild(dupBtn);
    const grpBtn=document.createElement("button"); grpBtn.className="btn sm"; grpBtn.textContent="Create group"; grpBtn.onclick=()=>wfGroupSelection(); actGrid.appendChild(grpBtn);
    const delBtn=document.createElement("button"); delBtn.className="btn sm err"; delBtn.textContent="Delete"; delBtn.onclick=()=>wfDeleteSelected(); actGrid.appendChild(delBtn);
    actBlock.appendChild(actGrid); body.appendChild(actBlock);

    const tipBlock=wfInspBlock();
    const tip=document.createElement("div"); tip.className="wf-insp-tip";
    tip.textContent="Ctrl+click / Shift+click to add/remove selection. Arrow keys move (Shift = 10px).";
    tipBlock.appendChild(tip); body.appendChild(tipBlock);
    return;
  }

  const node=wfNode(WF.selectedNode), act=wfCurAct(), fn=wfCurFn();
  if(node){
    const def=WF_NODES[node.type]||{label:node.type,fields:[]};
    const idEl=wfInspId(def.ico||"box", def.label||node.type, node.type);
    // Test this block alone — a small icon action tucked into the header's right
    // edge; jumps to Preview and draws match boxes (Ctrl+Enter equivalent).
    if(typeof wfCanTestNode==="function" && wfCanTestNode(node)){
      const tbtn=document.createElement("button"); tbtn.type="button"; tbtn.className="btn sm ico wf-insp-test-btn";
      tbtn.innerHTML=wfIco("target");
      tbtn.title="Test block - run this block and draw its match overlay (green = above threshold, red = best below threshold · Ctrl+Enter)";
      tbtn.onclick=()=>{ if(typeof wfRunSingleNode==="function") wfRunSingleNode(node); };
      idEl.appendChild(tbtn);
    }
    // A call block runs its whole function — the same one-click affordance the
    // testable blocks get above, so functions are runnable standalone.
    if(node.type==="call" && node.params && node.params.fn && typeof wfFnById==="function" && wfFnById(node.params.fn)){
      const fbtn=document.createElement("button"); fbtn.type="button"; fbtn.className="btn sm ico wf-insp-test-btn";
      fbtn.innerHTML=wfIco("play");
      fbtn.title="Run function - run this function's whole graph on its own (debug run, trail on its blocks)";
      fbtn.onclick=()=>{ if(typeof wfRunFunction==="function") wfRunFunction(node.params.fn); };
      idEl.appendChild(fbtn);
    }
    body.appendChild(idEl);

    const pblock=wfInspBlock("Parameters");
    if(node.type==="call"){ pblock.appendChild(wfCallPicker(node)); }
    else if(node.type==="switch" || node.type==="try_chain" || node.type==="and" || node.type==="sequence"){ pblock.appendChild(wfBranchCountEditor(node)); }
    else {
      if(!(def.fields||[]).length){
        const d=document.createElement("div"); d.className="wf-insp-tip"; d.textContent="This node has no parameters."; pblock.appendChild(d);
      }
      // Fields may declare showWhen:{key:val|[vals]} to appear only when another
      // param has a given value (e.g. Tap's x/y hide when target = found image).
      // Consecutive short coordinate-style numbers (x/y, w/h, x1/y1…) are paired
      // two-per-row so the panel stays compact instead of one tall column.
      const vis=(def.fields||[]).filter(f=>wfFieldVisible(node,f));
      for(let i=0;i<vis.length;i++){
        const f=vis[i], g=vis[i+1];
        if(f.t==="num" && WF_PAIR_KEYS.has(f.k) && g && g.t==="num" && WF_PAIR_KEYS.has(g.k)){
          pblock.appendChild(wfPairRow(node,f,g)); i++;
        } else {
          pblock.appendChild(wfFieldEl(node,f));
        }
      }
    }
    body.appendChild(pblock);

    if(node.type!=="note" && node.type!=="start" && node.type!=="try_next") body.appendChild(wfTimingField(node));
    if(node.type!=="note" && node.type!=="start" && node.type!=="try_next") body.appendChild(wfRetryField(node));
    const failBlk=wfFailShotBlock(node); if(failBlk) body.appendChild(failBlk);
    if(node.type==="try_chain" || node.type==="try_next"){
      const tip=document.createElement("div"); tip.className="wf-insp-tip wf-insp-pair-tip";
      if(node.type==="try_chain"){
        tip.innerHTML=`<b>Paired with Next branch</b> - runs arms <b>1 → 2 → …</b> on fail. Drop <b>Next branch</b> inside an arm to skip to the next arm without a real failure.`;
      } else {
        tip.innerHTML=`<b>Paired with Try in order</b> - place this inside a try arm to stop that arm and advance to the next numbered port (or <b>fail</b> if none left). Outside Try in order it does nothing.`;
      }
      body.appendChild(tip);
    }
    if(node.type!=="note") body.appendChild(wfNoteField(node));
    if(node.type!=="note") body.appendChild(wfLogField(node));
    body.appendChild(wfInspJsonBlock("Node", ()=>wfSerializeNode(node), o=>wfApplyNodeJson(node,o)));
    return;
  }

  if(fn){
    body.appendChild(wfInspId("function","Function","ƒ "+(fn.name||"")));
    const b=wfInspBlock("Function name");
    b.appendChild(wfActField("Name","text",fn.name,v=>{ fn.name=v; wfRenderFunctions(); wfRenderPalette(); const c=$("wf-cur-act"); if(c){ c.textContent="ƒ "+v; c.dataset.empty="0"; c.classList.add("is-fn"); c.title="Function · "+v; } }));
    const tip=document.createElement("div"); tip.className="wf-insp-tip"; tip.textContent="Arrange nodes for this function. It can be used as a node in any activity (drag from Functions).";
    b.appendChild(tip);
    body.appendChild(b);
    body.appendChild(wfInspJsonBlock("Function", ()=>wfSerializeFunction(fn), o=>wfApplyFunctionJson(fn,o)));
    return;
  }

  if(act){
    const typeLabel=act.type==="background"?"Background activity":"Sequence activity";
    body.appendChild(wfInspId(act.type==="background"?"layers":"play", typeLabel, act.name||""));

    const b=wfInspBlock("Configuration");
    b.appendChild(wfActField("Name","text",act.name,v=>{ act.name=v; wfRenderActivities(); const c=$("wf-cur-act"); if(c){ c.textContent=v; c.dataset.empty="0"; c.classList.remove("is-fn"); c.title="Activity · "+v; } }));
    if(act.type==="background") b.appendChild(wfActField("Interval (s)","num",act.pollInterval,v=>act.pollInterval=parseFloat(v)||1));
    else b.appendChild(wfActField("Retry count","num",act.maxRetries,v=>act.maxRetries=parseInt(v)||1));
    body.appendChild(b);


    body.appendChild(wfInspJsonBlock(act.type==="background"?"Background":"Activity", ()=>wfSerializeActivity(act), o=>wfApplyActivityJson(act,o)));

    const tipBlock=wfInspBlock();
    tipBlock.innerHTML=
      `<div class="wf-empty">
        <div class="wf-empty-t">Select a block to edit</div>
        <div class="wf-empty-s">Click a node on the canvas to see that block's parameters, note and log.</div>
        <div class="wf-empty-keys">
          <span><b>Ctrl+F</b> find block</span>
          <span><b>Del</b> delete</span>
          <span><b>Ctrl+D</b> duplicate</span>
        </div>
      </div>`;
    body.appendChild(tipBlock);
    return;
  }
  body.innerHTML=
    `<div class="wf-empty">
      <div class="wf-empty-ico" aria-hidden="true"><svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><rect width="8" height="8" x="3" y="3" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect width="8" height="8" x="13" y="13" rx="2"/></svg></div>
      <div class="wf-empty-t">No activity open</div>
      <div class="wf-empty-s">Select or create an activity in the corner panel, then drag nodes from the left palette onto the canvas.</div>
      <div class="wf-empty-keys">
        <span><b>+</b> add activity</span>
        <span><b>F1</b> shortcuts</span>
      </div>
    </div>`;
}

// Human-readable fallback for schema keys without an explicit label. Keeps
// implementation names such as `offsetX` or `max_swipes` out of the UI.
function wfFieldLabel(f){
  if(f&&f.lbl) return f.lbl;
  const key=String((f&&f.k)||"");
  const short={x:"X",y:"Y",w:"Width",h:"Height",x1:"X 1",y1:"Y 1",x2:"X 2",y2:"Y 2"};
  if(short[key]) return short[key];
  const text=key.replace(/_/g," ").replace(/([a-z0-9])([A-Z])/g,"$1 $2").trim();
  return text?text.charAt(0).toUpperCase()+text.slice(1):"Value";
}

// ── Variable picker infrastructure ───────────────────────────────────────────
// A single source of truth describing every variable the user can reference,
// with its declared type, scope (global/activity/node) and best-known value.
// Powers the combobox pickers on variable fields and the "insert variable"
// dropdown on text fields (log, message, format string…).
function wfVarInfoMap(){
  const map={};
  const walk=(vars,prefix,scope)=>{ (vars||[]).forEach(v=>{ const n=(v.name||"").trim(); if(!n) return; const full=prefix?prefix+"."+n:n; if(!map[full]) map[full]={type:v.type||"bool", scope, value:v.value, options:v.options, multiple:v.display==="toggle-group"&&!!v.multiple}; walk(v.children,full,scope); wfActiveOptionChildren(v).forEach(([opt,kids])=>walk(kids, full+"."+opt, scope)); }); };
  walk(WF.globals,"","global");
  const act=wfCurAct(); if(act) walk(act.vars,"","activity");
  const g=wfGraph(); wfGraphVarNames(g).forEach(n=>{ if(!map[n]) map[n]={type:"text", scope:"node", value:undefined}; });
  Object.keys(wfLiveVars).forEach(n=>{ if(!map[n]) map[n]={type:"text", scope:"live", value:wfLiveVars[n]}; });
  return map;
}
// Live-or-declared value + a short type hint for one variable name.
function wfVarBadgeInfo(name){
  const nm=String(name||"").trim(); if(!nm) return null;
  const map=wfVarInfoMap(); const info=map[nm]; if(!info) return null;
  const live=wfLiveVars[nm];
  const val=(live!==undefined)?live:info.value;
  return {type:info.type, scope:info.scope, value:val, live:live!==undefined};
}
const WF_VAR_SCOPE_LBL={global:"Global", activity:"Activity", node:"Node", live:"Live"};
// Group order in the variable menu — same as the Variables panel.
const WF_VAR_SCOPE_ORDER=["global","activity","node","live"];
// Floating dropdown listing every known variable (grouped by scope, filterable).
// `onPick(name)` fires with the chosen variable name. A "+ New global" row lets
// the user declare one on the spot without leaving the field.
let wfVarMenuEl=null;
function wfCloseVarMenu(){ if(wfVarMenuEl){ wfVarMenuEl.remove(); wfVarMenuEl=null; document.removeEventListener("mousedown",wfVarMenuOutside,true); } }
function wfVarMenuOutside(e){ if(wfVarMenuEl && !e.target.closest(".wf-varmenu") && !e.target.closest(".wf-var-pick")) wfCloseVarMenu(); }
function wfShowVarMenu(anchor,onPick,opts){
  wfCloseVarMenu();
  opts=opts||{};
  const menu=document.createElement("div"); menu.className="wf-varmenu"; wfVarMenuEl=menu;
  const search=document.createElement("input"); search.type="text"; search.className="wf-varmenu-search";
  search.placeholder="Search variables…"; search.spellcheck=false; search.autocomplete="off";
  menu.appendChild(search);
  const list=document.createElement("div"); list.className="wf-varmenu-list"; menu.appendChild(list);
  const map=wfVarInfoMap();
  const allowed=Array.isArray(opts.types)&&opts.types.length?new Set(opts.types):null;
  // Grouped by scope in the Variables panel's order, A→Z inside each group — a
  // plain A→Z sort interleaved the groups (Activity, Global, Activity again…).
  const scopeRank=s=>{ const i=WF_VAR_SCOPE_ORDER.indexOf(s); return i<0?WF_VAR_SCOPE_ORDER.length:i; };
  const names=Object.keys(map).filter(n=>!allowed||allowed.has(map[n].type))
    .sort((a,b)=>scopeRank(map[a].scope)-scopeRank(map[b].scope) || a.localeCompare(b));
  const curAct=typeof wfCurAct==="function"?wfCurAct():null;
  function render(filter){
    list.innerHTML="";
    const f=(filter||"").trim().toLowerCase();
    const shown=names.filter(n=>!f||n.toLowerCase().includes(f));
    if(!shown.length){ const e=document.createElement("div"); e.className="wf-varmenu-empty"; e.textContent=names.length?"No match.":"No variables yet."; list.appendChild(e); }
    let lastScope=null;
    shown.forEach(n=>{
      const info=map[n];
      if(info.scope!==lastScope){
        lastScope=info.scope;
        const s=document.createElement("div"); s.className="wf-varmenu-sep";
        s.textContent=(WF_VAR_SCOPE_LBL[info.scope]||info.scope)+(info.scope==="activity"&&curAct&&curAct.name?" · "+curAct.name:"");
        list.appendChild(s);
      }
      const row=document.createElement("button"); row.type="button"; row.className="wf-varmenu-item";
      const badge=wfVarBadgeInfo(n);
      const val=badge&&badge.value!==undefined&&badge.value!==null&&badge.value!==""?String(badge.value):"";
      row.innerHTML=`<span class="vn">${escHtml(n)}</span><span class="vt">${escHtml(info.type||"")}</span>`+(val?`<span class="vv">${escHtml(val)}</span>`:"");
      row.onclick=()=>{ onPick(n); wfCloseVarMenu(); };
      list.appendChild(row);
    });
  }
  render("");
  const addGlobal=document.createElement("button"); addGlobal.type="button"; addGlobal.className="wf-varmenu-add";
  addGlobal.innerHTML=`${wfIco("pin")}<span>New global variable…</span>`;
  addGlobal.onclick=()=>{
    uiPrompt({title:"New global variable", label:"Title", placeholder:"e.g. Đọc email"}).then(v=>{
      const title=(v||"").trim();
      if(!title) return;
      wfPushUndoDebounced();
      if(!Array.isArray(WF.globals)) WF.globals=[];
      const nm=wfUniqVarName(wfVarSlug(title)||"g"+(WF.globals.length+1), WF.globals.map(x=>x.name));
      WF.globals.push({name:nm, label:title, type:opts.newType||"text", value:"", children:[]});
      wfRenderVarsPanel(); onPick(nm); wfCloseVarMenu();
    });
  };
  menu.appendChild(addGlobal);
  const act=typeof wfCurAct==="function"?wfCurAct():null;
  if(act){
    const addLocal=document.createElement("button"); addLocal.type="button"; addLocal.className="wf-varmenu-add";
    addLocal.innerHTML=`${wfIco("pin")}<span>New local variable…</span>`;
    addLocal.onclick=()=>{
      uiPrompt({title:"New local variable", label:`Title (activity «${act.name||"activity"}»)`, placeholder:"e.g. Đọc email"}).then(v=>{
        const title=(v||"").trim();
        if(!title) return;
        wfPushUndoDebounced();
        if(!Array.isArray(act.vars)) act.vars=[];
        const nm=wfUniqVarName(wfVarSlug(title)||"v"+(act.vars.length+1), act.vars.map(x=>x.name));
        act.vars.push({name:nm, label:title, type:opts.newType||"text", value:"", children:[]});
        wfRenderVarsPanel(); onPick(nm); wfCloseVarMenu();
      });
    };
    menu.appendChild(addLocal);
  }
  document.body.appendChild(menu);
  const r=anchor.getBoundingClientRect();
  const mw=Math.max(220, r.width);
  menu.style.width=mw+"px";
  let left=Math.min(r.left, window.innerWidth-mw-8);
  let top=r.bottom+4;
  if(top+260>window.innerHeight) top=Math.max(8, r.top-264);
  menu.style.left=Math.max(8,left)+"px"; menu.style.top=top+"px";
  search.oninput=()=>render(search.value);
  setTimeout(()=>{ search.focus(); document.addEventListener("mousedown",wfVarMenuOutside,true); },0);
}
// Small "𝑥" button that opens the variable menu beside a field.
function wfVarPickBtn(onPick,title,opts){
  const b=document.createElement("button"); b.type="button"; b.className="btn sm ico wf-var-pick";
  b.title=title||"Pick a variable";
  b.innerHTML='<svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  b.onclick=(e)=>{ e.stopPropagation(); wfShowVarMenu(b,onPick,opts); };
  return b;
}
// Live value / type badge shown beside a variable-bound field. Returns the
// element (updates in place via .refresh(name)).
function wfVarBadge(){
  const bd=document.createElement("span"); bd.className="wf-var-badge";
  bd.refresh=(name)=>{
    const info=wfVarBadgeInfo(name);
    if(!info){ bd.style.display="none"; bd.innerHTML=""; return; }
    bd.style.display="";
    const val=(info.value===undefined||info.value===null||info.value==="")?"∅":String(info.value);
    bd.innerHTML=`<span class="t">${escHtml(info.type||"")}</span><span class="v${info.live?" live":""}">${escHtml(val)}</span>`;
    bd.title=`${name} · ${WF_VAR_SCOPE_LBL[info.scope]||info.scope}`+(info.live?" · runtime value":" · declared value");
  };
  return bd;
}

// A field that NAMES a variable to write/read (set_var name, read_var name…).
// Combobox: free-text input + variable menu button + a live type/value badge.
function wfVarNameField(node,f){
  const row=document.createElement("div"); row.className="wf-field wf-var-field";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; row.appendChild(lab);
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-var-input";
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.placeholder=f.ph||"variable name";
  const badge=wfVarBadge();
  const sync=()=>badge.refresh(inp.value);
  // The sibling Value control follows this variable's type live; the value
  // itself is only corrected once the name is committed (blur / pick), so
  // typing past a bool variable's name on the way to another doesn't rewrite it.
  inp.oninput=()=>{ wfPushUndoDebounced(); node.params[f.k]=inp.value; wfUpdNodeSum(node); wfRenderVarsPanel(); sync(); wfRefreshVarValues(row.parentElement); };
  inp.onchange=()=>{ wfNormalizeVarValue(node); wfRefreshVarValues(row.parentElement); };
  const pick=wfVarPickBtn(name=>{ inp.value=name; node.params[f.k]=name; wfPushUndoDebounced(); wfUpdNodeSum(node); wfRenderVarsPanel(); sync();
    wfNormalizeVarValue(node); wfRefreshVarValues(row.parentElement); }, "Choose an existing variable");
  row.appendChild(inp); row.appendChild(pick); row.appendChild(badge);
  sync();
  return row;
}

// ── Typed variable values ────────────────────────────────────────────────────
// Blocks whose `value` is assigned to / compared with the variable in `name`.
// Their Value control follows that variable's declared type instead of always
// being free text: a bool gets true | false, a select its options.
const WF_VAR_VALUE_NODES = new Set(["set_var","if_var","loop_until_var"]);
// Text operators compare as strings — a true/false or option pick would mislead.
const WF_TEXT_CMP_OPS = new Set(["contains","!contains","starts","ends","regex"]);

// What the `value` field should offer, from the declared type of the named
// variable: {type:"bool"|"select", opts:[…]} for a quick pick, {type:"number"}
// for a numeric hint, or null for plain text.
function wfVarValueKind(node,f){
  if(!f || f.k!=="value" || !WF_VAR_VALUE_NODES.has(node.type)) return null;
  const info=wfVarInfoMap()[String(node.params.name||"").trim()];
  if(!info) return null;
  const op=String(node.params.op||"==");
  const equality=node.type==="set_var" || op==="==" || op==="!=";
  if(info.type==="bool") return equality ? {type:"bool", opts:["true","false"]} : null;
  if(info.type==="select"){
    const opts=(info.options||[]).map(String).filter(Boolean);
    if(info.multiple){
      if(node.type==="set_var" || op==="==" || op==="!=") return {type:"multi",opts};
      return (op==="contains"||op==="!contains")&&opts.length?{type:"select",opts}:null;
    }
    const allowedOps = equality || op==="contains" || op==="!contains";
    return allowedOps && opts.length ? {type:"select", opts} : null;
  }
  if(info.type==="number" && !WF_TEXT_CMP_OPS.has(op)) return {type:"number"};
  return null;
}
// The option a stored value stands for ("True" → "true"), or null when it is
// something else (another variable's name, a {placeholder}, a stray literal).
function wfVarValueOpt(kind,raw){
  if(!kind || !kind.opts) return null;
  if(kind.type==="multi") return Array.isArray(raw)?raw:null;
  const s=String(raw===undefined||raw===null?"":raw).trim();
  if(kind.type==="bool"){ const l=s.toLowerCase(); return kind.opts.includes(l)?l:null; }
  return kind.opts.includes(s)?s:null;
}
// After the variable or operator changes, move a value that no longer fits the
// new type onto it — "0" becomes "true" for a bool, an unknown option the first
// option. A value that names another variable is left alone.
function wfNormalizeVarValue(node){
  const kind=wfVarValueKind(node,{k:"value"});
  if(!kind || !kind.opts) return;
  if(kind.type==="multi"){
    if(Array.isArray(node.params.value)||wfVarBadgeInfo(String(node.params.value||""))) return;
    wfPushUndoDebounced(); node.params.value=kind.opts.includes(node.params.value)?[node.params.value]:[];
    wfUpdNodeSum(node); return;
  }
  const raw=node.params.value;
  const cur=String(raw===undefined||raw===null?"":raw).trim();
  if(wfVarBadgeInfo(cur)) return;
  const opt=wfVarValueOpt(kind,cur);
  if(opt!==null && opt===raw) return;
  wfPushUndoDebounced();
  node.params.value = opt!==null ? opt : kind.opts[0];
  wfUpdNodeSum(node);
}
// Rebuild the typed Value controls beside a Name / Operator field that changed.
function wfRefreshVarValues(container){
  if(!container) return;
  container.querySelectorAll(".wf-var-field").forEach(r=>{ if(r._varRefresh) r._varRefresh(); });
}

// A VALUE field that may be a literal OR a reference to another variable
// (loop count, set_var value, if_var value, calc_var value). Picking a variable
// replaces the whole value with its name — the engine resolves a bare name to
// that variable's live value at run time. For a typed variable (see
// wfVarValueKind) the literal is a one-click pick instead of free text.
function wfVarRefField(node,f){
  const row=document.createElement("div"); row.className="wf-field wf-var-field";
  const set=v=>{
    const hadFocus=row.contains(document.activeElement);
    wfPushUndoDebounced(); node.params[f.k]=v; wfUpdNodeSum(node); if(f.refresh){ wfRenderCanvas(); wfRefreshNodeLogs(node); }
    build();
    if(hadFocus){ const el=row.querySelector(".wf-val-opt.on, .wf-val-select, .wf-var-input"); if(el) el.focus(); }
  };
  function build(){
    row.innerHTML="";
    const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; row.appendChild(lab);
    const kind=wfVarValueKind(node,f);
    const cur=node.params[f.k]!==undefined?node.params[f.k]:"";
    const opt=wfVarValueOpt(kind,cur);
    const pick=wfVarPickBtn(name=>set(name), "Use a variable as this value");

    if(kind&&kind.type==="multi"&&Array.isArray(cur)){
      const choices=document.createElement("div"); choices.className="wf-option-choices";
      kind.opts.forEach(option=>{
        const label=document.createElement("label"); label.className="wf-option-choice";
        const input=document.createElement("input"); input.type="checkbox"; input.checked=cur.includes(option);
        input.onchange=()=>set(input.checked?[...cur,option]:cur.filter(o=>o!==option));
        const text=document.createElement("span"); text.textContent=option; label.append(input,text); choices.appendChild(label);
      });
      row.append(choices,pick); return;
    }

    if(kind && kind.opts && kind.opts.length>0){
      // Short option sets read best as a segmented pick; long ones as a dropdown.
      const fits=kind.type==="bool" || (kind.opts.length<=3 && kind.opts.join("").length<=18);
      if(fits){
        const seg=document.createElement("div"); seg.className="wf-val-seg";
        seg.setAttribute("role","radiogroup"); seg.setAttribute("aria-label",wfFieldLabel(f));
        kind.opts.forEach(o=>{
          const b=document.createElement("button"); b.type="button";
          b.className="wf-val-opt"+(o===opt?" on":"")+(kind.type==="bool"?" is-"+o:"");
          b.textContent=o; b.title=o;
          b.setAttribute("role","radio"); b.setAttribute("aria-checked",String(o===opt));
          b.onclick=()=>{ if(o!==opt) set(o); };
          seg.appendChild(b);
        });
        row.appendChild(seg);
      } else {
        const sel=document.createElement("select"); sel.className="wf-val-select";
        kind.opts.forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; if(o===opt) op.selected=true; sel.appendChild(op); });
        sel.onchange=()=>set(sel.value);
        row.appendChild(sel);
      }
      row.appendChild(pick);
      return;
    }

    const numeric=f.t==="num" || (kind && kind.type==="number");
    const inp=document.createElement("input"); inp.type="text";  // text so a var name is typeable even on numeric fields
    inp.className="wf-var-input"; inp.inputMode=numeric?"decimal":"text";
    inp.value=cur;
    inp.placeholder=f.ph||(numeric?"number or variable":"value or variable");
    const badge=wfVarBadge();
    const sync=()=>{ const s=String(inp.value||"").trim(); badge.refresh(wfVarBadgeInfo(s)?s:""); };
    inp.oninput=()=>{ wfPushUndoDebounced();
      // Keep numeric literals as numbers; leave variable names / expressions as text.
      const s=inp.value;
      node.params[f.k]= (f.t==="num" && s!=="" && !isNaN(s) && wfVarBadgeInfo(String(s).trim())===null) ? parseFloat(s) : s;
      wfUpdNodeSum(node); if(f.k==="timeout") wfUpdNodeTimeoutChip(node); if(f.refresh){ wfRenderCanvas(); wfRefreshNodeLogs(node); } sync(); };
    // Typing a valid option by hand ("false") switches back to the quick pick.
    inp.onchange=()=>{ if(wfVarValueOpt(kind,inp.value)!==null) set(wfVarValueOpt(kind,inp.value)); };
    row.appendChild(inp); row.appendChild(pick);
    if(kind && kind.opts && kind.opts.length>0){
      const quick=document.createElement("button"); quick.type="button"; quick.className="btn sm ico wf-var-pick wf-val-quick";
      quick.title=kind.type==="bool" ? "Pick true / false" : "Pick one of the options";
      quick.setAttribute("aria-label",quick.title);
      quick.innerHTML=uiIco("toggle-left","uico-1");
      quick.onclick=e=>{ e.stopPropagation(); set(kind.type==="multi"?[]:kind.opts[0]); };
      row.appendChild(quick);
    }
    row.appendChild(badge);
    sync();
  }
  row._varRefresh=build;
  build();
  return row;
}

// A Windows path may be a literal selected from disk or a path/text variable.
// Keeping both actions beside one input avoids forcing users to copy paths by hand.
function wfPathField(node,f){
  const row=document.createElement("div"); row.className="wf-field wf-var-field wf-path-field";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; row.appendChild(lab);
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-var-input";
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.placeholder=f.ph||(f.pickFolder?"folder or path variable":"file or path variable");
  const badge=wfVarBadge();
  const commit=()=>{ wfPushUndoDebounced(); node.params[f.k]=inp.value; wfUpdNodeSum(node); badge.refresh(wfVarBadgeInfo(inp.value)?inp.value:""); };
  inp.oninput=commit;
  const variable=wfVarPickBtn(name=>{ inp.value=name; commit(); },"Use a path variable",{types:["path","text"],newType:"path"});
  const browse=document.createElement("button"); browse.type="button"; browse.className="btn sm ico wf-path-browse";
  browse.innerHTML=wfIco("folder"); browse.title=f.pickFolder?"Choose folder…":"Choose file…";
  browse.onclick=async()=>{
    const current=wfVarBadgeInfo(inp.value)?"":inp.value;
    const p=f.pickFolder?await api().pick_folder(current||""):await api().pick_file(current||"");
    if(p){ inp.value=p; commit(); }
  };
  row.appendChild(inp); row.appendChild(variable); row.appendChild(browse); row.appendChild(badge);
  badge.refresh(wfVarBadgeInfo(inp.value)?inp.value:"");
  return row;
}

// "insert {variable}" button for free-text fields that support {name}
// placeholder substitution (log message, format string, notify…). Inserts at
// the caret so the user can weave variables into a sentence.
function wfInsertVarBtn(inp){
  const b=document.createElement("button"); b.type="button"; b.className="btn sm ico wf-var-pick";
  b.title="Insert a variable placeholder {name}";
  b.innerHTML='<svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/></svg>';
  b.onclick=(e)=>{ e.stopPropagation(); wfShowVarMenu(b,name=>{
    const token="{"+name+"}";
    const s=inp.value||""; const a=inp.selectionStart??s.length, z=inp.selectionEnd??s.length;
    inp.value=s.slice(0,a)+token+s.slice(z);
    const pos=a+token.length; inp.focus(); try{ inp.setSelectionRange(pos,pos); }catch{}
    inp.dispatchEvent(new Event("input",{bubbles:true}));
  }); };
  return b;
}

function wfCallPicker(node){
  const row=document.createElement("div"); row.className="wf-field";
  const l=document.createElement("label"); l.textContent="function"; row.appendChild(l);
  const sel=document.createElement("select");
  if(!WF.functions.length){ const o=document.createElement("option"); o.value=""; o.textContent="(no functions)"; sel.appendChild(o); }
  WF.functions.forEach(fn=>{ const o=document.createElement("option"); o.value=fn.id; o.textContent=fn.name; if(fn.id===node.params.fn)o.selected=true; sel.appendChild(o); });
  sel.onchange=()=>{ wfPushUndoDebounced(); node.params.fn=sel.value; wfRenderCanvas(); };
  row.appendChild(sel); return row;
}

// Universal per-node timing: a pause before the block runs and a pause after it
// finishes (before the next block). Stored top-level like note/log, applied by
// the engine around every block — see src/workflow/engine.py _walk.
// The header's ⚙ opens the project-wide defaults dialog (wfNodeDefaultsModal):
// whatever is set there becomes the seed for every NEWLY-created block, so the
// delay/retry fields below show those values on creation.
function wfTimingField(node){
  const b=wfInspBlock("Timing",undefined,wfNodeDefaultsBtn());
  const mk=(key,label,hint)=>{
    const row=document.createElement("div"); row.className="wf-field";
    const l=document.createElement("label"); l.textContent=label; l.title=hint; row.appendChild(l);
    const inp=document.createElement("input"); inp.type="number"; inp.min="0"; inp.step="0.5";
    inp.value=(node[key]!==undefined&&node[key]!==null&&node[key]!==0)?node[key]:"";
    inp.placeholder="0";
    inp.oninput=()=>{ wfPushUndoDebounced(); node[key]=parseFloat(inp.value)||0; wfUpdNodeTiming(node); };
    row.appendChild(inp);
    const unit=document.createElement("span"); unit.className="hz-unit"; unit.textContent="s"; row.appendChild(unit);
    return row;
  };
  const pair=document.createElement("div"); pair.className="wf-field-pair";
  pair.appendChild(mk("delayBefore","Before","Wait this many seconds before running this block (e.g. wait for the screen to stabilize before finding an image)."));
  pair.appendChild(mk("delayAfter","After","After this block runs, wait this many seconds before moving to the next block."));
  b.appendChild(pair);
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.innerHTML="Idle wait <b>before</b> / <b>after</b> this block runs (seconds).";
  b.appendChild(hint);
  return b;
}

// ── Project-wide node defaults ────────────────────────────────────────────────
// The ⚙ next to "Timing" / "Failure handling" opens this dialog. Values set here
// become WF.nodeDefaults, which wfNewNode stamps onto every newly-created block.
// "Apply to existing blocks" updates every node already in the flow too (an
// overwrite, not a merge), so it's a separate explicit button.
function wfNodeDefaultsBtn(){
  const b=document.createElement("button"); b.type="button"; b.className="btn sm ico wf-insp-sec-gear";
  b.innerHTML=wfIco("settings");
  b.title="Set project-wide defaults for new blocks (Before/After wait, Retry, failure screenshot)";
  b.setAttribute("aria-label","Set project-wide node defaults");
  b.onclick=e=>{ e.stopPropagation(); wfNodeDefaultsModal(); };
  return b;
}
function wfGetNodeDefaults(){
  const d=(typeof WF!=="undefined"&&WF.nodeDefaults)||{};
  return { delayBefore:parseFloat(d.delayBefore)||0, delayAfter:parseFloat(d.delayAfter)||0,
    retryCount:parseInt(d.retryCount,10)||0, retryDelay:parseFloat(d.retryDelay)||0,
    screenshotOnFail:!!d.screenshotOnFail };
}
function wfNodeDefaultsModal(){
  if(typeof uiModal!=="function") return;
  let boxes={}, shotCb=null;
  const numRow=(id,label,hint)=>{
    const row=document.createElement("div"); row.className="wf-field";
    const l=document.createElement("label"); l.textContent=label; l.title=hint||""; row.appendChild(l);
    const inp=document.createElement("input"); inp.type="number"; inp.min="0"; inp.step="0.5";
    inp.value=""; row.appendChild(inp); boxes[id]=inp;
    const unit=document.createElement("span"); unit.className="hz-unit"; unit.textContent="s"; row.appendChild(unit);
    return row;
  };
  const cur=wfGetNodeDefaults();

  const body=el=>{
    const tip=document.createElement("div"); tip.className="wf-insp-tip";
    tip.innerHTML="These become the default <b>Before/After wait</b> &amp; <b>failure handling</b> for every <i>new</i> block you drop onto the canvas. They are stored in the workflow file.";
    el.appendChild(tip);

    const group=document.createElement("div"); group.className="wf-insp-grid"; group.style.marginTop="8px";
    group.appendChild(numRow("delayBefore","Before wait","Seconds to pause before a new block runs"));
    group.appendChild(numRow("delayAfter","After wait","Seconds to pause after a new block runs"));
    group.appendChild(numRow("retryCount","Retries","Automatic retries when a new block fails"));
    group.appendChild(numRow("retryDelay","Retry wait","Seconds between retry attempts"));
    boxes.delayBefore.value=cur.delayBefore||""; boxes.delayBefore.placeholder=cur.delayBefore?"":0;
    boxes.delayAfter.value=cur.delayAfter||""; boxes.delayAfter.placeholder=cur.delayAfter?"":0;
    boxes.retryCount.value=cur.retryCount||""; boxes.retryCount.placeholder=cur.retryCount?"":0;
    boxes.retryDelay.value=cur.retryDelay||""; boxes.retryDelay.placeholder=cur.retryDelay?"":0;
    el.appendChild(group);

    const shot=document.createElement("div"); shot.className="wf-field";
    const l=document.createElement("label"); l.textContent="Screenshot on fail"; shot.appendChild(l);
    const cb=document.createElement("span"); cb.className="cb"+(cur.screenshotOnFail?" checked":""); cb.innerHTML='<svg class="uico uico-0" aria-hidden="true" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
    cb.onclick=()=>{ cb.classList.toggle("checked",!cb.classList.contains("checked")); };
    shot.appendChild(cb);
    el.appendChild(shot);
    shotCb=cb;

    const applyExisting=document.createElement("button"); applyExisting.type="button"; applyExisting.className="btn sm";
    applyExisting.textContent="Apply to existing blocks";
    applyExisting.title="Overwrite every node already in the flow with these values (timing + failure handling)";
    applyExisting.onclick=()=>{
      WF.nodeDefaults=wfReadDefaults(boxes,shotCb);
      wfApplyNodeDefaults(true);
      uiModalClose(true);
      uiToast("Defaults saved and applied to every block.","success");
    };
    el.appendChild(applyExisting);
  };

  uiModal({
    title:"Project node defaults",
    width:"380px",
    body: el=>{ body(el); },
    buttons:[
      {label:"Cancel", value:false},
      {label:"Save defaults", value:true, kind:"accent"},
    ],
  }).then(v=>{
    if(!v) return;
    WF.nodeDefaults=wfReadDefaults(boxes,shotCb);
    if(typeof wfMarkDirty==="function") wfMarkDirty();
    uiToast("Node defaults saved - new blocks will use them.","success");
  });
}
// Read the dialog's inputs into a WF.nodeDefaults-shaped object.
function wfReadDefaults(boxes,shotCb){
  return { delayBefore:parseFloat(boxes.delayBefore.value)||0,
    delayAfter:parseFloat(boxes.delayAfter.value)||0,
    retryCount:parseInt(boxes.retryCount.value,10)||0,
    retryDelay:parseFloat(boxes.retryDelay.value)||0,
    screenshotOnFail:!!(shotCb&&shotCb.classList.contains("checked")) };
}
// Stamp the current defaults onto every node in the live flow (all activities +
// functions). Shares the field names wfNewNode uses so a "Apply to existing
// blocks" call produces the same shape as a fresh node.
function wfApplyNodeDefaults(includeRetry){
  const nd=wfGetNodeDefaults();
  const apply=n=>{
    if(!n||n.type==="start") return;
    n.delayBefore=nd.delayBefore; n.delayAfter=nd.delayAfter;
    if(includeRetry){ n.retryCount=nd.retryCount; n.retryDelay=nd.retryDelay; n.screenshotOnFail=nd.screenshotOnFail; }
    if(typeof wfUpdNodeTiming==="function") wfUpdNodeTiming(n);
    if(typeof wfUpdNodeRetry==="function") wfUpdNodeRetry(n);
  };
  const walkGraph=g=>{ (g&&g.nodes||[]).forEach(apply); };
  (WF.activities||[]).forEach(a=>walkGraph(a.graph));
  (WF.functions||[]).forEach(f=>walkGraph(f.graph));
  wfMarkDirty();
}

function wfUpdNodeTiming(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  // The chips are absolutely positioned under the block, so placement in the
  // DOM doesn't matter — just swap the whole badge row out.
  const old=el.querySelector(".wf-node-delay"); if(old) old.remove();
  const html=wfDelayChipsHtml(node);
  if(html) el.insertAdjacentHTML("beforeend", html);
}
// Same in-place swap for the timeout corner badge, called from every oninput
// that can change params.timeout. A badge mid-countdown is left alone — the
// run's own deadline is what it's showing.
function wfUpdNodeTimeoutChip(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  const old=el.querySelector(".wf-node-timeout");
  if(old && old.classList.contains("counting")) return;
  if(old) old.remove();
  const html=wfTimeoutChipHtml(node);
  if(html) el.insertAdjacentHTML("beforeend", html);
}

function wfRetryField(node){
  const b=wfInspBlock("Failure handling",undefined,wfNodeDefaultsBtn());
  const mkNum=(key,label,step)=>{
    const row=document.createElement("div"); row.className="wf-field";
    const l=document.createElement("label"); l.textContent=label; row.appendChild(l);
    const inp=document.createElement("input"); inp.type="number"; inp.min="0"; inp.step=step||"1";
    inp.value=(node[key]!==undefined&&node[key]!==null&&node[key]!==0)?node[key]:"";
    inp.placeholder="0";
    inp.oninput=()=>{ wfPushUndoDebounced(); node[key]=key==="retryCount"?(parseInt(inp.value,10)||0):(parseFloat(inp.value)||0); wfUpdNodeRetry(node); };
    row.appendChild(inp); return row;
  };
  const pair=document.createElement("div"); pair.className="wf-field-pair";
  pair.appendChild(mkNum("retryCount","Retries","1"));
  pair.appendChild(mkNum("retryDelay","Retry wait","0.5"));
  b.appendChild(pair);
  const row=document.createElement("div"); row.className="wf-field";
  const l=document.createElement("label"); l.textContent="Screenshot"; row.appendChild(l);
  const cb=document.createElement("span"); cb.className="cb"+(node.screenshotOnFail?" checked":""); cb.innerHTML='<svg class="uico uico-0" aria-hidden="true" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
  cb.onclick=()=>{ wfPushUndoDebounced(); node.screenshotOnFail=!node.screenshotOnFail; cb.classList.toggle("checked", !!node.screenshotOnFail); wfUpdNodeRetry(node); };
  row.appendChild(cb);
  const hint=document.createElement("div"); hint.className="wf-insp-tip"; hint.textContent="Retry re-runs on failure; screenshot saves the device image if the last attempt fails.";
  b.appendChild(row); b.appendChild(hint);
  return b;
}
function wfUpdNodeRetry(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  const parts=[];
  if(node.retryCount) parts.push(`${wfIco("loop")}<span>Retry ${node.retryCount}×</span>`);
  if(node.screenshotOnFail) parts.push(`${wfIco("camera")}<span>Screenshot on fail</span>`);
  let n=el.querySelector(".wf-node-retry");
  if(parts.length){
    if(!n){ n=document.createElement("div"); n.className="wf-node-retry"; const delay=el.querySelector(".wf-node-delay"), sum=el.querySelector(".wf-node-sum"); const anchor=delay||sum; if(anchor) anchor.after(n); else el.appendChild(n); el.classList.remove("collapsed"); }
    n.innerHTML=parts.join("");
  } else if(n){ n.remove(); }
}

// Failure screenshot from the last test run (engine saves one on every action's
// final failed attempt; see node_fail_shot in events.js). Thumbnail + click or
// "Open image" to open full-size in the OS viewer. Cleared when the next run starts.
function wfFailShotBlock(node){
  const path=(typeof wfFailShots!=="undefined") ? wfFailShots[node.id] : null;
  if(!path) return null;
  const b=wfInspBlock("Failure screenshot");
  const img=document.createElement("img");
  img.className="wf-fail-shot"; img.title="The screen when this block failed - click to open the original image";
  img.addEventListener("click",()=>{ try{ api().open_path(path); }catch{} });
  try{ api().image_thumbnail(path, 460).then(d=>{ if(d) img.src=d; else img.remove(); }); }catch{}
  b.appendChild(img);
  const row=document.createElement("div"); row.className="wf-field";
  const p=document.createElement("span"); p.className="wf-fail-shot-path";
  p.textContent=path.split(/[\\/]/).pop(); p.title=path;
  const open=document.createElement("button"); open.className="btn sm"; open.textContent="Open image";
  open.onclick=()=>{ try{ api().open_path(path); }catch{} };
  row.appendChild(p); row.appendChild(open); b.appendChild(row);
  return b;
}

function wfNoteField(node){
  const b=wfInspBlock("Note");
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-insp-input";
  inp.placeholder="note for this node…"; inp.value=node.note||"";
  inp.oninput=()=>{ wfPushUndoDebounced(); node.note=inp.value; wfUpdNodeNote(node); };
  b.appendChild(inp);
  return b;
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
  const b=wfInspBlock("Run logs");
  b.classList.add("wf-run-logs");
  node.outputLogs=wfOutputLogValues(node);
  const add=({key,label})=>{
    const row=document.createElement("div"); row.className="wf-field full wf-run-log-field";
    const lab=document.createElement("label"); lab.textContent=label; row.appendChild(lab);
    const inpRow=document.createElement("div"); inpRow.className="wf-run-log-input";
    const inp=document.createElement("input"); inp.type="text"; inp.className="wf-insp-input";
    inp.placeholder=key==="input"?"When entering this block…":key==="$error"?"When the action fails…":key==="$done"?"When this block finishes…":"Only when this exit is taken…";
    inp.setAttribute("aria-label",label);
    inp.value=key==="input"?(node.log||""):(node.outputLogs[key]||"");
    inp.oninput=()=>{ wfPushUndoDebounced(); if(key==="input") node.log=inp.value; else node.outputLogs[key]=inp.value; wfUpdNodeLog(node); };
    inpRow.appendChild(inp); inpRow.appendChild(wfInsertVarBtn(inp));
    row.appendChild(inpRow); b.appendChild(row);
  };
  wfNodeLogFields(node).forEach(add);
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.innerHTML='Only the log for the chosen exit runs. Leave a field blank to skip it. Input runs before execution; exit logs use updated <code>{variable_name}</code> values.';
  b.appendChild(hint);
  return b;
}
function wfRefreshNodeLogs(node){
  const block=document.querySelector("#wf-insp-body .wf-run-logs");
  if(block) block.replaceWith(wfLogField(node));
}
function wfUpdNodeLog(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  el.querySelectorAll(".wf-node-log").forEach(n=>n.remove());
  const thumb=el.querySelector(".wf-node-thumb");
  wfNodeLogEntries(node).forEach(({key,tag,text})=>{
    const n=document.createElement("div");
    n.className=`wf-node-log wf-node-log-${key==="input"?"in":"out"}`;
    const badge=document.createElement("b"); badge.textContent=tag; n.appendChild(badge);
    n.appendChild(document.createTextNode(text));
    if(thumb) el.insertBefore(n,thumb); else el.appendChild(n);
    el.classList.remove("collapsed");
  });
}

function wfActField(label,t,val,onset){
  const row=document.createElement("div"); row.className="wf-field";
  const l=document.createElement("label"); l.textContent=label; row.appendChild(l);
  const inp=document.createElement("input"); inp.type=t==="num"?"number":"text"; inp.value=val;
  inp.oninput=()=>{ wfPushUndoDebounced(); onset(inp.value); }; row.appendChild(inp); return row;
}

// Per-activity variables.
const wfActivityVarsExpanded=new WeakSet();
function wfVarsSection(act){
  if(!act.vars) act.vars=[];
  const b=wfInspBlock("Activity variables", act.vars.length);
  b.classList.add("wf-activity-vars");
  if(!act.vars.length){
    const empty=document.createElement("div"); empty.className="wf-vars-context";
    empty.textContent="No activity variables yet."; b.appendChild(empty);
  }
  act.vars.forEach((v,idx)=>wfBuildVarTree(act,v,idx,b));
  b.appendChild(wfVarAddBtn(act));
  return b;
}
function wfRefreshVarViews(){
  if(typeof wfRenderVarsPanel==="function") wfRenderVarsPanel();
  if(typeof wfRenderInspector==="function") wfRenderInspector();
}
// Identity delete across both a variable's own children and each select option's children.
function wfRemoveVarFromTree(list, target){
  if(!Array.isArray(list)) return false;
  const i=list.indexOf(target);
  if(i>=0){ list.splice(i,1); return true; }
  return list.some(parent=>{
    if(wfRemoveVarFromTree(parent.children||[], target)) return true;
    const oc=parent.optionChildren;
    if(!oc||typeof oc!=="object"||Array.isArray(oc)) return false;
    return Object.keys(oc).some(key=>wfRemoveVarFromTree(oc[key], target));
  });
}
function wfActiveOptionChildren(v){
  if(!v||v.type!=="select") return [];
  const oc=v.optionChildren;
  if(!oc||typeof oc!=="object"||Array.isArray(oc)) return [];
  const multi=v.display==="toggle-group"&&!!v.multiple;
  const active=multi?(Array.isArray(v.value)?v.value:[v.value]):[v.value];
  return active.filter(opt=>Array.isArray(oc[opt])).map(opt=>[opt, oc[opt]]);
}
function wfOptionChildList(v, option, create){
  if(!v.optionChildren||typeof v.optionChildren!=="object"||Array.isArray(v.optionChildren)){
    if(!create) return [];
    v.optionChildren={};
  }
  if(!Array.isArray(v.optionChildren[option])){
    if(!create) return [];
    v.optionChildren[option]=[];
  }
  return v.optionChildren[option];
}
function wfVarAddBtn(act, parentVar, parentIdx){
  const add=document.createElement("button"); add.type="button"; add.className="btn sm wf-activity-var-add"; add.innerHTML=wfIco("plus")+" Variable";
  add.onclick=()=>{
    wfPushUndoDebounced();
    const arr=parentVar?parentVar.children:(act.vars);
    const n=arr.length+1; const prefix=parentVar?(parentVar.name||"sub")+"_":"";
    arr.push({name:prefix+wfVarSlug("Setting "+n), label:"Setting "+n, type:"bool", value:false, children:[]});
    wfActivityVarsExpanded.add(arr[arr.length-1]);
    wfRenderInspector();
  };
  return add;
}
// Nested-variable indent step — one 4pt-scale unit (var(--s4), 12px) per depth,
// shared with wfBuildGlobChildren (render.js) so activity vars and globals nest identically.
const WF_VAR_INDENT = 12;
function wfBuildVarTree(act,v,idx,container,depth,ctx){
  depth=depth||0;
  ctx=ctx||{};
  v.children=v.children||[];
  const card=wfVarRow(act,v,idx,depth,ctx);
  container.appendChild(card);
  const full=(ctx.prefix?ctx.prefix+".":"")+(v.name||"");
  const childCtx={prefix:full, rootList:ctx.rootList||(act&&act.vars)||[], rerender:ctx.rerender};
  v.children.forEach((cv,ci)=>wfBuildVarTree(act,cv,ci,container,depth+1,childCtx));
}
function wfVarRow(act,v,idx,depth,ctx){
  depth=depth||0;
  ctx=ctx||{};
  const item=document.createElement("details"); item.className="wf-variable-item wf-activity-variable";
  item.open=wfActivityVarsExpanded.has(v);
  if(depth>0){ item.style.marginLeft=(depth*WF_VAR_INDENT)+"px"; item.classList.add("nested"); }
  const summary=document.createElement("summary");
  const title=document.createElement("span"); title.className="wf-variable-name";
  const type=document.createElement("span"); type.className="wf-variable-type";
  const value=document.createElement("span"); value.className="wf-variable-value";
  const updateSummary=()=>{
    title.textContent=v.label||v.name||"Variable"; type.textContent=v.type||"bool";
    value.textContent=Array.isArray(v.value)?v.value.join(", ")||"None":String(v.value??"");
    value.title=value.textContent;
  };
  updateSummary(); summary.append(title,type,value); item.appendChild(summary);
  item.addEventListener("toggle",()=>{
    if(item.open) wfActivityVarsExpanded.add(v); else wfActivityVarsExpanded.delete(v);
    updateSummary();
  });
  const card=document.createElement("div"); card.className="wf-var-card";
  // Line 1: drag-chip + title + delete + add-child button.
  const r1=document.createElement("div"); r1.className="wf-var-row";
  const chip=document.createElement("span"); chip.className="wf-var-chip"; chip.draggable=true;
  chip.innerHTML=wfIco("pin"); chip.title="Drag to canvas to create a check node";
  const fullName=(ctx.prefix?ctx.prefix+".":"")+(v.name||"");
  chip.addEventListener("dragstart",e=>{ wfPaletteDrag="var:"+(v.type||"bool")+":"+fullName; e.dataTransfer.effectAllowed="copy"; try{e.dataTransfer.setData("text/plain",fullName);}catch{} });
  chip.addEventListener("dragend",()=>{ wfPaletteDrag=null; });
  r1.appendChild(chip);
  const lbl=document.createElement("input"); lbl.type="text"; lbl.value=v.label||""; lbl.placeholder="Title (shown in settings)"; lbl.style.cssText="flex:1;min-width:0;font-weight:600;";
  lbl.setAttribute("aria-label","Variable title");
  // While the code name has never been edited by hand, keep it in sync with the
  // Title the user types ("Đọc email" → "doc_email").
  let autoName = !v.name || v.name===v.label || v.name===wfVarSlug(v.label||"");
  lbl.oninput=()=>{
    wfPushUndoDebounced(); v.label=lbl.value; wfRenderVarsPanel();
    if(autoName){ const s=wfVarSlug(lbl.value); if(s){ v.name=s; nm.value=s; } }
  };
  r1.appendChild(lbl);
  if(v.type!=="select"){
    const addChild=document.createElement("button"); addChild.type="button"; addChild.className="wf-side-mini"; addChild.innerHTML=wfIco("plus"); addChild.title="Add child variable"; addChild.setAttribute("aria-label",addChild.title);
    addChild.onclick=(e)=>{ e.stopPropagation(); wfPushUndoDebounced(); v.children=v.children||[]; const n=v.children.length+1; v.children.push({name:v.name+"_sub"+n, label:"Sub "+n, type:"bool", value:false, children:[]}); wfActivityVarsExpanded.add(v.children[v.children.length-1]); wfRefreshVarViews(); };
    r1.appendChild(addChild);
  }
  const del=document.createElement("button"); del.type="button"; del.className="wf-side-mini wf-activity-var-delete"; del.innerHTML=wfIco("trash"); del.title="Delete variable"; del.setAttribute("aria-label",del.title);
  del.onclick=()=>{
    wfPushUndoDebounced();
    // Locate by identity so siblings at the same depth cannot delete each other,
    // including a child that belongs to one select option.
    wfRemoveVarFromTree(ctx.rootList||(act&&act.vars)||[], v);
    (ctx.rerender||wfRefreshVarViews)();
  };
  r1.appendChild(del);
  // Line 2: name + type + default value.
  const r2=document.createElement("div"); r2.className="wf-var-row";
  const nm=document.createElement("input"); nm.type="text"; nm.value=v.name||""; nm.placeholder="variable (e.g. isClaim)"; nm.style.cssText="flex:1;min-width:0;font-size:10.5px;font-family:var(--mono);";
  nm.setAttribute("aria-label","Variable name");
  nm.oninput=()=>{ wfPushUndoDebounced(); v.name=nm.value; autoName=!v.name || v.name===wfVarSlug(v.label||""); };
  r2.appendChild(nm);
  const ty=document.createElement("select");
  ty.setAttribute("aria-label","Variable type");
  [["bool","bool"],["number","number"],["text","text"],["path","path"],["select","select"]].forEach(([val,lab])=>{ const o=document.createElement("option"); o.value=val; o.textContent=lab; if((v.type||"bool")===val)o.selected=true; ty.appendChild(o); });
  ty.onchange=()=>{
    wfPushUndoDebounced();
    v.type=ty.value;
    if(ty.value==="select"){ if(!v.options||!v.options.length) v.options=["A","B"]; v.value=v.options[0]; }
    else v.value = ty.value==="bool"?false : ty.value==="number"?0 : "";
    wfRenderInspector();
  };
  r2.appendChild(ty);
  card.appendChild(r1); card.appendChild(r2);
  if(v.type!=="select"){
    const row=document.createElement("div"); row.className="wf-field wf-activity-var-default";
    const label=document.createElement("label"); label.textContent="Default value";
    const control=wfVarValue(v); const input=control.matches("input,select,[role=checkbox]")?control:control.querySelector("input");
    if(input){ input.id=wfUid(); label.htmlFor=input.id; input.setAttribute("aria-label","Default value"); }
    row.append(label,control); card.appendChild(row);
  }
  // Line 3 (select only): options.
  if(v.type==="select"){
    card.appendChild(wfVarOptionsEditor(v,{
      act, depth, prefix:ctx.prefix||"",
      rootList:ctx.rootList||(act&&act.vars)||[],
      rerender:ctx.rerender||wfRefreshVarViews,
    }));
  }
  item.appendChild(card);
  ["input","change","click"].forEach(event=>card.addEventListener(event,updateSummary));
  return item;
}
// ── Helpers for nested variable deletion ───────────────────────────────────
function wfFindVarInArr(arr, idx, depth, level){
  if(level===depth) return {arr, i:idx};
  for(const v of arr){
    if(v.children&&v.children.length){
      const found=wfFindVarInArr(v.children, idx, depth, level+1);
      if(found) return found;
    }
  }
  return null;
}
function findParentVarArr(arr, idx, depth){
  const result=wfFindVarInArr(arr, idx, depth, 0);
  return result?result.arr:arr;
}
function findParentVarIdx(arr, idx, depth){
  const result=wfFindVarInArr(arr, idx, depth, 0);
  return result?result.i:-1;
}
// Edit one option per row; both radio columns write the same default/test value.
function wfVarOptionsEditor(v, ctx){
  ctx=ctx||{};
  const editor=document.createElement("div"); editor.className="wf-options-editor";
  const uid=wfUid();
  const rerender=ctx.rerender||wfRefreshVarViews;
  function changed(){ if(typeof wfRenderVarsPanel==="function") wfRenderVarsPanel(); }
  function draw(){
    editor.replaceChildren();
    const options=v.options||[];
    const multi=v.display==="toggle-group"&&!!v.multiple;
    const checked=option=>multi?(Array.isArray(v.value)&&v.value.includes(option)):v.value===option;
    const heading=document.createElement("div"); heading.className="wf-options-heading";
    const title=document.createElement("span"); title.textContent="Options";
    const def=document.createElement("span"); def.textContent="Default";
    heading.append(title,def); editor.appendChild(heading);
    const radios=[], previews=[];
    function select(value){
      wfPushUndoDebounced();
      if(multi){ const values=Array.isArray(v.value)?v.value:[]; v.value=values.includes(value)?values.filter(o=>o!==value):[...values,value]; }
      else v.value=value;
      changed();
      radios.forEach((r,i)=>{ r.checked=checked(options[i]); });
      previews.forEach((r,i)=>{ r.checked=checked(options[i]); });
    }
    options.forEach((option,index)=>{
      const row=document.createElement("div"); row.className="wf-option-row";
      const input=document.createElement("input"); input.type="text"; input.value=option;
      input.setAttribute("aria-label","Option "+(index+1));
      input.oninput=()=>input.setCustomValidity("");
      input.onchange=()=>{
        const value=input.value.trim();
        if(!value || options.some((o,i)=>i!==index&&o===value)){
          input.setCustomValidity(value?"Each option must be unique.":"Enter an option name.");
          input.reportValidity(); input.value=option; return;
        }
        if(value===option){ input.value=value; return; }
        wfPushUndoDebounced(); options[index]=value;
        if(v.optionChildren&&Object.prototype.hasOwnProperty.call(v.optionChildren, option)){
          v.optionChildren[value]=v.optionChildren[option];
          delete v.optionChildren[option];
        }
        if(v.value===option) v.value=value;
        else if(multi) v.value=(v.value||[]).map(o=>o===option?value:o);
        changed(); draw();
        editor.querySelectorAll('.wf-option-row input[type="text"]')[index]?.focus();
      };
      const radio=document.createElement("input"); radio.type=multi?"checkbox":"radio"; radio.name=uid+"-default";
      radio.checked=checked(option); radio.setAttribute("aria-label","Use "+option+" as default");
      radio.onchange=()=>select(option); radios.push(radio);
      const del=document.createElement("button"); del.type="button"; del.className="btn sm ico";
      del.innerHTML=wfIco("x"); del.title="Remove "+option; del.setAttribute("aria-label",del.title);
      del.disabled=options.length===1; del.onclick=()=>{
        wfPushUndoDebounced(); options.splice(index,1);
        if(v.optionChildren) delete v.optionChildren[option];
        if(multi) v.value=(v.value||[]).filter(o=>options.includes(o));
        else if(!options.includes(v.value)) v.value=options[0]||"";
        changed(); draw();
        editor.querySelectorAll('.wf-option-row input[type="text"]')[Math.min(index,options.length-1)]?.focus();
      };
      const addKid=document.createElement("button"); addKid.type="button"; addKid.className="btn sm ico";
      addKid.innerHTML=wfIco("plus"); addKid.title="Add variable for "+option; addKid.setAttribute("aria-label", addKid.title);
      addKid.onclick=()=>{
        wfPushUndoDebounced();
        const list=wfOptionChildList(v, option, true);
        const n=list.length+1;
        const slug=wfVarSlug(option)||"option";
        const child={name:(v.name||"var")+"_"+slug+"_"+n, label:option+" "+n, type:"bool", value:false, children:[]};
        list.push(child);
        wfActivityVarsExpanded.add(child);
        rerender();
      };
      row.append(input,radio,addKid,del);
      const block=document.createElement("div"); block.className="wf-option-block";
      block.appendChild(row);
      if(!checked(option)){ editor.appendChild(block); return; }
      const kids=wfOptionChildList(v, option, false);
      if(kids.length){
        const nest=document.createElement("div"); nest.className="wf-option-children";
        const parentName=(ctx.prefix?ctx.prefix+".":"")+(v.name||"");
        const childCtx={prefix:parentName+"."+option, rootList:ctx.rootList||(ctx.act&&ctx.act.vars)||[], rerender};
        kids.forEach((cv,ci)=>wfBuildVarTree(ctx.act||null, cv, ci, nest, 0, childCtx));
        block.appendChild(nest);
      }
      editor.appendChild(block);
    });
    const add=document.createElement("button"); add.type="button"; add.className="btn sm wf-option-add";
    add.textContent="+ Add option"; add.onclick=()=>{
      wfPushUndoDebounced(); let i=options.length+1;
      while(options.includes("Option "+i)) i++;
      const value="Option "+i; v.options=[...options,value];
      if(!multi&&!options.includes(v.value)) v.value=value;
      changed(); draw();
      const inputs=editor.querySelectorAll('.wf-option-row input[type="text"]');
      inputs[inputs.length-1]?.focus(); inputs[inputs.length-1]?.select();
    };
    editor.append(add,wfVarDisplay(v,()=>{ changed(); draw(); }));
    if(v.display==="toggle-group"){
      const label=document.createElement("label"); label.className="wf-var-row";
      const toggle=document.createElement("input"); toggle.type="checkbox"; toggle.checked=multi;
      toggle.onchange=()=>{
        wfPushUndoDebounced(); v.multiple=toggle.checked;
        v.value=toggle.checked?(options.includes(v.value)?[v.value]:[]):((v.value||[])[0]||options[0]||"");
        changed(); draw();
      };
      label.append(toggle,document.createTextNode("Allow multiple choices")); editor.appendChild(label);
    }
    const fieldset=document.createElement("fieldset"); fieldset.className="wf-option-preview";
    const legend=document.createElement("legend"); legend.textContent="Default / Test value"; fieldset.appendChild(legend);
    const choices=document.createElement("div"); choices.className="wf-option-choices";
    options.forEach(option=>{
      const label=document.createElement("label"); label.className="wf-option-choice";
      const radio=document.createElement("input"); radio.type=multi?"checkbox":"radio"; radio.name=uid+"-preview";
      radio.checked=checked(option); radio.onchange=()=>select(option); previews.push(radio);
      const text=document.createElement("span"); text.textContent=option;
      label.append(radio,text); choices.appendChild(label);
    });
    fieldset.appendChild(choices);
    const help=document.createElement("p"); help.className="wf-options-help";
    help.textContent=options.length?"Used when testing in Designer and as the Runner default.":"Add an option to choose a default.";
    editor.append(fieldset,help);
  }
  draw(); return editor;
}
// Local select variables can use either a dropdown or exclusive toggles in Runner.
function wfVarDisplay(v,onchange){
  const row=document.createElement("label"); row.className="wf-var-row";
  const title=document.createElement("span"); title.textContent="Runner display";
  const select=document.createElement("select");
  [["dropdown","Dropdown"],["toggle-group","Group toggle"]].forEach(([value,text])=>{
    const option=document.createElement("option"); option.value=value; option.textContent=text;
    option.selected=(v.display||"dropdown")===value; select.appendChild(option);
  });
  select.onchange=()=>{ wfPushUndoDebounced(); v.display=select.value;
    if(v.display!=="toggle-group"){ v.multiple=false; if(Array.isArray(v.value)) v.value=v.value[0]||(v.options||[])[0]||""; }
    if(onchange) onchange();
  };
  row.append(title,select);
  return row;
}
function wfVarValue(v){
  if((v.type||"bool")==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(v.value?" checked":""); cb.title="Default value";
    cb.setAttribute("role","checkbox"); cb.tabIndex=0; cb.setAttribute("aria-checked",String(!!v.value));
    cb.innerHTML='<svg class="uico uico-0" aria-hidden="true" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
    cb.onclick=()=>{ wfPushUndoDebounced(); v.value=!v.value; cb.classList.toggle("checked",v.value); cb.setAttribute("aria-checked",String(!!v.value)); };
    cb.onkeydown=e=>{ if(e.key===" "||e.key==="Enter"){ e.preventDefault(); cb.click(); } };
    return cb;
  }
  if(v.type==="select"){
    const sel=document.createElement("select"); sel.style.maxWidth="86px";
    (v.options||[]).forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; if(String(v.value)===String(o))op.selected=true; sel.appendChild(op); });
    sel.onchange=()=>{ wfPushUndoDebounced(); v.value=sel.value; };
    return sel;
  }
  const inp=document.createElement("input"); inp.type=v.type==="number"?"number":"text";
  inp.value=v.value!==undefined&&v.value!==null?v.value:"";
  inp.style.width=v.type==="path"?"100%":"58px";
  inp.oninput=()=>{ wfPushUndoDebounced(); v.value = v.type==="number"?(parseFloat(inp.value)||0):inp.value; };
  if(v.type!=="path") return inp;
  const wrap=document.createElement("div"); wrap.className="wf-var-path-value";
  const browse=document.createElement("button"); browse.type="button"; browse.className="btn sm ico"; browse.title="Choose file…"; browse.innerHTML=wfIco("folder");
  browse.onclick=async()=>{ const p=await api().pick_file(inp.value||""); if(p){ inp.value=p; v.value=p; wfPushUndoDebounced(); } };
  wrap.appendChild(inp); wrap.appendChild(browse);
  return wrap;
}

// ── Smart paste on coordinate fields ─────────────────────────────────────────
const WF_COORD_KEYS = ["x","y","w","h"];
// Swipe geometry: start → end plus the gesture duration. A copied swipe from
// the Preview panel ("x1, y1, x2, y2, duration") pastes into any of these.
const WF_SWIPE_KEYS = ["x1","y1","x2","y2","duration"];
// Parse "x, y", "x, y, w, h" or a swipe "x1, y1, x2, y2, duration" — commas,
// spaces and → / -> all work, and wrapping parentheses are tolerated.
function wfParseCoordPaste(txt){
  const s=String(txt||"").trim().replace(/^\(+|\)+$/g,"").trim();
  if(!s) return null;
  const parts=s.split(/\s*(?:,|→|->|\s)\s*/).filter(Boolean);
  if(parts.length<2 || parts.length>WF_SWIPE_KEYS.length) return null;
  const nums=parts.map(v=>Number(v));
  return nums.every(n=>Number.isFinite(n)) ? nums : null;
}
// Which numeric fields the paste fills: a Swipe-style block (x1…y2, duration)
// keeps its own set so a pasted region can't land in the wrong slots, and a
// plain coordinate block uses x/y/w/h. Returns null when this field isn't part
// of the block's coordinate set (e.g. Long press's duration).
function wfCoordKeysFor(node, f){
  if(f.t!=="num") return null;
  const def=WF_NODES[node.type];
  const nums=new Set((def&&def.fields||[]).filter(ff=>ff.t==="num").map(ff=>ff.k));
  const keys=(nums.has("x1")?WF_SWIPE_KEYS:WF_COORD_KEYS).filter(k=>nums.has(k));
  return keys.includes(f.k) ? keys : null;
}
function wfAttachCoordPaste(node, f, inp){
  const keys=wfCoordKeysFor(node,f);
  if(!keys) return;
  inp.addEventListener("paste", e=>{
    const nums=wfParseCoordPaste((e.clipboardData||{}).getData("text") || "");
    if(!nums) return;
    // More values than this node's fields hold (e.g. a swipe pasted into an
    // image region) — leave the native paste alone, but say why it didn't take.
    if(nums.length>keys.length){
      e.preventDefault();
      if(typeof uiToast==="function") uiToast("Clipboard has more values than this block holds - paste it into the matching block.","warning");
      return;
    }
    e.preventDefault();
    wfPushUndoDebounced();
    nums.forEach((val,i)=>{ if(i<keys.length) node.params[keys[i]]=val; });
    wfUpdNodeSum(node);
    if(f.refresh){ wfRenderCanvas(); wfRefreshNodeLogs(node); }
    const body=$("wf-insp-body");
    if(body){
      keys.forEach(key=>{
        const labEl=body.querySelector(`.wf-field > label[title="${key}"]`);
        const inpEl=labEl&&labEl.parentNode.querySelector("input");
        if(inpEl) inpEl.value=node.params[key];
      });
    }
  });
}

// A field is visible unless its showWhen:{key:val|[vals]} gate fails. Lets a
// block hide params that don't apply to the current mode (e.g. Tap's x/y when
// aiming at the last-found image instead of fixed coordinates).
function wfFieldVisible(node,f){
  if(!f.showWhen) return true;
  return Object.entries(f.showWhen).every(([k,want])=>{
    const cur=node.params[k];
    return Array.isArray(want) ? want.includes(cur) : cur===want;
  });
}

// Short numeric params that read as a coordinate/size pair — rendered two to a
// row (label + narrow input, side by side) so the inspector stays compact.
const WF_PAIR_KEYS = new Set(["x","y","w","h","x1","y1","x2","y2","offsetX","offsetY","min","max"]);
function wfPairRow(node,fA,fB){
  const wrap=document.createElement("div"); wrap.className="wf-field-pair";
  wrap.appendChild(wfFieldEl(node,fA));
  wrap.appendChild(wfFieldEl(node,fB));
  return wrap;
}

// Normalize a free-text / legacy clock value to HTML time input form (HH:MM).
// Accepts "8:00", "08:00", "8:00:00"; returns "" for blank or unparseable.
function wfNormTime(raw){
  if(raw===undefined||raw===null) return "";
  const s=String(raw).trim();
  if(!s) return "";
  const m=s.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if(!m) return "";
  const hh=Math.min(23, Math.max(0, parseInt(m[1],10)));
  const mm=Math.min(59, Math.max(0, parseInt(m[2],10)));
  return String(hh).padStart(2,"0")+":"+String(mm).padStart(2,"0");
}

function wfFieldEl(node,f){
  // Region is a special block (already styled as a panel).
  if(f.t==="region") return wfRegionField(node,f);

  const row=document.createElement("div"); row.className="wf-field";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; row.appendChild(lab);

  if(f.t==="key"){
    const box=document.createElement("div"); box.className="wf-key-preset";
    const sel=document.createElement("select"); sel.setAttribute("aria-label",wfFieldLabel(f));
    const value=String(node.params[f.k]??f.d??"");
    for(const preset of f.opts||[]){
      const op=document.createElement("option"); op.value=preset.v; op.textContent=preset.t; sel.appendChild(op);
    }
    const custom=document.createElement("option"); custom.value="__custom"; custom.textContent="Custom keycode…"; sel.appendChild(custom);
    sel.value=(f.opts||[]).some(p=>p.v===value)?value:"__custom";
    const inp=document.createElement("input"); inp.type="text"; inp.value=value;
    inp.setAttribute("aria-label",node.type==="key"?"Custom Android keycode":"Custom Windows virtual-key code");
    inp.placeholder=node.type==="key"?"Android code or KEYCODE_NAME":"Windows VK number";
    inp.hidden=sel.value!=="__custom";
    sel.onchange=()=>{
      inp.hidden=sel.value!=="__custom";
      if(!inp.hidden){ inp.focus(); inp.select(); return; }
      wfPushUndoDebounced(); node.params[f.k]=sel.value; inp.value=sel.value; wfUpdNodeSum(node);
    };
    inp.oninput=()=>{ wfPushUndoDebounced(); node.params[f.k]=inp.value; wfUpdNodeSum(node); };
    box.append(sel,inp); row.appendChild(box); return row;
  }

  if(f.t==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(node.params[f.k]?" checked":"");
    cb.setAttribute("role","checkbox"); cb.tabIndex=0; cb.setAttribute("aria-checked",String(!!node.params[f.k]));
    cb.innerHTML='<svg class="uico uico-0" aria-hidden="true" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
    // A bool that another field gates on (showWhen) must re-render the inspector
    // so the dependent field appears/disappears (e.g. loop infinite ↔ count).
    const gates=(WF_NODES[node.type]&&WF_NODES[node.type].fields||[]).some(ff=>ff.showWhen&&ff.showWhen[f.k]!==undefined);
    cb.onclick=()=>{ wfPushUndoDebounced(); node.params[f.k]=!node.params[f.k]; cb.classList.toggle("checked",node.params[f.k]); cb.setAttribute("aria-checked",String(!!node.params[f.k])); wfUpdNodeSum(node); if(f.refresh){ wfRenderCanvas(); wfRefreshNodeLogs(node); } if(gates) wfRenderInspector(); };
    cb.onkeydown=e=>{ if(e.key===" "||e.key==="Enter"){ e.preventDefault(); cb.click(); } };
    row.appendChild(cb); return row;
  }
  if(f.t==="select"){
    const sel=document.createElement("select");
    (f.opts||[]).forEach(o=>{ const v=(o&&o.v!==undefined)?o.v:o, t=(o&&o.t!==undefined)?o.t:o;
      const op=document.createElement("option"); op.value=v; op.textContent=t; if(String(node.params[f.k])===String(v))op.selected=true; sel.appendChild(op); });
    // If any sibling field gates on this one (showWhen), re-render the inspector
    // so gated fields appear/disappear as the selection changes.
    const gates=(WF_NODES[node.type]&&WF_NODES[node.type].fields||[]).some(ff=>ff.showWhen&&ff.showWhen[f.k]!==undefined);
    sel.onchange=()=>{ wfPushUndoDebounced(); node.params[f.k]=sel.value; wfUpdNodeSum(node); if(gates) wfRenderInspector();
      // A variable block's Value control depends on the operator (true/false
      // only makes sense for = and ≠).
      if(f.k==="op" && WF_VAR_VALUE_NODES.has(node.type)){ wfNormalizeVarValue(node); wfRefreshVarValues(row.parentElement); } };
    row.appendChild(sel); return row;
  }
  if(f.t==="tpls") return wfTplsField(node,f);
  if(f.t==="points") return wfPointsField(node,f);
  if(f.t==="sequence_points") return wfSequencePointsField(node,f);
  if(f.t==="sequence_images") return wfSequenceImagesField(node,f);

  // Color field: native swatch picker + hex text kept in sync both ways.
  if(f.t==="color"){
    const pick=document.createElement("input"); pick.type="color"; pick.className="wf-color-pick";
    const inp=document.createElement("input"); inp.type="text"; inp.placeholder="#RRGGBB";
    inp.style.fontFamily="var(--mono)"; inp.style.flex="1"; inp.style.minWidth="0";
    const valid=v=>/^#[0-9a-fA-F]{6}$/.test(v);
    const cur=node.params[f.k]!==undefined?String(node.params[f.k]):(f.d||"#ff0000");
    inp.value=cur; if(valid(cur)) pick.value=cur;
    const commit=v=>{ wfPushUndoDebounced(); node.params[f.k]=v; wfUpdNodeSum(node); };
    pick.oninput=()=>{ inp.value=pick.value; commit(pick.value); };
    inp.oninput=()=>{ let v=inp.value.trim(); if(v && v[0]!=="#") v="#"+v;
      if(valid(v)) pick.value=v; commit(v); };
    row.appendChild(pick); row.appendChild(inp);
    return row;
  }

  // Clock time (HH:MM) — native picker. Empty allowed (e.g. optional schedule).
  // Normalizes legacy free-text values like "8:00" → "08:00" for the input.
  if(f.t==="time"){
    const inp=document.createElement("input"); inp.type="time"; inp.className="wf-time-pick";
    const raw=node.params[f.k]!==undefined?node.params[f.k]:(f.d!==undefined?f.d:"");
    const norm=wfNormTime(raw);
    if(norm) inp.value=norm;
    // Keep stored param in HH:MM so the engine and node summary stay consistent.
    if(norm && String(raw).trim()!==norm) node.params[f.k]=norm;
    inp.onchange=()=>{ wfPushUndoDebounced(); node.params[f.k]=inp.value||""; wfUpdNodeSum(node); };
    inp.oninput=()=>{ wfPushUndoDebounced(); node.params[f.k]=inp.value||""; wfUpdNodeSum(node); };
    row.appendChild(inp);
    return row;
  }

  // Path = literal file/folder OR a path variable, with native browse action.
  if(f.t==="path"){ return wfPathField(node,f); }
  // Variable NAME field (declares/targets a variable) → combobox picker.
  if(f.var){ return wfVarNameField(node,f); }
  // Variable-or-literal VALUE field (loop count, set/if value…) → ref picker.
  if(f.varRef){ return wfVarRefField(node,f); }

  const inp=document.createElement("input");
  inp.type=f.t==="num"?"number":"text"; if(f.t==="num"&&f.step) inp.step=f.step;
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.oninput=()=>{ wfPushUndoDebounced(); node.params[f.k]= f.t==="num"?(parseFloat(inp.value)||0):inp.value; wfUpdNodeSum(node); if(f.k==="timeout") wfUpdNodeTimeoutChip(node); if(f.refresh){ wfRenderCanvas(); wfRefreshNodeLogs(node); } };
  wfAttachCoordPaste(node, f, inp);
  row.appendChild(inp);

  // Free-text fields that expand {name} placeholders get an insert-variable btn.
  if(f.t==="text" && f.insertVar){ row.appendChild(wfInsertVarBtn(inp)); }

  if(f.t==="tpl"){
    row.classList.add("full");   // label on top - a truncated "templa…" path tells the user nothing
    inp.style.fontSize="10px";
    const btn=document.createElement("button"); btn.className="btn sm"; btn.textContent="Choose…";
    const img=document.createElement("img"); img.className="wf-tpl-preview"; wfLoadThumb(img, node.params[f.k]);
    const sub=document.createElement("div"); sub.className="wf-tpl-row"; sub.appendChild(inp); sub.appendChild(btn); sub.appendChild(img); row.appendChild(sub);   // full-width row: input + picker + thumb
    const refresh=v=>{ wfPushUndoDebounced(); node.params[f.k]=v; wfUpdNodeSum(node); wfLoadThumb(img,v); wfUpdNodePreview(node); wfRenderCanvas(); };
    inp.oninput=()=>refresh(inp.value);
    btn.onclick=async()=>{ const p=await api().pick_template(); if(p){ if(typeof wfRememberTemplate==="function") wfRememberTemplate(p); inp.value=p; refresh(p); } };
    if(typeof wfLatestTemplate!=="undefined" && wfLatestTemplate){
      const latest=document.createElement("button"); latest.type="button"; latest.className="btn sm"; latest.textContent="Latest crop";
      latest.title=wfLatestTemplate;
      latest.onclick=()=>{ inp.value=wfLatestTemplate; refresh(wfLatestTemplate); };
      sub.insertBefore(latest,img);
    }
    return row;
  }
  return row;
}

function wfTplsField(node,f,row){
  // The multi-template list is a vertical stack — it needs full width, so wrap
  // it in a .wf-field.full block (label on top) instead of the default
  // label+control row which squeezes the list to the right of the label.
  const wrap=document.createElement("div"); wrap.className="wf-field full";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; wrap.appendChild(lab);
  const arr=()=> Array.isArray(node.params[f.k])?node.params[f.k]:(node.params[f.k]=[]);
  const list=document.createElement("div"); list.className="wf-tpls-list";
  function renderList(){
    list.innerHTML="";
    arr().forEach((path,idx)=>{
      const item=document.createElement("div"); item.className="wf-tpls-item";
      const r=document.createElement("div"); r.className="wf-tpls-hdr";
      const num=document.createElement("span"); num.className="num"; num.textContent=(idx+1)+".";
      const inp=document.createElement("input"); inp.type="text"; inp.value=path||"";
      const pick=document.createElement("button"); pick.className="btn sm"; pick.textContent="Choose…";
      const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Delete image";
      const img=document.createElement("img"); img.className="wf-tpl-preview"; wfLoadThumb(img, path);
      const commit=v=>{ wfPushUndoDebounced(); arr()[idx]=v; wfUpdNodeSum(node); wfUpdNodePreview(node); wfLoadThumb(img,v); wfRenderCanvas(); };
      inp.oninput=()=>commit(inp.value);
      pick.onclick=async()=>{ const pp=await api().pick_template(); if(pp){ if(typeof wfRememberTemplate==="function") wfRememberTemplate(pp); inp.value=pp; commit(pp); } };
      del.onclick=()=>{ wfPushUndoDebounced(); arr().splice(idx,1); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
      r.appendChild(num); r.appendChild(inp); r.appendChild(pick); r.appendChild(del); r.appendChild(img);
      item.appendChild(r); list.appendChild(item);
    });
    if(!arr().length){ const e=document.createElement("div"); e.className="wf-tpls-empty"; e.textContent="No images - add at least 2 to use \"or\"."; list.appendChild(e); }
  }
  renderList();
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Image";
  add.onclick=async()=>{ const pp=await api().pick_template(); if(!pp) return; wfPushUndoDebounced(); if(typeof wfRememberTemplate==="function") wfRememberTemplate(pp); arr().push(pp); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
  wrap.appendChild(list); wrap.appendChild(add);
  if(typeof wfLatestTemplate!=="undefined" && wfLatestTemplate){
    const latest=document.createElement("button"); latest.className="btn sm"; latest.textContent="+ Latest crop"; latest.title=wfLatestTemplate;
    latest.onclick=()=>{ wfPushUndoDebounced(); if(!arr().includes(wfLatestTemplate)) arr().push(wfLatestTemplate); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
    wrap.appendChild(latest);
  }
  return wrap;
}

// Coordinate list for Multi-point tap. Each row is one finger/target; the
// runtime dispatches the whole list as one concurrent batch.
function wfPointsField(node,f){
  const wrap=document.createElement("div"); wrap.className="wf-field full";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; wrap.appendChild(lab);
  const arr=()=>Array.isArray(node.params[f.k])?node.params[f.k]:(node.params[f.k]=[]);
  const list=document.createElement("div"); list.className="wf-points-list";
  const head=document.createElement("div"); head.className="wf-points-head";
  head.innerHTML="<span>Point</span><span>X</span><span>Y</span><span></span>";
  const commit=()=>{ wfPushUndoDebounced(); wfUpdNodeSum(node); };
  function renderList(){
    list.innerHTML=""; list.appendChild(head);
    arr().forEach((point,idx)=>{
      if(!point || typeof point!=="object") point=arr()[idx]={x:0,y:0};
      const row=document.createElement("div"); row.className="wf-point-row";
      const num=document.createElement("span"); num.className="num"; num.textContent=String(idx+1);
      const x=document.createElement("input"); x.type="number"; x.min="0"; x.placeholder="X"; x.setAttribute("aria-label",`Point ${idx+1} X`); x.value=Number(point.x)||0;
      const y=document.createElement("input"); y.type="number"; y.min="0"; y.placeholder="Y"; y.setAttribute("aria-label",`Point ${idx+1} Y`); y.value=Number(point.y)||0;
      x.oninput=()=>{ point.x=parseInt(x.value,10)||0; commit(); };
      y.oninput=()=>{ point.y=parseInt(y.value,10)||0; commit(); };
      const del=document.createElement("button"); del.type="button"; del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Delete point"; del.setAttribute("aria-label",`Delete point ${idx+1}`);
      del.onclick=()=>{ wfPushUndoDebounced(); arr().splice(idx,1); wfUpdNodeSum(node); renderList(); };
      row.appendChild(num); row.appendChild(x); row.appendChild(y); row.appendChild(del); list.appendChild(row);
    });
    if(!arr().length){ const empty=document.createElement("div"); empty.className="wf-tpls-empty"; empty.textContent="No touch points - add at least 2."; list.appendChild(empty); }
  }
  renderList();
  const actions=document.createElement("div"); actions.className="wf-points-actions";
  const add=document.createElement("button"); add.type="button"; add.className="btn sm"; add.textContent="+ Point";
  add.onclick=()=>{ wfPushUndoDebounced(); const picked=(typeof wfPvPoint!=="undefined"&&Array.isArray(wfPvPoint))?wfPvPoint:null; arr().push({x:picked?picked[0]:0,y:picked?picked[1]:0}); wfUpdNodeSum(node); renderList(); };
  actions.appendChild(add);
  if(typeof wfPvPoint!=="undefined" && Array.isArray(wfPvPoint)){
    const picked=document.createElement("span"); picked.className="wf-points-picked"; picked.textContent=`Last picked: ${wfPvPoint[0]}, ${wfPvPoint[1]}`; actions.appendChild(picked);
  }
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.textContent="All points start together. Hold duration keeps the touches overlapping; 60–100 ms works for most games.";
  wrap.appendChild(list); wrap.appendChild(actions); wrap.appendChild(hint);
  return wrap;
}

function wfSequencePointsField(node,f){
  const wrap=document.createElement("div"); wrap.className="wf-field full";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; wrap.appendChild(lab);
  const arr=()=>Array.isArray(node.params[f.k])?node.params[f.k]:(node.params[f.k]=[]);
  const list=document.createElement("div"); list.className="wf-points-list wf-sequence-points-list";
  const head=document.createElement("div"); head.className="wf-points-head";
  head.innerHTML="<span>Tap</span><span>X</span><span>Y</span><span>Delay (s)</span><span></span>"; list.appendChild(head);
  const commit=()=>{ wfPushUndoDebounced(); wfUpdNodeSum(node); };
  function renderList(){
    while(list.children.length>1) list.removeChild(list.lastChild);
    arr().forEach((point,idx)=>{
      if(!point || typeof point!=="object") point=arr()[idx]={x:0,y:0,delay:0};
      const row=document.createElement("div"); row.className="wf-point-row";
      const num=document.createElement("span"); num.className="num"; num.textContent=String(idx+1);
      const make=(key,placeholder)=>{ const input=document.createElement("input"); input.type="number"; input.min="0"; input.step=key==="delay"?"0.05":"1"; input.placeholder=placeholder; input.value=Number(point[key])||0; input.oninput=()=>{ point[key]=parseFloat(input.value)||0; commit(); }; return input; };
      const del=document.createElement("button"); del.type="button"; del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Delete tap";
      del.onclick=()=>{ wfPushUndoDebounced(); arr().splice(idx,1); wfUpdNodeSum(node); renderList(); };
      row.append(num,make("x","X"),make("y","Y"),make("delay","s"),del); list.appendChild(row);
    });
  }
  renderList();
  const actions=document.createElement("div"); actions.className="wf-points-actions";
  const add=document.createElement("button"); add.type="button"; add.className="btn sm"; add.textContent="+ Tap";
  add.onclick=()=>{ wfPushUndoDebounced(); const picked=(typeof wfPvPoint!=="undefined"&&Array.isArray(wfPvPoint))?wfPvPoint:null; arr().push({x:picked?picked[0]:0,y:picked?picked[1]:0,delay:0}); wfUpdNodeSum(node); renderList(); };
  actions.appendChild(add);
  const hint=document.createElement("div"); hint.className="wf-insp-tip"; hint.textContent="Tap theo thứ tự; delay được chờ sau mỗi tap, kể cả tap cuối.";
  wrap.append(list,actions,hint); return wrap;
}

function wfSequenceImagesField(node,f){
  const wrap=document.createElement("div"); wrap.className="wf-field full";
  const lab=document.createElement("label"); lab.textContent=wfFieldLabel(f); lab.title=f.k; wrap.appendChild(lab);
  const arr=()=>Array.isArray(node.params[f.k])?node.params[f.k]:(node.params[f.k]=[]);
  const list=document.createElement("div"); list.className="wf-sequence-images-list";
  const commit=()=>{ wfPushUndoDebounced(); wfUpdNodeSum(node); wfUpdNodePreview(node); wfRenderCanvas(); };
  function renderList(){
    list.innerHTML="";
    arr().forEach((item,idx)=>{
      if(!item || typeof item!=="object") item=arr()[idx]={template:"",threshold:.85,timeout:10,offsetX:0,offsetY:0,delay:0};
      const block=document.createElement("div"); block.className="wf-tpls-item";
      const title=document.createElement("div"); title.className="wf-tpls-hdr";
      const num=document.createElement("span"); num.className="num"; num.textContent=(idx+1)+".";
      const inp=document.createElement("input"); inp.type="text"; inp.placeholder="Template image"; inp.value=item.template||"";
      const pick=document.createElement("button"); pick.type="button"; pick.className="btn sm"; pick.textContent="Choose…";
      const del=document.createElement("button"); del.type="button"; del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Delete image";
      const img=document.createElement("img"); img.className="wf-tpl-preview"; wfLoadThumb(img,item.template);
      const set=(key,value)=>{ item[key]=value; commit(); };
      inp.oninput=()=>set("template",inp.value);
      pick.onclick=async()=>{ const path=await api().pick_template(); if(path){ if(typeof wfRememberTemplate==="function") wfRememberTemplate(path); inp.value=path; set("template",path); wfLoadThumb(img,path); } };
      del.onclick=()=>{ wfPushUndoDebounced(); arr().splice(idx,1); renderList(); commit(); };
      title.append(num,inp,pick,del,img);
      const opts=document.createElement("div"); opts.className="wf-region-panel"; opts.style.display="grid";
      [["threshold","Threshold",.05],["timeout","Timeout (s)",.1],["offsetX","Offset X",1],["offsetY","Offset Y",1],["delay","Delay (s)",.05]].forEach(([key,placeholder,step])=>{
        const input=document.createElement("input"); input.type="number"; input.min="0"; input.step=step; input.placeholder=placeholder; input.title=placeholder; input.value=Number(item[key])||0; input.oninput=()=>set(key,parseFloat(input.value)||0); opts.appendChild(input);
      });
      block.append(title,opts); list.appendChild(block);
    });
    if(!arr().length){ const e=document.createElement("div"); e.className="wf-tpls-empty"; e.textContent="No images - add at least 1."; list.appendChild(e); }
  }
  renderList();
  const add=document.createElement("button"); add.type="button"; add.className="btn sm"; add.textContent="+ Image tap";
  add.onclick=async()=>{ const path=await api().pick_template(); if(!path) return; wfPushUndoDebounced(); if(typeof wfRememberTemplate==="function") wfRememberTemplate(path); arr().push({template:path,threshold:.85,timeout:10,offsetX:0,offsetY:0,delay:0}); renderList(); commit(); };
  wrap.append(list,add);
  if(typeof wfLatestTemplate!=="undefined" && wfLatestTemplate){
    const latest=document.createElement("button"); latest.type="button"; latest.className="btn sm"; latest.textContent="+ Latest crop"; latest.title=wfLatestTemplate;
    latest.onclick=()=>{ wfPushUndoDebounced(); arr().push({template:wfLatestTemplate,threshold:.85,timeout:10,offsetX:0,offsetY:0,delay:.1}); renderList(); commit(); };
    wrap.appendChild(latest);
  }
  return wrap;
}

function wfRegionField(node,f){
  const wrap=document.createElement("div");
  wrap.style.cssText="display:flex;flex-direction:column;gap:5px;padding:5px 0;";
  const hdr=document.createElement("div"); hdr.className="wf-field"; hdr.style.margin="0";
  const lab=document.createElement("label"); lab.textContent="Search region"; lab.title="Limit image matching to one screen region (optional)"; hdr.appendChild(lab);
  const cb=document.createElement("span"); cb.className="cb";
  const enabled=()=> !!(node.params.regionX||node.params.regionY||node.params.regionW||node.params.regionH);
  cb.classList.toggle("checked", enabled());
  cb.innerHTML='<svg class="uico uico-0" aria-hidden="true" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
  cb.style.cursor="pointer";
  hdr.appendChild(cb);
  const panel=document.createElement("div"); panel.className="wf-region-panel";
  const makeCell=(key,ph)=>{
    const i=document.createElement("input"); i.type="number"; i.min="0"; i.placeholder=ph;
    i.value=node.params[key]!==undefined?node.params[key]:"";
    i.oninput=()=>{ wfPushUndoDebounced(); node.params[key]=parseFloat(i.value)||0; };
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
    wfPushUndoDebounced();
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
  if(typeof wfPvRegion!=="undefined" && Array.isArray(wfPvRegion)){
    const use=document.createElement("button"); use.type="button"; use.className="btn sm"; use.textContent="Use selected region";
    use.onclick=()=>{ wfPushUndoDebounced(); const r=wfPvRegion; node.params.regionX=r[0]; node.params.regionY=r[1]; node.params.regionW=r[2]; node.params.regionH=r[3]; x.input.value=r[0]; y.input.value=r[1]; w.input.value=r[2]; h.input.value=r[3]; sync(); };
    panel.appendChild(use);
  }
  wrap.appendChild(hdr); wrap.appendChild(panel);
  return wrap;
}

// Shared branch-count editor for dynamic branch blocks. Switch keeps detailed
// per-branch conditions; try_chain exposes numbered outputs; and waits for N inputs.
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
  inp.title="Enter branch count to quickly add/delete";
  inp.onchange=()=>{ wfPushUndoDebounced(); const n=wfNormalizeCount(inp.value, count, min); inp.value=n; onSet(n); };
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Branch"; add.title="Add one branch";
  add.onclick=()=>{ wfPushUndoDebounced(); onAdd(); };
  row.appendChild(inp); row.appendChild(add);
  return row;
}

function wfSetBranchCount(node, nextCount){
  const prev=wfNormalizeCount(node.params.count, node.type==="and"?2:3);
  node.params.count=nextCount;
  if(nextCount<prev && node.type!=="and"){
    const g=wfGraph();
    if(g) g.edges=(g.edges||[]).filter(e=>!(e.from===node.id && /^\d+$/.test(e.fromPort) && parseInt(e.fromPort,10)>nextCount));
    node.outputLogs=Object.fromEntries(Object.entries(wfOutputLogValues(node)).filter(([k])=>!/^\d+$/.test(k)||Number(k)<=nextCount));
  }
  wfUpdNodeSum(node); wfRenderCanvas();
  wfRefreshNodeLogs(node);
}

function wfCountBranchesEditor(node){
  const wrap=document.createElement("div");
  const isAnd=node.type==="and";
  const isSeq=node.type==="sequence";
  const fallback=isAnd?2:3;
  const count=()=>wfNormalizeCount(node.params.count, fallback);
  const render=()=>{ wrap.innerHTML="";
    wrap.appendChild(wfBranchCountControl(isAnd?"Expected branches":"Branch count", count(), n=>{ wfSetBranchCount(node,n); render(); }, ()=>{ wfSetBranchCount(node,count()+1); render(); }));
    const hint=document.createElement("div"); hint.className="wf-insp-tip";
    hint.textContent=isAnd
      ? "Wait until this many incoming parallel branches reach this node; continue only if all arrived branches had no errors."
      : isSeq
      ? "Run branch #1 → #2 → … #n in order, one step at a time. Every wired branch ALWAYS runs, even when an earlier one fails. When all of them are done the flow continues from the 'end' port (wire it to carry on; leave it empty to stop here)."
      : "Run branch #1 first; if it fails (or hits Next branch), try #2…#n. If all fail, use the 'fail' port.";
    wrap.appendChild(hint);
  };
  render();
  return wrap;
}

// Switch case editor.
function wfSwitchCasesEditor(node){
  const wrap=document.createElement("div");
  const cases=()=> Array.isArray(node.params.cases)?node.params.cases:(node.params.cases=[]);
  const addCase=()=>{ wfPushUndoDebounced(); cases().push({type:"if_image", params:wfDefaults("if_image")}); };
  const setCaseCount=n=>{
    const cs=cases();
    while(cs.length<n) addCase();
    while(cs.length>n) wfRemoveSwitchCase(node, cs.length-1);
    wfUpdNodeSum(node); wfRenderCanvas();
  };
  const list=document.createElement("div"); list.style.cssText="display:flex;flex-direction:column;gap:8px;";
  function render(){
    wfRefreshNodeLogs(node);
    const countCtl=wrap.querySelector(".wf-branch-count input");
    if(countCtl) countCtl.value=cases().length;
    list.innerHTML="";
    cases().forEach((c,idx)=>{
      const item=document.createElement("div"); item.className="wf-case";
      const hd=document.createElement("div"); hd.className="wf-case-hdr";
      const num=document.createElement("span"); num.className="wf-case-num"; num.textContent="#"+(idx+1);
      const sel=document.createElement("select");
      // Only case types valid for this project's controller (see wfSwitchCaseTypes),
      // plus whatever this case already holds so an imported file is never silently
      // rewritten.
      const opts=wfSwitchCaseTypes();
      if(c.type && !opts.includes(c.type) && WF_NODES[c.type]) opts.push(c.type);
      opts.forEach(t=>{ const op=document.createElement("option"); op.value=t;
        op.textContent=WF_NODES[t].label; if(c.type===t)op.selected=true; sel.appendChild(op); });
      sel.onchange=()=>{ wfPushUndoDebounced(); c.type=sel.value; c.params=wfDefaults(sel.value); render(); wfUpdNodeSum(node); };
      const up=document.createElement("button"); up.className="btn sm ico"; up.innerHTML=wfIco("chevron_up"); up.title="Up"; up.disabled=idx===0;
      up.onclick=()=>{ wfPushUndoDebounced(); wfReorderSwitchCase(node, idx, idx-1); render(); wfRenderCanvas(); };
      const dn=document.createElement("button"); dn.className="btn sm ico"; dn.innerHTML=wfIco("chevron_dn"); dn.title="Down"; dn.disabled=idx===cases().length-1;
      dn.onclick=()=>{ wfPushUndoDebounced(); wfReorderSwitchCase(node, idx, idx+1); render(); wfRenderCanvas(); };
      const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Delete branch";
      del.onclick=()=>{ wfPushUndoDebounced(); wfRemoveSwitchCase(node, idx); render(); wfRenderCanvas(); };
      hd.appendChild(num); hd.appendChild(sel); hd.appendChild(up); hd.appendChild(dn); hd.appendChild(del);
      item.appendChild(hd);
      const proxy={ id:node.id+"__c"+idx, type:c.type, params:c.params };
      ((WF_NODES[c.type]||{}).fields||[]).forEach(f=> item.appendChild(wfFieldEl(proxy,f)));
      list.appendChild(item);
    });
    if(!cases().length){ const e=document.createElement("div"); e.className="wf-insp-tip"; e.textContent='No branches. Click "+ Branch" or enter a branch count.'; list.appendChild(e); }
  }
  const countCtl=wfBranchCountControl("Branch count", cases().length, n=>{ setCaseCount(n); render(); }, ()=>{ addCase(); render(); wfRenderCanvas(); wfUpdNodeSum(node); }, 0);
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.textContent="Check from top to bottom: the first matching branch uses its port (#1..#n), otherwise use the 'else' port.";
  wrap.appendChild(countCtl); wrap.appendChild(list); wrap.appendChild(hint);
  render();
  return wrap;
}

function wfUpdNodeSum(node){
  const def=WF_NODES[node.type]; if(!def||!def.sum) return;
  const el=document.querySelector(`.wf-node[data-node="${node.id}"] .wf-node-sum`);
  let s=""; try{ s=def.sum(node.params); }catch{}
  if(!el) return;
  el.title=s;
  const dot=typeof wfColorDotHtml==="function"?wfColorDotHtml(node,def):"";
  const region=typeof wfRegionChip==="function"?wfRegionChip(node):"";
  el.innerHTML=wfNodeSumHtml(s, dot, {plain:def.kind==="note", chips:region?[region]:[]});
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
    if(!arr.length){ const e=document.createElement("span"); e.className="wf-tpl-empty"; e.textContent="(no image)"; strip.appendChild(e); return; }
    arr.forEach(p=>{ const im=document.createElement("img"); im.className="wf-node-thumb-sm"; strip.appendChild(im); wfLoadThumb(im,p); });
    return;
  }
  const img=el.querySelector(".wf-node-thumb");
  if(img) wfLoadThumb(img, wfTplOf(node));
}
