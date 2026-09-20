const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadScript(file, extra = {}) {
  const ctx = vm.createContext({
    console,
    document: { addEventListener() {} },
    window: { addEventListener() {} },
    localStorage: { getItem() { return null; }, setItem() {} },
    ...extra,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8'), ctx);
  return ctx;
}

function loadEdit(extra = {}) {
  let nextId = 0;
  return loadScript('edit.js', {
    WF: { activities: [], functions: [], edit: { kind: 'activity', id: null }, nodeDefaults: {} },
    WF_NODES: {
      tap: { fields: [] },
      tap_image: { fields: [{ k: 'template', t: 'tpl' }] },
      tap_image_any: { fields: [{ k: 'templates', t: 'tpls' }] },
      sequence_tap_image: { fields: [{ k: 'images', t: 'sequence_images' }] },
      swipe: { fields: [] },
    },
    wfDefaults(type) {
      if (type === 'tap') return { target: 'pos', x: 0, y: 0 };
      if (type === 'tap_image') return { template: '' };
      if (type === 'tap_image_any') return { templates: [] };
      if (type === 'sequence_tap_image') return { images: [{ template: '', threshold: .85 }] };
      if (type === 'swipe') return { mode: 'coordinates', x1: 0, y1: 0, x2: 0, y2: 0, duration: 300 };
      return {};
    },
    wfNormalizeNode: node => node,
    wfUid: () => `n${++nextId}`,
    ...extra,
  });
}

test('new image nodes reuse the latest successful crop in every image field shape', () => {
  const ctx = loadEdit();
  ctx.wfRememberTemplate('C:\\project\\templates\\button_ok_10_20_30_40.png');

  assert.equal(ctx.wfNewNode('tap_image', 1, 2).params.template,
    'templates/button_ok_10_20_30_40.png');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.wfNewNode('tap_image_any', 1, 2).params.templates)),
    ['templates/button_ok_10_20_30_40.png']);
  assert.equal(ctx.wfNewNode('sequence_tap_image', 1, 2).params.images[0].template,
    'templates/button_ok_10_20_30_40.png');
});

test('latest Preview point and swipe seed matching new nodes', () => {
  const ctx = loadEdit({
    wfPvPoint: [123, 456],
    wfPvSwipe: { x1: 10, y1: 20, x2: 300, y2: 400, duration: 275 },
  });

  assert.deepEqual(JSON.parse(JSON.stringify(ctx.wfNewNode('tap', 1, 2).params)),
    { target: 'pos', x: 123, y: 456 });
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.wfNewNode('swipe', 1, 2).params)),
    { mode: 'coordinates', x1: 10, y1: 20, x2: 300, y2: 400, duration: 275 });
});

test('applying a Library template updates supported selected nodes but rejects unrelated nodes', () => {
  const ctx = loadEdit();
  const single = { type: 'tap_image', params: { template: '' } };
  const many = { type: 'tap_image_any', params: { templates: [] } };
  const unrelated = { type: 'tap', params: { x: 1, y: 2 } };

  assert.equal(ctx.wfApplyTemplateToNode(single, 'templates/a.png'), true);
  assert.equal(single.params.template, 'templates/a.png');
  assert.equal(ctx.wfApplyTemplateToNode(many, 'templates/a.png'), true);
  assert.deepEqual(JSON.parse(JSON.stringify(many.params.templates)), ['templates/a.png']);
  assert.equal(ctx.wfApplyTemplateToNode(unrelated, 'templates/a.png'), false);
});

test('canvas edit shortcuts do not mutate hidden graph selections from Preview or Library', () => {
  const handlers = {};
  let deleted = 0;
  const ctx = loadScript('keyboard.js', {
    window: { addEventListener(type, fn) { handlers[type] = fn; } },
    WF: { sel: ['node-a'] },
    wfCurView: () => 'library',
    wfDeleteSelected: () => { deleted++; },
  });
  const event = { key: 'Delete', target: { tagName: 'BODY', closest: () => null }, preventDefault() {} };
  handlers.keydown(event);
  assert.equal(deleted, 0);

  ctx.wfCurView = () => 'preview';
  handlers.keydown(event);
  assert.equal(deleted, 0);
});

