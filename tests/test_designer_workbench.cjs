const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = name => fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', name), 'utf8');

function element(view) {
  const attrs = {};
  const classes = new Set();
  return { dataset: { view }, style: {}, attrs, tabIndex: -1,
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k]; },
    classList: { add: x => classes.add(x), remove: x => classes.delete(x),
      contains: x => classes.has(x), toggle(x, on) { if (on) classes.add(x); else classes.delete(x); } },
    focus() { this.focused = true; },
  };
}
function views() {
  const tabs = ['canvas', 'preview', 'library'].map(element);
  const container = element();
  container.addEventListener = () => {};
  const ids = Object.fromEntries(['workflow-view', 'wf-world', 'wf-preview-pane', 'wf-library-pane'].map(id => [id, element()]));
  ids['wf-view-tabs'] = container;
  const ctx = vm.createContext({
    document: { readyState: 'loading', addEventListener(type, fn) { if (type === 'DOMContentLoaded') this.ready = fn; }, querySelectorAll: sel => sel.includes('.wf-view-tab') ? tabs : [],
      getElementById: id => ids[id] || null },
    wfPvActive: false, wfPvAuto: false, WF: { controller: 'win32' },
    wfPvInit() {}, wfPvResize() {}, pvInitOcrBackends() {}, wfPvCapture() {},
    api: () => ({ scope_out_dir: () => Promise.resolve('') }), wfPvStopAuto() {},
    wfZoomApplyMode() {}, wfLibOpen() {}, wfGraph: () => null,
  });
  vm.runInContext(source('ui.js'), ctx);
  const preview = source('preview.js');
  vm.runInContext(preview.slice(preview.indexOf('let wfView ='), preview.indexOf('// Repurpose the shared toolbar')), ctx);
  return { ctx, tabs, ids };
}

test('view switching exposes one selected tab and restores Preview after Library', () => {
  const { ctx, tabs, ids } = views();
  for (const view of ['library', 'preview', 'canvas']) {
    ctx.wfSwitchView(view);
    for (const tab of tabs) {
      assert.equal(tab.getAttribute('aria-selected'), String(tab.dataset.view === view));
      assert.equal(tab.tabIndex, tab.dataset.view === view ? 0 : -1);
    }
    for (const [name, id] of [['canvas', 'wf-world'], ['preview', 'wf-preview-pane'], ['library', 'wf-library-pane']]) {
      assert.equal(ids[id].getAttribute('aria-hidden'), String(name !== view));
      assert.equal(ids[id].inert, name !== view);
    }
    assert.equal(ids['workflow-view'].classList.contains('wf-library-on'), view === 'library');
    assert.equal(ids['workflow-view'].classList.contains('wf-preview-on'), view === 'preview');
    if (view === 'preview') assert.equal(ids['wf-library-pane'].style.display, 'none');
  }
});

test('view navigation supports arrows and Home/End without stealing Tab or modifiers', () => {
  const { ctx, tabs } = views();
  const event = (key, target = tabs[0]) => ({ key, target, preventDefault() { this.prevented = true; } });
  const nav = (key, from, expected) => {
    const e = event(key, tabs[from]); ctx.wfViewKeydown(e);
    assert.equal(e.prevented, true);
    assert.equal(ctx.wfCurView(), expected);
    assert.equal(tabs.find(t => t.dataset.view === expected).focused, true);
  };
  nav('ArrowLeft', 0, 'library'); nav('ArrowRight', 2, 'canvas');
  nav('End', 0, 'library'); nav('Home', 2, 'canvas');
  for (const key of ['Tab', ' ', 'f']) {
    const e = event(key); ctx.wfViewKeydown(e); assert.equal(e.prevented, undefined);
  }
  for (const modifier of ['altKey', 'ctrlKey', 'metaKey', 'shiftKey']) {
    const e = Object.assign(event('ArrowRight'), { [modifier]: true });
    ctx.wfViewKeydown(e); assert.equal(e.prevented, undefined);
  }
});

test('save readout distinguishes untitled, dirty, saving and clean documents', async () => {
  const ids = { 'wf-save-btn': element(), 'wf-save-state': element(), 'wf-name': {value:'Flow'} };
  ids['wf-save-btn'].removeAttribute = k => delete ids['wf-save-btn'].attrs[k];
  let finish;
  const ctx = vm.createContext({$: id => ids[id], window:{addEventListener(){}},
    clearTimeout(){}, setTimeout(){}, wfSerialize:()=>({}), setStatus(){}, uiToast(){},
    api:()=>({workflow_save:()=>new Promise(resolve=>{finish=resolve;})}) });
  const io = source('io.js');
  vm.runInContext(io.slice(io.indexOf('let wfDirty='),io.indexOf('async function wfImport')),ctx);
  ctx.wfSyncDirtyUI(); assert.equal(ids['wf-save-state'].textContent,'Not saved');
  ctx.wfMarkDirty(); assert.equal(ids['wf-save-state'].textContent,'Unsaved changes');
  assert.equal(ids['wf-save-btn'].attrs['aria-label'],'Save workflow — unsaved changes');
  const pending=ctx.wfSave();
  assert.equal(ids['wf-save-state'].textContent,'Saving…');
  finish({ok:true}); await pending;
  assert.equal(ids['wf-save-state'].textContent,'Saved');
  assert.equal(ids['wf-save-btn'].attrs['aria-label'],'Save workflow');
  assert.ok(!ids['wf-save-btn'].title.includes('unsaved'), 'successful save must not restore stale dirty title');
  ctx.wfMarkDirty(); const failed=ctx.wfSave(); finish({ok:false}); await failed;
  assert.equal(ids['wf-save-state'].textContent,'Unsaved changes');
});
