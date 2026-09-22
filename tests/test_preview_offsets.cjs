const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/preview.js'), 'utf8');
const context = vm.createContext({
  console,
  window: { addEventListener() {} },
  document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
  WF_NODES: {
    win_click: { label: 'Mouse click' },
    tap_image: { label: 'Tap image' },
    sequence_tap_image: { label: 'Sequence tap image' },
  },
  wfParseRegionFromName() { return null; },
});
vm.runInContext(source, context);

const plain = value => JSON.parse(JSON.stringify(value));

test('fixed-point task preview shows only the final coordinate after offset', () => {
  const shapes = plain(context.wfPvShapesForNode({
    type: 'win_click', params: { x: 100, y: 200, offsetX: 12, offsetY: -8 },
  }));
  assert.deepEqual(shapes, [{
    kind: 'point', x: 112, y: 192, label: 'Mouse click', color: 'node', r: 9,
  }]);
});

test('image task preview calculates tap point from match centre plus node offset', () => {
  assert.deepEqual(
    plain(context.wfPvTapPointForRect([10, 20, 40, 30, .9], { offsetX: 7, offsetY: -3 })),
    [37, 32],
  );
});

test('sequence image preview keeps each item offset with its template', () => {
  const entries = plain(context.wfPvImageEntries({
    type: 'sequence_tap_image',
    params: { images: [
      { template: 'a.png', offsetX: 5, offsetY: 6 },
      { template: 'b.png', offsetX: -2, offsetY: 4 },
    ] },
  }));
  assert.deepEqual(entries.map(entry => [entry.path, entry.params.offsetX, entry.params.offsetY]), [
    ['a.png', 5, 6], ['b.png', -2, 4],
  ]);
});
