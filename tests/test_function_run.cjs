const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const read = f => fs.readFileSync(path.join(__dirname,'../apps/web/wf/js',f),'utf8');

// ── Finder: functions themselves are searchable ───────────────────────────────
function finderCtx(){
  const ctx=vm.createContext({
    document:{ addEventListener(){}, querySelector:()=>null, querySelectorAll:()=>[] },
    window:{ addEventListener(){} },
    performance, setTimeout, clearTimeout,
    WF_NODES:{ call:{label:"Call function", fields:[]}, tap:{label:"Tap",fields:[]} },
    WF:{activities:[{id:"a1",name:"Main",graph:{nodes:[{id:"n1",type:"tap",params:{}}],edges:[]}}],
        functions:[{id:"f1",name:"Collect rewards",graph:{nodes:[{id:"f1s",type:"tap",params:{}}],edges:[]}}]},
    wfFnById:id=>id==="f1"?{id:"f1",name:"Collect rewards"}:null,
    wfTplField:()=>null, escHtml:s=>String(s),
  });
  vm.runInContext(read('finder.js').slice(0, read('finder.js').indexOf('function wfFindRender')), ctx);
  return ctx;
}

test('finder indexes the function itself, not only its call blocks', () => {
  const ctx=finderCtx();
  const items=vm.runInContext('wfFindIndex()', ctx);
  const fn=items.filter(i=>i.kind==='fn');
  assert.equal(fn.length,1,'one function entry');
  assert.equal(fn[0].title,'ƒ Collect rewards');
  assert.ok(fn[0].hay.includes('collect'),'searchable by name');
  assert.ok(fn[0].hay.includes('function'),'searchable by the word "function"');
});

test('finder query matches functions and jumping opens the function', () => {
  const ctx=finderCtx();
  const hits=vm.runInContext('wfFindIndex().filter(i=>["collect","ƒ collect"].every(t=>i.hay.includes(t)))', ctx);
  assert.ok(hits.some(i=>i.kind==='fn'),'typing the function name finds the function');
  let opened=null;
  ctx.wfEditFunction=id=>{ opened=id; };
  ctx.wfFindClose=()=>{};
  ctx.wfFindJump(vm.runInContext('wfFindIndex().find(i=>i.kind==="fn")', ctx));
  assert.equal(opened,'f1','jumping a function hit opens it for editing');
});

// ── Right-click a Call function block → run that function standalone ──────────
function groupsCtx(){
  const menu={ children:[], style:{}, innerHTML:'', appendChild(el){ this.children.push(el); } };
  const makeEl=()=>({ innerHTML:'', title:'', type:'', className:'', setAttribute(){}, onclick:null });
  const ctx=vm.createContext({
    document:{ addEventListener(){}, querySelector:()=>null, querySelectorAll:()=>[],
      createElement:makeEl, body:{ appendChild(){} } },
    window:{ addEventListener(){} },
    performance, setTimeout, clearTimeout, requestAnimationFrame:f=>f(),
    WF_NODES:{ call:{label:"Call function", kind:"call", fields:[]}, tap:{label:"Tap", kind:"action", fields:[]} },
    WF:{ sel:["c1"], edit:{kind:"activity",id:"a1"}, activities:[], functions:[] },
    wfNode:id=>id==="c1"?{id:"c1",type:"call",params:{fn:"f1"}}:null,
    wfFnById:id=>id==="f1"?{id:"f1",name:"Collect rewards"}:null,
    wfIco:()=>"", escHtml:s=>String(s),
    wfCanTestNode:n=>!!n && n.type!=="call",
    wfSetAsDefault(){}, wfRunFromSelected(){}, wfRunSingleNode(){},
    wfGroupSelection(){}, wfCopy(){}, wfCut(){}, wfDuplicate(){},
    wfPaste(){}, wfDeleteSelected(){}, wfClipboard:null,
    $:id=>id==="wf-ctxmenu"?menu:(id==="wf-canvas"?{getBoundingClientRect:()=>({})}:null),
    wfHideMenu(){},
  });
  const src=read('groups.js');
  vm.runInContext(src.slice(src.indexOf('function wfShowMenu'), src.indexOf('function wfShowWireMenu')), ctx);
  return {ctx, menu};
}

test('right-clicking a Call function block offers to run that function', () => {
  const {ctx, menu}=groupsCtx();
  let ran=null;
  ctx.wfRunFunction=id=>{ ran=id; };
  ctx.wfShowMenu(10,10);
  const item=menu.children.find(c=>c.innerHTML.includes("Run function"));
  assert.ok(item, 'menu offers "Run function", got: '+menu.children.map(c=>c.innerHTML).join(' | '));
  assert.ok(item.innerHTML.includes('Collect rewards'), 'label names the function');
  item.onclick();
  assert.equal(ran,'f1','clicking runs that function');
});

test('a structural Call block is still not single-node testable', () => {
  const {ctx}=groupsCtx();
  assert.equal(ctx.wfCanTestNode({type:'call',params:{}}), false);
});

