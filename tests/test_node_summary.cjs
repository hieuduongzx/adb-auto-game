const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const renderJs = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/render.js'), 'utf8');
const layoutJs = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/layout.js'), 'utf8');

function load(){
  const start = renderJs.indexOf('const WF_SUM_MARKS');
  const end = renderJs.indexOf('function wfNodeEl(');
  assert.ok(start > 0 && end > start, 'summary helpers sit above wfNodeEl');
  const ctx = vm.createContext({ escHtml: s => String(s) });
  const base = layoutJs.slice(layoutJs.indexOf('const wfBase='), layoutJs.indexOf('// Top-level mode switch'));
  vm.runInContext(base + '\n' + renderJs.slice(start, end), ctx);
  return ctx;
}

test('identity stays on line 1 and qualifiers drop to chips', () => {
  const ctx = load();
  // Arrays born in the vm are a different realm, so compare JSON, not deepEqual.
  const parts = s => JSON.parse(vm.runInContext(`JSON.stringify(wfSumParts(${JSON.stringify(s)}))`, ctx));

  const gone = parts('until gone crop_20260715_063825_139_1036_55_17.png ×2');
  assert.equal(gone.main, 'crop_20260715_063825_139_1036_55_17.png');
  assert.deepEqual(gone.chips, ['until gone', '×2']);

  const point = parts('(1056, 141)');
  assert.equal(point.main, '(1056, 141)');
  assert.deepEqual(point.chips, []);

  const assign = parts('isFirstGoHome = false');
  assert.equal(assign.main, 'isFirstGoHome');
  assert.deepEqual(assign.chips, ['false']);

  const short = parts('i = 0');
  assert.equal(short.main, 'i = 0');
  assert.deepEqual(short.chips, []);

  const scroll = parts('↑ ≤10× → crop_20260715_063825_139_1036_55_17.png');
  assert.equal(scroll.main, 'crop_20260715_063825_139_1036_55_17.png');
  assert.deepEqual(scroll.chips, ['↑ ≤10×']);

  const loop = parts('↺ until found crop_20260715_063825.png ≤5×');
  assert.equal(loop.main, 'crop_20260715_063825.png');
  assert.deepEqual(loop.chips, ['≤5×']);

  const many = parts('3 points · together · 80ms');
  assert.equal(many.main, '3 points');
  assert.deepEqual(many.chips, ['together', '80ms']);

  const pair = parts('a.png / b.png');
  assert.equal(pair.main, 'a.png');
  assert.deepEqual(pair.chips, ['b.png']);

  const negated = parts('not found button.png');
  assert.equal(negated.main, 'button.png');
  assert.deepEqual(negated.chips, ['not']);

  const cmp = parts('isFirst == true');
  assert.equal(cmp.main, 'isFirst == true');
  assert.deepEqual(cmp.chips, []);
});

test('a long filename keeps its tail, a short one stays whole', () => {
  const ctx = load();
  const html = s => vm.runInContext(`wfNodeSumHtml(${JSON.stringify(s)}, "")`, ctx);
  const long = html('crop_20260715_063825_139_1036_55_17.png');
  assert.match(long, /wf-sum-file/);
  assert.match(long, /wf-sum-tail">_55_17\.png</);
  assert.match(long, /wf-sum-head">crop_20260715_063825_139_1036</);
  assert.doesNotMatch(long, /wf-sum-meta/);

  const withChip = html('until gone crop_20260715_063825_139_1036_55_17.png');
  assert.match(withChip, /wf-sum-meta/);
  assert.match(withChip, />until gone</);
  assert.match(withChip, /_55_17\.png/);

  const quote = html('"claim reward now"');
  assert.match(quote, /wf-sum-main">"claim reward now"</);
  assert.doesNotMatch(quote, /wf-sum-file/);
});

test('search region is a chip only when the node actually limits one', () => {
  const ctx = load();
  assert.equal(vm.runInContext(`wfRegionChip({params:{}})`, ctx), '');
  assert.equal(vm.runInContext(`wfRegionChip({params:{regionX:0,regionY:0,regionW:0,regionH:0}})`, ctx), '');
  assert.equal(vm.runInContext(`wfRegionChip({params:{regionX:12,regionY:40,regionW:200,regionH:80}})`, ctx), '12,40 200×80');
  const html = vm.runInContext(
    `wfNodeSumHtml('button.png', '', {chips:[wfRegionChip({params:{regionX:12,regionY:40,regionW:200,regionH:80}})]})`,
    ctx);
  assert.match(html, /wf-sum-chip">12,40 200×80</);
});

test('image names are no longer chopped to 14 characters before the card sees them', () => {
  const ctx = load();
  const name = 'crop_20260715_063825_139_1036_55_17.png';
  assert.equal(vm.runInContext(`wfBase('templates/${name}')`, ctx), name);
  assert.equal(vm.runInContext(`wfBase('')`, ctx), '(image)');
  assert.equal(vm.runInContext(`wfBaseAny(['templates/a.png'])`, ctx), 'a.png');
  assert.equal(vm.runInContext(`wfBaseAny(['templates/a.png','templates/b.png'])`, ctx), 'a.png / b.png');
  assert.equal(vm.runInContext(`wfBaseAny(['templates/a.png','templates/b.png','templates/c.png'])`, ctx), 'a.png +2');
});
