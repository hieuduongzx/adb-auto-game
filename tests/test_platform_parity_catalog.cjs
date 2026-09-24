const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const read = file => fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8');
function load() {
  const ctx = vm.createContext({
    document: { documentElement: {}, readyState: 'loading', addEventListener() {} },
    window: { addEventListener() {} }, getComputedStyle: () => ({ getPropertyValue: () => '' }),
    localStorage: { getItem: () => null }, setTimeout, clearTimeout, $: () => null,
  });
  const source = read('workflow.js');
  vm.runInContext(source.slice(0, source.indexOf('// edit = which graph')), ctx);
  vm.runInContext(`const WF={controller:'adb',edit:{kind:'activity',id:'a'},activities:[],functions:[],globals:[],sel:[]};`, ctx);
  for (const file of ['layout.js', 'io.js', 'edit.js', 'selection.js', 'history.js']) vm.runInContext(read(file), ctx);
  return ctx;
}
const names = ctx => vm.runInContext('Object.keys(WF_NODES)', ctx);
const node = (ctx, type) => vm.runInContext(`WF_NODES.${type}`, ctx);

test('the Designer catalog and the engine registry list exactly the same node types', () => {
  const engine = fs.readFileSync(path.join(__dirname, '../src/workflow/engine.py'), 'utf8');
  const block = engine.slice(engine.indexOf('NODE_TYPES: Dict'), engine.indexOf('# ── Emulator launch specs'));
  const py = new Set([...block.matchAll(/^    "(\w+)":\s*\{"label"/gm)].map(m => m[1]));
  const js = new Set(names(load()));
  assert.deepEqual([...js].filter(t => !py.has(t)).sort(), [], 'in the Designer but not the engine');
  assert.deepEqual([...py].filter(t => !js.has(t)).sort(), [], 'in the engine but not the Designer');
});

test('Tap text is an OCR condition with a bounded region and true/false outputs', () => {
  const c = load();
  const def = node(c, 'tap_text');
  assert.equal(def.cat, 'ocr');
  assert.equal(def.kind, 'condition');
  assert.deepEqual(Array.from(def.outs), ['true', 'false']);
  assert.deepEqual(Array.from(def.fields).map(f => f.k),
    ['text', 'x', 'y', 'w', 'h', 'timeout', 'taps', 'offsetX', 'offsetY', 'whitelist', 'delayAfterFind']);
  assert.deepEqual(JSON.parse(JSON.stringify(c.wfDefaults('tap_text'))), {
    text: '', x: 0, y: 0, w: 200, h: 80, timeout: 10,
    taps: '1', offsetX: 0, offsetY: 0, whitelist: '', delayAfterFind: 0,
  });
});

test('Wait for app works on both controllers, Kill process is Win32-only', () => {
  const c = load();
  assert.equal(c.wfNodeCtrl('wait_app'), null);
  assert.equal(c.wfNodeCtrl('if_app'), null);
  assert.equal(c.wfNodeCtrl('win_kill'), 'win32');
  assert.equal(c.wfNodeAllowed('wait_app', 'adb'), true);
  assert.equal(c.wfNodeAllowed('wait_app', 'win32'), true);
  assert.equal(c.wfNodeAllowed('win_kill', 'adb'), false);
  assert.equal(node(c, 'wait_app').kind, 'condition');
  assert.deepEqual(Array.from(node(c, 'wait_app').outs), ['true', 'false']);
});

test('Wait for app defaults to a 30s timeout and can wait for the app to close', () => {
  const c = load();
  const d = JSON.parse(JSON.stringify(c.wfDefaults('wait_app')));
  assert.equal(d.timeout, 30);
  assert.equal(d.negate, false);
  assert.match(node(c, 'wait_app').sum({ ...d, negate: true }), /until closed/);
  assert.match(node(c, 'wait_app').sum(d), /until running/);
});

test('Kill process defaults to killing the child tree', () => {
  const c = load();
  assert.equal(c.wfDefaults('win_kill').tree, true);
  assert.match(node(c, 'win_kill').sum({ tree: false }), /force-kill process$/);
});

test('If/Wait color can scan a region and show the right fields for each mode', () => {
  const c = load();
  for (const type of ['if_color', 'wait_color', 'loop_until_color']) {
    const fields = Array.from(node(c, type).fields);
    const where = fields.find(f => f.k === 'where');
    assert.ok(where, `${type} has a where selector`);
    assert.deepEqual(Array.from(where.opts).map(o => o.v), ['point', 'anywhere']);
    assert.equal(where.d, 'point');
  }
  const region = Array.from(node(c, 'if_color').fields).find(f => f.k === '_region');
  assert.deepEqual(JSON.parse(JSON.stringify(region.showWhen)), { where: 'anywhere' });
  const x = Array.from(node(c, 'if_color').fields).find(f => f.k === 'x');
  assert.deepEqual(JSON.parse(JSON.stringify(x.showWhen)), { where: 'point' });
  assert.match(node(c, 'if_color').sum({ color: '#f00', where: 'anywhere' }), /region/);
  assert.match(node(c, 'if_color').sum({ color: '#f00', x: 3, y: 4 }), /\(3,4\)/);
});

test('colour nodes saved before "where" existed keep checking their single point', () => {
  const c = load();
  for (const type of ['if_color', 'wait_color']) {
    const g = c.wfHydrateGraph({ nodes: [{ id: 'n', type, x: 0, y: 0, params: { color: '#ff0000', x: 5, y: 6 } }], edges: [] });
    const n = g.nodes.find(n => n.id === 'n');
    assert.equal(n.params.where, 'point', type);
    // inspector.js hides a field unless params[k] === showWhen[k] (strict), so a
    // missing `where` would have hidden x/y on every existing colour node.
    const gate = node(c, type).fields.find(f => f.k === 'x').showWhen;
    assert.equal(n.params.where, gate.where, `${type} x stays editable`);
  }
});
