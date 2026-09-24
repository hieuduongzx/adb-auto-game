const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '../apps/web/wf');
const css = fs.readFileSync(path.join(root, 'css/wf.css'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

test('Designer centers run controls between equal flexible toolbar columns', () => {
  assert.ok(/#toolbar\s*\{[^}]*display\s*:\s*grid/s.test(css), 'toolbar uses grid');
  assert.ok(/#toolbar\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) auto minmax\(0,\s*1fr\)/s.test(css), 'equal sides anchor run center');
  assert.ok(/\.tb-center\s*\{[^}]*justify-self:\s*center/s.test(css));
});

test('View tabs finish the top toolbar instead of occupying a separate row', () => {
  const toolbarEnd = html.indexOf('</header>');
  const tabs = html.indexOf('id="wf-view-tabs"');
  const right = html.indexOf('class="tb-zone tb-right"');
  assert.ok(right < tabs && tabs < toolbarEnd, 'view navigation is inside the right toolbar zone');
  assert.ok(html.indexOf('id="wf-shortcuts-btn"') < tabs, 'tabs follow the utility buttons');
  assert.equal((html.match(/id="wf-view-tabs"/g) || []).length, 1);
  assert.ok(!html.includes('class="wf-stage-header"'), 'no separate navigation row');
  assert.ok(/\.tb-right\s*\{[^}]*flex-wrap:\s*nowrap/s.test(css), 'tabs do not wrap below utilities');
});

test('Constrained toolbar gives run controls their own centered row without overlays', () => {
  assert.ok(/grid-template-areas:\s*"left right"\s*"center center"/.test(css));
  assert.ok(/\.tb-left\s*\{[^}]*flex-wrap:\s*wrap/s.test(css), 'long Win32 controls wrap instead of overlapping Run');
  assert.ok(!/\.tb-center\s*\{[^}]*position:\s*absolute/s.test(css));
});
