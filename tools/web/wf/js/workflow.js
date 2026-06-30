// ── Workflow designer (node-graph) ───────────────────────────────────────────
// Icon set: a compact inline-SVG library (Lucide-style, 24×24, stroke 1.8) so the
// node palette reads as a consistent professional tool, not a mixed emoji grab-bag.
// Each entry is the inner markup of an SVG (paths/shapes) wrapped at render time.
// Use wfIco(name) to get a full <svg>; unknown names fall back to a dot.
const WF_ICONS = {
  // flow / structure
  play:       '<polygon points="6 3 20 12 6 21 6 3"/>',
  square:     '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  loop:       '<path d="M17 2l4 4-4 4"/><path d="M3 11v-2a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  parallel:   '<path d="M12 4v16"/><path d="M4 8h4"/><path d="M16 8h4"/><path d="M4 16h4"/><path d="M16 16h4"/>',
  octagon:    '<polygon points="8 3 16 3 21 8 21 16 16 21 8 21 3 16 3 8 8 3"/>',
  // basic actions
  pointer:    '<path d="M3 3l7 18 2.5-7.5L20 11 3 3z"/>',
  hand:       '<path d="M6 11V6a2 2 0 1 1 4 0v4"/><path d="M10 10V4a2 2 0 1 1 4 0v6"/><path d="M14 10V5a2 2 0 1 1 4 0v7"/><path d="M18 12V8a2 2 0 1 1 4 0v8a6 6 0 0 1-6 6h-3a6 6 0 0 1-5-2.6L4 16a2 2 0 0 1 3-2.6L8 15"/>',
  dice:       '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.2"/><circle cx="15.5" cy="15.5" r="1.2"/><circle cx="12" cy="12" r="1.2"/>',
  timer:      '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2"/><path d="M9 2h6"/>',
  hourglass:  '<path d="M6 3h12"/><path d="M6 21h12"/><path d="M6 3c0 5 6 6 6 9s-6 4-6 9"/><path d="M18 3c0 5-6 6-6 9s6 4 6 9"/>',
  arrow_down: '<line x1="12" y1="4" x2="12" y2="20"/><polyline points="7 15 12 20 17 15"/>',
  // input
  keyboard:   '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h0M10 10h0M14 10h0M18 10h0M7 14h10"/>',
  disc:       '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  back:       '<polyline points="15 18 9 12 15 6"/>',
  home:       '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
  // image
  target:     '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
  eye:        '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  help:       '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.9.4-1.5 1-1.5 2"/><circle cx="12" cy="17" r="0.6"/>',
  layers:     '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17l9 5 9-5"/>',
  // ocr / text
  type:       '<polyline points="4 7 4 5 20 5 20 7"/><line x1="9" y1="5" x2="9" y2="19"/><line x1="6" y1="19" x2="12" y2="19"/>',
  scan_text:  '<path d="M4 7V5a2 2 0 0 1 2-2h2"/><path d="M16 3h2a2 2 0 0 1 2 2v2"/><path d="M4 17v2a2 2 0 0 0 2 2h2"/><path d="M16 21h2a2 2 0 0 0 2-2v-2"/><line x1="4" y1="12" x2="20" y2="12"/>',
  search:     '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/>',
  scissors:   '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><line x1="8" y1="8" x2="20" y2="18"/><line x1="8" y1="16" x2="20" y2="6"/>',
  // logic
  pin:        '<path d="M12 17v5"/><path d="M7 3h10l-2 7h4l-7 7-7-7h4L7 3z"/>',
  calculator: '<rect x="4" y="3" width="16" height="18" rx="2"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="12" x2="8" y2="12"/><line x1="12" y1="12" x2="12" y2="12"/><line x1="16" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="12" y1="16" x2="12" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/>',
  hash:       '<line x1="9" y1="3" x2="7" y2="21"/><line x1="17" y1="3" x2="15" y2="21"/><line x1="4" y1="9" x2="20" y2="9"/><line x1="3" y1="15" x2="19" y2="15"/>',
  git_branch: '<line x1="6" y1="3" x2="6" y2="21"/><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M18 11.5a6 6 0 0 1-6 6"/>',
  git_merge:  '<circle cx="18" cy="18" r="2.5"/><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><line x1="6" y1="8.5" x2="6" y2="15.5"/><path d="M6 8.5a9 9 0 0 0 9 9"/>',
  bell:       '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  scroll:     '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M9 7h6M9 11h6M9 15h4"/><path d="M17 14l2.5 2.5L17 19"/>',
  // misc
  rocket:     '<path d="M5 13c-2 1-3 4-3 7 3 0 6-1 7-3"/><path d="M14 4c3 1 6 4 6 8-2 2-5 3-9 3l-4-4c0-4 1-7 3-9z"/><circle cx="15" cy="9" r="1.4"/>',
  camera:     '<path d="M4 7h3l2-2h6l2 2h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"/><circle cx="12" cy="13" r="3.5"/>',
  edit:       '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>',
  message:    '<path d="M21 11.5a8.5 8.5 0 0 1-12 7.7L3 21l1.8-6A8.5 8.5 0 1 1 21 11.5z"/>',
  function:   '<path d="M15 4h-1a3 3 0 0 0-3 3v10a3 3 0 0 1-3 3"/><line x1="8" y1="11.5" x2="16" y2="11.5"/>',
  // ui chrome
  x:          '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  chevron_up: '<polyline points="6 15 12 9 18 15"/>',
  chevron_dn: '<polyline points="6 9 12 15 18 9"/>',
  expand:     '<polyline points="8 3 4 3 4 8"/><polyline points="16 3 20 3 20 8"/><polyline points="8 21 4 21 4 16"/><polyline points="16 21 20 21 20 16"/>',
  settings:   '<circle cx="12" cy="12" r="3"/><path d="M19.4 13.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V20a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H4a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5V4a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1H20a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  copy:       '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  clipboard:  '<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/>',
  trash:      '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  link_off:   '<path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 0 1 4 7"/><path d="M8 12h8"/><line x1="3" y1="3" x2="21" y2="21"/>',
  box:        '<rect x="4" y="4" width="16" height="16" rx="2" stroke-dasharray="4 3"/>',
  log:        '<path d="M14 3v4h4"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/>',
};
  function wfIco(name){
    const inner = WF_ICONS[name];
    if(!inner) return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/></svg>';
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
  }
  // Some node icos need a filled look (stop/launch) — mark them inline.
  function wfIcoHtml(name){ return wfIco(name); }

