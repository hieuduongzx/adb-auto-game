const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const read = file => fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8');

// Shared stubs: enough of the designer globals for base.js's countdown block
// and render.js's wfTimeoutChipHtml to run outside a browser.
function makeCtx(){
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
    function wfNode(id){ return {id, type:'wait_image', params:{timeout:3}}; }
    function wfNodeElById(){ return null; }
    function wfGraph(){ return {nodes:[],edges:[]}; }
    function wfIco(){ return ''; } function setStatus(){} function wfColorBranch(){}
    function wfMarkUnreached(){} function wfPaintCallStack(){} function wfCallStackClear(){}
    function wfResetActStatus(){}
    const wfRan={}, wfRanPort={}, wfNodeDur={}, wfNodeT0={}, wfFailShots={}, wfActStatus={}, wfCallStack=[];
    let wfRunNode=null, wfLiveNode=null, wfRunStopped=false, wfNodeTesting=false;
    const wfDelaySecs = v => { const n=parseFloat(v); return String(n) + 's'; };
    const escHtml = s => String(s);
  `, ctx);
  return ctx;
}

test('wfTimeoutChipHtml: only timeout-field blocks get a badge, value shown', () => {
  const ctx = makeCtx();
  vm.runInContext(read('render.js').slice(read('render.js').indexOf('function wfTimeoutChipHtml')), ctx);
  const html = vm.runInContext(`wfTimeoutChipHtml({id:'n1',type:'wait_image',params:{timeout:10}})`, ctx);
  assert.ok(html.includes('wf-node-timeout'), 'badge rendered');
  assert.ok(html.includes('10s'), 'limit text shown');
  assert.ok(html.includes('data-secs="10"'), 'secs stored on the chip');
  // tap has no timeout field → nothing.
  assert.equal(vm.runInContext(`wfTimeoutChipHtml({id:'n2',type:'tap',params:{}})`, ctx), '');
  // Non-numeric timeout ({var} or blank → default) → generic mark, no fake value.
  const varHtml = vm.runInContext(`wfTimeoutChipHtml({id:'n3',type:'wait_image',params:{timeout:'{t}'}})`, ctx);
  assert.ok(varHtml.includes('wf-node-timeout'));
  assert.ok(!varHtml.includes('{t}s'));
});

// Fake chip element good enough for wfPaintNodeDelay / wfClearNodeDelay.
function fakeChip(){
  const lbl = { textContent:'3s' };
  const set = new Set(['wf-node-timeout']);
  return { lbl,
    dataset:{ secs:'3' }, title:'',
    classList:{ add:c=>set.add(c), remove:c=>set.delete(c), contains:c=>set.has(c) },
    style:{ setProperty(){}, removeProperty(){} },
    querySelector: sel => sel==='.wf-timeout-label' ? lbl : null,
    // wfRestoreDelayChip resolves the node through the chip's owner element.
    closest: () => ({ dataset:{ node:'n1' } }),
  };
}

test('timeout countdown: start → counts down → clear restores static value', () => {
  const ctx = makeCtx();
  const chip = fakeChip();
  // The node element the painter will find, carrying our chip.
  const nodeEl = { dataset:{node:'n1'},
    classList:{ add(){}, remove(){} },
    querySelector: sel => sel==='.wf-node-timeout' ? chip : null,
    querySelectorAll: () => [] };
  vm.runInContext(read('base.js').slice(read('base.js').indexOf('// ── Live delayBefore')), ctx);
  ctx.document.querySelector = sel => sel==='.wf-node[data-node="n1"]' ? nodeEl : null;
  // wfPaintNodeDelay resolves the block through wfNodeElById — re-point the stub.
  vm.runInContext(`wfNodeElById = id => document.querySelector('.wf-node[data-node="'+id+'"]');`, ctx);
  // wfClearNodeDelay sweeps counting chips through querySelectorAll — feed it ours.
  ctx.document.querySelectorAll = sel => sel==='.wf-node-timeout.counting' ? [chip] : [];
  vm.runInContext(`wfStartNodeTimeout('n1');`, ctx);
  assert.equal(vm.runInContext('wfDelayState.phase', ctx), 'timeout');
  assert.equal(vm.runInContext('wfDelayState.total', ctx), 3);
  vm.runInContext('wfPaintNodeDelay()', ctx);
  assert.ok(/^[0-9.]+s$/.test(chip.lbl.textContent), 'counting label, got ' + chip.lbl.textContent);
  assert.ok(chip.classList.contains('counting'), 'counting class on');
  // Run over (node_result / stop) → badge shows the static limit again.
  vm.runInContext('wfClearNodeDelay()', ctx);
  assert.ok(/^3(\.0)?s$/.test(chip.lbl.textContent), 'static limit restored, got ' + chip.lbl.textContent);
  assert.ok(!chip.classList.contains('counting'));
});

test('delayBefore end re-arms the timeout countdown', () => {
  const ctx = makeCtx();
  vm.runInContext(`function wfNode(id){ return {id, type:'wait_image', params:{timeout:5}}; }`, ctx);
  vm.runInContext(read('base.js').slice(read('base.js').indexOf('// ── Live delayBefore')), ctx);
  vm.runInContext(`
    wfStartNodeTimeout('n1');                 // node_active arms the timeout
    wfStartNodeDelay('n1','before',2);        // node_delay "before" replaces it
    const mid = wfDelayState.phase;
    wfEndNodeDelay('n1');                     // engine's delay-end event…
    wfStartNodeTimeout('n1');                 // …events.js re-arms the timeout
    globalThis.__out = { mid, after: wfDelayState.phase, total: wfDelayState.total };
  `, ctx);
  // deepStrictEqual across vm contexts trips on prototypes — compare as JSON.
  assert.equal(JSON.stringify(vm.runInContext('__out', ctx)),
               JSON.stringify({ mid:'before', after:'timeout', total:5 }));
});
