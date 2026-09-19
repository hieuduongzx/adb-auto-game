const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const read = file => fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8');

// wfWireTone needs WF_NODES (node defs) and wfGraph (the live edge list).
function makeCtx(edges){
  const ctx = vm.createContext({
    document:{ documentElement:{}, readyState:'loading', addEventListener(){},
      querySelector: () => null, querySelectorAll: () => [] },
    window:{ addEventListener(){} },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    localStorage:{ getItem: () => null },
    performance, setTimeout, clearTimeout, setInterval, clearInterval,
    $: () => null,
  });
  vm.runInContext(read('workflow.js').slice(0, read('workflow.js').indexOf('// edit = which graph')), ctx);
  vm.runInContext(`const WF={controller:'adb',edit:{kind:'activity',id:'a'},activities:[],functions:[],globals:[],sel:[]};
    const __edges=${JSON.stringify(edges)};
    function wfGraph(){ return {nodes:[], edges:__edges}; }
    function wfIco(){ return ''; }
    const escHtml = s => String(s);
  `, ctx);
  vm.runInContext(read('render.js').slice(read('render.js').indexOf('function wfWireTone'), read('render.js').indexOf('function wfNodeEl')), ctx);
  return ctx;
}

test('converging wires on one input get distinct stable lane tones', () => {
  const edges = [
    {from:'a', fromPort:'out',  to:'t', toPort:'in'},
    {from:'b', fromPort:'true', to:'t', toPort:'in'},
    {from:'c', fromPort:'out',  to:'t', toPort:'in'},
  ];
  const ctx = makeCtx(edges);
  assert.equal(vm.runInContext(`wfWireTone('out','in',null,__edges[0])`, ctx), 'lane1');
  // Even a semantically-true wire yields to the fan-in lane once converging.
  assert.equal(vm.runInContext(`wfWireTone('true','in',null,__edges[1])`, ctx), 'lane2');
  assert.equal(vm.runInContext(`wfWireTone('out','in',null,__edges[2])`, ctx), 'lane3');
});

test('single-arrival inputs keep their semantic tone; loop return stays amber', () => {
  const edges = [ {from:'a', fromPort:'true', to:'t', toPort:'in'} ];
  const ctx = makeCtx(edges);
  assert.equal(vm.runInContext(`wfWireTone('true','in',{type:'if_image'},__edges[0])`, ctx), 't');
  assert.equal(vm.runInContext(`wfWireTone('out','loop',null,__edges[0])`, ctx), 'loop');
});

test('wires into different input ports of one node do not trigger fan-in', () => {
  const edges = [
    {from:'a', fromPort:'out', to:'t', toPort:'in'},
    {from:'b', fromPort:'out', to:'t', toPort:'loop'},
  ];
  const ctx = makeCtx(edges);
  const tone = vm.runInContext(`wfWireTone('out','in',{type:'tap'},__edges[0])`, ctx);
  assert.equal(tone, 'basic');   // cat of tap — not a lane
});

test('lane assignment wraps after six arrivals', () => {
  const edges = Array.from({length:8}, (_,i)=>({from:'s'+i, fromPort:'out', to:'t', toPort:'in'}));
  const ctx = makeCtx(edges);
  assert.equal(vm.runInContext(`wfWireTone('out','in',null,__edges[6])`, ctx), 'lane1');
  assert.equal(vm.runInContext(`wfWireTone('out','in',null,__edges[7])`, ctx), 'lane2');
});