// Node catalog: UI source of truth (icon, kind, output ports, param fields).
// Mirrors src/workflow/engine.py NODE_TYPES. kind: start|end|action|condition|loop.
const WF_NODES = {
  start:      {label:"Bắt đầu",   ico:"play", kind:"start", cat:null,    outs:["out"], fields:[]},
  end:        {label:"Kết thúc",  ico:"square", kind:"end",   cat:"flow",  outs:[],      fields:[]},
  tap:        {label:"Chạm",      ico:"pointer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Toạ độ"},{v:"found",t:"Ảnh vừa thấy"}],d:"pos"},{k:"x",t:"num"},{k:"y",t:"num"}], sum:p=>p.target==="found"?"↳ ảnh vừa thấy":`(${p.x}, ${p.y})`},
  double_tap: {label:"Chạm đúp",  ico:"hand",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Toạ độ"},{v:"found",t:"Ảnh vừa thấy"}],d:"pos"},{k:"x",t:"num"},{k:"y",t:"num"}], sum:p=>(p.target==="found"?"↳ ảnh vừa thấy":`(${p.x}, ${p.y})`)+" ×2"},
  tap_random: {label:"Chạm n.nhiên",ico:"dice",kind:"action",cat:"basic", outs:["out"], fields:[{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:100},{k:"h",t:"num",d:100}], sum:p=>`vùng (${p.x},${p.y}) ${p.w}×${p.h}`},
  long_press: {label:"Giữ",       ico:"timer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Toạ độ"},{v:"found",t:"Ảnh vừa thấy"}],d:"pos"},{k:"x",t:"num"},{k:"y",t:"num"},{k:"duration",t:"num",d:800}], sum:p=>(p.target==="found"?"↳ ảnh vừa thấy":`(${p.x},${p.y})`)+` ${p.duration}ms`},
  swipe:      {label:"Vuốt",      ico:"arrow_down",kind:"action",cat:"basic", outs:["out"], fields:[{k:"x1",t:"num"},{k:"y1",t:"num"},{k:"x2",t:"num"},{k:"y2",t:"num"},{k:"duration",t:"num",d:300}], sum:p=>`(${p.x1},${p.y1})→(${p.x2},${p.y2})`},
  swipe_dir:  {label:"Vuốt hướng",ico:"arrow_down",kind:"action",cat:"basic", outs:["out"], fields:[{k:"direction",t:"select",opts:["up","down","left","right"],d:"up"},{k:"distance",t:"num",d:400},{k:"duration",t:"num",d:300}], sum:p=>`${p.direction} ${p.distance}px`},
  wait:       {label:"Chờ",       ico:"timer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"seconds",t:"num",d:1,step:.5}], sum:p=>`${p.seconds}s`},
  wait_random:{label:"Chờ n.nhiên",ico:"hourglass",kind:"action",cat:"basic", outs:["out"], fields:[{k:"min",t:"num",d:.5,step:.5},{k:"max",t:"num",d:2,step:.5}], sum:p=>`${p.min}-${p.max}s`},
  send_text:  {label:"Nhập text", ico:"keyboard",kind:"action",cat:"input", outs:["out"], fields:[{k:"text",t:"text"}], sum:p=>`"${p.text||""}"`},
  key:        {label:"Phím",      ico:"disc",kind:"action",cat:"input", outs:["out"], fields:[{k:"keycode",t:"text",d:"BACK"}], sum:p=>`${p.keycode}`},
  back:       {label:"Back",      ico:"back",kind:"action",cat:"input", outs:["out"], fields:[], sum:()=>"phím back"},
  home:       {label:"Home",      ico:"home",kind:"action",cat:"input", outs:["out"], fields:[], sum:()=>"phím home"},
  tap_image:  {label:"Chạm ảnh",  ico:"target",kind:"condition",cat:"image", outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"taps",t:"select",opts:[{v:"1",t:"Chạm"},{v:"2",t:"Chạm đúp"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"offsetX",lbl:"Lệch X",t:"num",d:0},{k:"offsetY",lbl:"Lệch Y",t:"num",d:0},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>wfBase(p.template)+(p.taps=="2"?" ×2":"")+((p.offsetX||p.offsetY)?` +(${p.offsetX||0},${p.offsetY||0})`:"")},
  wait_image: {label:"Chờ ảnh",   ico:"timer",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>wfBase(p.template)},
  if_image:   {label:"Nếu ảnh",   ico:"help",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"negate",t:"bool",d:false},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>`${p.negate?"không ":""}thấy ${wfBase(p.template)}`},
  // "…_any" = OR over several images: true when ANY listed template matches.
  tap_image_any: {label:"Chạm 1 trong ảnh", ico:"target",kind:"condition",cat:"image", outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"taps",t:"select",opts:[{v:"1",t:"Chạm"},{v:"2",t:"Chạm đúp"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"mode",lbl:"Kiểu tìm",t:"select",opts:[{v:"sequential",t:"Tuần tự"},{v:"parallel",t:"Song song"}],d:"sequential"},{k:"offsetX",lbl:"Lệch X",t:"num",d:0},{k:"offsetY",lbl:"Lệch Y",t:"num",d:0},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>wfBaseAny(p.templates)+(p.taps=="2"?" ×2":"")+(p.mode==="parallel"?" //":"")},
  wait_image_any:{label:"Chờ 1 trong ảnh",  ico:"timer",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"mode",lbl:"Kiểu tìm",t:"select",opts:[{v:"sequential",t:"Tuần tự"},{v:"parallel",t:"Song song"}],d:"sequential"},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>wfBaseAny(p.templates)+(p.mode==="parallel"?" //":"")},
  if_image_any:  {label:"Nếu 1 trong ảnh",  ico:"layers",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"threshold",t:"num",d:.85,step:.05},{k:"negate",t:"bool",d:false},{k:"mode",lbl:"Kiểu tìm",t:"select",opts:[{v:"sequential",t:"Tuần tự"},{v:"parallel",t:"Song song"}],d:"sequential"},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>`${p.negate?"không ":""}thấy ${wfBaseAny(p.templates)}${p.mode==="parallel"?" //":""}`},
  wait_text:  {label:"Chờ chữ",   ico:"scan_text",kind:"condition",cat:"ocr",  outs:["true","false"], fields:[{k:"text",t:"text"},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"timeout",t:"num",d:10}], sum:p=>`"${p.text||""}"`},
  if_text:    {label:"Nếu chữ",   ico:"type",kind:"condition",cat:"ocr",outs:["true","false"], fields:[{k:"text",t:"text"},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"negate",t:"bool",d:false}], sum:p=>`${p.negate?"không ":""}có "${p.text||""}"`},
  read_var:   {label:"Đọc → biến",ico:"search",kind:"action",cat:"ocr",  outs:["out"], fields:[{k:"name",t:"text",d:"val",var:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80}], sum:p=>`→ ${p.name||"?"}`},
  parse_var:  {label:"Tách → biến",ico:"scissors",kind:"action",cat:"ocr",  outs:["out"], fields:[{k:"name",t:"text",d:"out",var:true},{k:"source",t:"select",opts:[{v:"region",t:"Vùng OCR"},{v:"var",t:"Từ biến"}],d:"region"},{k:"fromVar",lbl:"Biến nguồn",t:"text",d:"",var:true},{k:"pattern",t:"text",d:"(\\d+)/(\\d+)"},{k:"group",t:"num",d:1},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80}], sum:p=>`${p.name||"?"} = /${p.pattern||""}/g${p.group||1}`},
  loop:       {label:"Lặp lại",   ico:"loop",kind:"loop", cat:"flow",   ins:["in","loop"], outs:["body","done"], fields:[{k:"count",t:"num",d:3},{k:"infinite",t:"bool",d:true}], sum:p=>p.infinite?"∞ vô cực":`${p.count}×`},
  parallel:   {label:"Song song", ico:"parallel",kind:"parallel",cat:"flow", outs:[], fields:[{k:"count",lbl:"Số luồng",t:"num",d:3,refresh:true}], sum:p=>`${p.count||3} luồng song song`},
  try_chain:  {label:"Thử lần lượt",ico:"git_branch",kind:"try_chain",cat:"flow", outs:[], fields:[], sum:p=>`${p.count||3} nhánh · fail thì thử nhánh kế`},
  join:       {label:"Gộp",       ico:"git_merge",kind:"join",  cat:"flow", outs:["out"], fields:[], sum:()=>"chờ tất cả luồng → tiếp"},
  "break":    {label:"Thoát vòng",ico:"octagon",kind:"action",cat:"flow",  outs:["out"], fields:[], sum:()=>"break"},
  stop:       {label:"Dừng tất cả",ico:"octagon",kind:"stop", cat:"flow",  outs:[],      fields:[], sum:()=>"dừng phiên"},
  set_var:    {label:"Đặt biến",  ico:"pin",kind:"action",cat:"logic", outs:["out"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"value",t:"text",d:"0"}], sum:p=>`${p.name||"?"} = ${p.value}`},
  calc_var:   {label:"Tính biến", ico:"calculator",kind:"action",cat:"logic", outs:["out"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"op",t:"select",opts:["+","-","*","/","="],d:"+"},{k:"value",t:"text",d:"1"}], sum:p=>`${p.name} ${p.op}= ${p.value}`},
  if_var:     {label:"Nếu biến",  ico:"hash",kind:"condition",cat:"logic",outs:["true","false"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"op",t:"select",opts:["==","!=",">","<",">=","<="],d:"=="},{k:"value",t:"text",d:"0"}], sum:p=>`${p.name} ${p.op} ${p.value}`},
  // Multi-way branch: each case is its own condition; first true case wins its
  // own output port "c{i}", else the "default" port. Ports are dynamic (one per
  // case + default) — see wfNodeEl. Cases edited by wfSwitchCasesEditor.
  "switch":   {label:"Rẽ nhánh",  ico:"git_branch",kind:"switch",cat:"logic",outs:["default"], fields:[], sum:p=>`${(p.cases||[]).length} nhánh`},
  launch_app: {label:"Mở app",    ico:"rocket",kind:"action",cat:"misc",  outs:["out"], fields:[{k:"package",t:"text"},{k:"wait",lbl:"Chờ mở (s)",t:"num",d:0}], sum:p=>(p.package||"(package)")+(p.wait?` ·chờ ${p.wait}s`:"")},
  screenshot: {label:"Chụp",      ico:"camera",kind:"action",cat:"misc",  outs:["out"], fields:[], sum:()=>"chụp màn hình"},
  log:        {label:"Ghi log",   ico:"log",kind:"action",cat:"misc",  outs:["out"], fields:[{k:"message",t:"text"}], sum:p=>`"${p.message||""}"`},
  note:          {label:"Ghi chú",        ico:"message",  kind:"note",      cat:"misc",   outs:[],             fields:[{k:"text",t:"text",d:"ghi chú"}], sum:p=>p.text||""},
  call:          {label:"Function",       ico:"function", kind:"call",      cat:null,     outs:["out"],        fields:[]},
  scroll_find:   {label:"Kéo đến ảnh",   ico:"scroll",   kind:"condition", cat:"image",  outs:["true","false"],fields:[{k:"template",t:"tpl"},{k:"direction",lbl:"Hướng vuốt",t:"select",opts:[{v:"up",t:"↑ Lên"},{v:"down",t:"↓ Xuống"},{v:"left",t:"← Trái"},{v:"right",t:"→ Phải"}],d:"up"},{k:"max_swipes",lbl:"Tối đa vuốt",t:"num",d:10},{k:"swipe_distance",lbl:"Khoảng cách (px)",t:"num",d:400},{k:"threshold",t:"num",d:.85,step:.05},{k:"swipe_duration",lbl:"Thời gian vuốt (ms)",t:"num",d:300},{k:"_region",lbl:"Vùng tìm",t:"region"}], sum:p=>`${({"up":"↑","down":"↓","left":"←","right":"→"})[p.direction]||"↑"} ≤${p.max_swipes||10}× → ${wfBase(p.template)}`},
  random_branch: {label:"Chọn ngẫu nhiên",ico:"dice",   kind:"random",    cat:"flow",   outs:[],              fields:[{k:"count",lbl:"Số nhánh",t:"num",d:2,refresh:true}], sum:p=>`🎲 ${p.count||2} nhánh đều nhau`},
  format_var:    {label:"Định dạng chuỗi",ico:"type",   kind:"action",    cat:"logic",  outs:["out"],         fields:[{k:"name",lbl:"Biến đích",t:"text",d:"text",var:true},{k:"template",lbl:"Chuỗi mẫu",t:"text",d:"Vòng {round}/{total}"}], sum:p=>`${p.name||"?"} = "${p.template||""}"`},
  notify:        {label:"Thông báo",      ico:"bell",   kind:"action",    cat:"misc",   outs:["out"],         fields:[{k:"title",lbl:"Tiêu đề",t:"text",d:"Workflow"},{k:"message",lbl:"Nội dung",t:"text",d:"Đã hoàn thành!"},{k:"sound",lbl:"Phát âm thanh",t:"bool",d:true}], sum:p=>`🔔 [${p.title||"Workflow"}] ${p.message||""}`},
};
const WF_CATS = [ {key:"basic",label:"Cơ bản"}, {key:"input",label:"Phím & Nhập liệu"}, {key:"image",label:"Hình ảnh"}, {key:"ocr",label:"Văn bản (OCR)"}, {key:"flow",label:"Luồng"}, {key:"logic",label:"Biến / Điều kiện"}, {key:"misc",label:"Khác"} ];
const WF_PORT_LBL = { out:"", "true":"T", "false":"F", body:"lặp", done:"xong", fail:"fail", "1":"1", "2":"2", "3":"3" };
// Input-side port labels (only shown for nodes with >1 input, e.g. the loop).
const WF_IN_LBL = { in:"vào", loop:"lặp" };

