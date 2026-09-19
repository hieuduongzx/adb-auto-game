const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const read = file => fs.readFileSync(path.join(__dirname, '../apps/web/wf/js', file), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
function load() {
  const ctx=vm.createContext({
    document:{documentElement:{},readyState:'loading',addEventListener(){}},
    window:{addEventListener(){}},getComputedStyle:()=>({getPropertyValue:()=>''}),
    localStorage:{getItem:()=>null},setTimeout,clearTimeout,$:()=>null,
  });
  const source=read('workflow.js');
  vm.runInContext(source.slice(0,source.indexOf('// edit = which graph')),ctx);
  vm.runInContext(`const WF={controller:'adb',edit:{kind:'activity',id:'a'},activities:[],functions:[],globals:[],sel:[]};`,ctx);
  for(const file of ['layout.js','io.js','edit.js','selection.js','history.js']) vm.runInContext(read(file),ctx);
  return ctx;
}

test('palette merges aliases but retains separate ADB and Win32 keys and image variants',()=>{
  const c=load();
  for(const type of ['back','home','win_escape','wait_random','swipe_dir'])
    assert.equal(vm.runInContext(`WF_NODES.${type}.hidden`,c),true,type);
  assert.equal(c.wfNodeCtrl('key'),'adb');assert.equal(c.wfNodeCtrl('win_key'),'win32');
  for(const t of ['tap_image','tap_image_any','wait_image','wait_image_any','if_image','if_image_any'])
    assert.ok(!vm.runInContext(`WF_NODES.${t}.hidden`,c));
});

test('legacy nodes migrate without losing ids, coordinates, key hold semantics or wires',()=>{
  const c=load();
  const old=[['back',{},'key','4'],['home',{},'key','3'],['win_escape',{},'win_key','27'],
    ['wait_random',{min:.2,max:3},'wait'],['swipe_dir',{direction:'right',distance:50},'swipe']];
  for(const [type,params,want,keycode] of old){
    const graph=c.wfHydrateGraph({nodes:[{id:'old',type,x:20,y:30,params}],edges:[{from:'old',fromPort:'out',to:'e'}]});
    const n=graph.nodes.find(n=>n.id==='old');assert.equal(n.type,want);assert.equal(n.x,20);
    if(keycode)assert.equal(n.params.keycode,keycode);
    if(type==='wait_random')assert.equal(n.params.mode,'random');
    if(type==='swipe_dir')assert.equal(n.params.mode,'direction');
    assert.equal(graph.edges[0].from,'old');
  }
});

test('old Key custom values and new Wait/Swipe mode defaults survive hydration',()=>{
  const c=load();
  const ns=c.wfHydrateGraph({nodes:[{id:'k',type:'key',params:{keycode:'222'}},
    {id:'w',type:'wait',params:{seconds:0}},{id:'s',type:'swipe',params:{x1:0,x2:100}}]}).nodes;
  assert.equal(ns.find(n=>n.id==='k').params.keycode,'222');
  assert.equal(ns.find(n=>n.id==='w').params.mode,'fixed');
  assert.equal(ns.find(n=>n.id==='w').params.seconds,0);
  assert.equal(ns.find(n=>n.id==='s').params.mode,'coordinates');
});

test('legacy workflow OCR choices migrate to PP-OCRv5 Mobile',()=>{
  const c=load();
  assert.deepEqual(plain(vm.runInContext('WF_OCR_MODELS',c)),[
    {id:'ppocr_v5_mobile',label:'PP-OCRv5 Mobile'},
  ]);
  c.$=()=>({value:''});
  vm.runInContext(`function wfSyncSpeedUI(){} function wfRenderAll(){} function wfClearSel(){WF.sel=[]}
    function wfNormWinMatchBy(v){return v||'title'} function wfNormWinInputMode(v){return v||'background'}`,c);
  for(const oldName of ['', 'tesseract', 'easyocr', 'paddleocr']){
    c.wfHydrate({name:'ocr migration',ocr:oldName,activities:[],functions:[],globals:[]});
    assert.equal(vm.runInContext('WF.ocrBackend',c),'ppocr_v5_mobile',oldName||'empty');
  }
});

test('legacy output log expands to independent branch logs and round-trips',()=>{
  const c=load();
  const n=c.wfHydrateGraph({nodes:[{id:'n',type:'if_image',params:{},log:'in',outputLog:'legacy'}]}).nodes.find(n=>n.id==='n');
  assert.deepEqual(plain(n.outputLogs),{true:'legacy',false:'legacy'});
  n.outputLogs.true='found';n.outputLogs.false='';
  const graph=c.wfHydrateGraph(JSON.parse(JSON.stringify(c.wfCleanGraph({nodes:[n],edges:[]}))));
  assert.deepEqual(plain(graph.nodes.find(n=>n.id==='n').outputLogs),{true:'found',false:''});
});

test('log fields use actual static/dynamic output ports and action errors',()=>{
  const c=load();
  const fields=(type,params={})=>Array.from(c.wfNodeLogFields({type,params}),f=>f.key);
  assert.deepEqual(fields('if_image'),['input','true','false']);
  assert.deepEqual(fields('loop'),['input','body','done']);
  assert.deepEqual(fields('switch',{cases:[{},{}]}),['input','c0','c1','default']);
  assert.deepEqual(fields('sequence',{count:2}),['input','1','2','end']);
  assert.deepEqual(fields('tap'),['input','out','$error']);
  assert.deepEqual(fields('end'),['input','$done']);
});

test('node normalization removes logs for exits the node does not have',()=>{
  const c=load();
  const nodes=c.wfHydrateGraph({nodes:[
    {id:'a',type:'tap',params:{},outputLogs:{out:'ok','$error':'failed',true:'wrong',false:'wrong'}},
    {id:'c',type:'if_image',params:{},outputLogs:{true:'yes',false:'no',out:'wrong','$error':'wrong'}},
  ]}).nodes;
  assert.deepEqual(plain(nodes.find(n=>n.id==='a').outputLogs),{out:'ok','$error':'failed'});
  assert.deepEqual(plain(nodes.find(n=>n.id==='c').outputLogs),{true:'yes',false:'no'});
});

test('graph serialization omits output logs until one is configured',()=>{
  const c=load();
  const graph=c.wfCleanGraph({nodes:[
    {id:'a',type:'tap',x:0,y:0,params:{},outputLogs:{}},
    {id:'b',type:'if_image',x:0,y:0,params:{},outputLogs:{true:'',false:''}},
    {id:'c',type:'if_image',x:0,y:0,params:{},outputLogs:{true:'yes',false:''}},
  ],edges:[]});
  assert.equal(Object.hasOwn(graph.nodes[0],'outputLogs'),false);
  assert.equal(Object.hasOwn(graph.nodes[1],'outputLogs'),false);
  assert.deepEqual(plain(graph.nodes[2].outputLogs),{true:'yes',false:''});
});

test('per-port logs survive clipboard, undo and single-node JSON import',()=>{
  const c=load();
  vm.runInContext(`WF.activities=[{id:'a',graph:{nodes:[{id:'n',type:'if_image',x:10,y:10,params:{},log:'enter',outputLogs:{true:'yes',false:'no'}}],edges:[]}}];
    WF.sel=['n']; WF.selectedNode='n';
    function setStatus(){} function wfRenderCanvas(){} function wfMarkSel(){} function wfRenderInspector(){} function wfPopNodes(){}
    wfCopy();wfPaste();`,c);
  const nodes=vm.runInContext('WF.activities[0].graph.nodes',c);
  assert.deepEqual(plain(nodes[1].outputLogs),{true:'yes',false:'no'});
  nodes[1].outputLogs.true='different';assert.equal(nodes[0].outputLogs.true,'yes');
  vm.runInContext('wfUndo()',c);
  assert.equal(vm.runInContext('WF.activities[0].graph.nodes.filter(n=>n.type!=="start").length',c),1);
  const n={id:'x',type:'tap',params:{}};
  c.wfApplyNodeJson(n,{type:'if_image',outputLogs:{true:'T',false:'F'}});
  assert.deepEqual(plain(n.outputLogs),{true:'T',false:'F'});
});

test('switch logs follow cases when reordered or removed',()=>{
  const c=load();vm.runInContext(read('render.js'),c);
  vm.runInContext(`WF.activities=[{id:'a',graph:{nodes:[],edges:[]}}]`,c);
  const n={id:'s',type:'switch',params:{cases:[{id:'a'},{id:'b'},{id:'c'}]},outputLogs:{c0:'A',c1:'B',c2:'C',default:'D'}};
  c.wfReorderSwitchCase(n,0,2);
  assert.deepEqual(plain(n.outputLogs),{c0:'B',c1:'C',c2:'A',default:'D'});
  c.wfRemoveSwitchCase(n,1);
  assert.deepEqual(plain(n.outputLogs),{c0:'B',c1:'A',default:'D'});
});
