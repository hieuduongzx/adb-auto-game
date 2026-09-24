const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../apps/web/runner/js/runner.js'), 'utf8');

function element() {
  const attrs = {}, classes = new Set();
  return { attrs, dataset: {}, style: {}, textContent: '', innerHTML: '', hidden: false,
    classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
      toggle(x, on) { if(on) classes.add(x); else classes.delete(x); } },
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute(k) { return attrs[k]; },
    querySelectorAll() { return []; }, addEventListener() {} };
}
function runner() {
  const elements = new Map();
  const get = id => { if(!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  const ctx = vm.createContext({ document: { readyState: 'loading', addEventListener() {},
    getElementById: get, querySelectorAll: () => [], querySelector: () => null },
    window: {}, uiIco: () => '', setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, console });
  vm.runInContext(source, ctx);
  return { ctx, get, run: text => vm.runInContext(text, ctx) };
}

test('primary and pause accessible names follow backend run state', () => {
  const r = runner();
  r.run('S.loaded=true; refreshButtons()');
  assert.equal(r.get('btn-primary').attrs['aria-label'], 'Start workflow');
  r.ctx.window.__recv(JSON.stringify({type: 'running_state', data: {running: true, paused: false}}));
  assert.equal(r.get('btn-primary').attrs['aria-label'], 'Stop workflow');
  assert.equal(r.get('btn-pause').attrs['aria-label'], 'Pause workflow');
  assert.equal(r.get('status-text').textContent, 'RUNNING');
  r.ctx.window.__recv(JSON.stringify({type: 'running_state', data: {running: true, paused: true}}));
  assert.equal(r.get('btn-pause').attrs['aria-label'], 'Resume workflow');
  assert.equal(r.get('status-text').textContent, 'PAUSED');
  r.ctx.window.__recv(JSON.stringify({type: 'running_state', data: {running: false, outcome: 'failed'}}));
  assert.equal(r.get('status-text').textContent, 'FAILED');
  assert.equal(r.get('btn-primary').attrs['aria-label'], 'Start workflow');
});

test('activity rows expose enabled, disabled, paused and real background failures', () => {
  const r = runner();
  const activity = {id:'a', name:'Collect', type:'sequence', enabled:true, status:'pending'};
  const row = element(), meta = element(), dot = element();
  row.querySelector = selector => selector === '[data-meta]' ? meta : selector === '[data-dot]' ? dot : null;
  r.ctx.activity = activity; r.ctx.row = row;
  r.run('paintRow(activity, row)');
  assert.match(meta.innerHTML, />Enabled</);
  activity.enabled = false;
  r.run('paintRow(activity, row)');
  assert.match(meta.innerHTML, />Disabled</);
  activity.enabled = true; activity.status = 'running';
  r.run('S.running=true; S.paused=true; paintRow(activity, row)');
  assert.match(meta.innerHTML, />Paused</);
  assert.equal(dot.attrs['aria-label'], 'Status: Paused');
  activity.type = 'background'; activity.status = 'failed';
  r.run('paintRow(activity, row)');
  assert.match(meta.innerHTML, />Failed</);
  assert.equal(row.classList.contains('task-failed'), true);
  activity.status = 'completed';
  r.run('S.running=false; S.paused=false; paintRow(activity, row)');
  assert.match(meta.innerHTML, />Succeeded</);
  activity.enabled = false; activity.status = 'pending';
  r.run("S.running=true; S.runScope=['a']; paintRow(activity, row)");
  assert.match(meta.innerHTML, />Active</); // solo run ignores its checkbox
});

test('queue monitor follows activity events and separates settled from successful', () => {
  const r = runner();
  r.run(`S.loaded=true; S.activities=[
    {id:'a', name:'Collect', enabled:true, status:'pending'},
    {id:'b', name:'Battle', enabled:true, status:'pending'},
    {id:'c', name:'Disabled task', enabled:false, status:'pending'},
    {id:'bg', name:'Watch', type:'background', enabled:true, status:'pending'}]; updateProgress()`);
  assert.equal(r.get('queue-summary').textContent, '2 sequence · 1 background enabled');
  assert.equal(r.get('queue-current').textContent, 'Next: Collect');
  r.ctx.window.__recv(JSON.stringify({type:'running_state', data:{running:true}}));
  r.ctx.window.__recv(JSON.stringify({type:'activity_update', data:{id:'a', status:'running'}}));
  assert.equal(r.get('queue-current').textContent, 'Running: Collect');
  r.ctx.window.__recv(JSON.stringify({type:'activity_update', data:{id:'a', status:'failed'}}));
  assert.equal(r.get('queue-current').textContent, 'Next: Battle');
  assert.equal(r.get('prog-count').textContent, '1/2');
  assert.match(r.get('prog-count').attrs['aria-label'], /1 settled.*0 succeeded.*1 failed/);
  r.run("S.runScope=['c']; updateProgress()");
  assert.equal(r.get('queue-summary').textContent, 'Single activity run');
  assert.equal(r.get('queue-current').textContent, 'Next: Disabled task');
});
