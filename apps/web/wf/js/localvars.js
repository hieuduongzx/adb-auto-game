// ── Local (design/test) variable values ─────────────────────────────────────
// workflow.json's `value` fields are the DEFAULTS a build ships. This module
// keeps a separate map of design-test values in a sibling file
// (workflows/<Name>/local_vars.json) that a Test run overlays on top, while
// Build EXE never sees them.
//
// The map is flat and keyed by dotted variable path (the same key the engine
// uses): {globals:{path:val}, activities:{actId:{path:val}}}. A missing key
// means "use the default", so clearing a local value simply deletes it.
let wfLocalVars = { globals: {}, activities: {} };
let _wfLocalSaveTimer = null;

function wfLocalScopeMap(scope, actId){
  if(!wfLocalVars || typeof wfLocalVars!=="object") wfLocalVars={globals:{},activities:{}};
  if(scope==="global"){
    if(!wfLocalVars.globals || typeof wfLocalVars.globals!=="object") wfLocalVars.globals={};
    return wfLocalVars.globals;
  }
  if(!wfLocalVars.activities || typeof wfLocalVars.activities!=="object") wfLocalVars.activities={};
  const id=String(actId||"");
  if(!wfLocalVars.activities[id] || typeof wfLocalVars.activities[id]!=="object") wfLocalVars.activities[id]={};
  return wfLocalVars.activities[id];
}
function wfLocalHas(scope, actId, full){
  const m=wfLocalScopeMap(scope,actId);
  return Object.prototype.hasOwnProperty.call(m, full);
}
function wfLocalGet(scope, actId, full){
  return wfLocalScopeMap(scope,actId)[full];
}
// The value a Test run will actually use: local if set, else the default.
function wfLocalEffective(v, scope, actId, full){
  return wfLocalHas(scope,actId,full) ? wfLocalGet(scope,actId,full) : (v?v.value:undefined);
}
function wfLocalSet(scope, actId, full, value){
  wfLocalScopeMap(scope,actId)[full]=value;
  wfSaveLocalVarsSoon();
}
function wfLocalClear(scope, actId, full){
  const m=wfLocalScopeMap(scope,actId);
  if(Object.prototype.hasOwnProperty.call(m,full)) delete m[full];
  wfSaveLocalVarsSoon();
}
function wfSaveLocalVarsSoon(){
  clearTimeout(_wfLocalSaveTimer);
  _wfLocalSaveTimer=setTimeout(async()=>{
    try{ await api().save_local_vars(JSON.stringify(wfLocalVars)); }
    catch(e){ if(typeof uiToast==="function") uiToast("Couldn't save test values: "+String(e&&e.message||e),"error"); }
  }, 600);
}
async function wfLoadLocalVars(){
  try{
    const data=await api().get_local_vars();
    wfLocalVars=(data&&typeof data==="object")?data:{globals:{},activities:{}};
    if(!wfLocalVars.globals) wfLocalVars.globals={};
    if(!wfLocalVars.activities) wfLocalVars.activities={};
  }catch(e){
    wfLocalVars={globals:{},activities:{}};
  }
  return wfLocalVars;
}

// Build the "Local (test)" editor for one variable: a value control that writes
// into the local map, plus a clear (↺) button that reverts to the default.
function wfLocalValueCtl(v, scope, actId, full){
  const row=document.createElement("div"); row.className="wf-var-row wf-local-row";
  const tag=document.createElement("span"); tag.className="wf-local-tag"; tag.textContent="LOCAL";
  tag.title="Value used only by Test run (local_vars.json) — never built into the .exe";
  row.appendChild(tag);

  const type=v.type||"bool";
  if(type==="bool"){
    const has=wfLocalHas(scope,actId,full);
    const cur=has?!!wfLocalGet(scope,actId,full):!!v.value;
    const cb=document.createElement("span"); cb.className="cb"+(cur?" checked":"")+(has?"":" local-inherit");
    cb.setAttribute("role","checkbox"); cb.tabIndex=0; cb.setAttribute("aria-checked",String(cur));
    cb.title=has?"Local test value":"Follows default — click to set a test value";
    cb.innerHTML=uiIco("check","uico-0");
    cb.onclick=()=>{
      const next=!cb.classList.contains("checked");
      wfLocalSet(scope,actId,full,next); cb.classList.toggle("checked",next);
      cb.classList.remove("local-inherit"); cb.title="Local test value";
      cb.setAttribute("aria-checked",String(next));
      if(typeof wfRenderVarsPanel==="function") wfRenderVarsPanel();
    };
    cb.onkeydown=e=>{ if(e.key===" "||e.key==="Enter"){ e.preventDefault(); cb.click(); } };
    row.appendChild(cb);
  } else if(type==="select"){
    const sel=document.createElement("select"); sel.className="wf-local-select";
    const def=(Array.isArray(v.value)?v.value.join(", "):String(v.value==null?"":v.value));
    const inherit=document.createElement("option"); inherit.value=""; inherit.textContent="Default ("+def+")";
    sel.appendChild(inherit);
    (v.options||[]).forEach(o=>{ const op=document.createElement("option"); op.value=op.textContent=o; sel.appendChild(op); });
    const has=wfLocalHas(scope,actId,full);
    sel.value=has?String(wfLocalGet(scope,actId,full)):"";
    sel.onchange=()=>{
      if(sel.value==="") wfLocalClear(scope,actId,full);
      else wfLocalSet(scope,actId,full,sel.value);
      if(typeof wfRenderVarsPanel==="function") wfRenderVarsPanel();
    };
    row.appendChild(sel);
  } else {
    const has=wfLocalHas(scope,actId,full);
    const inp=document.createElement("input");
    inp.type=type==="number"?"number":"text";
    inp.className="wf-local-input"; inp.style.flex="1"; inp.style.minWidth="0";
    inp.value=has?String(wfLocalGet(scope,actId,full)):"";
    inp.placeholder="Default: "+(v.value===undefined||v.value===null||v.value===""?"∅":String(v.value));
    inp.title="Leave blank to use the default";
    inp.oninput=()=>{
      const s=inp.value;
      if(s===""){ wfLocalClear(scope,actId,full); return; }
      wfLocalSet(scope,actId,full, type==="number"?(parseFloat(s)||0):s);
    };
    row.appendChild(inp);
    if(type==="path"){
      const browse=document.createElement("button"); browse.type="button"; browse.className="btn sm ico";
      browse.title="Choose file…"; browse.innerHTML=uiIco("folder","uico-0");
      browse.onclick=async()=>{
        try{ const p=await api().pick_file(inp.value||""); if(p){ inp.value=p; wfLocalSet(scope,actId,full,p); } }catch{}
      };
      row.appendChild(browse);
    }
  }

  const clear=document.createElement("button"); clear.type="button"; clear.className="btn sm ico wf-local-clear";
  clear.title="Clear local value (use default)";
  clear.innerHTML=uiIco("x","uico-0");
  clear.disabled=!wfLocalHas(scope,actId,full);
  clear.onclick=()=>{ wfLocalClear(scope,actId,full); if(typeof wfRenderVarsPanel==="function") wfRenderVarsPanel(); };
  row.appendChild(clear);
  return row;
}
