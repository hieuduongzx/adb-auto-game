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

test('select option children round-trip with the option they belong to', () => {
  const ctx = vm.createContext({window:{addEventListener(){}}, document:{readyState:'loading', addEventListener(){}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/io.js'), 'utf8'), ctx);
  const vars = [{name:'difficulty', type:'select', value:'Hard', options:['Easy','Hard'],
    optionChildren:{
      Hard:[{name:'lives', type:'number', value:1, children:[]}],
      Easy:[{name:'lives', type:'select', display:'toggle-group', value:'A', options:['A','B'],
        optionChildren:{A:[{name:'potion', type:'bool', value:true}]}}],
    }}];
  const result = ctx.wfHydVars(JSON.parse(JSON.stringify(ctx.wfSerialVars(vars))));
  assert.equal(result[0].optionChildren.Hard[0].name, 'lives');
  assert.equal(result[0].optionChildren.Hard[0].value, 1);
  assert.equal(result[0].optionChildren.Easy[0].display, 'toggle-group');
  assert.equal(result[0].optionChildren.Easy[0].optionChildren.A[0].name, 'potion');
  assert.equal(result[0].optionChildren.Easy[0].optionChildren.A[0].value, true);
  const plain = ctx.wfSerialVars([{name:'flag', type:'bool', value:false}]);
  assert.equal(plain[0].optionChildren, undefined);
});

test('option children survive save/load under their option', () => {
  const ctx = vm.createContext({window:{addEventListener(){}}, document:{readyState:'loading', addEventListener(){}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/io.js'), 'utf8'), ctx);
  const vars = [{name:'element', type:'select', value:'Fire', options:['Fire','Water'],
    optionChildren:{Fire:[{name:'dmg', type:'number', value:1}], Water:[{name:'wet', type:'bool', value:true}]}}];
  const result = ctx.wfHydVars(JSON.parse(JSON.stringify(ctx.wfSerialVars(vars))));
  assert.equal(result[0].optionChildren.Fire[0].name, 'dmg');
  assert.equal(result[0].optionChildren.Water[0].name, 'wet');
});
