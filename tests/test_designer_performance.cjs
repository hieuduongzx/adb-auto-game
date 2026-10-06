const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const read=file=>fs.readFileSync(path.join(__dirname,'../apps/web/wf/js',file),'utf8');

class Element {
  constructor(tag='g'){
    this.tag=tag; this.children=[]; this.parentNode=null;
    this.dataset={}; this.attributes={}; this.classes=new Set(); this.writes=0;
    this.classList={contains:c=>this.classes.has(c),
      toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c),
      add:(...cs)=>cs.forEach(c=>this.classes.add(c)),remove:(...cs)=>cs.forEach(c=>this.classes.delete(c))};
  }
  setAttribute(key,value){
    this.attributes[key]=String(value); this.writes++;
    if(key==='class') this.classes=new Set(value.split(' '));
  }
  getAttribute(key){return this.attributes[key];}
  get firstChild(){return this.children[0]||null;}
  get nextSibling(){const xs=this.parentNode?.children||[];return xs[xs.indexOf(this)+1]||null;}
  get innerHTML(){return '';}
  set innerHTML(_value){this.children.forEach(c=>c.parentNode=null);this.children=[];}
  remove(){if(this.parentNode){const xs=this.parentNode.children;xs.splice(xs.indexOf(this),1);this.parentNode=null;}}
  appendChild(child){child.remove();this.children.push(child);child.parentNode=this;return child;}
  insertBefore(child,before){if(child===before)return child;child.remove();const i=before?this.children.indexOf(before):-1;
    if(i<0)this.children.push(child);else this.children.splice(i,0,child);child.parentNode=this;return child;}
  querySelectorAll(selector){
    const [tag,cls]=selector.split('.');
    const matches=el=>(!tag||el.tag===tag)&&el.classes.has(cls);
    const all=[];for(const c of this.children){if(matches(c))all.push(c);all.push(...c.querySelectorAll(selector));}return all;
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}

function setup(){
  const svg=new Element('svg'),world={offsetParent:{}},elements=new Map();
  const graph={nodes:[],edges:[]};let current=graph,scans=0;
  const ctx=vm.createContext({
    WF:{sel:[]},WF_GEOMETRY:{width:144,height:64,terminal:48,port:8,gap:16,inset:4},
    WF_NODES:{tap:{kind:'action',cat:'basic',label:'Tap'},start:{kind:'start',label:'Start'}},WF_PORT_LBL:{},
    wfGesture:null,wfGraph:()=>current,wfNodeElById:id=>elements.get(id),
    wfRanPort:{},wfIsBranchPort:p=>p==='true'||p==='false',
    document:{createElementNS:(_ns,tag)=>new Element(tag),addEventListener(){},
      querySelectorAll:selector=>{assert.equal(selector,'#wf-world .wf-node');scans++;return [...elements.values()];}},
    window:{addEventListener(){}},localStorage:{getItem:()=>null},
    $:id=>id==='wf-wires'?svg:id==='wf-world'?world:null,
  });
  vm.runInContext(read('render.js'),ctx);
  vm.runInContext(read('wires.js'),ctx);
  function addNode(id,x,y,ports=['in','out']){
    const n={id,type:'tap',x,y,params:{}};graph.nodes.push(n);
    const el=new Element('div');el.dataset.node=id;el.offsetLeft=x;el.offsetTop=y;el.offsetWidth=144;el.offsetHeight=64;
    for(const port of ports){const p=new Element('span');p.classes.add('wf-port');p.classes.add(port==='in'||port==='loop'?'in':'out');
      p.dataset.port=port;p.offsetLeft=port==='in'||port==='loop'?0:136;p.offsetTop=28;p.offsetWidth=p.offsetHeight=8;el.appendChild(p);}
    elements.set(id,el);return el;
  }
  return {ctx,graph,svg,world,elements,addNode,setGraph:g=>current=g,scans:()=>scans};
}

test('graph rendering indexes each edge once and keeps fan-in lanes and warnings',()=>{
  const {ctx}=setup();const edges=Array.from({length:1000},(_,i)=>({from:'s'+i,fromPort:'out',to:'t',toPort:'in'}));
  const nodes=[{id:'t',type:'and',params:{count:1000}},...edges.map(e=>({id:e.from,type:'tap',params:{}}))];
  // Per-node and per-wire rendering must consume the index, never scan edges.
  edges.find=edges.filter=edges.some=()=>assert.fail('unexpected repeated edge scan');
  const g={nodes,edges};const index=ctx.wfBuildRenderIndex(g);
  assert.equal(index.incomingCount.get('t'),1000);
  assert.equal(index.incoming.get('t').get('in')[0],edges[0]);
  assert.equal(index.outgoing.get('s999').get('out'),edges[999]);
  assert.deepEqual(Array.from(ctx.wfNodeWarnings(nodes[0],{fields:[],kind:'action'},g,index)),[]);
  for(let i=0;i<edges.length;i++) assert.equal(ctx.wfWireTone('out','in',null,edges[i],index),'lane'+(i%6+1));
  assert.equal(ctx.wfWireTone('out','loop',null,edges[0],index),'loop');
});

