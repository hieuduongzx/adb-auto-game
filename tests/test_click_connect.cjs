const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const path=require('node:path');
function setup(){
  const handlers={}, canvasHandlers={}, classes=new Set(), graph={nodes:[],edges:[]}, undo=[];
  const canvas={classList:{add:x=>classes.add(x),remove:(...xs)=>xs.forEach(x=>classes.delete(x))},addEventListener:(n,f,capture)=>{ if(!canvasHandlers[n] || capture) canvasHandlers[n]=f; },getBoundingClientRect:()=>({left:0,top:0})};
  const ctx=vm.createContext({getComputedStyle:()=>({getPropertyValue:()=>''}),document:{addEventListener:(n,f)=>handlers[n]=f,querySelectorAll:()=>[],querySelector:()=>null},window:{addEventListener:(n,f)=>handlers['window:'+n]=f},
    $:id=>id==='wf-canvas'?canvas:null,wfGesture:null,wfCanvasReady:false,wfPointer:{},wfPvActive:false,wfSpace:false,wfPan:{x:0,y:0},wfZoom:1,WF:{sel:[]},
    wfGraph:()=>graph,wfPushUndo:()=>undo.push(JSON.parse(JSON.stringify(graph))),wfClearTemp(){},wfDrawTempWire(){},wfDrawWires(){},wfRenderCanvas(){},wfCancelCamAnim(){},wfWorldMotionHint(){},wfApplyTransform(){},wfSetZoom(){},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/groups.js'),'utf8'),ctx);
  ctx.wfInitCanvas();
  ctx.wfNodeUnderPointer=()=> 'b'; ctx.wfNearestInPort=()=> 'in';
  const event=(x=10,y=20,button=0)=>({clientX:x,clientY:y,button,target:{closest:()=>null},preventDefault(){},stopPropagation(){},stopImmediatePropagation(){}});
  return {ctx,handlers,canvasHandlers,graph,undo,classes,event};
}
test('click release keeps wire armed, second port click connects with undo',()=>{
 const {ctx,handlers,event,graph,undo}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
 assert.equal(ctx.wfGesture?.mode,'connect'); assert.equal(graph.edges.length,0);
 ctx.wfStartConnect(event(300,200),'b','in','in');
 assert.deepEqual(JSON.parse(JSON.stringify(graph.edges)),[{from:'a',fromPort:'out',to:'b',toPort:'in'}]);
 assert.equal(undo.length,1); assert.equal(undo[0].edges.length,0); assert.equal(ctx.wfGesture,null);
});
test('input-first click connects exact loop input and replaces only chosen output',()=>{
 const {ctx,handlers,event,graph}=setup();
 graph.edges=[{from:'a',fromPort:'true',to:'old',toPort:'in'},{from:'a',fromPort:'false',to:'other',toPort:'in'}];
 ctx.wfStartConnect(event(),'b','loop','in'); handlers.mouseup(event());
 ctx.wfStartConnect(event(300,200),'a','true','out');
 assert.deepEqual(JSON.parse(JSON.stringify(graph.edges)),[{from:'a',fromPort:'false',to:'other',toPort:'in'},{from:'a',fromPort:'true',to:'b',toPort:'loop'}]);
});
test('same direction and self connections are ignored without undo',()=>{
 const {ctx,handlers,event,graph,undo}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
 ctx.wfStartConnect(event(),'b','out','out'); ctx.wfStartConnect(event(),'a','in','in');
 assert.equal(graph.edges.length,0); assert.equal(undo.length,0); assert.equal(ctx.wfGesture.from,'a');
});
test('pending wire survives pan and empty canvas clicks; right click cancels',()=>{
 const {ctx,handlers,canvasHandlers,event,graph,classes}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
 ctx.wfCanvasMouseDown(event()); handlers.mouseup(event());
 ctx.wfCanvasMouseDown(event(10,20,1)); handlers.mousemove(event(110,120,1)); handlers.mouseup(event(110,120,1));
 assert.equal(ctx.wfPan.x,100); assert.equal(ctx.wfGesture?.mode,'connect'); assert.ok(classes.has('wf-connecting'));
 canvasHandlers.contextmenu(event(110,120,2));
 assert.equal(ctx.wfGesture,null); assert.equal(graph.edges.length,0); assert.ok(!classes.has('wf-connecting'));
});
test('group drag cannot replace a pending connection',()=>{
 const {ctx,handlers,event}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
 ctx.wfNodesInGroup=()=>[];
 ctx.wfStartGroupMove(event(),{x:0,y:0});
 assert.equal(ctx.wfGesture.mode,'connect');
 ctx.wfStartGroupResize(event(),{w:100,h:100});
 assert.equal(ctx.wfGesture.mode,'connect');
});
test('Escape cancels pending wire before run/selection shortcuts',()=>{
 const {ctx,handlers,event,graph}=setup();
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/keyboard.js'),'utf8'),ctx);
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
 handlers['window:keydown']({...event(),key:'Escape'});
 assert.equal(ctx.wfGesture,null); assert.equal(graph.edges.length,0);
});
test('zoom redraws pending wire at last pointer position',()=>{
 const {ctx,handlers,event}=setup();
 ctx.wfStartConnect(event(),'a','out','out'); handlers.mouseup(event());
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
