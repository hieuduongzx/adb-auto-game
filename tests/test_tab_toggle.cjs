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
  return {handler:listeners.keydown, keyup:listeners.keyup, blur:listeners.blur, ctx};
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

// ── Space: hold = pan modifier, double-tap = reset zoom ─────────────────────
function spaceHarness(view){
  const h=loadHandler();
  // Declared with `let` in workflow.js, which this harness does not load.
  Object.assign(h.ctx,{wfSpace:false,wfSpaceArmed:false,wfSpaceUsed:false});
  h.ctx.wfCurView=()=>view;
  h.ctx.wfPvActive=view==='preview';
  h.resets={canvas:0, preview:0};
  h.ctx.wfZoomReset=()=>{ h.resets.canvas++; };
  h.ctx.wfPvResetZoom=()=>{ h.resets.preview++; };
  h.t=1000;                                    // fake clock, ms
  h.ctx.performance={ now:()=>h.t };
  return h;
}
const body={ tagName:'BODY', closest:()=>null };
const tapSpace=(h,target=body)=>{ h.handler(makeEvent(' ',target)); h.keyup({key:' '}); };
const none={canvas:0,preview:0};

test('A single Space tap never resets the zoom (stray press is harmless)', () => {
  for(const view of ['canvas','preview']){
    const h=spaceHarness(view);
    tapSpace(h);
    assert.deepEqual(h.resets,none,view);
  }
});

test('Double-tapping Space on the Canvas resets the graph zoom', () => {
  const h=spaceHarness('canvas');
  tapSpace(h); h.t+=200; tapSpace(h);
  assert.deepEqual(h.resets,{canvas:1,preview:0});
});

test('Double-tapping Space on the Preview resets the mirror zoom', () => {
  const h=spaceHarness('preview');
  tapSpace(h); h.t+=200; tapSpace(h);
  assert.deepEqual(h.resets,{canvas:0,preview:1});
});

test('Two taps too far apart are not a double-tap', () => {
  const h=spaceHarness('canvas');
  tapSpace(h); h.t+=600; tapSpace(h);
  assert.deepEqual(h.resets,none);
  h.t+=200; tapSpace(h);                       // …but that one pairs with the previous
  assert.equal(h.resets.canvas,1);
});

test('A double-tap is spent: a third tap starts a new pair', () => {
  const h=spaceHarness('canvas');
  tapSpace(h); h.t+=100; tapSpace(h); h.t+=100; tapSpace(h);
  assert.equal(h.resets.canvas,1);
  h.t+=100; tapSpace(h);
  assert.equal(h.resets.canvas,2);
});

test('Holding Space to pan does not reset, and breaks a pending double-tap', () => {
  for(const view of ['canvas','preview']){
    const h=spaceHarness(view);
    h.handler(makeEvent(' ',body));
    assert.equal(h.ctx.wfSpace,true,`${view}: Space arms pan mode`);
    h.ctx.wfSpaceUsed=true;                    // what the pan mousedown does
    h.keyup({key:' '});
    assert.deepEqual(h.resets,none,`${view}: a pan is not a tap`);
    assert.equal(h.ctx.wfSpace,false);
    // tap, pan, tap → the pan sits between the taps, so no reset.
    const g=spaceHarness(view);
    tapSpace(g);
    g.t+=100; g.handler(makeEvent(' ',body)); g.ctx.wfSpaceUsed=true; g.keyup({key:' '});
    g.t+=100; tapSpace(g);
    assert.deepEqual(g.resets,none,`${view}: pan between taps`);
  }
});

test('Space repeat while held keeps the pan flag', () => {
  const h=spaceHarness('canvas');
  h.handler(makeEvent(' ',body));
  h.ctx.wfSpaceUsed=true;
  h.handler(Object.assign(makeEvent(' ',body),{repeat:true}));   // key auto-repeat
  h.keyup({key:' '});
  h.t+=100; tapSpace(h);
  assert.equal(h.resets.canvas,0);
});

test('Space on a focused button or in a field never resets the zoom', () => {
  for(const target of [
    { tagName:'BUTTON', closest:sel=>sel.includes('button')?{}:null },
    { tagName:'INPUT', isContentEditable:false, closest:()=>null }]){
    const h=spaceHarness('canvas');
    tapSpace(h,target); h.t+=100; tapSpace(h,target);
    assert.deepEqual(h.resets,none,target.tagName);
  }
});

test('Space does nothing on the Library view', () => {
  const h=spaceHarness('library');
  tapSpace(h); h.t+=100; tapSpace(h);
  assert.deepEqual(h.resets,none);
});

test('Losing window focus mid-press is not a tap and clears a pending one', () => {
  const h=spaceHarness('canvas');
  tapSpace(h);
  h.t+=100;
  h.handler(makeEvent(' ',body));
  h.blur();                                    // window loses focus; the keyup never arrives
  h.keyup({key:' '});                          // a later stray release must not count either
  h.t+=100; tapSpace(h);
  assert.equal(h.resets.canvas,0);
  assert.equal(h.ctx.wfSpace,false);
});