test('wire redraws retain DOM identity, focus target and execution colours',()=>{
  const {ctx,graph,svg,addNode}=setup();addNode('a',0,0,['true','false']);addNode('b',200,0);addNode('c',200,160);
  graph.edges.push({from:'a',fromPort:'true',to:'b'},{from:'a',fromPort:'false',to:'c'});
  ctx.wfRanPort.a='true';ctx.wfDrawWires();
  const groups=svg.children.slice();const hit=groups[0].querySelector('.wire-hit');
  const writes=groups.map(gr=>gr.__parts.p.writes);
  ctx.wfDrawWires();assert.deepEqual(svg.children,groups);
  assert.equal(groups[0].querySelector('.wire-hit'),hit);
  assert.deepEqual(groups.map(gr=>gr.__parts.p.writes),writes,'unchanged paths do not write attributes');
  assert.ok(groups[0].__parts.p.classList.contains('took-wire'));
  assert.ok(groups[1].__parts.p.classList.contains('nottook-wire'));
  assert.equal(vm.runInContext('wfWireGroupsByFrom.get("a").length',ctx),2);
});

test('moving nodes updates only adjacent paths without rescanning DOM ports',()=>{
  const {ctx,graph,svg,addNode,scans}=setup();const a=addNode('a',0,0);addNode('b',200,0);addNode('c',400,0);addNode('d',600,0);
  graph.edges.push({from:'a',fromPort:'out',to:'b'},{from:'c',fromPort:'out',to:'d'});ctx.wfDrawWires();
  const moved=svg.children.find(gr=>gr.__edge.from==='a'),untouched=svg.children.find(gr=>gr.__edge.from==='c');
  const path=moved.__parts.p.getAttribute('d'),writes=untouched.__parts.p.writes;
  a.offsetLeft=80;a.offsetTop=40;ctx.wfDrawWires(['a']);
  assert.equal(scans(),1);assert.notEqual(moved.__parts.p.getAttribute('d'),path);
  assert.equal(untouched.__parts.p.writes,writes);
  assert.equal(ctx.wfPortPt('a','out').x,220,'fallback aliases are translated only once');
  assert.equal(ctx.wfPortPt('a','out').y,72);
  const fastPath=moved.__parts.p.getAttribute('d');ctx.wfDrawWires();assert.equal(moved.__parts.p.getAttribute('d'),fastPath);
});

test('wire reconciliation removes old edges, refreshes tones and replaces graphs',()=>{
  const {ctx,graph,svg,addNode,setGraph}=setup();addNode('a',0,0);addNode('b',200,0);
  const old={from:'a',fromPort:'out',to:'b'};graph.edges.push(old);ctx.wfDrawWires();const grp=svg.firstChild;
  old.toPort='loop';ctx.wfDrawWires();assert.equal(svg.firstChild,grp);assert.ok(grp.__parts.p.classList.contains('tone-loop'));
  graph.edges=[];ctx.wfDrawWires();assert.equal(svg.children.length,0);assert.equal(grp.parentNode,null);
  const next={nodes:graph.nodes,edges:[{from:'b',fromPort:'out',to:'a'}]};setGraph(next);ctx.wfDrawWires();
  assert.equal(svg.children.length,1);assert.equal(svg.firstChild.__edge,next.edges[0]);
  setGraph(null);ctx.wfDrawWires();assert.equal(svg.children.length,0);
  assert.equal(vm.runInContext('wfWireGroups.size+wfWireGroupsByFrom.size+wfWireRoutesByNode.size+wfWireIdx.ports.size',ctx),0);
});

test('hidden canvas redraw defers geometry reads and resumes from live sizes',()=>{
  const {ctx,graph,svg,world,addNode,scans}=setup();const a=addNode('a',0,0);addNode('b',200,0);
  graph.edges.push({from:'a',fromPort:'out',to:'b'});ctx.wfDrawWires();
  world.offsetParent=null;a.offsetLeft=96;ctx.wfDrawWires(['a']);assert.equal(scans(),1);
  assert.equal(vm.runInContext('wfWiresStale',ctx),true);
  world.offsetParent={};ctx.wfDrawWires(['a']);assert.equal(scans(),2);assert.equal(ctx.wfPortPt('a','out').x,236);
  assert.equal(svg.children.length,1);
});

test('a late thumbnail response cannot overwrite a newer path or a cleared image',async()=>{
  const source=read('base.js'),pending=[];
  const ctx=vm.createContext({api:()=>({image_thumbnail:()=>new Promise(resolve=>pending.push(resolve))})});
  vm.runInContext(source.slice(source.indexOf('async function wfLoadThumb'),source.indexOf('// ── Thumbnail hover zoom')),ctx);
  const img={dataset:{},style:{},removeAttribute(){delete this.src;}};
  const first=ctx.wfLoadThumb(img,'old.png'),second=ctx.wfLoadThumb(img,'new.png');
  pending[1]('new-data');await second;pending[0]('old-data');await first;assert.equal(img.src,'new-data');
  const third=ctx.wfLoadThumb(img,'pending.png');await ctx.wfLoadThumb(img,'');pending[2]('stale-data');await third;
  assert.equal(img.src,undefined);assert.equal(img.style.display,'none');
});
