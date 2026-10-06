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
const node = (ctx, type) => vm.runInContext(`WF_NODES.${type}`, ctx);
const fields = (ctx, type) => Array.from(node(ctx, type).fields);

const MATCH_NODES = ['tap_text', 'wait_text', 'if_text', 'loop_until_text'];

test('OCR match nodes offer a literal-vs-regex choice', () => {
  const c = load();
  for (const type of MATCH_NODES) {
    const match = fields(c, type).find(f => f.k === 'match');
    assert.ok(match, `${type} has a match selector`);
    assert.equal(match.t, 'select');
    assert.deepEqual(Array.from(match.opts).map(o => o.v), ['text', 'pattern']);
    assert.equal(match.d, 'text');
    assert.deepEqual(JSON.parse(JSON.stringify(fields(c, type).find(f => f.k === 'text').showWhen)), { match: 'text' });
    assert.deepEqual(JSON.parse(JSON.stringify(fields(c, type).find(f => f.k === 'pattern').showWhen)), { match: 'pattern' });
  }
});

test('legacy OCR nodes keep their text field visible after the upgrade', () => {
  const c = load();
  for (const type of MATCH_NODES) {
    const g = c.wfHydrateGraph({ nodes: [{ id: 'n', type, x: 0, y: 0, params: { text: 'PLAY' } }], edges: [] });
    const n = g.nodes.find(n => n.id === 'n');
    assert.equal(n.params.match, 'text', type);
    const gate = fields(c, type).find(f => f.k === 'text').showWhen;
    assert.equal(n.params.match, gate.match, `${type} text stays editable`);
  }
});

test('OCR match summaries show the pattern in regex mode', () => {
  const c = load();
  assert.match(node(c, 'if_text').sum({ match: 'pattern', pattern: '\\d+/\\d+' }), /\/\\d\+\/\\d\+\//);
  assert.match(node(c, 'wait_text').sum({ match: 'pattern', pattern: 'x', negate: true }), /until gone .*\/x\//);
  assert.match(node(c, 'tap_text').sum({ match: 'pattern', pattern: 'x' }), /\/x\//);
  assert.match(node(c, 'loop_until_text').sum({ match: 'pattern', pattern: 'x' }), /↺ until \/x\//);
  assert.match(node(c, 'if_text').sum({ match: 'text', text: 'PLAY' }), /contains "PLAY"/);
});

test('text-reading nodes expose optional pattern extraction', () => {
  const c = load();
  for (const type of ['read_var', 'adb_shell', 'win_info', 'format_var']) {
    const f = fields(c, type);
    assert.ok(f.some(x => x.k === 'pattern'), `${type} has pattern`);
    const group = f.find(x => x.k === 'group');
    assert.ok(group, `${type} has group`);
    assert.equal(group.t, 'num');
    assert.equal(group.d, 1);
  }
});

test('text producers are recognised as variable sources', () => {
  const c = load();
  vm.runInContext(read('render.js'), c);
  const g = { nodes: [
    { id: 'a', type: 'format_var', params: { name: 'label' } },
    { id: 'b', type: 'adb_shell', params: { name: 'shellOut' } },
    { id: 'c', type: 'win_info', params: { name: 'winTitle' } },
  ], edges: [] };
  const names = Array.from(c.wfGraphVarNames(g));
  assert.deepEqual(names.sort(), ['label', 'shellOut', 'winTitle']);
});
