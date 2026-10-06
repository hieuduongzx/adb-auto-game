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
  const frames = new Map();
  let nextFrame = 0;
  const get = id => { if(!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  const ctx = vm.createContext({ document: { readyState: 'loading', addEventListener() {},
    getElementById: get, querySelectorAll: () => [], querySelector: () => null },
    window: {}, uiIco: () => '', setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, console,
    requestAnimationFrame: cb => { frames.set(++nextFrame, cb); return nextFrame; },
    cancelAnimationFrame: id => frames.delete(id) });
  vm.runInContext(source, ctx);
  return { ctx, get, frames, run: text => vm.runInContext(text, ctx) };
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

test('activity rows narrate run states and leave enabled/disabled to the checkbox', () => {
  const r = runner();
  const activity = {id:'a', name:'Collect', type:'sequence', enabled:true, status:'pending'};
  const row = element(), meta = element(), dot = element();
  row.querySelector = selector => selector === '[data-meta]' ? meta : selector === '[data-dot]' ? dot : null;
  r.ctx.activity = activity; r.ctx.row = row;
  // An enabled or disabled activity says nothing here — the checkbox carries
  // that state (see renderMeta); only run states are narrated.
  r.run('paintRow(activity, row)');
  assert.doesNotMatch(meta.innerHTML, /Enabled|Disabled/);
  assert.equal(row.classList.contains('task-off'), false);
  activity.enabled = false;
  r.run('paintRow(activity, row)');
  assert.doesNotMatch(meta.innerHTML, /Enabled|Disabled/);
  assert.equal(row.classList.contains('task-off'), true);
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
  assert.doesNotMatch(meta.innerHTML, /Disabled/); // solo run ignores its checkbox
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

test('pending start blocks duplicate full and solo requests while allowing Stop once running', async () => {
  const r = runner();
  let release, starts=0, solos=0;
  r.ctx.window.pywebview = {api:{start:()=>{ starts++; return new Promise(resolve=>release=resolve); },
    run_activity:async()=>{ solos++; return true; }}};
  r.run("S.loaded=true; S.activities=[{id:'a', name:'A', enabled:true}]");
  const first = r.run('onStart()');
  await r.run('onStart()');
  await r.run("onRunActivity('a')");
  assert.equal(starts, 1); assert.equal(solos, 0);
  assert.equal(r.get('btn-primary').disabled, true);
  r.ctx.window.__recv(JSON.stringify({type:'running_state',data:{running:true}}));
  assert.equal(r.get('btn-primary').disabled, false);
  release(true); await first;
  assert.equal(r.run('S.starting'), false);
});

test('rejected solo run clears its pending guard and restores Start', async () => {
  const r = runner();
  r.ctx.window.pywebview = {api:{run_activity:async()=>{throw new Error('bridge unavailable');}}};
  r.run("S.loaded=true; S.activities=[{id:'a', name:'A'}]");
  await r.run("onRunActivity('a')");
  assert.equal(r.run('S.starting'), false);
  assert.equal(r.run('S.runScope'), null);
  assert.equal(r.get('btn-primary').disabled, false);
});

test('run shortcuts ignore text fields, contenteditable, and repeat events', () => {
  const r = runner();
  let starts=0, stops=0, prevented=0;
  r.ctx.startProbe=()=>starts++; r.ctx.stopProbe=()=>stops++;
  r.run('onStart=startProbe; onStop=stopProbe');
  for(const el of [{tagName:'INPUT'}, {tagName:'TEXTAREA'}, {tagName:'SELECT'}, {isContentEditable:true}]){
    r.ctx.document.activeElement=el;
    r.ctx.event={key:'Enter',ctrlKey:true,preventDefault:()=>prevented++};
    r.run('onGlobalKey(event)');
  }
  r.ctx.document.activeElement=null;
  r.ctx.event={key:'Enter',ctrlKey:true,repeat:true,preventDefault:()=>prevented++};
  r.run('S.running=true; onGlobalKey(event)');
  assert.equal(starts+stops+prevented, 0);
  r.ctx.event.repeat=false;
  r.run('onGlobalKey(event)');
  assert.equal(stops, 1);
});

test('initial state restores terminal outcomes and a live solo run scope', () => {
  const r=runner();
  r.run("S.loaded=true; S.activities=[{id:'a',name:'A',enabled:false,status:'failed'}]");
  r.ctx.snapshot={running:false,paused:false,outcome:'failed',outcomeReason:'Missing image',runScope:['a']};
  r.run('applyRunState(snapshot)');
  assert.equal(r.get('status-text').textContent, 'FAILED');
  assert.equal(r.run('S.runScope[0]'), 'a');
  r.ctx.snapshot={running:true,paused:true,runScope:['a'],startedAt:123};
  r.run('applyRunState(snapshot)');
  assert.equal(r.get('status-text').textContent, 'PAUSED');
  assert.equal(r.run('_elapsedStart'), 123000);
});

test('failed checkbox save retains the previous enabled state', async () => {
  const r=runner();
  r.ctx.window.pywebview={api:{toggle_activity:async()=>false}};
  r.run("S.activities=[{id:'a',name:'A',enabled:true}]");
  assert.equal(await r.run('setActivityEnabled(S.activities[0],false)'),false);
  assert.equal(r.run('S.activities[0].enabled'),true);
  assert.equal(r.run('S.activities[0].savingEnabled'),false);
});

test('init applies state before waiting on changelog and update modals', () => {
  const init=source.slice(source.indexOf('async function init(){'));
  assert.ok(init.indexOf('applyRunState(st)') < init.indexOf('await maybeShowPendingChangelog()'));
  assert.ok(init.indexOf('applyRunState(st)') < init.indexOf('await maybePromptUpdate()'));
});

test('a log burst queues one frame, retains the newest 500, and Clear cancels pending lines', () => {
  const r=runner();
  r.run('for(let i=0;i<1000;i++) appendLog({text:"Line "+i,level:"info"})');
  assert.equal(r.frames.size, 1);
  assert.equal(r.run('S.logTotal'), 1000);
  assert.equal(r.run('_pendingLog.length'), 500);
  assert.equal(r.run('_pendingLog[0].text'), 'Line 500');
  r.get('log-body').children=[];
  r.run('clearLog()');
  assert.equal(r.frames.size, 0);
  assert.equal(r.run('_pendingLog.length'), 0);
  assert.equal(r.run('S.logTotal'), 0);
});
