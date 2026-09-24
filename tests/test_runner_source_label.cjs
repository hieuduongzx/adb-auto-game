const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../apps/web/runner/js/runner.js'), 'utf8');
const assignment = source.match(/\$\("flow-sub"\)\.textContent = [\s\S]*?;/)[0];
for (const [controller, label] of [['win32', 'Window'], ['adb', 'Android']]) {
  for (const version of ['', '1.2.3']) {
    test(`${controller} source label preserves version ${version || '(none)'}`, () => {
      const element = {};
      vm.runInNewContext(assignment, { $: () => element, data: {controller}, U: {version} });
      assert.equal(element.textContent, label + (version ? ` · v${version}` : ''));
    });
  }
}
