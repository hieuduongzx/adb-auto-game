const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

test('local select display survives save/load and activity duplication, including children', () => {
  const ctx = vm.createContext({window:{addEventListener(){}}, document:{readyState:'loading', addEventListener(){}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/io.js'), 'utf8'), ctx);
  const vars = [{name:'difficulty', type:'select', display:'toggle-group', value:'Normal', options:['Easy','Normal','Hard'],
    children:[{name:'mode', type:'select', display:'toggle-group', value:'A', options:['A','B']}]}];
  const result = ctx.wfHydVars(JSON.parse(JSON.stringify(ctx.wfSerialVars(vars))));
  assert.equal(result[0].display, 'toggle-group');
  assert.equal(result[0].children[0].display, 'toggle-group');
  assert.equal(result[0].value, 'Normal');
  vars[0].multiple=true; vars[0].value=['Easy','Hard'];
  const multi=ctx.wfHydVars(JSON.parse(JSON.stringify(ctx.wfSerialVars(vars))));
  assert.equal(multi[0].multiple,true);
  assert.deepEqual(Array.from(multi[0].value),['Easy','Hard']);
  assert.equal(ctx.wfHydVars([{name:'old', type:'select', options:['A']}])[0].display, 'dropdown');
});
