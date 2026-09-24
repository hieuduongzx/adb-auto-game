const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../apps/web/wf/js/inspector.js'), 'utf8');
const ctx = vm.createContext({document: {addEventListener() {}}, window: {addEventListener() {} }});
vm.runInContext(source, ctx);

test('image inspector groups target, branching and timing while retaining original fields', () => {
  const fields = [{k:'template',t:'tpl'}, {k:'timeout',t:'num'}, {k:'offsetX',t:'num'},
    {k:'offsetY',t:'num'}, {k:'negate',t:'bool'}, {k:'_region',t:'region'}];
  const groups = ctx.wfInspFieldGroups({type:'wait_image'}, fields);
  assert.deepEqual(Array.from(groups, g=>g.label), ['Target & capture','Branching','Timing']);
  assert.deepEqual(Array.from(groups[0].fields, f=>f.k), ['template','offsetX','offsetY','_region']);
  assert.equal(groups[0].fields[0], fields[0], 'do not clone/replace schema fields or callbacks');
  assert.equal(groups.reduce((n,g)=>n+g.fields.length,0), fields.length);
});

test('variable operator and value stay together; unknown schema fields remain editable', () => {
  const fields = [{k:'name',var:true,t:'text'}, {k:'op',t:'select'}, {k:'value',varRef:true,t:'text'}, {k:'futureParam',t:'text'}];
  const groups=ctx.wfInspFieldGroups({type:'if_var'},fields);
  assert.equal(groups.length,1);
  assert.equal(groups[0].label,'Parameters');
  assert.deepEqual(Array.from(groups[0].fields),fields);
});

test('wait modes stay with timing, while swipe mode stays with target coordinates', () => {
  assert.equal(ctx.wfInspFieldGroups({type:'wait'},[{k:'mode',t:'select'},{k:'seconds',t:'num'}])[0].label,'Timing');
  const g=ctx.wfInspFieldGroups({type:'swipe'},[{k:'mode',t:'select'},{k:'x1',t:'num'},{k:'y1',t:'num'},{k:'duration',t:'num'}]);
  assert.deepEqual(Array.from(g,x=>x.label),['Target & capture','Timing']);
  assert.equal(g[0].fields.length,3);
});

test('selection readout identifies the selected node, multiple selection and cleared selection', () => {
  const state={};
  ctx.$=id=>id==='wf-selection-state'?state:null;
  ctx.WF={sel:['n1'],selectedNode:'n1'};
  ctx.WF_NODES={tap:{label:'Tap'}};
  ctx.wfNode=id=>id==='n1'?{id:'n1',type:'tap',label:'Confirm <OK>'}:null;
  ctx.wfSyncInspectorSelection();
  assert.equal(state.textContent,'Selected · Confirm <OK> · n1');
  assert.equal(state.title,state.textContent);
  ctx.WF.sel=['n1','n2']; ctx.WF.selectedNode=null;
  ctx.wfSyncInspectorSelection(); assert.equal(state.textContent,'2 blocks selected');
  ctx.WF.sel=[];
  ctx.wfSyncInspectorSelection(); assert.equal(state.textContent,'No block selected');
});