// Parse a filename like ``btn_ok_120_340_80_40.png`` into {x,y,w,h}.
// Works on the basename (with or without extension). Returns null if no
// _<int>_<int>_<int>_<int> suffix is found.
function wfParseRegionFromName(path){
  if(!path) return null;
  const base = path.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
  const m = base.match(/_(\d+)_(\d+)_(\d+)_(\d+)$/);
  if(!m) return null;
  return { x:parseInt(m[1],10), y:parseInt(m[2],10), w:parseInt(m[3],10), h:parseInt(m[4],10) };
}

function wfTemplatePathForRegion(node){
  const p = node && node.params || {};
  return p.template || (Array.isArray(p.templates) ? (p.templates.find(Boolean)||"") : "") || "";
}

function wfApplyRegionFromTplName(node, tplPath){
  // Fill region from the filename when the user explicitly enables "Vùng tìm".
  const def = WF_NODES[node.type];
  const hasRegion = def && (def.fields||[]).some(f => f.t === "region");
  if(!hasRegion) return false;
  const r = wfParseRegionFromName(tplPath);
  if(!r) return false;
  node.params.regionX = r.x; node.params.regionY = r.y;
  node.params.regionW = r.w; node.params.regionH = r.h;
  return true;
}

function wfIns(type){ const def=WF_NODES[type]; return (def&&def.ins)||["in"]; }

