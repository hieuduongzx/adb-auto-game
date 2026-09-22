const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const HTML = fs.readFileSync(path.join(__dirname, '../apps/web/wf/index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(__dirname, '../apps/web/wf/css/wf.css'), 'utf8');
const BASE_CSS = fs.readFileSync(path.join(__dirname, '../apps/web/wf/css/base.css'), 'utf8');

function cssRule(source, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(source);
  assert.ok(match, `missing CSS rule for ${selector}`);
  return match[1];
}

function load(file, extra = {}) {
  const ctx = vm.createContext({
    document: { addEventListener() {} }, window: { addEventListener() {} },
    localStorage: { getItem() { return null; } },
    WF_GEOMETRY: { width:144, height:64 }, ...extra,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8'), ctx);
  return ctx;
}

test('Designer uses the shared workbench shell, toolbar, workspace, and status primitives', () => {
  assert.match(HTML, /<div id="app" class="workbench-shell">/);
  assert.match(HTML, /<header id="toolbar" class="workbench-bar" aria-label="Designer toolbar">/);
  assert.match(HTML, /<main id="workflow-view" class="workbench-main"[^>]*aria-label="Workflow designer workspace">/);
  assert.match(HTML, /<footer id="footer" class="workbench-status" aria-label="Designer status">/);
});

test('Designer dock headers and surfaces follow the shared flat panel grammar', () => {
  assert.ok((HTML.match(/class="[^"]*\bpnl-hd\b/g) || []).length >= 4,
    'major docked work areas expose shared panel headers');
  for (const selector of ['#wf-side .pnl', '#wf-insp-panel', '#log-card']) {
    const rule = cssRule(CSS, selector);
    assert.match(rule, /border-radius:\s*0/);
    assert.match(rule, /box-shadow:\s*none/);
  }
});

test('Designer geometry remains locked to the approved grid footprints', () => {
  assert.match(BASE_CSS, /--node-w:\s*144px/);
  assert.match(BASE_CSS, /--node-h:\s*64px/);
  assert.match(BASE_CSS, /--term-size:\s*48px/);
});

test('orthogonal return wire clears both nodes even when ports are level', () => {
  const ctx = load('wires.js');
  const a = { x:400, y:100, edge:400, bottom:150 };
  const b = { x:100, y:100, edge:100, bottom:150 };
  const points = ctx.wfOrthogonalPoints(a,b);
  assert.deepEqual(JSON.parse(JSON.stringify(points[0])), a);
  assert.deepEqual(JSON.parse(JSON.stringify(points.at(-1))), b);
  assert.ok(points.some(p => p.y > 150), 'return lane must run outside the cards');
  for (let i=1;i<points.length;i++) {
    assert.ok(points[i].x===points[i-1].x || points[i].y===points[i-1].y);
  }
  assert.ok(ctx.wfStraightPath(a,b).includes('Q'), 'corners should be rounded');
});

test('compact layout respects wide nodes and tall multi-output nodes', () => {
  const sizes = { a:[330,140], b:[200,88], c:[200,88], d:[200,88] };
  const ctx=load('layout.js', {
    wfSnap:x=>x,
    wfNodeElById:id=>({offsetWidth:sizes[id][0],offsetHeight:sizes[id][1]}),
  });
  const g={nodes:Object.keys(sizes).map(id=>({id,type:'tap',x:0,y:0})),edges:[]};
  ctx.wfLayoutCompact(g);
  for (let i=0;i<g.nodes.length;i++) for(let j=i+1;j<g.nodes.length;j++) {
    const a=g.nodes[i], b=g.nodes[j], [aw,ah]=sizes[a.id], [bw,bh]=sizes[b.id];
    assert.ok(a.x+aw<=b.x || b.x+bw<=a.x || a.y+ah<=b.y || b.y+bh<=a.y,
      `${a.id} and ${b.id} must not overlap`);
  }
});

test('standard arrange modes keep connected nodes close without overlap', () => {
  const size=[144,64];
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:size[0],height:size[1]},wfSnap:x=>x,
    wfNodeElById:()=>({offsetWidth:size[0],offsetHeight:size[1]}),
  });
  const makeGraph=()=>({
    nodes:['a','b','c'].map(id=>({id,type:'tap',x:0,y:0})),
    edges:[{from:'a',to:'b'},{from:'b',to:'c'}],
  });
  const horizontal=makeGraph();ctx.wfLayoutHorizontal(horizontal);
  assert.equal(horizontal.nodes[1].x-horizontal.nodes[0].x-size[0],32);
  assert.equal(horizontal.nodes[2].x-horizontal.nodes[1].x-size[0],32);
  const vertical=makeGraph();ctx.wfLayoutVertical(vertical);
  assert.equal(vertical.nodes[1].y-vertical.nodes[0].y-size[1],24);
  assert.equal(vertical.nodes[2].y-vertical.nodes[1].y-size[1],24);
});