test('workflow undo and redo do not mutate hidden graphs outside Canvas', () => {
  const handlers = {};
  let undo = 0, redo = 0;
  loadScript('keyboard.js', {
    window: { addEventListener(type, fn) { handlers[type] = fn; } },
    WF: { sel: [] }, wfCurView: () => 'preview',
    wfUndo: () => { undo++; }, wfRedo: () => { redo++; },
  });
  const event = key => ({ key, ctrlKey: true, target: { tagName: 'BODY', closest: () => null }, preventDefault() {} });
  handlers.keydown(event('z'));
  handlers.keydown(event('y'));
  assert.equal(undo, 0);
  assert.equal(redo, 0);
});

test('Ctrl+Z inside an input keeps native text undo instead of undoing the workflow', () => {
  const handlers = {};
  let undo = 0;
  loadScript('keyboard.js', {
    window: { addEventListener(type, fn) { handlers[type] = fn; } },
    WF: { sel: [] },
    wfUndo: () => { undo++; },
  });
  let prevented = false;
  handlers.keydown({
    key: 'z', ctrlKey: true,
    target: { tagName: 'INPUT', isContentEditable: false },
    preventDefault() { prevented = true; },
  });
  assert.equal(undo, 0);
  assert.equal(prevented, false);
});

test('switching graphs restores each graph camera instead of resetting the canvas', () => {
  const ctx = loadEdit({
    WF: {
      activities: [
        { id: 'a', graph: { nodes: [] } },
        { id: 'b', graph: { nodes: [] } },
      ],
      functions: [], edit: { kind: 'activity', id: 'a' }, nodeDefaults: {},
    },
    wfPan: { x: 120, y: 80 }, wfZoom: 1.5,
    wfClearSel() {}, wfRenderAll() {},
  });

  ctx.wfSelectActivity('b');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.wfPan)), { x: 0, y: 0 });
  assert.equal(ctx.wfZoom, 1);
  ctx.wfPan = { x: -40, y: 15 }; ctx.wfZoom = .8;
  ctx.wfSelectActivity('a');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.wfPan)), { x: 120, y: 80 });
  assert.equal(ctx.wfZoom, 1.5);
  ctx.wfSelectActivity('b');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.wfPan)), { x: -40, y: 15 });
  assert.equal(ctx.wfZoom, .8);
});

test('renaming or deleting the latest crop keeps Designer context valid', () => {
  const ctx = loadEdit();
  ctx.wfRememberTemplate('templates/old.png');
  ctx.wfTemplateContextRenamed('templates/old.png', 'templates/new.png');
  assert.equal(ctx.wfNewNode('tap_image', 1, 2).params.template, 'templates/new.png');
  ctx.wfTemplateContextDeleted('templates/new.png');
  assert.equal(ctx.wfNewNode('tap_image', 1, 2).params.template, '');
});

test('template context updates require the same relative path, not only the same basename', () => {
  const ctx = loadEdit();
  ctx.wfRememberTemplate('templates/a/icon.png');
  ctx.wfTemplateContextDeleted('templates/b/icon.png');
  assert.equal(ctx.wfNewNode('tap_image', 1, 2).params.template, 'templates/a/icon.png');
  ctx.wfTemplateContextRenamed('templates/b/icon.png', 'renamed.png');
  assert.equal(ctx.wfNewNode('tap_image', 1, 2).params.template, 'templates/a/icon.png');
  ctx.wfTemplateContextRenamed('templates/a/icon.png', 'renamed.png');
  assert.equal(ctx.wfNewNode('tap_image', 1, 2).params.template, 'templates/renamed.png');
});

test('undo saves the outgoing graph camera and restores the snapshot graph camera', () => {
  const calls = [];
  const ctx = loadScript('history.js', {
    WF: {
      edit: { kind: 'activity', id: 'a' }, activities: [], functions: [], globals: [],
      sel: [], selectedNode: null, speedhack: {},
    },
    wfTakeSnapshot: undefined,
    wfCleanGraph: g => g, wfHydrateGraph: g => g,
    wfSaveGraphCamera: () => calls.push('save'),
    wfRestoreGraphCamera: (kind, id) => calls.push(`restore:${kind}:${id}`),
    wfRenderAll() {}, setStatus() {}, wfMarkDirty() {},
  });
  vm.runInContext(`_undoStack.push({
    editKind:'activity', editId:'b', activities:[{id:'b',name:'B',type:'sequence',enabled:true,vars:[],graph:{nodes:[],edges:[],groups:[]}}], functions:[], globals:[],
    package:'', speedhack:{}, sel:[], selectedNode:null
  })`, ctx);
  ctx.wfUndo();
  assert.deepEqual(calls, ['save', 'restore:activity:b']);
});
