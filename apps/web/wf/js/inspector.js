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
function wfInspBlock(label,count){
  const b=document.createElement("div"); b.className="wf-insp-block";
  if(label){
    const s=document.createElement("div"); s.className="wf-insp-sec";
    s.innerHTML=`<span>${escHtml(label)}</span>`;
    if(count!==undefined&&count!==null&&count!=="") s.innerHTML+=`<span class="sec-count">${escHtml(String(count))}</span>`;
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
  toggle.innerHTML=`<svg class="wf-json-chev" width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4.5L6 8l3.5-3.5"/></svg><span>Preview ${escHtml(label)} JSON</span>`;
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
      tbtn.title="Test block — run this block and draw its match overlay (green = above threshold, red = best below threshold · Ctrl+Enter)";
      tbtn.onclick=()=>{ if(typeof wfRunSingleNode==="function") wfRunSingleNode(node); };
      idEl.appendChild(tbtn);
    }
    body.appendChild(idEl);

    const pblock=wfInspBlock("Parameters");
    if(node.type==="call"){ pblock.appendChild(wfCallPicker(node)); }
    else if(node.type==="switch" || node.type==="try_chain" || node.type==="and"){ pblock.appendChild(wfBranchCountEditor(node)); }
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
        tip.innerHTML=`<b>Paired with Next branch</b> — runs arms <b>1 → 2 → …</b> on fail. Drop <b>Next branch</b> inside an arm to skip to the next arm without a real failure.`;
      } else {
        tip.innerHTML=`<b>Paired with Try in order</b> — place this inside a try arm to stop that arm and advance to the next numbered port (or <b>fail</b> if none left). Outside Try in order it does nothing.`;
      }
      body.appendChild(tip);
    }
    if(node.type!=="note") body.appendChild(wfNoteField(node));
    if(node.type!=="note" && node.type!=="start") body.appendChild(wfLogField(node));
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

    body.appendChild(wfVarsSection(act));

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
      <div class="wf-empty-ico" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><path d="M10 6.5h5.5A2 2 0 0 1 17.5 8.5V14"/></svg></div>
      <div class="wf-empty-t">No activity open</div>
      <div class="wf-empty-s">Select or create an activity in the corner panel, then drag nodes from the left palette onto the canvas.</div>
      <div class="wf-empty-keys">
        <span><b>+</b> add activity</span>
        <span><b>F1</b> shortcuts</span>
      </div>
    </div>`;
}

// ── Variable picker infrastructure ───────────────────────────────────────────
// A single source of truth describing every variable the user can reference,
// with its declared type, scope (global/activity/node) and best-known value.
// Powers the combobox pickers on variable fields and the "insert variable"
// dropdown on text fields (log, message, format string…).
function wfVarInfoMap(){
  const map={};
  const walk=(vars,prefix,scope)=>{ (vars||[]).forEach(v=>{ const n=(v.name||"").trim(); if(!n) return; const full=prefix?prefix+"."+n:n; if(!map[full]) map[full]={type:v.type||"bool", scope, value:v.value}; walk(v.children,full,scope); }); };
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
// Floating dropdown listing every known variable (grouped by scope, filterable).
// `onPick(name)` fires with the chosen variable name. A "+ New global" row lets
// the user declare one on the spot without leaving the field.
let wfVarMenuEl=null;
function wfCloseVarMenu(){ if(wfVarMenuEl){ wfVarMenuEl.remove(); wfVarMenuEl=null; document.removeEventListener("mousedown",wfVarMenuOutside,true); } }
function wfVarMenuOutside(e){ if(wfVarMenuEl && !e.target.closest(".wf-varmenu") && !e.target.closest(".wf-var-pick")) wfCloseVarMenu(); }
function wfShowVarMenu(anchor,onPick){
  wfCloseVarMenu();
  const menu=document.createElement("div"); menu.className="wf-varmenu"; wfVarMenuEl=menu;
  const search=document.createElement("input"); search.type="text"; search.className="wf-varmenu-search";
  search.placeholder="Search variables…"; search.spellcheck=false; search.autocomplete="off";
  menu.appendChild(search);
  const list=document.createElement("div"); list.className="wf-varmenu-list"; menu.appendChild(list);
  const map=wfVarInfoMap();
  const names=Object.keys(map).sort();
  function render(filter){
    list.innerHTML="";
    const f=(filter||"").trim().toLowerCase();
    const shown=names.filter(n=>!f||n.toLowerCase().includes(f));
    if(!shown.length){ const e=document.createElement("div"); e.className="wf-varmenu-empty"; e.textContent=names.length?"No match.":"No variables yet."; list.appendChild(e); }
    let lastScope=null;
    shown.forEach(n=>{
      const info=map[n];
      if(info.scope!==lastScope){ lastScope=info.scope; const s=document.createElement("div"); s.className="wf-varmenu-sep"; s.textContent=WF_VAR_SCOPE_LBL[info.scope]||info.scope; list.appendChild(s); }
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
    uiPrompt({title:"New global variable", label:"Variable name", placeholder:"e.g. round"}).then(v=>{
      const nm=(v||"").trim();
      if(!nm) return;
      wfPushUndoDebounced();
      if(!Array.isArray(WF.globals)) WF.globals=[];
      if(!WF.globals.some(x=>x.name===nm)) WF.globals.push({name:nm, label:nm, type:"text", value:"", children:[]});
      wfRenderVarsPanel(); onPick(nm); wfCloseVarMenu();
    });
  };
  menu.appendChild(addGlobal);
  const act=typeof wfCurAct==="function"?wfCurAct():null;
  if(act){
    const addLocal=document.createElement("button"); addLocal.type="button"; addLocal.className="wf-varmenu-add";
    addLocal.innerHTML=`${wfIco("pin")}<span>New local variable…</span>`;
    addLocal.onclick=()=>{
      uiPrompt({title:"New local variable", label:`Name (activity «${act.name||"activity"}»)`, placeholder:"e.g. step"}).then(v=>{
        const nm=(v||"").trim();
        if(!nm) return;
        wfPushUndoDebounced();
        if(!Array.isArray(act.vars)) act.vars=[];
        if(!act.vars.some(x=>x.name===nm)) act.vars.push({name:nm, label:nm, type:"text", value:"", children:[]});
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
function wfVarPickBtn(onPick,title){
  const b=document.createElement("button"); b.type="button"; b.className="btn sm ico wf-var-pick";
  b.title=title||"Pick a variable";
  b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4l16 16M20 4L4 20"/></svg>';
  b.onclick=(e)=>{ e.stopPropagation(); wfShowVarMenu(b,onPick); };
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
  const lab=document.createElement("label"); lab.textContent=f.lbl||f.k; lab.title=f.k; row.appendChild(lab);
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-var-input";
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.placeholder=f.ph||"variable name";
  const badge=wfVarBadge();
  const sync=()=>badge.refresh(inp.value);
  inp.oninput=()=>{ wfPushUndoDebounced(); node.params[f.k]=inp.value; wfUpdNodeSum(node); wfRenderVarsPanel(); sync(); };
  const pick=wfVarPickBtn(name=>{ inp.value=name; node.params[f.k]=name; wfPushUndoDebounced(); wfUpdNodeSum(node); wfRenderVarsPanel(); sync(); }, "Choose an existing variable");
  row.appendChild(inp); row.appendChild(pick); row.appendChild(badge);
  sync();
  return row;
}

// A VALUE field that may be a literal OR a reference to another variable
// (loop count, set_var value, if_var value, calc_var value). Picking a variable
// replaces the whole value with its name — the engine resolves a bare name to
// that variable's live value at run time.
function wfVarRefField(node,f){
  const row=document.createElement("div"); row.className="wf-field wf-var-field";
  const lab=document.createElement("label"); lab.textContent=f.lbl||f.k; lab.title=f.k; row.appendChild(lab);
  const inp=document.createElement("input"); inp.type=f.t==="num"?"text":"text";  // text so a var name is typeable even on numeric fields
  inp.className="wf-var-input"; inp.inputMode=f.t==="num"?"numeric":"text";
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.placeholder=f.ph||(f.t==="num"?"number or variable":"value or variable");
  const badge=wfVarBadge();
  const sync=()=>{ const s=String(inp.value||"").trim(); badge.refresh(wfVarBadgeInfo(s)?s:""); };
  const commit=refresh=>{ wfPushUndoDebounced();
    // Keep numeric literals as numbers; leave variable names / expressions as text.
    const s=inp.value;
    node.params[f.k]= (f.t==="num" && s!=="" && !isNaN(s) && wfVarBadgeInfo(String(s).trim())===null) ? parseFloat(s) : s;
    wfUpdNodeSum(node); if(refresh) wfRenderCanvas(); sync(); };
  inp.oninput=()=>commit(!!f.refresh);
  const pick=wfVarPickBtn(name=>{ inp.value=name; commit(!!f.refresh); }, "Use a variable as this value");
  row.appendChild(inp); row.appendChild(pick); row.appendChild(badge);
  sync();
  return row;
}

// "insert {variable}" button for free-text fields that support {name}
// placeholder substitution (log message, format string, notify…). Inserts at
// the caret so the user can weave variables into a sentence.
function wfInsertVarBtn(inp){
  const b=document.createElement("button"); b.type="button"; b.className="btn sm ico wf-var-pick";
  b.title="Insert a variable placeholder {name}";
  b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4H5a1 1 0 0 0-1 1v5a1 1 0 0 1-1 1 1 1 0 0 1 1 1v5a1 1 0 0 0 1 1h2"/><path d="M17 4h2a1 1 0 0 1 1 1v5a1 1 0 0 0 1 1 1 1 0 0 0-1 1v5a1 1 0 0 1-1 1h-2"/></svg>';
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
function wfTimingField(node){
  const b=wfInspBlock("Timing");
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
  hint.innerHTML="<b>Before</b> = wait before this block runs · <b>After</b> = wait after it finishes, before the next block (seconds).";
  b.appendChild(hint);
  return b;
}
function wfUpdNodeTiming(node){
  const el=document.querySelector(`.wf-node[data-node="${node.id}"]`); if(!el) return;
  // The chips are absolutely positioned under the block, so placement in the
  // DOM doesn't matter — just swap the whole badge row out.
  const old=el.querySelector(".wf-node-delay"); if(old) old.remove();
  const html=wfDelayChipsHtml(node);
  if(html) el.insertAdjacentHTML("beforeend", html);
}

function wfRetryField(node){
  const b=wfInspBlock("Failure handling");
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
  const cb=document.createElement("span"); cb.className="cb"+(node.screenshotOnFail?" checked":""); cb.innerHTML='<svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
  cb.onclick=()=>{ wfPushUndoDebounced(); node.screenshotOnFail=!node.screenshotOnFail; cb.classList.toggle("checked", !!node.screenshotOnFail); wfUpdNodeRetry(node); };
  row.appendChild(cb);
  const hint=document.createElement("div"); hint.className="wf-insp-tip"; hint.textContent="Retry runs this block again when it fails. Screenshot saves a failure image when the final attempt still fails.";
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
  img.className="wf-fail-shot"; img.title="The screen when this block failed — click to open the original image";
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
  const b=wfInspBlock("Run log");
  const row=document.createElement("div"); row.className="wf-field full";
  const inpRow=document.createElement("div"); inpRow.style.cssText="display:flex;gap:5px;align-items:center;";
  const inp=document.createElement("input"); inp.type="text"; inp.className="wf-insp-input";
  inp.placeholder="write a log each time this node runs…"; inp.value=node.log||"";
  inp.oninput=()=>{ wfPushUndoDebounced(); node.log=inp.value; wfUpdNodeLog(node); };
  inpRow.appendChild(inp); inpRow.appendChild(wfInsertVarBtn(inp));
  row.appendChild(inpRow); b.appendChild(row);
  const hint=document.createElement("div"); hint.className="wf-insp-tip";
  hint.innerHTML='Insert variables with <code>{variable_name}</code>.';
  b.appendChild(hint);
  return b;
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
  inp.oninput=()=>{ wfPushUndoDebounced(); onset(inp.value); }; row.appendChild(inp); return row;
}

// Per-activity variables.
function wfVarsSection(act){
  if(!act.vars) act.vars=[];
  const b=wfInspBlock("Activity variables", act.vars.length);
  b.style.gap="2px";
  act.vars.forEach((v,idx)=>wfBuildVarTree(act,v,idx,b));
  b.appendChild(wfVarAddBtn(act));
  return b;
}
function wfVarAddBtn(act, parentVar, parentIdx){
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Variable"; add.style.alignSelf="flex-start";
  add.onclick=()=>{
    wfPushUndoDebounced();
    const arr=parentVar?parentVar.children:(act.vars);
    const n=arr.length+1; const prefix=parentVar?(parentVar.name||"sub")+"_":"";
    arr.push({name:prefix+"var"+n, label:"Setting "+n, type:"bool", value:false, children:[]});
    wfRenderInspector();
  };
  return add;
}
// Nested-variable indent step — one 4pt-scale unit (var(--s4), 12px) per depth,
// shared with wfBuildGlobChildren (render.js) so activity vars and globals nest identically.
const WF_VAR_INDENT = 12;
function wfBuildVarTree(act,v,idx,container,depth){
  depth=depth||0;
  v.children=v.children||[];
  const card=wfVarRow(act,v,idx,depth);
  container.appendChild(card);
  v.children.forEach((cv,ci)=>{
    cv.children=cv.children||[];
    const subCard=wfVarRow(act,cv,ci,depth+1);
    container.appendChild(subCard);
    cv.children.forEach((ccv,cci)=>{ ccv.children=ccv.children||[]; container.appendChild(wfVarRow(act,ccv,cci,depth+2)); });
  });
}
function wfVarRow(act,v,idx,depth){
  depth=depth||0;
  const card=document.createElement("div"); card.className="wf-var-card";
  if(depth>0) card.style.marginLeft=(depth*WF_VAR_INDENT)+"px";
  // Line 1: drag-chip + title + delete + add-child button.
  const r1=document.createElement("div"); r1.className="wf-var-row";
  const chip=document.createElement("span"); chip.className="wf-var-chip"; chip.draggable=true;
  chip.textContent="🔖"; chip.title="Drag to canvas to create a check node";
  chip.addEventListener("dragstart",e=>{ wfPaletteDrag="var:"+(v.type||"bool")+":"+(v.name||""); e.dataTransfer.effectAllowed="copy"; try{e.dataTransfer.setData("text/plain",v.name||"");}catch{} });
  chip.addEventListener("dragend",()=>{ wfPaletteDrag=null; });
  r1.appendChild(chip);
  const lbl=document.createElement("input"); lbl.type="text"; lbl.value=v.label||""; lbl.placeholder="Title (shown in settings)"; lbl.style.cssText="flex:1;min-width:0;font-weight:600;";
  lbl.oninput=()=>{ wfPushUndoDebounced(); v.label=lbl.value; };
  r1.appendChild(lbl);
  const addChild=document.createElement("button"); addChild.className="btn sm"; addChild.textContent="+ Child"; addChild.title="Add child variable (nested)";
  addChild.onclick=(e)=>{ e.stopPropagation(); wfPushUndoDebounced(); v.children=v.children||[]; const n=v.children.length+1; v.children.push({name:v.name+"_sub"+n, label:"Sub "+n, type:"bool", value:false, children:[]}); wfRenderInspector(); };
  r1.appendChild(addChild);
  const del=document.createElement("button"); del.className="wf-act-del"; del.innerHTML=wfIco("x"); del.title="Delete variable";
  del.onclick=()=>{
    wfPushUndoDebounced();
    // Find parent array and remove this var
    const parentArr = depth>0 ? (findParentVarArr(act.vars, idx, depth)||act.vars) : act.vars;
    if(depth>0){ const pi=findParentVarIdx(act.vars, idx, depth); if(pi>=0) parentArr.splice(pi,1); }
    else act.vars.splice(idx,1);
    wfRenderInspector();
  };
  r1.appendChild(del);
  // Line 2: name + type + default value.
  const r2=document.createElement("div"); r2.className="wf-var-row";
  const nm=document.createElement("input"); nm.type="text"; nm.value=v.name||""; nm.placeholder="variable (e.g. isClaim)"; nm.style.cssText="flex:1;min-width:0;font-size:10.5px;font-family:var(--mono);";
  nm.oninput=()=>{ wfPushUndoDebounced(); v.name=nm.value; };
  r2.appendChild(nm);
  const ty=document.createElement("select");
  [["bool","bool"],["number","number"],["text","text"],["select","select"]].forEach(([val,lab])=>{ const o=document.createElement("option"); o.value=val; o.textContent=lab; if((v.type||"bool")===val)o.selected=true; ty.appendChild(o); });
  ty.onchange=()=>{
    wfPushUndoDebounced();
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
    const opt=document.createElement("input"); opt.type="text"; opt.placeholder="options: A, B, C"; opt.value=(v.options||[]).join(", ");
    opt.style.cssText="flex:1;min-width:0;font-size:10.5px;";
    opt.onchange=()=>{ wfPushUndoDebounced(); v.options=opt.value.split(",").map(s=>s.trim()).filter(Boolean); if(!v.options.includes(v.value)) v.value=v.options[0]||""; wfRenderInspector(); };
    r3.appendChild(opt); card.appendChild(r3);
  }
  return card;
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
function wfVarValue(v){
  if((v.type||"bool")==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(v.value?" checked":""); cb.title="Default value";
    cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
    cb.onclick=()=>{ wfPushUndoDebounced(); v.value=!v.value; cb.classList.toggle("checked",v.value); };
    return cb;
  }
  if(v.type==="select"){
    const sel=document.createElement("select"); sel.style.maxWidth="86px";
    (v.options||[]).forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; if(String(v.value)===String(o))op.selected=true; sel.appendChild(op); });
    sel.onchange=()=>{ wfPushUndoDebounced(); v.value=sel.value; };
    return sel;
  }
  const inp=document.createElement("input"); inp.type=v.type==="number"?"number":"text";
  inp.value=v.value!==undefined&&v.value!==null?v.value:""; inp.style.width="58px";
  inp.oninput=()=>{ wfPushUndoDebounced(); v.value = v.type==="number"?(parseFloat(inp.value)||0):inp.value; };
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
    wfPushUndoDebounced();
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
  const lab=document.createElement("label"); lab.textContent=f.lbl||f.k; lab.title=f.k; row.appendChild(lab);

  if(f.t==="bool"){
    const cb=document.createElement("span"); cb.className="cb"+(node.params[f.k]?" checked":"");
    cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
    // A bool that another field gates on (showWhen) must re-render the inspector
    // so the dependent field appears/disappears (e.g. loop infinite ↔ count).
    const gates=(WF_NODES[node.type]&&WF_NODES[node.type].fields||[]).some(ff=>ff.showWhen&&ff.showWhen[f.k]!==undefined);
    cb.onclick=()=>{ wfPushUndoDebounced(); node.params[f.k]=!node.params[f.k]; cb.classList.toggle("checked",node.params[f.k]); wfUpdNodeSum(node); if(f.refresh) wfRenderCanvas(); if(gates) wfRenderInspector(); };
    row.appendChild(cb); return row;
  }
  if(f.t==="select"){
    const sel=document.createElement("select");
    (f.opts||[]).forEach(o=>{ const v=(o&&o.v!==undefined)?o.v:o, t=(o&&o.t!==undefined)?o.t:o;
      const op=document.createElement("option"); op.value=v; op.textContent=t; if(node.params[f.k]===v)op.selected=true; sel.appendChild(op); });
    // If any sibling field gates on this one (showWhen), re-render the inspector
    // so gated fields appear/disappear as the selection changes.
    const gates=(WF_NODES[node.type]&&WF_NODES[node.type].fields||[]).some(ff=>ff.showWhen&&ff.showWhen[f.k]!==undefined);
    sel.onchange=()=>{ wfPushUndoDebounced(); node.params[f.k]=sel.value; wfUpdNodeSum(node); if(gates) wfRenderInspector(); };
    row.appendChild(sel); return row;
  }
  if(f.t==="tpls") return wfTplsField(node,f);

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

  // Variable NAME field (declares/targets a variable) → combobox picker.
  if(f.var){ return wfVarNameField(node,f); }
  // Variable-or-literal VALUE field (loop count, set/if value…) → ref picker.
  if(f.varRef){ return wfVarRefField(node,f); }

  const inp=document.createElement("input");
  inp.type=f.t==="num"?"number":"text"; if(f.t==="num"&&f.step) inp.step=f.step;
  inp.value=node.params[f.k]!==undefined?node.params[f.k]:"";
  inp.oninput=()=>{ wfPushUndoDebounced(); node.params[f.k]= f.t==="num"?(parseFloat(inp.value)||0):inp.value; wfUpdNodeSum(node); if(f.refresh) wfRenderCanvas(); };
  wfAttachCoordPaste(node, f, inp);
  row.appendChild(inp);

  // Free-text fields that expand {name} placeholders get an insert-variable btn.
  if(f.t==="text" && f.insertVar){ row.appendChild(wfInsertVarBtn(inp)); }

  // Path fields marked pickFolder get a "browse for a folder" button next to
  // the text input (e.g. the emulator install dir on launch_emulator).
  if(f.pickFolder){
    inp.style.fontSize="10px";
    const btn=document.createElement("button"); btn.className="btn sm ico"; btn.title="Choose folder…";
    btn.innerHTML=wfIco("folder");
    btn.onclick=async()=>{ const p=await api().pick_folder(inp.value||""); if(p){ inp.value=p; wfPushUndoDebounced(); node.params[f.k]=p; wfUpdNodeSum(node); } };
    row.appendChild(btn);
  }

  if(f.t==="tpl"){
    inp.style.fontSize="10px";
    const btn=document.createElement("button"); btn.className="btn sm"; btn.textContent="Choose…";
    const img=document.createElement("img"); img.className="wf-tpl-preview"; wfLoadThumb(img, node.params[f.k]);
    row.appendChild(btn); row.appendChild(img);   // thumb beside the picker button
    const refresh=v=>{ wfPushUndoDebounced(); node.params[f.k]=v; wfUpdNodeSum(node); wfLoadThumb(img,v); wfUpdNodePreview(node); wfRenderCanvas(); };
    inp.oninput=()=>refresh(inp.value);
    btn.onclick=async()=>{ const p=await api().pick_template(); if(p){ inp.value=p; refresh(p); } };
    return row;
  }
  return row;
}

function wfTplsField(node,f,row){
  // The multi-template list is a vertical stack — it needs full width, so wrap
  // it in a .wf-field.full block (label on top) instead of the default
  // label+control row which squeezes the list to the right of the label.
  const wrap=document.createElement("div"); wrap.className="wf-field full";
  const lab=document.createElement("label"); lab.textContent=f.lbl||f.k; lab.title=f.k; wrap.appendChild(lab);
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
      pick.onclick=async()=>{ const pp=await api().pick_template(); if(pp){ inp.value=pp; commit(pp); } };
      del.onclick=()=>{ wfPushUndoDebounced(); arr().splice(idx,1); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
      r.appendChild(num); r.appendChild(inp); r.appendChild(pick); r.appendChild(del); r.appendChild(img);
      item.appendChild(r); list.appendChild(item);
    });
    if(!arr().length){ const e=document.createElement("div"); e.className="wf-tpls-empty"; e.textContent="No images — add at least 2 to use \"or\"."; list.appendChild(e); }
  }
  renderList();
  const add=document.createElement("button"); add.className="btn sm"; add.textContent="+ Image";
  add.onclick=async()=>{ wfPushUndoDebounced(); const pp=await api().pick_template(); arr().push(pp||""); wfUpdNodeSum(node); wfUpdNodePreview(node); renderList(); wfRenderCanvas(); };
  wrap.appendChild(list); wrap.appendChild(add);
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
  cb.innerHTML='<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>';
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
  }
  wfUpdNodeSum(node); wfRenderCanvas();
}

function wfCountBranchesEditor(node){
  const wrap=document.createElement("div");
  const isAnd=node.type==="and";
  const fallback=isAnd?2:3;
  const count=()=>wfNormalizeCount(node.params.count, fallback);
  const render=()=>{ wrap.innerHTML="";
    wrap.appendChild(wfBranchCountControl(isAnd?"Expected branches":"Branch count", count(), n=>{ wfSetBranchCount(node,n); render(); }, ()=>{ wfSetBranchCount(node,count()+1); render(); }));
    const hint=document.createElement("div"); hint.className="wf-insp-tip";
    hint.textContent=isAnd
      ? "Wait until this many incoming parallel branches reach this node; continue only if all arrived branches had no errors."
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
      (WF_NODES[c.type].fields||[]).forEach(f=> item.appendChild(wfFieldEl(proxy,f)));
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
  const dot=typeof wfColorDotHtml==="function"?wfColorDotHtml(node,def):"";
  if(dot) el.innerHTML=dot+escHtml(s); else el.textContent=s;
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
