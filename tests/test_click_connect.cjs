const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const path=require('node:path');
function setup({ snap = x => x, align = false } = {}){
  const handlers={}, canvasHandlers={}, classes=new Set(), graph={nodes:[],edges:[]}, groups=[], undo=[], nodeElements=new Map();
  const canvas={classList:{add:x=>classes.add(x),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),toggle(x,on){on?classes.add(x):classes.delete(x);}},addEventListener:(n,f,capture)=>{ if(!canvasHandlers[n] || capture) canvasHandlers[n]=f; },getBoundingClientRect:()=>({left:0,top:0})};
  const world={getBoundingClientRect:()=>({left:0,top:0}),appendChild(){}};
  let pointElement=null;
  const ctx=vm.createContext({getComputedStyle:()=>({getPropertyValue:()=>''}),document:{addEventListener:(n,f)=>handlers[n]=f,querySelectorAll:()=>[],querySelector:sel=>{ const m=/data-node="([^"]+)"/.exec(sel); return m?nodeElements.get(m[1])||null:null; },getElementById:()=>null,createElement:()=>({style:{},remove(){}}),elementFromPoint:()=>pointElement},window:{addEventListener:(n,f)=>handlers['window:'+n]=f},
    $:id=>id==='wf-canvas'?canvas:id==='wf-world'?world:null,wfGesture:null,wfCanvasReady:false,wfPointer:{},wfPvActive:false,wfSpace:false,wfGroupMode:false,wfPan:{x:0,y:0},wfZoom:1,wfAlignOn:align,wfSnapOn:true,WF_GRID:16,WF_NODES:{start:{kind:'start'},end:{kind:'end'},tap:{kind:'action'}},WF:{sel:[]},
    wfGraph:()=>graph,wfNode:id=>graph.nodes.find(node=>node.id===id),wfNodeElById:id=>nodeElements.get(id)||null,wfSnap:snap,
    wfSelectOne(id){ctx.WF.sel=id?[id]:[];},wfMarkSel(){},wfRenderInspector(){},
    wfPushUndo:()=>{const state=JSON.parse(JSON.stringify(graph));state.groups=JSON.parse(JSON.stringify(groups));undo.push(state);},wfClearTemp(){},wfDrawTempWire(){},wfDrawWires(){},wfRenderCanvas(){},wfCancelCamAnim(){},wfWorldMotionHint(){},wfApplyTransform(){},wfSetZoom(){},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/groups.js'),'utf8'),ctx);
  ctx.wfGroups=()=>groups;
  ctx.wfInitCanvas();
  ctx.wfNodeUnderPointer=()=> 'b'; ctx.wfNearestInPort=()=> 'in';
  const event=(x=10,y=20,button=0)=>({clientX:x,clientY:y,button,target:{closest:()=>null},preventDefault(){},stopPropagation(){},stopImmediatePropagation(){}});
  return {ctx,handlers,canvasHandlers,graph,groups,undo,classes,event,nodeElements,setPointElement:el=>{pointElement=el;}};
}
test('grid mode keeps dragged nodes on whole cells even when smart align finds a half-cell target',()=>{
 const snap=v=>Math.round(v/16)*16;
 const {ctx,handlers,event,graph,nodeElements}=setup({snap,align:true});
 const classList={add(){},remove(){}};
 const port=offsetTop=>({offsetTop,offsetHeight:8});
 graph.nodes.push({id:'drag',type:'tap',x:0,y:0},{id:'other',type:'tap',x:24,y:24});
 nodeElements.set('drag',{offsetWidth:144,offsetHeight:64,classList,style:{},querySelectorAll:()=>[port(28)]});
 nodeElements.set('other',{offsetWidth:144,offsetHeight:64,classList,style:{},querySelectorAll:()=>[port(28)]});

 ctx.wfStartMove(event(0,0),graph.nodes[0]);
 handlers.mousemove(event(23,23));

 assert.deepEqual([graph.nodes[0].x,graph.nodes[0].y],[16,16]);
 assert.equal(graph.nodes[0].x%16,0);
 assert.equal(graph.nodes[0].y%16,0);
});

test('start and end nodes can snap to half-grid positions for straight wires',()=>{
 const snap=v=>Math.round(v/16)*16;
 const {ctx,handlers,event,graph,nodeElements}=setup({snap,align:true});
 const classList={add(){},remove(){}};
 const port=offsetTop=>({offsetTop,offsetHeight:6});
 graph.nodes.push({id:'start',type:'start',x:0,y:0},{id:'card',type:'tap',x:32,y:16});
 nodeElements.set('start',{offsetWidth:48,offsetHeight:48,classList,style:{},querySelectorAll:()=>[port(21)]});
 nodeElements.set('card',{offsetWidth:144,offsetHeight:64,classList,style:{},querySelectorAll:()=>[port(29)]});

 ctx.wfStartMove(event(0,0),graph.nodes[0]);
 handlers.mousemove(event(23,23));

 assert.deepEqual([graph.nodes[0].x,graph.nodes[0].y],[24,24]);
 assert.equal((graph.nodes[0].y+24),graph.nodes[1].y+32,
   'terminal and regular-card ports share one horizontal line');
});

test('clicking a port without dragging cancels instead of arming click-connect',()=>{
 const {ctx,handlers,event,graph,undo,classes}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
 assert.equal(ctx.wfGesture,null); assert.equal(graph.edges.length,0); assert.equal(undo.length,0);
 assert.ok(!classes.has('wf-connecting'));
 ctx.wfStartConnect(event(300,200),'b','in','in'); handlers.mouseup(event(300,200));
 assert.equal(ctx.wfGesture,null); assert.equal(graph.edges.length,0);
});
test('input-first drag connects exact input and replaces only chosen output',()=>{
 const {ctx,handlers,event,graph,undo,setPointElement}=setup();
 graph.edges=[{from:'a',fromPort:'true',to:'old',toPort:'in'},{from:'a',fromPort:'false',to:'other',toPort:'in'}];
 const node={dataset:{node:'a'}}, port={dataset:{port:'true'},closest:sel=>sel==='.wf-port.out'?port:sel==='.wf-node'?node:null};
 setPointElement(port);
 ctx.wfStartConnect(event(),'b','loop','in'); handlers.mousemove(event(300,200)); handlers.mouseup(event(300,200));
 assert.deepEqual(JSON.parse(JSON.stringify(graph.edges)),[{from:'a',fromPort:'false',to:'other',toPort:'in'},{from:'a',fromPort:'true',to:'b',toPort:'loop'}]);
 assert.equal(undo.length,1); assert.equal(ctx.wfGesture,null);
});
test('dropping onto a node clears the dashed preview before the canvas redraws',()=>{
 const {ctx,handlers,event}=setup();
 const seen=[];
 ctx.wfRenderCanvas=()=>seen.push(ctx.wfGesture && ctx.wfGesture.mode);
 ctx.wfDrawWires=()=>seen.push('wires:'+(ctx.wfGesture && ctx.wfGesture.mode));
 ctx.wfStartConnect(event(),'a','out','out');
 handlers.mousemove(event(80,80));
 handlers.mouseup(event(80,80));
 assert.equal(ctx.wfGesture,null);
 assert.deepEqual(seen, [null]);
 assert.ok(!seen.includes('connect'));
});
test('right click cancels an active drag connection',()=>{
 const {ctx,canvasHandlers,event,graph,classes}=setup();
 ctx.wfStartConnect(event(),'a','out','out');
 assert.equal(ctx.wfGesture?.mode,'connect'); assert.ok(classes.has('wf-connecting'));
 canvasHandlers.contextmenu(event(110,120,2));
 assert.equal(ctx.wfGesture,null); assert.equal(graph.edges.length,0); assert.ok(!classes.has('wf-connecting'));
});
test('dragging empty space inside the smallest group moves its frame and members',()=>{
 const {ctx,handlers,event,graph,groups,undo}=setup();
 graph.nodes.push({id:'inside',x:130,y:130},{id:'outside',x:500,y:500});
 groups.push(
   {id:'large',x:0,y:0,w:400,h:400},
   {id:'small',x:100,y:100,w:200,h:200},
 );
 ctx.wfCanvasMouseDown(event(150,150));
 assert.equal(ctx.wfGesture?.mode,'groupmove');
 assert.equal(ctx.wfGesture.gr.id,'small');
 handlers.mousemove(event(190,210));
 assert.deepEqual([groups[1].x,groups[1].y],[140,160]);
 assert.deepEqual([graph.nodes[0].x,graph.nodes[0].y],[170,190]);
 assert.deepEqual([graph.nodes[1].x,graph.nodes[1].y],[500,500]);
 assert.equal(undo.length,1,'the original position is snapshotted once');
 handlers.mousemove(event(210,230));
 handlers.mouseup(event(210,230));
 assert.equal(undo.length,1);
});
test('clicking group interior without moving does not create undo history',()=>{
 const {ctx,handlers,event,groups,undo}=setup();
 groups.push({id:'group',x:0,y:0,w:200,h:200});
 ctx.wfCanvasMouseDown(event(50,50));
 handlers.mouseup(event(50,50));
 assert.equal(undo.length,0);
});
test('group drag cannot replace a pending connection',()=>{
 const {ctx,handlers,event}=setup();
 ctx.wfStartConnect(event(),'a','out','out');
 ctx.wfNodesInGroup=()=>[];
 ctx.wfStartGroupMove(event(),{x:0,y:0});
 assert.equal(ctx.wfGesture.mode,'connect');
 ctx.wfStartGroupResize(event(),{w:100,h:100});
 assert.equal(ctx.wfGesture.mode,'connect');
});
test('Escape cancels pending wire before run/selection shortcuts',()=>{
 const {ctx,handlers,event,graph}=setup();
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/keyboard.js'),'utf8'),ctx);
 ctx.wfStartConnect(event(),'a','out','out');
 handlers['window:keydown']({...event(),key:'Escape'});
 assert.equal(ctx.wfGesture,null); assert.equal(graph.edges.length,0);
});
test('zoom redraws pending wire at last pointer position',()=>{
 const {ctx,handlers,event}=setup();
 ctx.wfStartConnect(event(),'a','out','out');
 ctx.wfGesture.mx=120; ctx.wfGesture.my=80;
 const source=fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/workflow.js'),'utf8');
 vm.runInContext(source.slice(source.indexOf('function wfApplyTransform(){'),source.indexOf('// Corner readout')),ctx);
 const world={style:{}}; ctx.$=id=>id==='wf-world'?world:null;
 ctx.wfCrispPx=x=>x; ctx.wfSyncGrid=ctx.wfSyncLod=ctx.wfSyncZoomBadge=()=>{};
 let point=null; ctx.wfDrawTempWire=(x,y)=>point=[x,y];
 ctx.wfZoom=0.5; ctx.wfApplyTransform();
 assert.deepEqual(point,[120,80]); assert.equal(ctx.wfGesture.mode,'connect');
});
test('existing output drag still loose-connects on release',()=>{
 const {ctx,handlers,event,graph,undo}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mousemove(event(300,200)); handlers.mouseup(event(300,200));
 assert.equal(graph.edges[0].to,'b'); assert.equal(ctx.wfGesture,null); assert.equal(undo.length,1);
});
