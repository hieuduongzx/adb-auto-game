const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/workflow.js'), 'utf8');
const syncGridSource = source.slice(
  source.indexOf('function wfSyncGrid(){'),
  source.indexOf('// Temporarily promote #wf-world')
);

function renderGrid({ snap = true, zoom = 1, pan = { x: 0, y: 0 } } = {}) {
  const canvas = { style: {} };
  const ctx = vm.createContext({
    wfSnapOn: snap,
    wfZoom: zoom,
    wfPan: pan,
    WF_GRID: 16,
    wfCrispPx: value => value,
    $: id => id === 'wf-canvas' ? canvas : null,
    getComputedStyle: () => ({
      getPropertyValue: name => ({
        '--grid-dot': 'major-dot',
        '--grid-dot-minor': 'minor-dot',
        '--grid-line': 'minor-line',
        '--grid-line-major': 'major-line',
      })[name] || '',
    }),
  });
  vm.runInContext(syncGridSource, ctx);
  ctx.wfSyncGrid();
  return canvas.style;
}

test('snap grid renders 16px lines with a stronger line every five cells', () => {
  const style = renderGrid({ snap: true });
  assert.match(style.backgroundImage, /linear-gradient\(to right, minor-line/);
  assert.match(style.backgroundImage, /linear-gradient\(to bottom, minor-line/);
  assert.match(style.backgroundImage, /linear-gradient\(to right, major-line/);
  assert.match(style.backgroundImage, /linear-gradient\(to bottom, major-line/);
  assert.equal(style.backgroundSize, '16px 16px,16px 16px,80px 80px,80px 80px');
});

test('grid-off canvas keeps the quieter dotted background', () => {
  const style = renderGrid({ snap: false });
  assert.match(style.backgroundImage, /^radial-gradient/);
  assert.doesNotMatch(style.backgroundImage, /linear-gradient/);
});

test('grid lines follow canvas zoom and pan', () => {
  const style = renderGrid({ snap: true, zoom: 0.5, pan: { x: 7, y: 9 } });
  assert.equal(style.backgroundSize, '8px 8px,8px 8px,40px 40px,40px 40px');
  assert.equal(style.backgroundPosition, '7px 9px,7px 9px,7px 9px,7px 9px');
});

test('toggling snap refreshes the canvas background immediately', () => {
  const toggleSource = source.slice(
    source.indexOf('function wfToggleSnap(){'),
    source.indexOf('function wfTogglePreview(){')
  );
  let syncs = 0;
  const ctx = vm.createContext({
    wfSnapOn: false,
    wfSyncGrid: () => { syncs += 1; },
    wfSyncToggleBtns() {},
    wfSaveSettings() {},
  });
  vm.runInContext(toggleSource, ctx);
  ctx.wfToggleSnap();
  assert.equal(ctx.wfSnapOn, true);
  assert.equal(syncs, 1);
});
