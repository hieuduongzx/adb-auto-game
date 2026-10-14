const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../apps/web/runner/js/runner.js'), 'utf8');
// The text of one top-level `function name(){…}` (brace-matched).
function fnSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} is defined`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unbalanced ${name}`);
}
const code = fnSource('fmtNextStart') + '\n' + fnSource('renderFlowSub');

function subtitle(state) {
  const element = {};
  const ctx = { $: () => element, U: { version: state.version || '' }, Date,
    S: { loaded: true, running: !!state.running, controller: state.controller,
         schedule: state.schedule || { enabled: false, next: null } } };
  vm.runInNewContext(code + '\nrenderFlowSub();', ctx);
  return element.textContent;
}

for (const [controller, label] of [['win32', 'Windows'], ['adb', 'Android']]) {
  for (const version of ['', '1.2.3']) {
    test(`${controller} source label preserves version ${version || '(none)'}`, () => {
      assert.equal(subtitle({ controller, version }), label + (version ? ` · v${version}` : ''));
    });
  }
}

test('an enabled schedule names the next start while idle, not while running', () => {
  const schedule = { enabled: true, next: Date.now() / 1000 + 90 * 60 };
  assert.match(subtitle({ controller: 'adb', schedule }), /^Android · next start (today|tomorrow) \d\d:\d\d · in 1h 30m$/);
  assert.equal(subtitle({ controller: 'adb', schedule, running: true }), 'Android');
});