test('horizontal arrange keeps a whole chain on one center line', () => {
  const sizeOf={
    s:[48,48], a:[144,64], b:[144,64], c:[144,64], d:[144,64], e:[144,64], z:[48,48],
  };
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:144,height:64},
    wfSnap:v=>Math.round(v/16)*16,
    wfNodeElById:id=>({offsetWidth:sizeOf[id][0],offsetHeight:sizeOf[id][1]}),
  });
  const ids=['s','a','b','c','d','e','z'];
  const g={
    nodes:ids.map(id=>({id,type:id==='s'?'start':id==='z'?'end':'tap',x:0,y:0})),
    edges:ids.slice(1).map((id,i)=>({from:ids[i],to:id})),
  };
  ctx.wfLayoutHorizontal(g);
  const by=Object.fromEntries(g.nodes.map(n=>[n.id,n]));
  const center=id=>by[id].y+sizeOf[id][1]/2;
  assert.deepEqual(ids.map(id=>by[id].x), [16,96,272,448,624,800,976]);
  ids.forEach(id=>assert.equal(center(id), center('s')));
  assert.equal(by.a.y, by.s.y-8);
});

test('vertical arrange keeps a whole chain in one column', () => {
  const sizeOf={ s:[48,48], a:[144,64], b:[144,64] };
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:144,height:64},
    wfSnap:v=>Math.round(v/16)*16,
    wfNodeElById:id=>({offsetWidth:sizeOf[id][0],offsetHeight:sizeOf[id][1]}),
  });
  const g={
    nodes:['s','a','b'].map(id=>({id,type:id==='s'?'start':'tap',x:0,y:0})),
    edges:[{from:'s',to:'a'},{from:'a',to:'b'}],
  };
  ctx.wfLayoutVertical(g);
  const by=Object.fromEntries(g.nodes.map(n=>[n.id,n]));
  const center=id=>by[id].x+sizeOf[id][0]/2;
  assert.equal(center('s'), center('a'));
  assert.equal(center('a'), center('b'));
  assert.equal(by.a.y, by.s.y+48+24);
  assert.equal(by.b.y, by.a.y+64+24);
  assert.equal(by.a.x, by.b.x);
});

test('mix arrange folds a long chain down the last column', () => {
  const sizeOf={
    s:[48,48], a:[144,64], b:[144,64], c:[144,64], d:[144,64], e:[144,64], z:[48,48],
  };
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:144,height:64},
    wfSnap:v=>Math.round(v/16)*16,
    wfNodeElById:id=>({offsetWidth:sizeOf[id][0],offsetHeight:sizeOf[id][1]}),
  });
  const ids=['s','a','b','c','d','e','z'];
  const g={
    nodes:ids.map(id=>({id,type:id==='s'?'start':id==='z'?'end':'tap',x:0,y:0})),
    edges:[
      {from:'s',fromPort:'out',to:'a'},
      {from:'a',fromPort:'true',to:'b'},
      {from:'b',fromPort:'true',to:'c'},
      {from:'c',fromPort:'true',to:'d'},
      {from:'d',fromPort:'true',to:'e'},
      {from:'e',fromPort:'out',to:'z'},
    ],
  };
  ctx.wfLayoutMix(g);
  const by=Object.fromEntries(g.nodes.map(n=>[n.id,n]));
  const center=id=>by[id].y+sizeOf[id][1]/2;
  // start + three cards on the rail, the next two stacked under the last
  // card, End stepped out to the right and center-aligned with that card.
  assert.deepEqual(ids.map(id=>by[id].x), [16,96,272,448,448,448,624]);
  assert.equal(by.a.y, by.s.y-8);
  assert.equal(by.b.y, by.a.y);
  assert.equal(by.c.y, by.a.y);
  assert.equal(center('a'), center('s'));
  assert.equal(by.d.y, by.c.y+64+24);
  assert.equal(by.e.y, by.d.y+64+24);
  assert.equal(by.z.x, by.e.x+144+32);
  assert.equal(center('z'), center('e'));
});

