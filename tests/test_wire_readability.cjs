const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const ctx = vm.createContext({
  document:{addEventListener(){}}, window:{addEventListener(){}},
  localStorage:{getItem(){return null;}},
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/wf/js/wires.js'),'utf8'),ctx);
const plain = v => JSON.parse(JSON.stringify(v));

test('return link from a side node routes below the entire intervening row',()=>{
  const a={x:660,y:130,edge:710,bottom:170};
  const b={x:110,y:130,edge:80,bottom:170};
  const blocks=[{left:80,right:220,bottom:170},{left:260,right:404,bottom:225},
    {left:445,right:590,bottom:170},{left:610,right:730,bottom:170}];
  const routed=vm.runInContext(`wfRouteReturn(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks)},0)`,ctx);
  const points=plain(vm.runInContext(`wfOrthogonalPoints(${JSON.stringify(routed.a)},${JSON.stringify(routed.b)})`,ctx));
  assert.ok(points[2].y>=253,`return must clear tallest intervening node: ${points[2].y}`);
  assert.equal(points[2].y,points[3].y);
  assert.equal(points[0].x,a.x);
  assert.equal(points.at(-1).x,b.x);
  const d=vm.runInContext(`wfWirePath(${JSON.stringify(routed.a)},${JSON.stringify(routed.b)})`,ctx);
  assert.match(d,/ Q/,'spline mode should use rounded outside return instead of overlapping the row');
});

test('return link takes the nearby open corridor instead of detouring below distant cards',()=>{
  const a={x:680,y:90,edge:704,bottom:120};
  const b={x:120,y:380,edge:96,bottom:410};
  const blocks=[
    {left:80,right:220,top:48,bottom:120},
    {left:260,right:404,top:50,bottom:130},
    {left:445,right:590,top:320,bottom:400},
    {left:640,right:780,top:55,bottom:120},
  ];
  const routed=vm.runInContext(`wfRouteReturn(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks)},0)`,ctx);
  const points=plain(vm.runInContext(`wfOrthogonalPoints(${JSON.stringify(routed.a)},${JSON.stringify(routed.b)})`,ctx));
  assert.ok(points[2].y>144 && points[2].y<296,
    `expected an open lane between rows, got ${points[2].y}`);
});

test('the two real long returns stay near the graph instead of diving below its bottom row',()=>{
  const workflow=JSON.parse(fs.readFileSync(path.join(__dirname,'../workflows/GirlWars/GirlWars.json'),'utf8'));
  const graph=workflow.activities.find(a=>a.id==='sequence_y0b1').graph;
  const nodes=new Map(graph.nodes.map(n=>[n.id,n]));
  const blocks=graph.nodes.map(n=>({id:n.id,left:n.x,right:n.x+(n.type==='start'||n.type==='end'?48:144),top:n.y,bottom:n.y+(n.type==='start'||n.type==='end'?48:64)}));
  for(const [from,to] of [['nxxatqvh','nij39omx'],['n6t0kzpb','nt1m0dej']]){
    const source=nodes.get(from), target=nodes.get(to);
    const a={x:source.x+140,y:source.y+32,edge:source.x+144,bottom:source.y+64};
    const b={x:target.x+4,y:target.y+32,edge:target.x,bottom:target.y+64};
    const route=plain(vm.runInContext(`wfFindReturnPoints(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks.filter(n=>n.id!==from&&n.id!==to))})`,ctx));
    assert.ok(route,`${from} must have a route`);
    assert.deepEqual(route[0],{x:a.x,y:a.y});
    assert.deepEqual(route.at(-1),{x:b.x,y:b.y});
    assert.ok(Math.max(...route.map(p=>p.y))<1100,`${from} should not travel below the bottom row`);
    for(let i=1;i<route.length;i++){
      const p=route[i-1],q=route[i];
      assert.ok(p.x===q.x || p.y===q.y,`${from}: diagonal segment`);
      // The port stubs start inside their own cards. Other cards must remain clear.
      for(const block of blocks.filter(n=>n.id!==from&&n.id!==to)){
        const insideX=p.x===q.x ? p.x>block.left && p.x<block.right : Math.max(p.x,q.x)>block.left && Math.min(p.x,q.x)<block.right;
        const insideY=p.y===q.y ? p.y>block.top && p.y<block.bottom : Math.max(p.y,q.y)>block.top && Math.min(p.y,q.y)<block.bottom;
        assert.ok(!(insideX&&insideY),`${from} crosses node ${block.id}`);
      }
    }
    const again=plain(vm.runInContext(`wfFindReturnPoints(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks.filter(n=>n.id!==from&&n.id!==to))})`,ctx));
    assert.deepEqual(route,again);
  }
});

test('rendered return path follows obstacle waypoints without changing ordinary link modes',()=>{
  const a={x:500,y:100,edge:504,bottom:132,routePoints:[{x:500,y:100},{x:520,y:100},{x:520,y:180},{x:80,y:180},{x:80,y:100},{x:100,y:100}]};
  const b={x:100,y:100,edge:96,bottom:132};
  const d=vm.runInContext(`wfWirePath(${JSON.stringify(a)},${JSON.stringify(b)})`,ctx);
  assert.match(d,/520,180/);
  assert.match(d,/80,180/);
  assert.match(d,/ Q/);
  const ordinary=vm.runInContext(`wfWirePath(${JSON.stringify({...a,routePoints:undefined})},${JSON.stringify(b)})`,ctx);
  assert.notEqual(d,ordinary);
});

test('same-level return leaves the source rightwards and enters the destination from its left',()=>{
  const a={x:500,y:110,edge:504,bottom:140},b={x:104,y:110,edge:100,bottom:140};
  const blocks=[{left:270,right:340,top:80,bottom:140}];
  const points=plain(vm.runInContext(`wfFindReturnPoints(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks)})`,ctx));
  assert.ok(points);
  assert.ok(points[1].x>a.edge);
  assert.ok(points.at(-2).x<b.edge);
  assert.ok(points.some(p=>p.y>140 || p.y<80));
});

test('parallel obstacle-aware returns separate their middle lanes',()=>{
  const a={x:500,y:110,edge:520,bottom:155},b={x:100,y:110,edge:80,bottom:155};
  const blocks=[{left:240,right:390,top:80,bottom:160}];
  const run=lane=>plain(vm.runInContext(`wfFindReturnPoints(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks)},${lane})`,ctx));
  const first=run(0),second=run(1);
  assert.ok(first&&second);
  assert.notDeepEqual(first,second);
  assert.deepEqual(run(1),second);
});

test('parallel return links have distinct stable lanes',()=>{
  const a={x:500,y:110,edge:520,bottom:155},b={x:100,y:110,edge:80,bottom:155};
  const blocks=[{left:80,right:520,bottom:155}];
  const y=i=>vm.runInContext(`wfRouteReturn(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks)},${i}).a.returnY`,ctx);
  assert.ok(y(1)>y(0));
  assert.equal(y(1),y(1));
});
