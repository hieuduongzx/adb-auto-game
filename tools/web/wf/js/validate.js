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
    edges.forEach(e=>{
      if(!byId.has(e.from)) add("err",`Wire starts from missing node ${e.from}`,ctx,null);
      if(!byId.has(e.to)) add("err",`Wire points to missing node ${e.to}`,ctx,null);
    });
    nodes.forEach(n=>{
      const def=WF_NODES[n.type];
      if(!def){ add("err",`Unknown node type: ${n.type}`,ctx,n.id); return; }
      if(def.kind!=="start" && def.kind!=="note" && !edges.some(e=>e.to===n.id)) add("warn","No incoming wire",ctx,n.id);
      (def.fields||[]).forEach(f=>{
        const v=(n.params||{})[f.k];
        if(f.t==="tpl" && !String(v||"").trim()) add("err",`${def.label}: missing template`,ctx,n.id);
        if(f.t==="tpls" && (!Array.isArray(v)||!v.some(x=>String(x||"").trim()))) add("err",`${def.label}: empty template list`,ctx,n.id);
        if(f.var && String(v||"").trim() && !varNames.has(String(v).trim())) add("warn",`Variable not declared yet: ${v}`,ctx,n.id);
      });
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
  wfPan.x=canvas.clientWidth/2-(n.x+80)*wfZoom;
  wfPan.y=canvas.clientHeight/2-(n.y+30)*wfZoom;
  wfApplyTransform(); wfDrawWires();
}
function wfValidateShow(){
  const issues=wfValidationIssues();
  const errs=issues.filter(i=>i.sev==="err").length;
  const warns=issues.length-errs;
  if(!issues.length){ setStatus("Workflow check passed"); alert("✓ Workflow check passed"); return true; }
  let html=`Workflow check: ${errs} error(s), ${warns} warning(s)\n\n`;
  html+=issues.slice(0,30).map((i,idx)=>`${idx+1}. [${i.sev.toUpperCase()}] ${i.ctx.name}: ${i.msg}`).join("\n");
  if(issues.length>30) html+=`\n… +${issues.length-30} more`;
  alert(html);
  setStatus(`Workflow check: ${errs} errors, ${warns} warnings`);
  wfFocusIssue(issues[0]);
  return errs===0;
}
async function wfRunFromSelected(step){
  if(wfRunning){ setStatus("Workflow is already running"); return; }
  if(!WF.activities.length){ alert("No activities."); return; }
  const g=wfGraph(), node=WF.selectedNode&&wfNode(WF.selectedNode);
  const startId=node ? node.id : null;
  if(!startId){ setStatus("Select a block first"); return; }
  wfResetRunViz(); wfSetRunning(true);
  const ok=await api().workflow_run_from_node(JSON.stringify(wfSerialize()), WF.edit.kind, WF.edit.id, startId, !!step);
  if(!ok) wfSetRunning(false);
}
let wfDebugMode=false;
async function wfStartStepRun(){ wfDebugMode=true; await wfRunFromSelected(true); }
function wfDebugAutoStep(){ if(wfDebugMode) setStatus("Paused — click Next step"); }
async function wfDebugStep(){
  try{ await api().workflow_debug_step(); setStatus("Step"); }catch{ setStatus("No paused debug run"); }
}