test('mix arrange keeps the true rail straight and drops false below it', () => {
  const sizeOf={ s:[144,64], t:[144,64], f:[144,64], n:[144,64] };
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:144,height:64},
    wfSnap:v=>Math.round(v/16)*16,
    wfNodeElById:id=>({offsetWidth:sizeOf[id][0],offsetHeight:sizeOf[id][1]}),
  });
  const g={
    nodes:['s','t','f','n'].map(id=>({id,type:'tap',x:0,y:0})),
    edges:[
      {from:'s',fromPort:'true',to:'t'},
      {from:'s',fromPort:'false',to:'f'},
      {from:'f',fromPort:'out',to:'n'},
    ],
  };
  ctx.wfLayoutMix(g);
  const by=Object.fromEntries(g.nodes.map(n=>[n.id,n]));
  assert.equal(by.t.y, by.s.y);
  assert.equal(by.t.x, by.s.x+144+32);
  assert.equal(by.f.x, by.t.x);
  assert.equal(by.f.y, by.t.y+64+24);
  assert.equal(by.n.y, by.f.y);
  assert.equal(by.n.x, by.f.x+144+32);
});

test('compact arrange uses a 16px gutter in both directions', () => {
  const size=[144,64];
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:size[0],height:size[1]},wfSnap:x=>x,
    wfNodeElById:()=>({offsetWidth:size[0],offsetHeight:size[1]}),
  });
  const g={nodes:['a','b','c','d'].map(id=>({id,type:'tap',x:0,y:0})),edges:[]};
  ctx.wfLayoutCompact(g);
  const xs=[...new Set(g.nodes.map(n=>n.x))].sort((a,b)=>a-b);
  const ys=[...new Set(g.nodes.map(n=>n.y))].sort((a,b)=>a-b);
  assert.equal(xs[1]-xs[0]-size[0],16);
  assert.equal(ys[1]-ys[0]-size[1],16);
});

test('radial arrange contracts sparse rings while keeping nodes separate', () => {
  const size=[144,64];
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:size[0],height:size[1]},wfSnap:x=>x,
    wfNodeElById:()=>({offsetWidth:size[0],offsetHeight:size[1]}),
  });
  const g={
    nodes:['root','a','b'].map(id=>({id,type:id==='root'?'start':'tap',x:0,y:0})),
    edges:[{from:'root',to:'a'},{from:'root',to:'b'}],
  };
  ctx.wfLayoutRadial(g);
  const top=Math.min(...g.nodes.map(n=>n.y));
  const bottom=Math.max(...g.nodes.map(n=>n.y+size[1]));
  assert.ok(bottom-top<=420,`sparse radial layout is ${bottom-top}px tall`);
  for(let i=0;i<g.nodes.length;i++) for(let j=i+1;j<g.nodes.length;j++) {
    const a=g.nodes[i],b=g.nodes[j];
    assert.ok(a.x+size[0]<=b.x||b.x+size[0]<=a.x||a.y+size[1]<=b.y||b.y+size[1]<=a.y);
  }
});

