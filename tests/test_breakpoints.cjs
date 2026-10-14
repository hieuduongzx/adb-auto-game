const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const read = file => fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8');
function load() {
  const ctx = vm.createContext({
    document: { documentElement: {}, readyState: 'loading', addEventListener() {}, querySelectorAll: () => [] },
    window: { addEventListener() {} }, getComputedStyle: () => ({ getPropertyValue: () => '' }),
    localStorage: { getItem: () => null }, setTimeout, clearTimeout, $: () => null,
  });
  const source = read('workflow.js');
  vm.runInContext(source.slice(0, source.indexOf('// edit = which graph')), ctx);
  vm.runInContext(`const WF={controller:'adb',edit:{kind:'activity',id:'a'},activities:[],functions:[],globals:[],sel:[]};`, ctx);
  for (const file of ['layout.js', 'io.js', 'edit.js', 'selection.js', 'history.js', 'validate.js']) vm.runInContext(read(file), ctx);
  vm.runInContext(`var status=""; function setStatus(s){ status=s; } function wfNodeElById(){ return null; }`, ctx);
  return ctx;
}

test('a breakpoint survives save and reload; a cleared one leaves no key', () => {
  const c = load();
  const saved = c.wfCleanGraph({ nodes: [
    { id: 'a', type: 'tap', x: 0, y: 0, params: {}, breakpoint: true },
    { id: 'b', type: 'tap', x: 0, y: 0, params: {} },
  ], edges: [] });
  assert.equal(saved.nodes[0].breakpoint, true);
  assert.equal('breakpoint' in saved.nodes[1], false);
  const back = c.wfHydrateGraph(JSON.parse(JSON.stringify(saved)));
  assert.equal(back.nodes.find(n => n.id === 'a').breakpoint, true);
});

test('F9 toggles the selection as one; Start and notes never take one', () => {
  const c = load();
  vm.runInContext(`WF.activities=[{id:'a',graph:{nodes:[
    {id:'s',type:'start',x:0,y:0,params:{}},{id:'t',type:'tap',x:0,y:0,params:{}},
    {id:'u',type:'tap',x:0,y:0,params:{},breakpoint:true},{id:'n',type:'note',x:0,y:0,params:{}}],edges:[]}}];
    WF.sel=['s','t','u','n'];`, c);
  c.wfToggleBreakpoint();
  const flags = () => JSON.parse(vm.runInContext(`JSON.stringify(WF.activities[0].graph.nodes.map(n=>!!n.breakpoint))`, c));
  assert.deepEqual(flags(), [false, true, true, false]);   // mixed → all on
  c.wfToggleBreakpoint();
  assert.deepEqual(flags(), [false, false, false, false]); // all on → all off
  vm.runInContext(`WF.sel=['s']`, c);
  c.wfToggleBreakpoint();
  assert.deepEqual(flags(), [false, false, false, false]);
  assert.match(vm.runInContext('status', c), /Select a block/);
});

test('Shift+F9 clears breakpoints in every activity and function', () => {
  const c = load();
  vm.runInContext(`WF.activities=[{id:'a',graph:{nodes:[{id:'t',type:'tap',x:0,y:0,params:{},breakpoint:true}],edges:[]}}];
    WF.functions=[{id:'f',graph:{nodes:[{id:'g',type:'tap',x:0,y:0,params:{},breakpoint:true}],edges:[]}}];`, c);
  c.wfClearAllBreakpoints();
  assert.equal(vm.runInContext(`[...WF.activities,...WF.functions].flatMap(o=>o.graph.nodes).some(n=>n.breakpoint)`, c), false);
  assert.match(vm.runInContext('status', c), /Cleared 2 breakpoints/);
});