// edit = which graph the canvas is showing: an activity or a function.
// sel = ids of all selected nodes (multi-select); selectedNode = primary (inspector).
const WF = { name:"My Workflow", version:2, templatesDir:"templates", activities:[], functions:[],
  globals:[],
  speedhack:{enabled:false, speed:2.0, package:""},
  edit:{kind:"activity", id:null}, sel:[], selectedNode:null };
let wfSpace=false;  // space held → pan instead of box-select
const WF_GRID=20;   // grid step; snapping is opt-in (default off)
let wfSnapOn=false;
let wfPreviewAll=false;   // global: show image thumbnail on every image block
// Live runtime variable values pushed from the engine during a test run.
// Keyed by var name -> current value (stringified for display).
let wfLiveVars={};
let wfFreshVar=null;       // name of the most-recently-changed var (brief highlight)
let wfVarsCollapsed=false;
let wfActCollapsed=false;
const wfSnap=v=> wfSnapOn ? Math.round(v/WF_GRID)*WF_GRID : Math.round(v);
function wfSaveSettings(){ try{ const lc=$("log-card"), sd=$("wf-side"), insp=$("wf-inspector"); api().save_settings({snap:wfSnapOn, previewAll:wfPreviewAll, logOpen: !(lc&&lc.classList.contains("collapsed")), sideW: sd?sd.offsetWidth:undefined, inspW: insp?insp.offsetWidth:undefined}); }catch{} }
function wfSyncToggleBtns(){
  // Icon buttons: state shows as colour (.on) + tooltip, never overwrite the SVG.
  const s=$("wf-snap-btn"); if(s){ s.title="Bám lưới: "+(wfSnapOn?"Bật":"Tắt"); s.classList.toggle("on",wfSnapOn); }
  const p=$("wf-preview-btn"); if(p){ p.title="Preview ảnh: "+(wfPreviewAll?"Bật":"Tắt"); p.classList.toggle("on",wfPreviewAll); }
  wfSyncSpeedUI();
}
// ── Speed hack — a standalone manual tool, decoupled from "Chạy thử" ──────────
// The ⚡ toggle enables the feature (still saved into the flow for the Runner GUI)
// and reveals a separate ▶ button; pressing ▶ is what actually injects Frida here.
let wfSpeedRunning=false;   // is the standalone injection currently on?
function wfSyncSpeedUI(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,package:""});
  const b=$("wf-speed-btn"); if(b){ b.title="Speed hack: "+(sh.enabled?"Bật":"Tắt")+" (tăng tốc game bằng Frida — cần root)"; b.classList.toggle("on",sh.enabled); }
  const v=$("wf-speed-val"); if(v && document.activeElement!==v) v.value=sh.speed;
  const pk=$("wf-speed-pkg"); if(pk && document.activeElement!==pk) pk.value=sh.package||"";
  const grp=$("wf-speed-group"); if(grp) grp.classList.toggle("on", sh.enabled);
  const rb=$("wf-speed-run-btn");
  if(rb){
    rb.style.display = sh.enabled ? "inline-flex" : "none";
    rb.innerHTML = wfSpeedRunning ? WF_ICO_STOP : WF_ICO_PLAY;
    rb.title = wfSpeedRunning ? "Tắt speed hack" : "Bật speed hack ngay (độc lập với Chạy thử)";
    rb.classList.toggle("ok", !wfSpeedRunning); rb.classList.toggle("err", wfSpeedRunning);
  }
}
function wfSpeedFromUI(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,package:""});
  const v=parseFloat($("wf-speed-val").value); sh.speed=(isNaN(v)||v<=0)?1:v;
  sh.package=($("wf-speed-pkg").value||"").trim();
}
// Speed value edited: persist, and if the hack is live, push the new scale.
function wfSpeedChanged(){ wfSpeedFromUI(); if(wfSpeedRunning){ const sh=WF.speedhack; api().speedhack_start(sh.speed, sh.package); } }
function wfToggleSpeed(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,package:""});
  wfSpeedFromUI(); sh.enabled=!sh.enabled;
  if(!sh.enabled && wfSpeedRunning){ api().speedhack_stop(); wfSpeedRunning=false; }  // disabling stops it
  wfSyncSpeedUI();
}
// Best-effort package: the field, else the first "Mở app" node's package.
function wfAutoPackage(){
  const graphs=[...WF.activities.map(a=>a.graph), ...WF.functions.map(f=>f.graph)];
  for(const g of graphs){ for(const n of (g&&g.nodes||[])){
    if(n.type==="launch_app"){ const p=((n.params||{}).package||"").trim(); if(p) return p; } } }
  return "";
}
// The ▶/⏹ button: actually inject (or stop) the speed hack, on its own.
async function wfSpeedRun(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,package:""});
  wfSpeedFromUI();
  if(wfSpeedRunning){ await api().speedhack_stop(); return; }
  const pkg=sh.package||wfAutoPackage();
  if(!pkg){ alert("Nhập package game (hoặc thêm node Mở app) để bật speed hack."); return; }
  const ok=await api().speedhack_start(sh.speed, pkg);
  if(!ok){ wfSpeedRunning=false; wfSyncSpeedUI(); }
}
function wfToggleSnap(){ wfSnapOn=!wfSnapOn; wfSyncToggleBtns(); wfSaveSettings(); }
function wfTogglePreview(){ wfPreviewAll=!wfPreviewAll; wfSyncToggleBtns(); wfRenderCanvas(); wfSaveSettings(); }
let wfRunning=false;
let wfPan={x:0,y:0};
let wfZoom=1;           // canvas zoom factor
function wfApplyTransform(){ const w=$("wf-world"); if(w) w.style.transform=`translate(${wfPan.x}px,${wfPan.y}px) scale(${wfZoom})`;
  const lbl=$("wf-zoom-lbl"); if(lbl) lbl.textContent=Math.round(wfZoom*100)+"%"; }
