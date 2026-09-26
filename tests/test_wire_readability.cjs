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

test('parallel return links have distinct stable lanes',()=>{
  const a={x:500,y:110,edge:520,bottom:155},b={x:100,y:110,edge:80,bottom:155};
  const blocks=[{left:80,right:520,bottom:155}];
  const y=i=>vm.runInContext(`wfRouteReturn(${JSON.stringify(a)},${JSON.stringify(b)},${JSON.stringify(blocks)},${i}).a.returnY`,ctx);
  assert.ok(y(1)>y(0));
  assert.equal(y(1),y(1));
});
