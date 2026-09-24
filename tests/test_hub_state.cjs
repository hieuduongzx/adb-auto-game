const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../apps/web/hub/js/hub.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../apps/web/hub/index.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../apps/web/hub/css/hub.css'), 'utf8');
function loadHub(backend) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: '', textContent: '', hidden: false, disabled: false, dataset: {}, style: {},
      attrs: {}, children: [], value: '',
      classList: { add() {}, remove() {}, toggle() {} },
      setAttribute(key, value) { this.attrs[key] = value; },
      querySelector(selector) { return element(id + selector); },
      querySelectorAll() { return []; },
      addEventListener() {}, appendChild() {}, focus() {},
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    window: { pywebview: { api: backend } },
    document: { readyState: 'loading', addEventListener() {}, removeEventListener() {},
      getElementById: element, querySelectorAll() { return []; },
      createElement: () => element('created'), body: element('body') },
    getComputedStyle: () => ({ gridTemplateColumns: '200px 200px 200px' }),
    uiIco: () => '<svg></svg>', setTimeout() {}, clearInterval() {}, setInterval() {},
  });
  vm.runInContext(source, context);
  return { context, element };
}
const game = { path: 'workflows/Example/workflow.json', folder: 'Example', name: 'Example', controller: 'adb', activityCount: 2 };

test('scan-first hierarchy and feedback use flat, non-overlapping workbench surfaces', () => {
  assert.match(css, /\.library-message\s*\{[^}]*display:\s*flex/);
  assert.doesNotMatch(/\.library-message\s*\{([^}]*)\}/.exec(css)[1], /position:\s*absolute/);
  assert.match(css, /\.game-state\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/);
  assert.match(css, /\.game-info\s*\{[^}]*order:\s*-1/);
  assert.doesNotMatch(css, /box-shadow:\s*var\(--sh-/);
});

test('refresh failure retains cached cards and exposes a persistent retry', async () => {
  let reject = false;
  const { context, element } = loadHub({ list_workflows: async () => {
    if (reject) throw new Error('disk unavailable');
    return { workflows: [game], dir: 'workflows' };
  } });
  await context.loadList();
  const cached = element('grid').innerHTML;
  reject = true;
  await context.loadList();
  assert.equal(element('grid').innerHTML, cached, 'failed refresh must not erase the cached shelf');
  assert.equal(element('grid').attrs['aria-busy'], 'false');
  assert.match(element('library-message-text').textContent, /could not refresh.*last loaded/i);
  assert.equal(element('btn-library-retry').hidden, false);
  assert.equal(element('btn-refresh').disabled, false);
  assert.match(html, /id="library-message"[^>]*role="status"[^>]*aria-live="polite"/);
});

test('initial load failure is not an empty library; Retry recovers through the wired button', async () => {
  let fail = true;
  const { context, element } = loadHub({ list_workflows: async () => {
    if (fail) throw new Error('offline');
    return { workflows: [], dir: 'workflows' };
  } });
  context.wire();
  context.renderSkeleton();
  await context.loadList();
  assert.equal(element('grid').innerHTML, '', 'failed load must stop showing animated skeletons');
  assert.equal(element('empty').hidden, true, 'unknown library is not an empty library');
  assert.equal(element('count').textContent, 'Unavailable');
  fail = false;
  await element('btn-library-retry').onclick();
  assert.equal(element('library-message').hidden, true);
  assert.equal(element('empty').hidden, false);
  assert.equal(element('empty.empty-title').textContent, 'No projects yet');
  assert.equal(element('count').textContent, '0 projects');
});

test('cards expose truthful saved metadata without inventing a connection state', () => {
  const { context } = loadHub({});
  const markup = context.cardHtml({ ...game, modified: '2026-09-24 17:42' }, 0);
  assert.match(markup, /class="game-state"[^>]*>Last saved 2026-09-24 17:42</);
  assert.doesNotMatch(markup, /Connected|Online|Ready/);
});

test('refresh announces loading without replacing cached cards and keeps busy during search', async () => {
  let resolve;
  const backend = { list_workflows: async () => ({ workflows: [game] }) };
  const { context, element } = loadHub(backend);
  await context.loadList();
  const cached = element('grid').innerHTML;
  backend.list_workflows = () => new Promise(r => { resolve = r; });
  const pending = context.loadList();
  assert.equal(element('grid').innerHTML, cached);
  assert.equal(element('grid').attrs['aria-busy'], 'true');
  assert.match(element('library-message-text').textContent, /Refreshing/);
  assert.equal(element('btn-refresh').disabled, true);
  context.render();
  assert.equal(element('grid').attrs['aria-busy'], 'true');
  resolve({ workflows: [game] });
  await pending;
  assert.equal(element('grid').attrs['aria-busy'], 'false');
  assert.equal(element('btn-refresh').disabled, false);
});

test('missing bridge and invalid response are failures, never a successful empty library', async () => {
  const { context, element } = loadHub(null);
  context.renderSkeleton();
  await context.loadList();
  assert.equal(element('grid').attrs['aria-busy'], 'false');
  assert.equal(element('grid').innerHTML, '');
  assert.equal(element('btn-library-retry').hidden, false);
  assert.match(element('library-message-text').textContent, /unavailable/i);
  context.window.pywebview.api = { list_workflows: async () => ({ error: 'disk' }) };
  await context.loadList();
  assert.equal(element('empty').hidden, true);
  assert.equal(element('count').textContent, 'Unavailable');
  context.window.pywebview.api = { list_workflows: async () => ({ workflows: [game] }) };
  await context.loadList();
  const cached = element('grid').innerHTML;
  context.window.pywebview.api.list_workflows = async () => ({ workflows: null });
  await context.loadList();
  assert.equal(element('grid').innerHTML, cached);
  assert.equal(element('btn-library-retry').hidden, false);
});