function wfSetZoom(z, cx, cy){
  z=Math.max(0.3, Math.min(2.5, z));
  const canvas=$("wf-canvas"); if(!canvas) { wfZoom=z; wfApplyTransform(); return; }
  // Keep the point (cx,cy) — relative to the canvas — fixed while zooming.
  if(cx===undefined){ const r=canvas.getBoundingClientRect(); cx=r.width/2; cy=r.height/2; }
  const wx=(cx-wfPan.x)/wfZoom, wy=(cy-wfPan.y)/wfZoom;
  wfZoom=z;
  wfPan.x=cx-wx*wfZoom; wfPan.y=cy-wy*wfZoom;
  wfApplyTransform();
  const lbl=$("wf-zoom-lbl"); if(lbl) lbl.textContent=Math.round(wfZoom*100)+"%";
}
function wfZoomBy(f){ wfSetZoom(wfZoom*f); }
function wfZoomReset(){ wfSetZoom(1); }
// Drag-to-resize the left sidebar; width persists in settings.
function wfInitSideResizer(){
  const side=$("wf-side"), rez=$("wf-side-resizer"); if(!side||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  rez.addEventListener("mousedown",e=>{ e.preventDefault(); drag={x:e.clientX, w:side.offsetWidth}; rez.classList.add("drag"); document.body.style.cursor="col-resize"; });
  window.addEventListener("mousemove",e=>{ if(!drag) return; side.style.width=Math.max(150, Math.min(480, drag.w+(e.clientX-drag.x)))+"px"; });
  window.addEventListener("mouseup",()=>{ if(!drag) return; drag=null; rez.classList.remove("drag"); document.body.style.cursor=""; wfSaveSettings(); });
}
// Drag-to-resize the right inspector; width persists in settings.
function wfInitInspResizer(){
  const insp=$("wf-inspector"), rez=$("wf-insp-resizer"); if(!insp||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  rez.addEventListener("mousedown",e=>{ e.preventDefault(); drag={x:e.clientX, w:insp.offsetWidth}; rez.classList.add("drag"); document.body.style.cursor="col-resize"; });
  window.addEventListener("mousemove",e=>{ if(!drag) return; insp.style.width=Math.max(180, Math.min(520, drag.w-(e.clientX-drag.x)))+"px"; });
  window.addEventListener("mouseup",()=>{ if(!drag) return; drag=null; rez.classList.remove("drag"); document.body.style.cursor=""; wfSaveSettings(); });
}
// Fit & center all blocks of the current graph into the canvas. Uses the live DOM
// node bounds (world coords), so it's exact regardless of node heights.
function wfFit(){
  const canvas=$("wf-canvas"); if(!canvas) return;
  const els=[...document.querySelectorAll("#wf-world .wf-node")];
  if(!els.length){ wfPan={x:0,y:0}; wfSetZoom(1); return; }
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  els.forEach(el=>{ const x=el.offsetLeft,y=el.offsetTop,w=el.offsetWidth,h=el.offsetHeight;
    if(x<minX)minX=x; if(y<minY)minY=y; if(x+w>maxX)maxX=x+w; if(y+h>maxY)maxY=y+h; });
  const pad=70, cw=canvas.clientWidth, ch=canvas.clientHeight;
  const z=Math.max(0.2, Math.min(cw/((maxX-minX)+pad*2), ch/((maxY-minY)+pad*2), 1.5));
  wfZoom=z;
  wfPan.x=(cw-(minX+maxX)*z)/2;
  wfPan.y=(ch-(minY+maxY)*z)/2;
  wfApplyTransform();
}
