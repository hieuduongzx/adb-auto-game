const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const baseCss = fs.readFileSync(path.join(__dirname, '../apps/web/wf/css/base.css'), 'utf8');
const wfCss = fs.readFileSync(path.join(__dirname, '../apps/web/wf/css/wf.css'), 'utf8');
const renderJs = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/render.js'), 'utf8');
const workflowJs = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/workflow.js'), 'utf8');

const GRID = 16;
const tok = (src, name) => {
  const m = src.match(new RegExp(name.replace(/[-]/g, '\\-') + ':\\s*(-?[\\d.]+)px'));
  assert.ok(m, name + ' must be a px token');
  return parseFloat(m[1]);
};
const cells = v => {
  assert.equal(v % GRID, 0, `${v}px is ${v / GRID} cells — must be a whole number of ${GRID}px cells`);
  return v / GRID;
};

test('node card, terminal and try_next sizes are whole grid cells', () => {
  assert.equal(cells(tok(baseCss, '--node-w')), 9, 'card = 9 cells wide');
  assert.equal(cells(tok(baseCss, '--node-h')), 4, 'card = 4 cells tall');
  assert.equal(cells(tok(baseCss, '--term-size')), 3, 'start/end = 3 cells');
  assert.equal(tok(baseCss, '--port-sz'), 6, 'connection dots stay visually compact');
  assert.equal(cells(tok(baseCss, '--port-gap')), 1, 'slot pitch = 1 cell');
  const m = wfCss.match(/\.wf-node\.try_next \{[^}]*width:(\d+)px[^}]*min-height:(\d+)px/);
  assert.ok(m, 'try_next rule found');
  assert.equal(cells(+m[1]), 7, 'try_next = 7 cells wide');
  assert.equal(cells(+m[2]), 2, 'try_next = 2 cells tall');
});

test('every canvas node silhouette has square corners', () => {
  assert.equal(tok(baseCss, '--node-r'), 0, 'the shared node corner token must be square');

  const selectors = [
    '.wf-node-hd',
    '.wf-node.condition:not(.wf-stacked)',
    '.wf-node.loop:not(.wf-stacked)',
    '.wf-node.call:not(.wf-stacked)',
    '.wf-node.try_next',
    '.wf-next-body',
    '.wf-node.start',
    '.wf-node.end',
    '.wf-node.start::after',
    '.wf-node.end::after',
    '.wf-node-tri',
    '.wf-node.running-call::before',
  ];

  const cssWithoutComments = wfCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [...cssWithoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, prelude, body]) => ({
    selectors: prelude.split(',').map(selector => selector.trim()),
    body,
  }));
  for (const selector of selectors) {
    const rule = rules.find(candidate => candidate.selectors.includes(selector)
      && /border-radius:/.test(candidate.body));
    assert.ok(rule, `${selector} rule must exist`);
    assert.match(rule.body, /border-radius:\s*(?:0|var\(--node-r\))\s*;/,
      `${selector} must render with square corners`);
  }
});

test('canvas group frames use the same square geometry as nodes', () => {
  const cssWithoutComments = wfCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [...cssWithoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, prelude, body]) => ({
    selectors: prelude.split(',').map(selector => selector.trim()),
    body,
  }));
  for (const selector of ['.wf-group', '.wf-group-hd', '.wf-group-resize']) {
    const rule = rules.find(candidate => candidate.selectors.includes(selector));
    assert.ok(rule, `${selector} rule must exist`);
    assert.match(rule.body, /border-radius:\s*(?:0|var\(--node-r\))\s*;/,
      `${selector} must use square node geometry`);
  }
});

test('regular cards are 9x4 cells and terminals are 3x3 cells', () => {
  assert.equal(tok(baseCss, '--node-h'), 64);
  assert.equal(tok(baseCss, '--term-size'), 48);
});

test('the primary card port row centres on a grid line', () => {
  const h = tok(baseCss, '--node-h'), sz = tok(baseCss, '--port-sz');
  const rowTop = Math.round((h - sz) / 2);          // WF_ROW_TOP in render.js
  const center = rowTop + sz / 2;                   // dot centre in card coords
  assert.equal(center % GRID, 0, `port centre ${center}px must sit on a ${GRID}px line`);
});

test('WF_GRID stays 16 and grown multi-port cards snap to whole cells', () => {
  const m = workflowJs.match(/const WF_GRID=(\d+)/);
  assert.ok(m, 'WF_GRID constant found');
  assert.equal(+m[1], 16);
  assert.match(renderJs, /Math\.ceil\([^)]*WF_ROW_TOP[\s\S]{0,160}?\/WF_GRID\)\*WF_GRID/,
    'multi-port minHeight must snap up to a whole cell');
});

test('drop offsets put the card corner at the pointer and on-grid', () => {
  // Corner-at-pointer: no offset (drop/quick-connect) or grid-multiple offsets
  // (screen-centre insert) — a half-card 90px (4.5 cells) pushed the corner
  // dead centre of a cell, which is exactly the "never on a grid point" bug.
  for (const [file, pat, want] of [
    ['render.js', /wfSnap\(\(cr\.left\+cr\.width\/2-wr\.left\)\/wfZoom-(\d+)\)/, 80],
    ['groups.js', /wfSnap\(\(e\.clientX-wr\.left\)\/wfZoom\)/, null],
  ]) {
    const src = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8');
    const m = src.match(pat);
    assert.ok(m, file + ' drop position matches');
    if (want !== null) assert.equal(+m[1], want, file + ' centre offset must be a grid multiple');
  }
  const groups = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/groups.js'), 'utf8');
  assert.ok(/wfSnap\(\(clientX-wr\.left\)\/wfZoom\)/.test(groups),
    'quick-connect places the corner at the pointer');
});
