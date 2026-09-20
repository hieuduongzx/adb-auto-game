const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

function setup() {
  const graph = {nodes:[{id:'start',type:'start'},{id:'a',type:'tap'},{id:'b',type:'tap'}],edges:[{from:'a',to:'b'}]};
  let resolve, calls=0, undo=0, current=graph;
  const ctx=vm.createContext({WF:{sel:['a'],selectedNode:'a'},document:{},
    wfGraph:()=>current, uiConfirm:()=>{calls++;return new Promise(r=>{resolve=r;});},
    wfPushUndo:()=>undo++,wfRenderCanvas(){},wfRenderInspector(){},setStatus(){},uiToast(){}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/selection.js'),'utf8'),ctx);
  return {ctx,graph,answer:v=>resolve(v),calls:()=>calls,undo:()=>undo,switchGraph:()=>{current={nodes:[],edges:[]};}};
}
test('deletion waits for confirmation, cancellation preserves graph and undo',async()=>{
  const s=setup(); const pending=s.ctx.wfDeleteSelected();
  assert.equal(s.graph.nodes.length,3); assert.equal(s.undo(),0);
  s.answer(false); await pending;
  assert.equal(s.graph.nodes.length,3); assert.equal(s.graph.edges.length,1); assert.equal(s.undo(),0);
});
test('confirmed deletion removes connected wires, protects start and records one undo',async()=>{
  const s=setup(); const pending=s.ctx.wfDeleteNodes(['start','a']);
  await s.ctx.wfDeleteNode('b'); assert.equal(s.calls(),1);
  s.answer(true); await pending;
  assert.deepEqual(s.graph.nodes.map(n=>n.id),['start','b']);
  assert.equal(s.graph.edges.length,0); assert.equal(s.undo(),1); assert.equal(s.ctx.WF.selectedNode,null);
});
test('switching graphs while confirmation is open cancels deletion',async()=>{
  const s=setup(); const pending=s.ctx.wfDeleteNode('a');
  s.switchGraph(); s.answer(true); await pending;
  assert.equal(s.graph.nodes.length,3); assert.equal(s.undo(),0);
});
