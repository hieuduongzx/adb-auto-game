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
  vm.runInContext(read('workflow.js').slice(0, read('workflow.js').indexOf('// edit = which graph')), ctx);
  vm.runInContext(`const WF={controller:'adb',edit:{kind:'activity',id:'a'},activities:[],functions:[],globals:[],sel:[]};`, ctx);
  for (const file of ['layout.js', 'io.js', 'edit.js', 'selection.js', 'history.js']) vm.runInContext(read(file), ctx);
  return ctx;
}
const node = (ctx, type) => vm.runInContext(`WF_NODES.${type}`, ctx);

test('find-then-tap nodes expose a zero-valued post-find delay', () => {
  const c = load();
  for (const type of ['tap_image', 'tap_image_any', 'tap_all_images', 'tap_text', 'tap_color']) {
    const field = Array.from(node(c, type).fields).find(f => f.k === 'delayAfterFind');
    assert.ok(field, `${type} has delayAfterFind`);
    assert.equal(field.d, 0);
    assert.equal(field.t, 'num');
    assert.equal(field.min, 0);
  }
  for (const type of ['wait_image', 'wait_image_any', 'if_image', 'if_image_any']) {
    assert.equal(Array.from(node(c, type).fields).some(f => f.k === 'delayAfterFind'), false, `${type} does not tap`);
  }
});

test('new sequence image entries distinguish pre-tap and post-tap waits', () => {
  const c = load();
  const defaults = vm.runInContext("wfDefaults('sequence_tap_image')", c);
  assert.deepEqual(JSON.parse(JSON.stringify(defaults.images[0])), {
    template: '', threshold: .85, timeout: 10, offsetX: 0, offsetY: 0,
    delayAfterFind: 0, delay: .1,
  });
});

test('node delay round-trips while legacy before migrates and after is discarded', () => {
  const c = load();
  for (const type of ['tap_image', 'tap_image_any', 'tap_all_images', 'tap_text', 'tap_color', 'sequence_tap_image']) {
    const params = type === 'sequence_tap_image'
      ? {images: [{template: 'a.png', delayAfterFind: 2.5, delay: .1}]}
      : {delayAfterFind: 2.5};
    // Legacy OCR text nodes gain match:'text' on load so the text field stays visible.
    const expected = type === 'tap_text' ? {...params, match: 'text'} : params;
    const original = {id: 'n', type, x: 10, y: 20, params, delayBefore: 1, delayAfter: 3};
    const saved = JSON.parse(JSON.stringify(c.wfSerializeNode(original)));
    const restored = c.wfHydrateGraph({nodes: [saved], edges: []}).nodes.find(n => n.id === 'n');
    assert.deepEqual(JSON.parse(JSON.stringify(restored.params)), expected);
    assert.equal(restored.delay, 1);
    assert.equal(restored.delayAfter, undefined);
    assert.equal(saved.delayAfter, undefined);
    const imported = {id: 'copy', type, params: {}};
    c.wfApplyNodeJson(imported, saved);
    assert.deepEqual(JSON.parse(JSON.stringify(imported.params)), expected);
  }
  const legacy = c.wfHydrateGraph({nodes: [{id:'old',type:'tap_image',params:{delay:2}}]}).nodes.find(n => n.id === 'old');
  assert.equal(legacy.delay, 2);
  assert.equal(legacy.params.delayAfterFind, undefined);
  const defaults = c.wfHydNodeDefaults({delayBefore: 4, delayAfter: 9, retryCount: 2});
  assert.equal(defaults.delay, 4);
  assert.equal(defaults.delayAfter, undefined);
  assert.equal(c.wfSerialNodeDefaults(defaults).delayAfter, undefined);
});

test('post-find delay survives clipboard copying', () => {
  const c = load();
  vm.runInContext(`WF.activities=[{id:'a',graph:{nodes:[{id:'n',type:'tap_image',x:10,y:10,params:{delayAfterFind:2.5}}],edges:[]}}];
    WF.sel=['n']; WF.selectedNode='n';
    function setStatus(){} function wfRenderCanvas(){} function wfMarkSel(){} function wfRenderInspector(){} function wfPopNodes(){}
    wfCopy();wfPaste();`,c);
  assert.equal(vm.runInContext('WF.activities[0].graph.nodes[1].params.delayAfterFind',c),2.5);
});

function inspector(c) {
  c.document.createElement = tag => ({tag, children: [], style: {}, attrs: {},
    appendChild(child) {this.children.push(child); return child;},
    append(...children) {this.children.push(...children);},
    setAttribute(key, value) {this.attrs[key] = value;},
  });
  vm.runInContext(read('inspector.js'), c);
  vm.runInContext(`function wfFieldLabel(f){return f.lbl||f.k;}
    function wfAttachCoordPaste(){} function wfPushUndoDebounced(){} function wfUpdNodeSum(){}
    function wfUpdNodePreview(){} function wfRenderCanvas(){} function wfLoadThumb(){} function uiIco(){return '';}`, c);
}
function descendants(el) {return [el, ...el.children.flatMap(descendants)];}

test('numeric inspector shows zero for older nodes and clamps invalid delay', () => {
  const c = load(); inspector(c);
  const n = {type: 'tap_image', params: {}};
  const f = node(c,'tap_image').fields.find(f => f.k === 'delayAfterFind');
  const input = descendants(c.wfFieldEl(n,f)).find(e => e.tag === 'input');
  assert.equal(input.value, 0);
  for (const [raw, expected] of [['2.5',2.5],['-1',0],['Infinity',0],['',0]]) {
    input.value=raw; input.oninput(); assert.equal(n.params.delayAfterFind,expected);
  }
});

test('sequence editor separates the two waits and preserves offsets', () => {
  const c = load(); inspector(c);
  const n = {type: 'sequence_tap_image', params: {images:[{template:'a.png',delay:.2,offsetX:-4}]}};
  const root = c.wfSequenceImagesField(n,{k:'images'});
  const inputs = descendants(root).filter(e => e.tag === 'input');
  const before = inputs.find(e => e.title === 'Delay after find (s)');
  const after = inputs.find(e => e.title === 'Delay after tap (s)');
  assert.equal(before.value,0); assert.equal(after.value,.2);
  before.value='1.25'; before.oninput();
  assert.equal(n.params.images[0].delayAfterFind,1.25);
  assert.equal(n.params.images[0].delay,.2);
  assert.equal(n.params.images[0].offsetX,-4);
});

test('legacy sequence entries remain readable without a new wait', () => {
  const c = load();
  const graph = vm.runInContext(`wfHydrateGraph({nodes:[{id:'n',type:'sequence_tap_image',params:{images:[{template:'a.png',threshold:.85,timeout:10,offsetX:0,offsetY:0,delay:.2}]} }],edges:[]})`, c);
  const item = graph.nodes.find(n => n.id === 'n').params.images[0];
  assert.equal(item.delay, .2);
  assert.equal(item.delayAfterFind, undefined);
});
