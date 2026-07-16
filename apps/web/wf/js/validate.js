// ── Workflow validation + debug run helpers ─────────────────────────────────
function wfValidationIssues(){
  const issues=[];
  const graphs=[];
  WF.activities.forEach(a=>graphs.push({kind:"activity", owner:a, name:a.name||a.id, graph:a.graph}));
  WF.functions.forEach(f=>graphs.push({kind:"function", owner:f, name:"ƒ "+(f.name||f.id), graph:f.graph}));
  const add=(sev,msg,ctx,nodeId)=>issues.push({sev,msg,ctx,nodeId});
  const varNames=new Set(wfAllVarNames());
  graphs.forEach(ctx=>{
    const g=ctx.graph||{nodes:[],edges:[]};
    const nodes=g.nodes||[], edges=g.edges||[];
    const byId=new Map(nodes.map(n=>[n.id,n]));
    if(!nodes.some(n=>n.type==="start")) add("err","Missing Start node",ctx,null);
    // Success = "did the walk reach an End node": a function call without one
    // always returns F (false); a sequence activity without one is always
    // marked failed (red) after a run. Background tasks poll forever — skip.
    if(!nodes.some(n=>n.type==="end")){
      if(ctx.kind==="function") add("warn","Function has no End node — calls will always return F (false)",ctx,null);
      else if(ctx.owner.type!=="background") add("warn","Activity has no End node — it will always be marked failed (red)",ctx,null);
    }
    edges.forEach(e=>{
      if(!byId.has(e.from)) add("err",`Wire starts from missing node ${e.from}`,ctx,null);
      if(!byId.has(e.to)) add("err",`Wire points to missing node ${e.to}`,ctx,null);
    });
    nodes.forEach(n=>{
      const def=WF_NODES[n.type];
      if(!def){ add("err",`Unknown node type: ${n.type}`,ctx,n.id); return; }
      const cat=(typeof WF_CATS!=="undefined")?WF_CATS.find(c=>c.key===def.cat):null;
      if(cat&&cat.ctrl&&cat.ctrl!==WF.controller){
        add("err",`${def.label} is ${cat.ctrl==="adb"?"ADB-only":"Win32-only"} but this project uses ${WF.controller.toUpperCase()}`,ctx,n.id);
      }
      if(def.kind!=="start" && def.kind!=="note" && !edges.some(e=>e.to===n.id)) add("warn","No incoming wire",ctx,n.id);
      (def.fields||[]).forEach(f=>{
        const v=(n.params||{})[f.k];
        if(f.t==="tpl" && !String(v||"").trim()) add("err",`${def.label}: missing template`,ctx,n.id);
        if(f.t==="tpls" && (!Array.isArray(v)||!v.some(x=>String(x||"").trim()))) add("err",`${def.label}: empty template list`,ctx,n.id);
        if(f.t==="points" && (!Array.isArray(v)||v.length<2)) add("err",`${def.label}: add at least 2 touch points`,ctx,n.id);
        if(f.t==="points" && Array.isArray(v)&&v.length>10) add("warn",`${def.label}: only the first 10 touch points will run`,ctx,n.id);
        if(f.var && String(v||"").trim() && !varNames.has(String(v).trim())) add("warn",`Variable not declared yet: ${v}`,ctx,n.id);
      });
      if(n.type==="win_launch" && !String((n.params||{}).path||"").trim()) add("err","Launch program: choose an executable or path variable",ctx,n.id);
      if(n.type==="parallel"){
        const count=Math.max(1,parseInt((n.params||{}).count)||3);
        for(let i=1;i<=count;i++) if(!edges.some(e=>e.from===n.id && e.fromPort===String(i))) add("warn",`Parallel branch #${i} is not wired`,ctx,n.id);
      }
      if(n.type==="try_chain"){
        const count=Math.max(1,parseInt((n.params||{}).count)||3);
        let wired=0; for(let i=1;i<=count;i++) if(edges.some(e=>e.from===n.id && e.fromPort===String(i))) wired++;
        if(!wired) add("err","Try in order has no wired branches",ctx,n.id);
        if(!edges.some(e=>e.from===n.id && e.fromPort==="fail")) add("warn","Try in order has no fail path",ctx,n.id);
      }
      if(n.type==="and"){
        const expected=Math.max(1,parseInt((n.params||{}).count)||2);
        const incoming=edges.filter(e=>e.to===n.id).length;
        if(incoming!==expected) add("err",`And expects ${expected} incoming branches, found ${incoming}`,ctx,n.id);
      }
      if(n.type==="switch"){
        const cs=(n.params||{}).cases||[];
        if(!cs.length) add("warn","Switch has no cases",ctx,n.id);
      }
      if(n.type==="call"){
        const fid=(n.params||{}).fn;
        if(!fid || !WF.functions.some(f=>f.id===fid)) add("err","Call node has no function selected",ctx,n.id);
      }
    });
  });
  return issues;
}
function wfFocusIssue(issue){
  if(!issue) return;
  if(issue.ctx.kind==="activity") wfSelectActivity(issue.ctx.owner.id);
  else wfEditFunction(issue.ctx.owner.id);
  if(issue.nodeId){ WF.sel=[issue.nodeId]; WF.selectedNode=issue.nodeId; wfRenderCanvas(); wfRenderInspector(); const n=wfNode(issue.nodeId); if(n) wfCenterOnNode(n); }
}
function wfCenterOnNode(n){
  const canvas=$("wf-canvas"); if(!canvas||!n) return;
  const tx=canvas.clientWidth/2-(n.x+80)*wfZoom;
  const ty=canvas.clientHeight/2-(n.y+30)*wfZoom;
  wfAnimateCamera(tx,ty,wfZoom,240);
}
// ── Validation panel — a docked list over the canvas (click a row → jump to
// the node). Replaces the old truncated alert(); stays open while fixing so
// each repaired issue is one click away from the next.
function wfValidatePanelClose(){
  const p=document.getElementById("wf-vald"); if(p) p.remove();
}
function wfValidatePanelShow(issues){
  wfValidatePanelClose();
  issues = issues || wfValidationIssues();
  const canvas=$("wf-canvas"); if(!canvas) return;
  const errs=issues.filter(i=>i.sev==="err").length;
  const warns=issues.length-errs;
  const p=document.createElement("div"); p.className="wf-find wf-vald"; p.id="wf-vald";
  const sum = issues.length
    ? `<b class="e">${errs} error${errs===1?"":"s"}</b> · <b class="w">${warns} warning${warns===1?"":"s"}</b>`
    : `<b class="ok">✓ No issues found</b>`;
  p.innerHTML=`<div class="wf-vald-bar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 2.5 18a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>
      <span class="wf-vald-sum">${sum}</span>
      <span class="spacer"></span>
      <button class="btn sm" id="wf-vald-re">Re-check</button>
      <button class="wf-pal-search-clr" id="wf-vald-x" title="Close (Esc)" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="wf-find-list" id="wf-vald-list"></div>`;
  canvas.appendChild(p);
  const list=p.querySelector("#wf-vald-list");
  if(!issues.length){
    list.innerHTML=`<div class="wf-find-empty">The workflow is ready to run — no broken wires, missing templates or bad branches found.</div>`;
  }
  issues.forEach(i=>{
    const row=document.createElement("button"); row.type="button"; row.className="wf-find-item";
    row.innerHTML=`<span class="wf-vald-sev ${i.sev}">${i.sev==="err"?"ERROR":"WARN"}</span>`+
      `<span class="t">${escHtml(i.ctx.name)}</span><span class="s">${escHtml(i.msg)}</span>`;
    row.onclick=()=>wfFocusIssue(i);
    list.appendChild(row);
  });
  p.querySelector("#wf-vald-x").onclick=wfValidatePanelClose;
  p.querySelector("#wf-vald-re").onclick=()=>wfValidatePanelShow();
}
function wfValidateShow(){
  const issues=wfValidationIssues();
  const errs=issues.filter(i=>i.sev==="err").length;
  const warns=issues.length-errs;
  setStatus(issues.length?`Check: ${errs} errors, ${warns} warnings`:"Workflow check: OK");
  wfValidatePanelShow(issues);
  return errs===0;
}
async function wfRunFromSelected(step){
  if(wfRunning){ setStatus("Workflow is already running"); return; }
  if(!WF.activities.length){ uiToast("No activities yet.","warning"); return; }
  const g=wfGraph(), node=WF.selectedNode&&wfNode(WF.selectedNode);
  const startId=node ? node.id : null;
  if(!startId){ setStatus("Select a block first"); return; }
  wfResetRunViz(); wfSetRunning(true);
  const ok=await api().workflow_run_from_node(JSON.stringify(wfSerialize()), WF.edit.kind, WF.edit.id, startId, !!step);
  if(!ok) wfSetRunning(false);
}
let wfDebugMode=false;
async function wfStartStepRun(){ wfDebugMode=true; await wfRunFromSelected(true); }
// Visual pause marker: the block the engine is holding on gets a steady blue
// ring + ⏸ chip (CSS .wf-node.paused), and the Next-step toolbar button pulses
// so the one control that resumes execution is obvious. Cleared on each step
// and whenever the run ends (wfSetRunning(false) → wfClearDebugPause).
function wfClearDebugPause(){
  document.querySelectorAll(".wf-node.paused").forEach(el=>el.classList.remove("paused"));
  const nb=$("wf-step-next-btn"); if(nb) nb.classList.remove("paused");
}
function wfDebugAutoStep(){
  if(!wfDebugMode) return;
  setStatus("Paused — click Next step");
  const el=wfNodeElById(wfRunNode); if(el) el.classList.add("paused");
  const nb=$("wf-step-next-btn"); if(nb) nb.classList.add("paused");
}
async function wfDebugStep(){
  wfClearDebugPause();
  try{ await api().workflow_debug_step(); setStatus("Step"); }catch{ setStatus("No paused debug run"); }
}
