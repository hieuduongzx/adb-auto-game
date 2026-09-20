const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

// Load keyboard.js and capture its window keydown handler.
function loadHandler(){
  const listeners={};
  const ctx=vm.createContext({
    window:{ addEventListener:(type,fn)=>{ listeners[type]=fn; } },
    performance,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/keyboard.js'),'utf8'),ctx);
  return {handler:listeners.keydown, ctx};
}
function makeEvent(key, target){
  return { key, target, defaultPrevented:false,
    ctrlKey:false, metaKey:false, shiftKey:false,
    preventDefault(){ this.defaultPrevented=true; } };
}

test('Tab toggles Canvas ↔ Preview even when a button has focus', () => {
  const {handler, ctx} = loadHandler();
  ctx.wfToggleView = () => 'preview';
  let switched=null;
  ctx.wfSwitchView = v => { switched=v; };
  // Focus on the Copy button the user just clicked (no typing).
  const btnTarget = { tagName:'BUTTON', closest:sel=>sel.includes('button')?{}:null };
  handler(makeEvent('Tab', btnTarget));
  assert.equal(switched, 'preview', 'Tab on a focused button must switch views');
  // Body focus — same.
  switched=null;
  handler(makeEvent('Tab', { tagName:'BODY', closest:()=>null }));
  assert.equal(switched, 'preview', 'Tab on the body must switch views');
});

test('Tab keeps native behaviour while typing in a field', () => {
  const {handler, ctx} = loadHandler();
  let switched=null;
  ctx.wfToggleView = () => 'preview';
  ctx.wfSwitchView = v => { switched=v; };
  const inp = { tagName:'INPUT', isContentEditable:false, closest:()=>null };
  const e = makeEvent('Tab', inp);
  handler(e);
  assert.equal(switched, null, 'no view switch while typing');
  assert.equal(e.defaultPrevented, false, 'native Tab traversal preserved in fields');
});

test('Space still activates a focused button (native)', () => {
  const {handler, ctx} = loadHandler();
  let switched=null;
  ctx.wfToggleView = () => 'preview';
  ctx.wfSwitchView = v => { switched=v; };
  const btnTarget = { tagName:'BUTTON', closest:sel=>sel.includes('button')?{}:null };
  const e = makeEvent(' ', btnTarget);
  handler(e);
  assert.equal(switched, null, 'Space must stay native on buttons');
  assert.equal(e.defaultPrevented, false);
});