test('radial arrange uses both axes for a deep sparse workflow', () => {
  const size=[144,64];
  const ctx=load('layout.js',{
    WF_GEOMETRY:{width:size[0],height:size[1]},wfSnap:x=>x,
    wfNodeElById:()=>({offsetWidth:size[0],offsetHeight:size[1]}),
  });
  const ids=Array.from({length:8},(_,i)=>`n${i}`);
  const g={
    nodes:ids.map((id,i)=>({id,type:i?'tap':'start',x:0,y:0})),
    edges:ids.slice(1).map((id,i)=>({from:ids[i],to:id})),
  };
  ctx.wfLayoutRadial(g);
  const minX=Math.min(...g.nodes.map(n=>n.x)),maxX=Math.max(...g.nodes.map(n=>n.x+size[0]));
  const minY=Math.min(...g.nodes.map(n=>n.y)),maxY=Math.max(...g.nodes.map(n=>n.y+size[1]));
  assert.ok(maxX-minX>400,'deep radial flow must fan out horizontally');
  assert.ok(Math.max(maxX-minX,maxY-minY)<1300,'deep radial flow must remain compact');
  for(let i=0;i<g.nodes.length;i++) for(let j=i+1;j<g.nodes.length;j++) {
    const a=g.nodes[i],b=g.nodes[j];
    assert.ok(a.x+size[0]<=b.x||b.x+size[0]<=a.x||a.y+size[1]<=b.y||b.y+size[1]<=a.y);
  }
});

test('return wire has finite geometry for self-links, vertical and close ports', () => {
  const ctx=load('wires.js');
  for(const b of [{x:200,y:40},{x:200,y:180},{x:208,y:42},{x:600,y:180}]) {
    const a={x:200,y:40,bottom:100};
    const d=ctx.wfStraightPath(a,b);
    assert.ok(!/NaN|Infinity/.test(d));
    vm.runInContext('wfLinkMode="straight"',ctx);
    const m=ctx.wfLinkMid(a,b);
    assert.ok([m.x,m.y,m.ang].every(Number.isFinite));
  }
});

test('fit frames real bounds above the activity dock and focuses only selected nodes', () => {
  const source=fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/workflow.js'),'utf8');
  const nodes=[{dataset:{node:'a'},offsetLeft:10,offsetTop:0,offsetWidth:200,offsetHeight:88},
    {dataset:{node:'b'},offsetLeft:700,offsetTop:240,offsetWidth:200,offsetHeight:160}];
  const ctx=vm.createContext({
    WF:{sel:['b']},wfPan:{x:0,y:0},wfZoom:1,
    document:{querySelectorAll:()=>nodes},
    $:id=>id==='wf-canvas'?{clientWidth:1000,clientHeight:700,getBoundingClientRect:()=>({top:50})}:
      {offsetParent:{},classList:{contains:()=>false},getBoundingClientRect:()=>({top:530})},
    wfCancelCamAnim(){},wfApplyTransform(){},
  });
  vm.runInContext(source.slice(source.indexOf('function wfFit(animate'),source.indexOf('function wfFitSelection')),ctx);
  ctx.wfFit(false);
  for(const n of nodes){
    assert.ok(ctx.wfPan.x+n.offsetLeft*ctx.wfZoom>=68);
    assert.ok(ctx.wfPan.y+n.offsetTop*ctx.wfZoom>=60);
    assert.ok(ctx.wfPan.x+(n.offsetLeft+n.offsetWidth)*ctx.wfZoom<=976);
    assert.ok(ctx.wfPan.y+(n.offsetTop+n.offsetHeight)*ctx.wfZoom<=456);
  }
  ctx.wfFit(false,true);
  assert.equal(ctx.wfZoom,1);
  const before={...ctx.wfPan};ctx.WF.sel=[];ctx.wfFit(false,true);
  assert.deepEqual({...ctx.wfPan},before,'empty selection must not move the camera');
});

test('held arrow nudges snapshot the original position once, before moving', () => {
  const handlers={},node={id:'a',x:100,y:100},snapshots=[];
  const ctx=load('keyboard.js',{
    window:{addEventListener:(type,fn)=>handlers[type]=fn},
    WF:{sel:['a']},wfGraph:()=>({nodes:[node]}),wfRenderCanvas(){},
    wfPushUndo:()=>snapshots.push({...node}),
  });
  const event={key:'ArrowRight',target:{tagName:'BODY'},preventDefault(){}};
  handlers.keydown(event);handlers.keydown(event);
  assert.equal(node.x,102);assert.equal(snapshots.length,1);assert.equal(snapshots[0].x,100);
  handlers.keyup(event);handlers.keydown(event);
  assert.equal(snapshots.length,2);assert.equal(snapshots[1].x,102);
});
