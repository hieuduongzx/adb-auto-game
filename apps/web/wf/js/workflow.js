// ── Workflow designer (node-graph) ───────────────────────────────────────────
// Read the shared canvas geometry once so render, auto-layout and CSS agree.
const WF_GEOMETRY=(()=>{
  const css=getComputedStyle(document.documentElement);
  const px=(name,fallback)=>parseFloat(css.getPropertyValue(name))||fallback;
  return Object.freeze({width:px('--node-w',184),height:px('--node-h',78),
    terminal:px('--term-size',42),port:px('--port-sz',10),
    inset:px('--port-inset',-5),gap:px('--port-gap',20)});
})();
// Icon set: a compact inline-SVG library (Lucide-style, 24×24, stroke 1.8) so the
// node palette reads as a consistent professional tool, not a mixed emoji grab-bag.
// Each entry is the inner markup of an SVG (paths/shapes) wrapped at render time.
// Use wfIco(name) to get a full <svg>; unknown names fall back to a dot.
// Node / palette icon names -> the shared Lucide set (see shared/icons.js).
// The geometry used to live here as hand-drawn paths whose header claimed
// "stroke 1.8" while wfIco() rendered them at 2. One set, one weight, one file.
const WF_ICONS = {
  play: "play",
  square: "square",
  loop: "repeat",
  parallel: "split",
  sequence: "list-tree",
  octagon: "octagon",
  pointer: "mouse-pointer-2",
  touches: "pointer",
  hand: "hand",
  dice: "dice-5",
  timer: "timer",
  clock: "clock",
  hourglass: "hourglass",
  alarm: "alarm-clock",
  calendar: "calendar",
  smartphone: "smartphone",
  monitor: "monitor",
  power: "power",
  battery: "battery",
  arrow_down: "arrow-down",
  keyboard: "keyboard",
  disc: "disc",
  back: "chevron-left",
  home: "house",
  target: "target",
  eye: "eye",
  help: "circle-question-mark",
  layers: "layers",
  type: "type",
  scan_text: "scan-text",
  search: "search",
  scissors: "scissors",
  droplet: "droplet",
  pipette: "pipette",
  pin: "pin",
  calculator: "calculator",
  hash: "hash",
  git_branch: "git-branch",
  git_merge: "git-merge",
  skip: "skip-forward",
  bell: "bell",
  scroll: "scroll-text",
  rocket: "rocket",
  camera: "camera",
  edit: "pencil",
  message: "message-circle",
  function: "square-function",
  maximize: "maximize",
  minimize: "minimize",
  move: "move",
  x: "x",
  plus: "plus",
  check: "check",
  chevron_up: "chevron-up",
  chevron_dn: "chevron-down",
  chevron_right: "chevron-right",
  expand: "maximize",
  settings: "settings",
  copy: "copy",
  clipboard: "clipboard",
  trash: "trash-2",
  link_off: "link-2-off",
  box: "square-dashed",
  log: "file-text",
  folder: "folder",
  crash: "triangle-alert",
};
  function wfIco(name){
    // Unknown names fall back to a neutral dot rather than a broken glyph.
    // "disc" is the shared set's dot — "circle-dot" was never in it, so every
    // unmapped name used to render as nothing at all.
    return uiIco(WF_ICONS[name] || "disc");
  }

// Display label for package-bearing nodes (Launch / Stop / Uninstall / If app).
// pkgSrc "project" → workflow package from Project settings; else custom text.
function wfPkgLabel(p){
  const src=String((p&&p.pkgSrc)||"").trim().toLowerCase();
  // Legacy nodes (no pkgSrc): show custom package if set, else project package.
  if(!src || src==="project"){
    const proj=(typeof WF!=="undefined" && WF.package)?String(WF.package).trim():"";
    if(proj) return proj;
    // Old file with only a free-text package and no pkgSrc — still show it.
    if(!src){ const c=String((p&&p.package)||"").trim(); if(c) return c; }
    return "⚙ project package";
  }
  return String((p&&p.package)||"").trim() || "(package)";
}
// Same idea for If app running, which is controller-neutral: in a Win32 project
// there is no package — "project" means the Project-settings target window, and
// a custom value is matched against that window's title.
function wfAppTargetLabel(p){
  if((typeof WF==="undefined") || WF.controller!=="win32") return wfPkgLabel(p);
  const src=String((p&&p.pkgSrc)||"").trim().toLowerCase();
  if(src==="custom") return String((p&&p.package)||"").trim() || "(title)";
  const win=(WF.win32&&String(WF.win32.window||"").trim())||"";
  return win || "🪟 project window";
}

// Display label for Launch program: pathSrc "project" → the Project-settings
// game path; "custom" → the node's own path. Legacy nodes (no pathSrc) use their
// own path when set, else the project one — same rule as the engine.
function wfLaunchPathLabel(p){
  const src=String((p&&p.pathSrc)||"").trim().toLowerCase();
  const own=String((p&&p.path)||"").trim();
  const base=s=>s.split(/[\\/]/).pop();
  if(src==="custom" || (!src && own)) return own ? base(own) : "(program)";
  const proj=(typeof WF!=="undefined" && WF.win32)?String(WF.win32.path||"").trim():"";
  return proj ? base(proj) : "⚙ project game path";
}

// States shared by If window … / Wait for window …. "size" compares the CLIENT
// area (what captures and templates use) with W×H, give or take `tolerance` px.
const WF_WIN_STATES = [
  {v:"exists",t:"Exists (still running)"},{v:"foreground",t:"Is the active window"},
  {v:"minimized",t:"Is minimized"},{v:"size",t:"Has client size W×H"},
];
const WF_WIN_SIZE_FIELDS = [
  {k:"width",lbl:"Client width",t:"num",d:1280,showWhen:{state:"size"}},
  {k:"height",lbl:"Client height",t:"num",d:720,showWhen:{state:"size"}},
  {k:"tolerance",lbl:"Tolerance (px)",t:"num",d:0,showWhen:{state:"size"}},
];
function wfWinStateLabel(p){
  if((p&&p.state)!=="size") return (p&&p.state)||"exists";
  const tol=Number(p.tolerance)||0;
  return `${p.width??1280}×${p.height??720}${tol?`±${tol}`:""}`;
}

// Named Windows virtual keys for the Win32 keyboard node. Values remain VK
// numbers in JSON/runtime, but users choose readable key names instead of
// memorising codes.
const WF_WIN_KEYS = [
  {v:"13",t:"Enter"},{v:"27",t:"Escape"},{v:"32",t:"Space"},{v:"9",t:"Tab"},{v:"8",t:"Backspace"},
  {v:"37",t:"← Left"},{v:"38",t:"↑ Up"},{v:"39",t:"→ Right"},{v:"40",t:"↓ Down"},
  {v:"46",t:"Delete"},{v:"45",t:"Insert"},{v:"36",t:"Home"},{v:"35",t:"End"},{v:"33",t:"Page Up"},{v:"34",t:"Page Down"},
  {v:"16",t:"Shift"},{v:"17",t:"Ctrl"},{v:"18",t:"Alt"},
  ...Array.from({length:12},(_,i)=>({v:String(112+i),t:"F"+(i+1)})),
  ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map(ch=>({v:String(ch.charCodeAt(0)),t:ch})),
  ..."0123456789".split("").map(ch=>({v:String(ch.charCodeAt(0)),t:ch})),
];
function wfWinKeyLabel(value){
  const hit=WF_WIN_KEYS.find(k=>String(k.v)===String(value));
  return hit?hit.t:("VK "+value);
}

// Android keycodes are a separate namespace from Windows virtual keys.
const WF_ADB_KEYS = [
  {v:"4",t:"Back",name:"BACK"},{v:"3",t:"Home",name:"HOME"},
  {v:"187",t:"Recent apps",name:"APP_SWITCH"},{v:"82",t:"Menu",name:"MENU"},
  {v:"66",t:"Enter",name:"ENTER"},{v:"67",t:"Backspace",name:"DEL"},
  {v:"61",t:"Tab",name:"TAB"},{v:"62",t:"Space",name:"SPACE"},
  {v:"19",t:"Up",name:"DPAD_UP"},{v:"20",t:"Down",name:"DPAD_DOWN"},
  {v:"21",t:"Left",name:"DPAD_LEFT"},{v:"22",t:"Right",name:"DPAD_RIGHT"},
  {v:"23",t:"D-pad center",name:"DPAD_CENTER"},
  {v:"24",t:"Volume up",name:"VOLUME_UP"},{v:"25",t:"Volume down",name:"VOLUME_DOWN"},
  {v:"164",t:"Mute",name:"VOLUME_MUTE"},{v:"26",t:"Power",name:"POWER"},
  {v:"85",t:"Play / Pause",name:"MEDIA_PLAY_PAUSE"},{v:"84",t:"Search",name:"SEARCH"},
];
function wfAdbKeyValue(value){
  const raw=String(value??"4").trim();
  const hit=WF_ADB_KEYS.find(k=>k.v===raw||k.name===raw.toUpperCase().replace(/^KEYCODE_/,""));
  return hit?hit.v:raw;
}
function wfAdbKeyLabel(value){
  const code=wfAdbKeyValue(value), hit=WF_ADB_KEYS.find(k=>k.v===code);
  return hit?hit.t:("Key "+code);
}

// Comparison operators shared by If variable / Loop until variable / switch
// cases. The string-shaped ones (contains / starts / ends / regex) matter most
// for OCR results, which rarely equal a literal exactly.
const WF_CMP_OPS = [
  {v:"==",t:"= equals"},{v:"!=",t:"≠ not equal"},
  {v:">",t:"> greater"},{v:"<",t:"< less"},
  {v:">=",t:"≥ at least"},{v:"<=",t:"≤ at most"},
  {v:"contains",t:"⊃ contains"},{v:"!contains",t:"⊅ does not contain"},
  {v:"starts",t:"^ starts with"},{v:"ends",t:"$ ends with"},
  {v:"regex",t:".* matches regex"},
  {v:"is_integer",t:"is integer"},{v:"is_not_integer",t:"is not integer"},
  {v:"is_number",t:"is number"},{v:"is_not_number",t:"is not number"},
  {v:"is_text",t:"is text"},{v:"is_not_text",t:"is not text"},
  {v:"is_empty",t:"is empty"},{v:"is_not_empty",t:"is not empty"},
];

// The emulator nodes' target picker. "Selected device" resolves against the
// toolbar's device select (the serial is handed to the engine), "Last used"
// against the instance the last Launch emulator saved. Families are listed for
// when neither applies — an emulator this app never launched and that isn't in
// the device list yet. One array so the five nodes can't drift apart.
const WF_EMU_TARGET_OPTS = [
  {v:"selected", t:"Selected device (toolbar)"},
  {v:"last",     t:"Last used (saved)"},
  {v:"ldplayer", t:"LDPlayer"},
  {v:"mumu",     t:"MuMu"},
  {v:"nox",      t:"Nox"},
  {v:"memu",     t:"MEmu"},
  {v:"bluestacks", t:"BlueStacks"},
];
// Same picker, MuMu only — Emulator resolution drives the console's settings
// keys, which no other family exposes.
const WF_EMU_TARGET_OPTS_MUMU = [
  {v:"selected", t:"Selected device (toolbar)"},
  {v:"last",     t:"Last used (saved)"},
  {v:"mumu",     t:"MuMu"},
];
// What the emulator nodes print on the canvas for the chosen target. The
// selected serial is read live so the node says which device it means, not just
// "selected" — the ambiguity that made this option necessary in the first place.
function wfEmuTargetLabel(p){
  p=p||{};
  const k=String(p.emulator||"last").toLowerCase();
  if(k==="selected"){
    const s=(typeof S!=="undefined"&&S.connectedSerial)||"";
    return s?("selected ("+s+")"):"selected device";
  }
  if(k==="last"||!k) return "last used";
  const i=parseInt(p.index)||0;
  return k+(i?(" #"+i):"");
}

// Node catalog: UI source of truth (icon, kind, output ports, param fields).
// Mirrors src/workflow/engine.py NODE_TYPES. kind: start|end|action|condition|loop.
const WF_NODES = {
  start:      {label:"Start",   ico:"play", kind:"start", cat:null,    outs:["out"], fields:[]},
  end:        {label:"End",  ico:"square", kind:"end",   cat:"flow",  outs:[],      fields:[]},
  tap:        {label:"Tap",      ico:"pointer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},{k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"}], sum:p=>(p.target==="found"?"↳ last found image":`(${p.x}, ${p.y})`)+(p.taps=="2"?" ×2":"")},
  multi_tap:  {label:"Multi-point tap",ico:"touches",kind:"action",cat:"basic",outs:["out"],fields:[{k:"points",lbl:"Touch points",t:"points",d:[{x:0,y:0},{x:100,y:100}]},{k:"duration",lbl:"Hold duration (ms)",t:"num",d:80}],sum:p=>{const a=Array.isArray(p.points)?p.points:[];return `${a.length} points · together · ${Math.max(20,Number(p.duration)||80)}ms`; }},
  sequence_tap: {label:"Sequence tap",ico:"list_numbered",kind:"action",cat:"basic",outs:["out"],fields:[{k:"sequenceId",lbl:"Sequence ID",t:"text",d:"main"},{k:"points",lbl:"Tap sequence",t:"sequence_points",d:[{x:0,y:0,delay:0.1},{x:100,y:100,delay:0.1}]}],sum:p=>{const a=Array.isArray(p.points)?p.points:[];return `${a.length} taps · ${p.sequenceId||"main"}`; }},
  sequence_tap_image: {label:"Sequence tap image",ico:"target",kind:"action",cat:"image",outs:["out"],fields:[{k:"sequenceId",lbl:"Sequence ID",t:"text",d:"main"},{k:"images",lbl:"Image sequence",t:"sequence_images",d:[{template:"",threshold:.85,timeout:10,offsetX:0,offsetY:0,delay:.1}]}],sum:p=>{const a=Array.isArray(p.images)?p.images:[];return `${a.length} images · ${p.sequenceId||"main"}`; }},
  stop_sequence: {label:"Stop sequence",ico:"octagon",kind:"action",cat:"flow",outs:["out"],fields:[{k:"sequenceId",lbl:"Sequence ID",t:"text",d:"main"}],sum:p=>`stop ${p.sequenceId||"main"}`},
  // Hidden from the palette — superseded by tap(taps=2); old files still open/run fine.
  double_tap: {label:"Double tap",  ico:"hand",kind:"action",cat:"basic", hidden:true, outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},{k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}}], sum:p=>(p.target==="found"?"↳ last found image":`(${p.x}, ${p.y})`)+" ×2"},
  tap_random: {label:"Random tap",ico:"dice",kind:"action",cat:"basic", outs:["out"], fields:[
    {k:"x1",lbl:"From X",t:"num",d:0},{k:"y1",lbl:"From Y",t:"num",d:0},
    {k:"x2",lbl:"To X",t:"num",d:100},{k:"y2",lbl:"To Y",t:"num",d:100}
  ], sum:p=>`X ${Math.min(Number(p.x1)||0,Number(p.x2)||0)}–${Math.max(Number(p.x1)||0,Number(p.x2)||0)} · Y ${Math.min(Number(p.y1)||0,Number(p.y2)||0)}–${Math.max(Number(p.y1)||0,Number(p.y2)||0)}`},
  long_press: {label:"Long press",       ico:"timer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},{k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}},{k:"duration",lbl:"Duration (ms)",t:"num",d:800}], sum:p=>(p.target==="found"?"↳ last found image":`(${p.x},${p.y})`)+` ${p.duration}ms`},
  swipe: {label:"Swipe",search:"direction coordinates",ico:"arrow_down",kind:"action",cat:"basic",outs:["out"], fields:[
    {k:"mode",lbl:"Swipe mode",t:"select",opts:[{v:"coordinates",t:"Coordinates"},{v:"direction",t:"Direction from screen center"}],d:"coordinates"},
    {k:"x1",t:"num",showWhen:{mode:"coordinates"}},{k:"y1",t:"num",showWhen:{mode:"coordinates"}},
    {k:"x2",t:"num",showWhen:{mode:"coordinates"}},{k:"y2",t:"num",showWhen:{mode:"coordinates"}},
    {k:"direction",t:"select",opts:[{v:"up",t:"Up"},{v:"down",t:"Down"},{v:"left",t:"Left"},{v:"right",t:"Right"}],d:"up",showWhen:{mode:"direction"}},
    {k:"distance",lbl:"Distance (px)",t:"num",d:400,showWhen:{mode:"direction"}},
    {k:"duration",lbl:"Duration (ms)",t:"num",d:300}
  ],sum:p=>p.mode==="direction"?`${p.direction||"up"} ${p.distance??400}px`:`(${p.x1},${p.y1})→(${p.x2},${p.y2})`},
  swipe_dir:  {label:"Swipe direction",ico:"arrow_down",kind:"action",cat:"basic", hidden:true, outs:["out"], fields:[{k:"direction",t:"select",opts:[{v:"up",t:"↑ Up"},{v:"down",t:"↓ Down"},{v:"left",t:"← Left"},{v:"right",t:"→ Right"}],d:"up"},{k:"distance",lbl:"Distance (px)",t:"num",d:400},{k:"duration",lbl:"Duration (ms)",t:"num",d:300}], sum:p=>`${({up:"↑",down:"↓",left:"←",right:"→"})[p.direction]||"↑"} ${p.distance}px`},
  wait: {label:"Wait",search:"random duration range",ico:"timer",kind:"action",cat:"basic",outs:["out"], fields:[
    {k:"mode",lbl:"Wait mode",t:"select",opts:[{v:"fixed",t:"Fixed duration"},{v:"random",t:"Random range"}],d:"fixed"},
    {k:"seconds",lbl:"Duration (s)",t:"num",d:1,step:.5,showWhen:{mode:"fixed"}},
    {k:"min",lbl:"Minimum (s)",t:"num",d:.5,step:.5,showWhen:{mode:"random"}},
    {k:"max",lbl:"Maximum (s)",t:"num",d:2,step:.5,showWhen:{mode:"random"}}
  ],sum:p=>p.mode==="random"?`${p.min??.5}–${p.max??2}s · random`:`${p.seconds??1}s`},
  wait_random:{label:"Random wait",ico:"hourglass",kind:"action",cat:"basic", hidden:true, outs:["out"], fields:[{k:"min",t:"num",d:.5,step:.5},{k:"max",t:"num",d:2,step:.5}], sum:p=>`${p.min}-${p.max}s`},
  send_text:  {label:"Input text", ico:"keyboard",kind:"action",cat:"input", outs:["out"], fields:[{k:"text",t:"text",insertVar:true}], sum:p=>`"${p.text||""}"`},
  key: {label:"Key (ADB)",search:"back home android preset",ico:"disc",kind:"action",cat:"input",outs:["out"],fields:[{k:"keycode",lbl:"Key preset",t:"key",opts:WF_ADB_KEYS,d:"4"}],sum:p=>wfAdbKeyLabel(p.keycode??"4")},
  back:       {label:"Back",      ico:"back",kind:"action",cat:"input", hidden:true, outs:["out"], fields:[], sum:()=>"Back key"},
  home:       {label:"Home",      ico:"home",kind:"action",cat:"input", hidden:true, outs:["out"], fields:[], sum:()=>"Home key"},
  tap_image:  {label:"Tap image",  ico:"target",kind:"condition",cat:"image", outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>wfBase(p.template)+(p.taps=="2"?" ×2":"")+((p.offsetX||p.offsetY)?` +(${p.offsetX||0},${p.offsetY||0})`:"")},
  wait_image: {label:"Wait image",   ico:"timer",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"negate",lbl:"Negate - wait until it DISAPPEARS",t:"bool",d:false},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>(p.negate?"until gone ":"")+wfBase(p.template)},
  if_image:   {label:"If image",   ico:"help",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"negate",t:"bool",d:false},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${p.negate?"not ":""}found ${wfBase(p.template)}`},
  // "…_any" = OR over several images: true when ANY listed template matches.
  tap_image_any: {label:"Tap any image", ico:"target",kind:"condition",cat:"image", outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"mode",lbl:"Search mode",t:"select",opts:[{v:"sequential",t:"Sequential"},{v:"parallel",t:"Parallel"}],d:"sequential"},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>wfBaseAny(p.templates)+(p.taps=="2"?" ×2":"")+(p.mode==="parallel"?" //":"")},
  wait_image_any:{label:"Wait any image",  ico:"timer",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"mode",lbl:"Search mode",t:"select",opts:[{v:"sequential",t:"Sequential"},{v:"parallel",t:"Parallel"}],d:"sequential"},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>wfBaseAny(p.templates)+(p.mode==="parallel"?" //":"")},
  if_image_any:  {label:"If any image",  ico:"layers",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"threshold",t:"num",d:.85,step:.05},{k:"negate",t:"bool",d:false},{k:"mode",lbl:"Search mode",t:"select",opts:[{v:"sequential",t:"Sequential"},{v:"parallel",t:"Parallel"}],d:"sequential"},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${p.negate?"not ":""}found ${wfBaseAny(p.templates)}${p.mode==="parallel"?" //":""}`},
  wait_text:  {label:"Wait text",   ico:"scan_text",kind:"condition",cat:"ocr",  outs:["true","false"], fields:[{k:"text",t:"text",varRef:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"timeout",t:"num",d:10},{k:"negate",lbl:"Negate - wait until it DISAPPEARS",t:"bool",d:false},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}], sum:p=>(p.negate?"until gone ":"")+`"${p.text||""}"`},
  if_text:    {label:"If text",   ico:"type",kind:"condition",cat:"ocr",outs:["true","false"], fields:[{k:"text",t:"text",varRef:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"negate",t:"bool",d:false},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}], sum:p=>`${p.negate?"not ":""}contains "${p.text||""}"`},
  read_var:   {label:"Read → variable",ico:"search",kind:"action",cat:"ocr",  outs:["out"], fields:[{k:"name",t:"text",d:"val",var:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}], sum:p=>`→ ${p.name||"?"}`},
  parse_var:  {label:"Parse → variable",ico:"scissors",kind:"action",cat:"ocr",  outs:["out"], fields:[{k:"name",t:"text",d:"out",var:true},{k:"source",t:"select",opts:[{v:"region",t:"OCR region"},{v:"var",t:"From variable"}],d:"region"},{k:"fromVar",lbl:"Source variable",t:"text",d:"",var:true,showWhen:{source:"var"}},{k:"pattern",t:"text",d:"(\\d+)/(\\d+)"},{k:"group",t:"num",d:1},{k:"x",t:"num",showWhen:{source:"region"}},{k:"y",t:"num",showWhen:{source:"region"}},{k:"w",t:"num",d:200,showWhen:{source:"region"}},{k:"h",t:"num",d:80,showWhen:{source:"region"}},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:"",showWhen:{source:"region"}}], sum:p=>`${p.name||"?"} = /${p.pattern||""}/g${p.group||1}`},
  // ── Color (pixel) nodes — compare screen pixels against a #RRGGBB colour.
  // Tolerance = max per-channel difference (same rule as DevScope's Inspect color).
  tap_color:  {label:"Tap color", ico:"droplet",kind:"condition",cat:"color", outs:["true","false"], fields:[{k:"color",t:"color",d:"#ff0000"},{k:"tolerance",lbl:"Tolerance",t:"num",d:10},{k:"timeout",t:"num",d:10},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${p.color||"?"} ±${p.tolerance??10}`+(p.taps=="2"?" ×2":"")},
  wait_color: {label:"Wait color",ico:"droplet",kind:"condition",cat:"color", outs:["true","false"], fields:[{k:"color",t:"color",d:"#ff0000"},{k:"tolerance",lbl:"Tolerance",t:"num",d:10},{k:"x",t:"num"},{k:"y",t:"num"},{k:"timeout",t:"num",d:10},{k:"negate",lbl:"Negate - wait until the color is GONE",t:"bool",d:false}], sum:p=>(p.negate?"until gone ":"")+`(${p.x||0},${p.y||0}) = ${p.color||"?"}`},
  if_color:   {label:"If color",  ico:"droplet",kind:"condition",cat:"color", outs:["true","false"], fields:[{k:"color",t:"color",d:"#ff0000"},{k:"tolerance",lbl:"Tolerance",t:"num",d:10},{k:"x",t:"num"},{k:"y",t:"num"},{k:"negate",t:"bool",d:false}], sum:p=>`${p.negate?"not ":""}(${p.x||0},${p.y||0}) ≈ ${p.color||"?"}`},
  read_color: {label:"Read color → variable",ico:"pipette",kind:"action",cat:"color", outs:["out"], fields:[{k:"name",lbl:"Target variable",t:"text",d:"color",var:true},{k:"x",t:"num"},{k:"y",t:"num"}], sum:p=>`${p.name||"?"} = px(${p.x||0},${p.y||0})`},
  loop:       {label:"Repeat",   ico:"loop",kind:"loop", cat:"flow",   ins:["in","loop"], outs:["body","done"], fields:[{k:"infinite",t:"bool",d:true},{k:"count",lbl:"Repeat count",t:"num",varRef:true,d:3,showWhen:{infinite:false}}], sum:p=>p.infinite?"∞ infinite":`${p.count}×`},
  parallel:   {label:"Parallel", ico:"parallel",kind:"parallel",cat:"flow", outs:[], fields:[{k:"count",lbl:"Thread count",t:"num",d:3,refresh:true}], sum:p=>`${p.count||3} parallel threads`},
  // Sequential fan-out: run branches 1..N one after another, ALWAYS. Unlike Try
  // in order it never stops on a success and never gives up on a failure — every
  // wired branch runs. No shared output port; each branch carries its own path.
  sequence:   {label:"Sequence", ico:"sequence",kind:"sequence",cat:"flow", outs:[], fields:[], sum:p=>`${p.count||3} steps · run in order, always`},
  try_chain:  {label:"Try in order",ico:"git_branch",kind:"try_chain",cat:"flow", outs:[], fields:[], sum:p=>`${p.count||3} branches · on fail try next branch`, pair:"try"},
  // Inside a Try in order arm: stop this branch and advance to the next numbered
  // port (or fail if none left). Like Break loop, but for try_chain.
  try_next:   {label:"Next branch",ico:"skip",kind:"try_next",cat:"flow", outs:[], fields:[], sum:()=>"skip → next try_chain branch", pair:"try"},
  join:       {label:"Join",       ico:"git_merge",kind:"join",  cat:"flow", outs:["out"], fields:[], sum:()=>"wait for all threads → continue"},
  and:        {label:"And",        ico:"git_merge",kind:"and",   cat:"flow", outs:["out"], fields:[{k:"count",lbl:"Branch count",t:"num",d:2,refresh:true}], sum:p=>`${p.count||2} branches · all must succeed`},
  "break":    {label:"Break loop",ico:"octagon",kind:"action",cat:"flow",  outs:["out"], fields:[], sum:()=>"break"},
  stop:       {label:"Stop all",ico:"octagon",kind:"stop", cat:"flow",  outs:[],      fields:[], sum:()=>"stop session"},
  set_var:    {label:"Set variable",  ico:"pin",kind:"action",cat:"logic", outs:["out"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"value",t:"text",varRef:true,d:"0"}], sum:p=>`${p.name||"?"} = ${p.value}`},
  calc_var:   {label:"Calculate variable", ico:"calculator",kind:"action",cat:"logic", outs:["out"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"op",t:"select",opts:[{v:"+",t:"+ Add"},{v:"-",t:"− Subtract"},{v:"*",t:"× Multiply"},{v:"/",t:"÷ Divide"},{v:"%",t:"% Remainder"},{v:"min",t:"Min of the two"},{v:"max",t:"Max of the two"},{v:"round",t:"Round (value = decimals)"},{v:"abs",t:"Absolute value"},{v:"=",t:"= Assign"}],d:"+"},{k:"value",t:"text",varRef:true,d:"1"}], sum:p=>`${p.name} ${p.op}= ${p.value}`},
  if_var:     {label:"If variable",  ico:"hash",kind:"condition",cat:"logic",outs:["true","false"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"op",t:"select",opts:WF_CMP_OPS,d:"=="},{k:"value",t:"text",varRef:true,d:"0"}], sum:p=>`${p.name} ${p.op} ${p.value}`},
  // Multi-way branch: each case is its own condition; first true case wins its
  // own output port "c{i}", else the "default" port. Ports are dynamic (one per
  // case + default) — see wfNodeEl. Cases edited by wfSwitchCasesEditor.
  "switch":   {label:"Switch",  ico:"git_branch",kind:"switch",cat:"logic",outs:["default"], fields:[], sum:p=>`${(p.cases||[]).length} branches`},
  // ── App lifecycle (ADB package · Win32 window title where noted) ───────────
  // pkgSrc: "project" = workflow package from Project settings; "custom" = free text / var.
  // The category is controller-neutral: launch/stop/uninstall/install are ADB-only
  // (ctrl:"adb"), while exit + if-running are implemented for BOTH backends.
  launch_app: {label:"Launch app",    ico:"rocket",kind:"action",cat:"app", ctrl:"adb", outs:["out"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"wait",lbl:"Launch wait (s)",t:"num",d:0}
  ], sum:p=>wfPkgLabel(p)+(p.wait?` ·wait ${p.wait}s`:"")},
  // Force-stop an app (optionally clear its data) — pairs with Launch app for restart-game flows. ADB-only at runtime.
  app_stop: {label:"Stop app", ico:"octagon", kind:"action", cat:"app", ctrl:"adb", outs:["out"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"clearData",lbl:"Clear app data (pm clear)",t:"bool",d:false}
  ], sum:p=>`⛔ ${wfPkgLabel(p)}`+(p.clearData?" +clear":"")},
  // Exit the current app — no package needed (ADB: force-stop foreground · Win32: close the window).
  app_exit: {label:"Exit current app", ico:"x", kind:"action", cat:"app", ctrl:null, outs:["out"], fields:[], sum:()=>"exit current app"},
  // Uninstall an app (pm uninstall; -k = keep data). ADB-only at runtime.
  app_uninstall: {label:"Uninstall app", ico:"trash", kind:"action", cat:"app", ctrl:"adb", outs:["out"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"keepData",lbl:"Keep data & cache (-k)",t:"bool",d:false}
  ], sum:p=>`🗑 ${wfPkgLabel(p)}`+(p.keepData?" ·keep":"")},
  // Install an APK sitting on the PC (adb install) — the missing counterpart of
  // Uninstall app. ADB-only.
  app_install: {label:"Install app (APK)", ico:"box", kind:"action", cat:"app", ctrl:"adb", outs:["out"], fields:[
    {k:"apk",lbl:"APK file",t:"path",d:"",pickFile:true},
    {k:"reinstall",lbl:"Reinstall, keep data (-r)",t:"bool",d:true},
    {k:"grantPerms",lbl:"Grant all permissions (-g)",t:"bool",d:false},
    {k:"timeout",lbl:"Timeout (s)",t:"num",d:180}
  ], sum:p=>`📦 ${(String(p.apk||"(apk)")).split(/[\\/]/).pop()}`+(p.reinstall?" -r":"")},
  // ADB: package of the foreground app contains a string · Win32: the TARGET
  // window's own title contains it (blank = "is my target window still alive?").
  if_app: {label:"If app running", ico:"smartphone", kind:"condition", cat:"app", ctrl:null, outs:["true","false"], fields:[
    {k:"pkgSrc",lbl:"Target",t:"select",opts:[{v:"project",t:"From Project settings"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",lbl:"Package / title contains",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"negate",t:"bool",d:false}
  ], sum:p=>`${p.negate?"not ":""}app ~ "${wfAppTargetLabel(p)}"`},
  // ── Utilities ──────────────────────────────────────────────────────────────
  // Capture one frame and (by default) write it to disk. Turning "Save" off makes
  // it a pure "refresh the frame now" step for the node that follows.
  screenshot: {label:"Screenshot",      ico:"camera",kind:"action",cat:"basic", outs:["out"], fields:[
    {k:"save",lbl:"Save a PNG file",t:"bool",d:true},
    {k:"name",lbl:"File name prefix",t:"text",insertVar:true,d:"shot",showWhen:{save:true}},
    {k:"folder",lbl:"Folder (blank = <workflow>/out/screenshots)",t:"path",d:"",pickFolder:true,showWhen:{save:true}},
    {k:"pathVar",lbl:"Store saved path in variable",t:"text",d:"",var:true,showWhen:{save:true}}
  ], sum:p=>(p.save===false?"refresh frame only":`save "${p.name||"shot"}_<time>.png"`)},
  log:        {label:"Log",   ico:"log",kind:"action",cat:"misc",  outs:["out"], fields:[{k:"message",t:"text",insertVar:true}], sum:p=>`"${p.message||""}"`},
  note:          {label:"Note",        ico:"message",  kind:"note",      cat:"misc",   outs:[],             fields:[{k:"text",t:"text",d:"note"}], sum:p=>p.text||""},
  notify:        {label:"Notify",      ico:"bell",   kind:"action",    cat:"misc",   outs:["out"],         fields:[{k:"title",lbl:"Title",t:"text",insertVar:true,d:"Workflow"},{k:"message",lbl:"Message",t:"text",insertVar:true,d:"Completed!"},{k:"sound",lbl:"Play sound",t:"bool",d:true}], sum:p=>`🔔 [${p.title||"Workflow"}] ${p.message||""}`},
  // Function call returns a boolean: "true" when the function's walk reached an
  // End node, "false" when it dead-ended (e.g. a node inside timed out).
  call:          {label:"Function",       ico:"function", kind:"call",      cat:null,     outs:["true","false"], fields:[]},
  scroll_find:   {label:"Scroll to image",   ico:"scroll",   kind:"condition", cat:"image",  outs:["true","false"],fields:[{k:"template",t:"tpl"},{k:"direction",lbl:"Swipe direction",t:"select",opts:[{v:"up",t:"↑ Up"},{v:"down",t:"↓ Down"},{v:"left",t:"← Left"},{v:"right",t:"→ Right"}],d:"up"},{k:"max_swipes",lbl:"Max swipes",t:"num",d:10},{k:"swipe_distance",lbl:"Distance (px)",t:"num",d:400},{k:"threshold",t:"num",d:.85,step:.05},{k:"swipe_duration",lbl:"Swipe duration (ms)",t:"num",d:300},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${({"up":"↑","down":"↓","left":"←","right":"→"})[p.direction]||"↑"} ≤${p.max_swipes||10}× → ${wfBase(p.template)}`},
  // Loop the body until the template appears: body loops back via the "loop"
  // port; image found → "found"; maxLoops exhausted (0 = ∞) → "fail". Replaces
  // the loop-∞ + if_image + break cluster.
  loop_until_image: {label:"Loop until image", ico:"loop", kind:"loop_until", cat:"image", ins:["in","loop"], outs:["body","found","fail"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"maxLoops",lbl:"Max loops (0 = ∞)",t:"num",varRef:true,d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`↺ until found ${wfBase(p.template)}`+((parseInt(p.maxLoops)||0)>0?` ≤${p.maxLoops}×`:"")},
  // Same loop_until shape for the other three probe kinds, so "repeat until
  // <condition>" no longer only exists for images (was: loop ∞ + if_* + break).
  loop_until_color: {label:"Loop until color", ico:"loop", kind:"loop_until", cat:"color", ins:["in","loop"], outs:["body","found","fail"], fields:[
    {k:"color",t:"color",d:"#ff0000"},
    {k:"tolerance",lbl:"Tolerance",t:"num",d:10},
    {k:"where",lbl:"Check",t:"select",opts:[{v:"point",t:"One point (x, y)"},{v:"anywhere",t:"Anywhere in region"}],d:"point"},
    {k:"x",t:"num",showWhen:{where:"point"}},{k:"y",t:"num",showWhen:{where:"point"}},
    {k:"maxLoops",lbl:"Max loops (0 = ∞)",t:"num",varRef:true,d:0},
    {k:"_region",lbl:"Search region",t:"region"}
  ], sum:p=>`↺ until ${p.color||"?"} ±${p.tolerance??10}`+((parseInt(p.maxLoops)||0)>0?` ≤${p.maxLoops}×`:"")},
  loop_until_text: {label:"Loop until text", ico:"loop", kind:"loop_until", cat:"ocr", ins:["in","loop"], outs:["body","found","fail"], fields:[
    {k:"text",t:"text",varRef:true},
    {k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},
    {k:"maxLoops",lbl:"Max loops (0 = ∞)",t:"num",varRef:true,d:0},
    {k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}
  ], sum:p=>`↺ until "${p.text||""}"`+((parseInt(p.maxLoops)||0)>0?` ≤${p.maxLoops}×`:"")},
  loop_until_var: {label:"Loop until variable", ico:"loop", kind:"loop_until", cat:"logic", ins:["in","loop"], outs:["body","found","fail"], fields:[
    {k:"name",t:"text",d:"i",var:true},
    {k:"op",t:"select",opts:WF_CMP_OPS,d:">="},
    {k:"value",t:"text",varRef:true,d:"10"},
    {k:"maxLoops",lbl:"Max loops (0 = ∞)",t:"num",varRef:true,d:0}
  ], sum:p=>`↺ until ${p.name||"?"} ${p.op||">="} ${p.value}`+((parseInt(p.maxLoops)||0)>0?` ≤${p.maxLoops}×`:"")},
  // Find a template and store its centre in two variables — the only way to get
  // a match position into arithmetic (the implicit "last found" can only be tapped).
  find_image_pos: {label:"Find image → position", ico:"search", kind:"condition", cat:"image", outs:["true","false"], fields:[
    {k:"template",t:"tpl"},
    {k:"nameX",lbl:"X → variable",t:"text",d:"foundX",var:true},
    {k:"nameY",lbl:"Y → variable",t:"text",d:"foundY",var:true},
    {k:"threshold",t:"num",d:.85,step:.05},
    {k:"_region",lbl:"Search region",t:"region"}
  ], sum:p=>`${wfBase(p.template)} → ${p.nameX||"?"}, ${p.nameY||"?"}`},
  // Wait for the screen to stop changing (animation / loading settled) instead of
  // guessing a fixed Wait duration.
  wait_stable: {label:"Wait until screen settles", ico:"hourglass", kind:"condition", cat:"basic", outs:["true","false"], fields:[
    {k:"settle",lbl:"Must stay still for (s)",t:"num",d:1,step:.5},
    {k:"timeout",lbl:"Timeout (s)",t:"num",d:15},
    {k:"tolerance",lbl:"Pixel change tolerance",t:"num",d:2,step:.5},
    {k:"_region",lbl:"Search region",t:"region"}
  ], sum:p=>`🧊 still ${p.settle??1}s · ≤${p.timeout??15}s`},
  // Tap EVERY position matching the template on the current frame (loot-collection sweeps).
  tap_all_images: {label:"Tap all matches", ico:"layers", kind:"condition", cat:"image", outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"maxTaps",lbl:"Max taps (0 = all)",t:"num",varRef:true,d:0},{k:"delayBetween",lbl:"Delay between taps (s)",t:"num",d:.15,step:.05},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`tap all ${wfBase(p.template)}`+((parseInt(p.maxTaps)||0)>0?` ≤${p.maxTaps}`:"")+(p.taps=="2"?" ×2":"")},
  random_branch: {label:"Random branch",ico:"dice",   kind:"random",    cat:"flow",   outs:[],              fields:[{k:"count",lbl:"Branch count",t:"num",d:2,refresh:true}], sum:p=>`🎲 ${p.count||2} even branches`},
  format_var:    {label:"Format string",ico:"type",   kind:"action",    cat:"logic",  outs:["out"],         fields:[{k:"name",lbl:"Target variable",t:"text",d:"text",var:true},{k:"template",lbl:"Template string",t:"text",insertVar:true,d:"Round {round}/{total}"}], sum:p=>`${p.name||"?"} = "${p.template||""}"`},
  // ── Time ───────────────────────────────────────────────────────────────────
  get_time:      {label:"Get time → variable", ico:"clock", kind:"action", cat:"time", outs:["out"], fields:[{k:"name",lbl:"Target variable",t:"text",d:"now",var:true},{k:"part",lbl:"Value",t:"select",opts:[{v:"hm",t:"HH:MM"},{v:"hms",t:"HH:MM:SS"},{v:"hour",t:"Hour (0-23)"},{v:"minute",t:"Minute"},{v:"second",t:"Second"},{v:"date",t:"Date YYYY-MM-DD"},{v:"datetime",t:"Date & time"},{v:"weekday",t:"Weekday (1=Mon…7=Sun)"},{v:"timestamp",t:"Unix timestamp"},{v:"custom",t:"Custom (strftime)"}],d:"hm"},{k:"format",lbl:"strftime format",t:"text",d:"%H:%M",showWhen:{part:"custom"}}], sum:p=>`${p.name||"?"} = ${({hm:"HH:MM",hms:"HH:MM:SS",hour:"hour",minute:"minute",second:"second",date:"date",datetime:"datetime",weekday:"weekday",timestamp:"timestamp",custom:p.format||"?"})[p.part||"hm"]}`},
  wait_until:    {label:"Wait until time", ico:"alarm", kind:"action", cat:"time", outs:["out"], fields:[{k:"time",lbl:"Time",t:"time",d:"08:00"},{k:"nextDay",lbl:"If passed → wait next day",t:"bool",d:true}], sum:p=>`⏰ ${p.time||"08:00"}`},
  if_time:       {label:"If within time", ico:"clock", kind:"condition", cat:"time", outs:["true","false"], fields:[{k:"from",lbl:"From",t:"time",d:"08:00"},{k:"to",lbl:"To",t:"time",d:"22:00"},{k:"negate",lbl:"Negate (outside window)",t:"bool",d:false}], sum:p=>`${p.negate?"not ":""}${p.from||"00:00"}–${p.to||"23:59"}`},
  // ── Device (ADB / emulator) ────────────────────────────────────────────────
  device_info:   {label:"Device info → variable", ico:"smartphone", kind:"action", cat:"device", outs:["out"], fields:[{k:"name",lbl:"Target variable",t:"text",d:"info",var:true},{k:"prop",lbl:"Property",t:"select",opts:[{v:"battery",t:"Battery level (%)"},{v:"current_app",t:"Current app package"},{v:"width",t:"Screen width"},{v:"height",t:"Screen height"},{v:"model",t:"Model"},{v:"brand",t:"Brand"},{v:"android",t:"Android version"},{v:"sdk",t:"SDK level"},{v:"serial",t:"Serial"},{v:"ip",t:"IP address"}],d:"battery"}], sum:p=>`${p.name||"?"} = ${p.prop||"battery"}`},
  screen_power:  {label:"Screen power", ico:"power", kind:"action", cat:"device", outs:["out"], fields:[{k:"action",lbl:"Action",t:"select",opts:[{v:"on",t:"Wake / On"},{v:"off",t:"Sleep / Off"},{v:"toggle",t:"Toggle (power key)"}],d:"on"}], sum:p=>`🖥 ${({on:"wake",off:"sleep",toggle:"toggle"})[p.action||"on"]}`},
  // Read side of Screen power — branch on whether the display is awake.
  if_screen_on:  {label:"If screen is on", ico:"power", kind:"condition", cat:"device", outs:["true","false"], fields:[{k:"negate",lbl:"Negate (screen is off)",t:"bool",d:false}], sum:p=>`🖥 screen ${p.negate?"off":"on"}?`},
  if_device_size:{label:"If device size", ico:"smartphone", kind:"condition", cat:"device", outs:["true","false"], fields:[
    {k:"width",lbl:"Screen width",t:"num",d:1920},
    {k:"height",lbl:"Screen height",t:"num",d:1080},
    {k:"tolerance",lbl:"Tolerance (px)",t:"num",d:0},
    {k:"negate",lbl:"Negate (different size)",t:"bool",d:false}
  ], sum:p=>`📱 ${p.negate?"not ":""}${p.width??1920}×${p.height??1080}${Number(p.tolerance)?`±${p.tolerance}`:""}`},
  // Escape hatch: run any adb shell command and capture stdout into a variable.
  adb_shell:     {label:"ADB shell → variable", ico:"log", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"command",lbl:"Shell command",t:"text",insertVar:true,d:"getprop ro.product.model"},
    {k:"name",lbl:"Output → variable",t:"text",d:"out",var:true},
    {k:"failIfEmpty",lbl:"Treat empty output as failure",t:"bool",d:false}
  ], sum:p=>`💻 ${String(p.command||"").slice(0,28)||"(command)"} → ${p.name||"?"}`},
  // Launch the emulator PROCESS on the PC (not an app inside it). Optional "at"
  // waits until a clock time first → "sit idle until 07:00, then boot LDPlayer".
  launch_emulator:{label:"Launch emulator", ico:"monitor", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"pathSrc",lbl:"Emulator",t:"select",opts:[{v:"project",t:"Project emulator setting"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"emulator",lbl:"Family",t:"select",opts:[{v:"ldplayer",t:"LDPlayer"},{v:"mumu",t:"MuMu"},{v:"nox",t:"Nox"},{v:"memu",t:"MEmu"},{v:"bluestacks",t:"BlueStacks"},{v:"custom",t:"Custom command"}],d:"ldplayer",showWhen:{pathSrc:"custom"}},
    {k:"index",lbl:"Instance index",t:"num",d:0},
    {k:"instance",lbl:"Instance name (BlueStacks)",t:"text",d:"",showWhen:{pathSrc:"custom",emulator:"bluestacks"}},
    {k:"path",lbl:"Install folder / console .exe (blank = auto)",t:"path",d:"",pickFolder:true,showWhen:{pathSrc:"custom"}},
    {k:"command",lbl:"Custom command ({index})",t:"text",d:"",showWhen:{pathSrc:"custom",emulator:"custom"}},
    {k:"at",lbl:"Schedule at (blank = now)",t:"time",d:""},
    {k:"nextDay",lbl:"If time passed → wait next day",t:"bool",d:true},
    {k:"wait",lbl:"Wait for ADB ready (s)",t:"num",d:60},
    {k:"port",lbl:"ADB port override (blank = auto)",t:"num"},
  ], sum:p=>`▶ ${p.pathSrc==="project"?"project emulator":(p.emulator||"ldplayer")}${(p.index?(" #"+p.index):"")}${p.at?(" ⏰"+p.at):""}`},
  // Is an emulator instance booted & its ADB responding (sys.boot_completed)?
  // "Last used" re-checks the instance saved by the last successful Launch
  // emulator (data/emulator_state.json) — skip the boot when it's already up.
  if_emulator:{label:"If emulator ready", ico:"monitor", kind:"condition", cat:"device", outs:["true","false"], fields:[
    {k:"emulator",lbl:"Emulator",t:"select",opts:[{v:"last",t:"Last used (saved)"},{v:"ldplayer",t:"LDPlayer"},{v:"mumu",t:"MuMu"},{v:"nox",t:"Nox"},{v:"memu",t:"MEmu"},{v:"bluestacks",t:"BlueStacks"}],d:"last"},
    {k:"index",lbl:"Instance index (ignored for Last used)",t:"num",d:0},
    {k:"port",lbl:"ADB port override (blank = auto)",t:"num"},
    {k:"attach",lbl:"Attach as active device when ready",t:"bool",d:true},
  ], sum:p=>`🖥 ${(!p.emulator||p.emulator==="last")?"last used":(p.emulator+((parseInt(p.index)||0)?(" #"+p.index):""))} ready?`},
  // Poll until the emulator finishes Android boot (adb connect + sys.boot_completed
  // == 1), or until timeout. Use after Launch emulator (with wait=0) or when the
  // instance is already starting outside this flow.
  wait_emulator:{label:"Wait emulator ready", ico:"timer", kind:"condition", cat:"device", outs:["true","false"], fields:[
    {k:"emulator",lbl:"Emulator",t:"select",opts:[{v:"last",t:"Last used (saved)"},{v:"ldplayer",t:"LDPlayer"},{v:"mumu",t:"MuMu"},{v:"nox",t:"Nox"},{v:"memu",t:"MEmu"},{v:"bluestacks",t:"BlueStacks"}],d:"last"},
    {k:"index",lbl:"Instance index (ignored for Last used)",t:"num",d:0},
    {k:"port",lbl:"ADB port override (blank = auto)",t:"num"},
    {k:"timeout",lbl:"Timeout (s)",t:"num",d:120},
    {k:"attach",lbl:"Attach as active device when ready",t:"bool",d:true},
  ], sum:p=>`⏳ ${(!p.emulator||p.emulator==="last")?"last used":(p.emulator+((parseInt(p.index)||0)?(" #"+p.index):""))} ≤${p.timeout??120}s`},
  // Resize the emulator's own PC window (the player UI — MuMu/LDPlayer/…), not
  // the game inside it. Width/Height = the CLIENT area (the Android screen) —
  // the title bar is compensated, so the device isn't letterboxed with black
  // side bars. Finds the player window by process name; "last" reuses the
  // instance saved by Launch emulator. Pure Win32, so it also works in ADB
  // flows — e.g. snap MuMu to 1920×1080 right after boot.
  resize_emulator:{label:"Resize emulator", ico:"maximize", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"emulator",lbl:"Emulator",t:"select",opts:WF_EMU_TARGET_OPTS,d:"selected"},
    {k:"index",lbl:"Instance index (ignored for Last used / Selected)",t:"num",d:0},
    {k:"pathSrc",lbl:"Install folder",t:"select",opts:[{v:"project",t:"Project emulator setting"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"path",lbl:"Install folder (blank = auto)",t:"path",d:"",pickFolder:true,showWhen:{pathSrc:"custom"}},
    {k:"width",lbl:"Client width (Android screen)",t:"num",d:1920},
    {k:"height",lbl:"Client height (Android screen)",t:"num",d:1080},
    {k:"x",lbl:"Window X (blank = keep)",t:"num"},
    {k:"y",lbl:"Window Y (blank = keep)",t:"num"},
  ], sum:p=>`📐 ${wfEmuTargetLabel(p)} → ${p.width||1920}×${p.height||1080}`},
  // Kill the emulator instance — closing the app inside ≠ closing the emulator;
  // the instance keeps running and holds RAM/CPU + ADB port. Preferred path is
  // the family's console shutdown (LDPlayer/MuMu/Nox/MEmu); falls back to
  // taskkilling the player window's process tree when no console exists or it
  // can't be resolved. "last" reuses the instance saved by Launch emulator.
  kill_emulator:{label:"Kill emulator", ico:"octagon", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"emulator",lbl:"Emulator",t:"select",opts:WF_EMU_TARGET_OPTS,d:"selected"},
    {k:"index",lbl:"Instance index (ignored for Last used / Selected)",t:"num",d:0},
    {k:"pathSrc",lbl:"Install folder",t:"select",opts:[{v:"project",t:"Project emulator setting"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"path",lbl:"Install folder (blank = auto)",t:"path",d:"",pickFolder:true,showWhen:{pathSrc:"custom"}},
  ], sum:p=>`⏹ ${wfEmuTargetLabel(p)}`},
  // Reboot a wedged instance (frozen UI, ADB gone, app stuck) — what app_stop
  // can't fix. Console reboot when the family has one (LDPlayer/MuMu/Nox/MEmu),
  // else kill the player + relaunch. Wait > 0 polls sys.boot_completed so the
  // next node runs against a booted device.
  restart_emulator:{label:"Restart emulator", ico:"loop", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"emulator",lbl:"Emulator",t:"select",opts:WF_EMU_TARGET_OPTS,d:"selected"},
    {k:"index",lbl:"Instance index (ignored for Last used / Selected)",t:"num",d:0},
    {k:"pathSrc",lbl:"Install folder",t:"select",opts:[{v:"project",t:"Project emulator setting"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"path",lbl:"Install folder (blank = auto)",t:"path",d:"",pickFolder:true,showWhen:{pathSrc:"custom"}},
    {k:"wait",lbl:"Wait for boot (s · 0 = don't wait)",t:"num",d:120},
    {k:"port",lbl:"ADB port override (blank = auto)",t:"num"},
    {k:"attach",lbl:"Attach as active device when ready",t:"bool",d:true},
  ], sum:p=>`♻ ${wfEmuTargetLabel(p)}${(p.wait??120)>0?(" ≤"+(p.wait??120)+"s"):""}`},
  // Set the DEVICE resolution (Android screen px + DPI) — the value templates
  // were cropped against. Resize emulator only changes the PC window, so a
  // 1920×1080 window over a 1600×900 device still letterboxes. MuMu only; the
  // instance must restart to apply, which this node does by default.
  emulator_resolution:{label:"Emulator resolution", ico:"smartphone", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"emulator",lbl:"Emulator (MuMu only)",t:"select",opts:WF_EMU_TARGET_OPTS_MUMU,d:"selected"},
    {k:"index",lbl:"Instance index (ignored for Last used / Selected)",t:"num",d:0},
    {k:"pathSrc",lbl:"Install folder",t:"select",opts:[{v:"project",t:"Project emulator setting"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"path",lbl:"Install folder (blank = auto)",t:"path",d:"",pickFolder:true,showWhen:{pathSrc:"custom"}},
    {k:"width",lbl:"Device width (px)",t:"num",d:1920},
    {k:"height",lbl:"Device height (px)",t:"num",d:1080},
    {k:"dpi",lbl:"DPI",t:"num",d:280},
    {k:"restart",lbl:"Restart instance to apply",t:"bool",d:true},
    {k:"wait",lbl:"Wait for boot after restart (s)",t:"num",d:120,showWhen:{restart:true}},
    {k:"port",lbl:"ADB port override (blank = auto)",t:"num",showWhen:{restart:true}},
    {k:"attach",lbl:"Attach as active device when ready",t:"bool",d:true,showWhen:{restart:true}},
  ], sum:p=>`📱 ${p.width||1920}×${p.height||1080} @${p.dpi||280}dpi${(p.restart===false)?"":" ♻"}`},
  // ── Win32 input (PC keyboard & mouse) ────────────────────────────────────────
  // Only used when the project's Controller = Win32. The tap/swipe/image/color/
  // OCR nodes still work on Win32 through the shared screen-capture pipeline;
  // these cover what a single left-button touch model can't express.
  win_send_text:{label:"Input text", ico:"keyboard", kind:"action", cat:"win32", outs:["out"], fields:[{k:"text",t:"text",insertVar:true}], sum:p=>`"${p.text||""}"`},
  // mode: press = down → hold → up (a game only moves while the key is down, so
  // walking wants a few hundred ms); down / up keep a key held across blocks.
  win_key:      {label:"Key (Win32)",search:"press key escape esc preset", ico:"disc", kind:"action", cat:"win32", outs:["out"], fields:[
    {k:"keycode",lbl:"Key preset",t:"key",opts:WF_WIN_KEYS,d:"13"},
    {k:"mode",lbl:"Action",t:"select",opts:[{v:"press",t:"Press (down → hold → up)"},{v:"down",t:"Hold down (until Release)"},{v:"up",t:"Release (key up)"}],d:"press"},
    {k:"hold",lbl:"Hold (ms)",t:"num",d:80,showWhen:{mode:"press"}},
  ], sum:p=>`${({down:"⬇ hold ",up:"⬆ release "})[p.mode]||""}${wfWinKeyLabel(p.keycode??"13")}${(!p.mode||p.mode==="press")?` ${p.hold??80}ms`:""}`},
  // Key + modifiers (Ctrl+C, Alt+Enter, Ctrl+Shift+Esc…). Background modes send
  // Alt combos as WM_SYSKEYDOWN, which is what apps actually listen for.
  win_hotkey:   {label:"Hotkey (combo)", ico:"keyboard", kind:"action", cat:"win32", outs:["out"], fields:[
    {k:"ctrl",lbl:"Ctrl",t:"bool",d:true},
    {k:"shift",lbl:"Shift",t:"bool",d:false},
    {k:"alt",lbl:"Alt",t:"bool",d:false},
    {k:"win",lbl:"Win",t:"bool",d:false},
    {k:"keycode",lbl:"Key",t:"select",opts:WF_WIN_KEYS,d:"67"}
  ], sum:p=>[p.ctrl&&"Ctrl",p.shift&&"Shift",p.alt&&"Alt",p.win&&"Win",wfWinKeyLabel(p.keycode??"67")].filter(Boolean).join("+")},
  win_escape:   {label:"Escape key", ico:"back", kind:"action", cat:"win32", hidden:true, outs:["out"], fields:[], sum:()=>"Esc"},
  // Right / middle click (the left button is the shared Tap node).
  win_click:    {label:"Mouse click", ico:"pointer", kind:"action", cat:"win32", outs:["out"], fields:[
    {k:"button",lbl:"Button",t:"select",opts:[{v:"right",t:"Right"},{v:"middle",t:"Middle"},{v:"left",t:"Left"}],d:"right"},
    {k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},
    {k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}},
    {k:"clicks",t:"select",opts:[{v:"1",t:"Click"},{v:"2",t:"Double click"}],d:"1"},
    {k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0}
  ], sum:p=>`${(p.button||"right")} · `+(p.target==="found"?"↳ last found image":`(${p.x||0}, ${p.y||0})`)+(p.clicks=="2"?" ×2":"")},
  win_scroll:   {label:"Mouse wheel", ico:"scroll", kind:"action", cat:"win32", outs:["out"], fields:[
    {k:"direction",lbl:"Direction",t:"select",opts:[{v:"down",t:"↓ Down"},{v:"up",t:"↑ Up"},{v:"left",t:"← Left"},{v:"right",t:"→ Right"}],d:"down"},
    {k:"notches",lbl:"Notches",t:"num",d:3},
    {k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},
    {k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}}
  ], sum:p=>`${({up:"↑",down:"↓",left:"←",right:"→"})[p.direction]||"↓"} ×${p.notches??3}`},
  win_mouse_move:{label:"Move mouse (hover)", ico:"move", kind:"action", cat:"win32", outs:["out"], fields:[
    {k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},
    {k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}}
  ], sum:p=>p.target==="found"?"↳ last found image":`hover (${p.x||0}, ${p.y||0})`},
  // ── Win32 window (lifecycle / geometry / state) ──────────────────────────────
  // pathSrc: "project" = game path from Project settings (re-pointable in the
  // Runner's Settings tab); "custom" = this node's own path / path variable.
  win_launch:   {label:"Launch program", ico:"rocket", kind:"action", cat:"window", outs:["out"], fields:[
    {k:"pathSrc",lbl:"Game path",t:"select",opts:[{v:"project",t:"Project game path"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"path",lbl:"Program (.exe) path",t:"path",d:"",pickFile:true,showWhen:{pathSrc:"custom"}},
    {k:"args",lbl:"Arguments (optional)",t:"text",d:""},
    {k:"window",lbl:"Wait for window title (optional)",t:"text",d:""},
    {k:"wait",lbl:"Wait for window (s)",t:"num",d:30},
  ], sum:p=>`▶ ${wfLaunchPathLabel(p)}`},
  win_activate: {label:"Activate window", ico:"monitor", kind:"action", cat:"window", outs:["out"], fields:[], sum:()=>"bring window to front"},
  win_close:    {label:"Close window", ico:"x", kind:"action", cat:"window", outs:["out"], fields:[], sum:()=>"close target window"},
  // client: W×H is the game area (captures/templates), frame added on top.
  // center: centre on the monitor's work area. Both off on nodes saved before
  // they existed (outer size, top-left kept); new nodes default both on.
  win_resize:   {label:"Resize window", ico:"maximize", kind:"action", cat:"window", outs:["out"], fields:[
    {k:"width",lbl:"Width",t:"num",d:1280},{k:"height",lbl:"Height",t:"num",d:720},
    {k:"client",lbl:"Size = game area (client, without borders)",t:"bool",d:true},
    {k:"center",lbl:"Center on screen",t:"bool",d:true},
  ], sum:p=>`${p.width||1280}×${p.height||720}${p.client?" client":""}${p.center?" · center":""}`},
  win_move:     {label:"Move window", ico:"move", kind:"action", cat:"window", outs:["out"], fields:[{k:"x",lbl:"Screen X",t:"num",d:0},{k:"y",lbl:"Screen Y",t:"num",d:0}], sum:p=>`(${p.x||0}, ${p.y||0})`},
  win_minimize: {label:"Minimize window", ico:"minimize", kind:"action", cat:"window", outs:["out"], fields:[], sum:()=>"minimize"},
  win_maximize: {label:"Maximize window", ico:"maximize", kind:"action", cat:"window", outs:["out"], fields:[], sum:()=>"maximize"},
  win_restore:  {label:"Restore window", ico:"monitor", kind:"action", cat:"window", outs:["out"], fields:[], sum:()=>"restore"},
  win_always_on_top: {label:"Always on top", ico:"pin", kind:"action", cat:"window", outs:["out"], fields:[{k:"enabled",lbl:"Enabled",t:"bool",d:true}], sum:p=>p.enabled?"📌 on top":"📌 normal"},
  win_set_title: {label:"Set window title", ico:"type", kind:"action", cat:"window", outs:["out"], fields:[{k:"title",lbl:"New title",t:"text",d:"Game"}], sum:p=>`"${p.title||"?"}"`},
  win_style:    {label:"Set window style", ico:"settings", kind:"action", cat:"window", outs:["out"], fields:[{k:"style",lbl:"Style",t:"select",opts:[{v:"windowed",t:"Windowed (with frame)"},{v:"borderless",t:"Borderless"},{v:"popup",t:"Popup"}],d:"windowed"}], sum:p=>`${p.style||"windowed"}`},
  // Win32 conditions — the target window's own state (crash detection etc.), not
  // the foreground window's. Previously Win32 projects had no condition at all.
  win_if_window:{label:"If window …", ico:"help", kind:"condition", cat:"window", outs:["true","false"], fields:[
    {k:"state",lbl:"State",t:"select",opts:WF_WIN_STATES,d:"exists"},
    ...WF_WIN_SIZE_FIELDS,
    {k:"negate",t:"bool",d:false}
  ], sum:p=>`🪟 ${p.negate?"not ":""}${wfWinStateLabel(p)}`},
  win_wait_window:{label:"Wait for window …", ico:"timer", kind:"condition", cat:"window", outs:["true","false"], fields:[
    {k:"state",lbl:"State",t:"select",opts:WF_WIN_STATES,d:"exists"},
    ...WF_WIN_SIZE_FIELDS,
    {k:"timeout",lbl:"Timeout (s)",t:"num",d:30},
    {k:"negate",lbl:"Negate - wait for the opposite",t:"bool",d:false}
  ], sum:p=>`🪟 ${p.negate?"not ":""}${wfWinStateLabel(p)} ≤${p.timeout??30}s`},
  // Win32's answer to Device info → variable.
  win_info:     {label:"Window info → variable", ico:"monitor", kind:"action", cat:"window", outs:["out"], fields:[
    {k:"name",lbl:"Target variable",t:"text",d:"info",var:true},
    {k:"prop",lbl:"Property",t:"select",opts:[{v:"width",t:"Client width"},{v:"height",t:"Client height"},{v:"x",t:"Window X (screen)"},{v:"y",t:"Window Y (screen)"},{v:"title",t:"Title"},{v:"class",t:"Class name"},{v:"pid",t:"Process ID"},{v:"exe",t:"Executable"},{v:"hwnd",t:"Window handle"},{v:"foreground",t:"Is foreground (true/false)"},{v:"minimized",t:"Is minimized (true/false)"}],d:"width"}
  ], sum:p=>`${p.name||"?"} = ${p.prop||"width"}`},
};
// `ctrl` restricts a category to one project controller: the Device/emulator
// Device and Android Keys/Input nodes are ADB-only; Win32 window/keyboard nodes
// are PC-only. Visual/basic/flow groups work on both. A node may override its
// category with its own `ctrl` (see WF_NODES.app_exit / if_app, which the engine
// implements for BOTH backends) or clear it with ctrl:null.
// Order follows task adjacency: direct input first; visual recognition groups
// stay together (Image → Text → Color); decision/flow groups stay together;
// platform lifecycle tools sit near each other at the end.
const WF_CATS = [
  {key:"basic", label:"Basic"},
  {key:"input", label:"Keys & Input (ADB)", ctrl:"adb"},
  {key:"image", label:"Image"},
  {key:"ocr",   label:"Text (OCR)"},
  {key:"color", label:"Color",   closed:true},
  {key:"logic", label:"Variables / Conditions"},
  {key:"flow",  label:"Flow"},
  {key:"time",  label:"Time",    closed:true},
  {key:"app",   label:"App", closed:true},
  {key:"device",label:"Device (ADB)",  ctrl:"adb",   closed:true},
  {key:"win32", label:"Win32 input (PC)", ctrl:"win32"},
  {key:"window",label:"Win32 window (PC)", ctrl:"win32"},
  {key:"misc",  label:"Other",   closed:true},
];
// Which controller a node belongs to: its own `ctrl` when set (including null =
// "both", overriding the category), else its category's. Used by the palette,
// the validator and the switch-case list so all three agree.
function wfNodeCtrl(type){
  const def=WF_NODES[type];
  if(!def) return null;
  if(Object.prototype.hasOwnProperty.call(def,"ctrl")) return def.ctrl||null;
  const cat=WF_CATS.find(c=>c.key===def.cat);
  return (cat&&cat.ctrl)||null;
}
function wfNodeAllowed(type, ctrl){
  const need=wfNodeCtrl(type);
  return !need || need===(ctrl||"adb");
}
// PC-side emulator nodes that carry an install-folder path. They share the
// project-level emulator setting (WF.emulator) unless a node picks "Custom".
const WF_EMU_NODE_TYPES=["launch_emulator","resize_emulator","kill_emulator","restart_emulator","emulator_resolution"];
// Palette pairs: related nodes rendered as one framed unit so the relationship
// is obvious (e.g. Try in order + Next branch). Order of `types` = display order.
// Search: if any member matches, the whole pair still shows (all members).
const WF_PAL_PAIRS = [
  { id:"try", types:["try_chain","try_next"], label:"Try pair",
    hint:"Try arms 1→2→… · Next branch skips to the next arm" },
];
// "body" is where the loop's contents hang off; the loop-back INPUT is what is
// labelled "loop" (WF_IN_LBL). Calling both of them "loop" made a Repeat block
// read as if it had the same port twice.
const WF_PORT_LBL = { out:"", "true":"True", "false":"False", body:"body", done:"done", found:"found", fail:"fail", "1":"1", "2":"2", "3":"3" };
// Input-side port labels (only shown for nodes with >1 input, e.g. the loop).
const WF_IN_LBL = { in:"in", loop:"loop" };

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
  // Fill region from the filename when the user explicitly enables "Search region".
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

// One port model for canvas rendering and per-exit log configuration.
function wfNodeOutputPorts(node){
  const p=node.params||{}, type=node.type;
  if(type==="switch") return (p.cases||[]).map((_,i)=>"c"+i).concat("default");
  if(["parallel","random_branch","sequence","try_chain"].includes(type)){
    const ports=Array.from({length:Math.max(1,parseInt(p.count)||(type==="random_branch"?2:3))},(_,i)=>String(i+1));
    return ports.concat(type==="sequence"?["end"]:type==="try_chain"?["fail"]:[]);
  }
  return ((WF_NODES[type]||{}).outs||[]).slice();
}
function wfNodeLogFields(node){
  const kind=(WF_NODES[node.type]||{}).kind;
  if(kind==="note") return [];
  const fields=[{key:"input",label:"Log Input",tag:"IN"}];
  const labels={out:"Output",true:"True",false:"False",body:"Body",done:"Done",found:"Found",fail:"Fail",end:"End",default:"Default"};
  for(const port of wfNodeOutputPorts(node)){
    const label=labels[port]||(/^c\d+$/.test(port)?"Case "+(Number(port.slice(1))+1):"Branch "+port);
    fields.push({key:port,label:"Log "+label,tag:label.toUpperCase()});
  }
  if(["end","stop","try_next"].includes(kind)) fields.push({key:"$done",label:"Log Done",tag:"DONE"});
  if(kind==="action"||kind==="and") fields.push({key:"$error",label:"Log Error",tag:"ERROR"});
  return fields;
}
function wfOutputLogValues(node){
  const valid=new Set(wfNodeLogFields(node).filter(f=>f.key!=="input").map(f=>f.key));
  if(node.outputLogs && typeof node.outputLogs==="object" && !Array.isArray(node.outputLogs))
    return Object.fromEntries(Object.entries(node.outputLogs).filter(([k,v])=>valid.has(k)&&typeof v==="string"));
  return node.outputLog ? Object.fromEntries([...valid].map(k=>[k,node.outputLog])) : {};
}
function wfNodeLogEntries(node){
  const logs=wfOutputLogValues(node);
  return wfNodeLogFields(node).map(f=>({...f,text:f.key==="input"?(node.log||""):(logs[f.key]||"")})).filter(f=>f.text);
}

// Recognition-model registry. Keep the selector plumbing even with one model
// so future recognition models can be added without redesigning Project or
// Preview settings.
const WF_OCR_MODELS=[{id:"ppocr_v5_mobile",label:"PP-OCRv5 Mobile"}];
function wfNormalizeOcrBackend(value){
  const id=String(value||"").trim().toLowerCase();
  return WF_OCR_MODELS.some(model=>model.id===id)?id:WF_OCR_MODELS[0].id;
}
function wfOcrModelLabel(value){
  const id=wfNormalizeOcrBackend(value);
  return (WF_OCR_MODELS.find(model=>model.id===id)||{}).label||id;
}
function wfNormalizeNode(node){
  const p=node.params||(node.params={});
  if(node.type==="back"||node.type==="home"){
    p.keycode=node.type==="back"?"4":"3"; node.type="key";
  }else if(node.type==="win_escape"){
    node.type="win_key"; p.keycode="27"; p.mode="press"; p.hold=0;
  }else if(node.type==="wait_random"){
    node.type="wait"; p.mode="random";
  }else if(node.type==="swipe_dir"){
    node.type="swipe"; p.mode="direction";
  }
  if(["key","win_key","wait","swipe"].includes(node.type)){
    for(const f of WF_NODES[node.type].fields){
      if(p[f.k]===undefined) p[f.k]=f.d!==undefined?f.d:(f.t==="num"?0:"");
    }
  }
  if(node.type==="key") p.keycode=wfAdbKeyValue(p.keycode);
  node.outputLogs=wfOutputLogValues(node);
  delete node.outputLog;
  return node;
}

// edit = which graph the canvas is showing: an activity or a function.
// sel = ids of all selected nodes (multi-select); selectedNode = primary (inspector).
const WF = { name:"My Workflow", version:2, templatesDir:"templates", activities:[], functions:[],
  globals:[],
  // Release version stamped onto a standalone Runner .exe built from this
  // workflow (Build EXE). Saved into the flow JSON (key "buildVersion").
  buildVersion:"1.0.0",
  // Target Android package for this workflow (ADB). Top-level, not part of speedhack.
  package:"",
  // Speed hack toggle + multiplier only; package lives on WF.package.
  // native = compiled-C clock hook (smoother at high scales, but some protected
  // titles crash when Frida compiles it — off by default).
  speedhack:{enabled:false, speed:2.0, native:false},
  // Which backend drives the flow: "adb" (device/emulator) or "win32" (PC window).
  controller:"adb",
  win32:{window:"", matchBy:"title", inputMode:"background"},
  // Shared emulator choice for ADB projects: the family + install folder that
  // Launch emulator (and the other emulator nodes) use by default. Edited in
  // Project settings here and in the Runner's Settings tab; nodes can opt out
  // per-node via their own "Emulator" source = Custom. Saved into the flow JSON
  // (key "emulator").
  emulator:{kind:"ldplayer", path:""},
  // Recognition model for text-reading blocks (wait_text/if_text/read_var/parse_var…).
  // The registry currently exposes only PP-OCRv5 Mobile; the selected model is
  // saved into the flow JSON (key "ocr") for Runner and test runs.
  ocrBackend:WF_OCR_MODELS[0].id,
  // Screen capture source for ADB projects: "scrcpy" (fast/headless) or "adb"
  // (screencap). Saved into the flow JSON (key "capture") per game workflow.
  captureBackend:"scrcpy",
  // Input transport for ADB projects: "adb" (shell `input`, most compatible) or
  // "scrcpy" (control socket, far lower latency). Saved into the flow JSON
  // (key "input") per game workflow.
  inputBackend:"adb",
  // Project-wide defaults applied to EVERY newly-created node (seeded by
  // wfNewNode). Edited from the Inspector's Timing / Failure-handling gear
  // (wfNodeDefaultsModal), saved into the flow JSON (key "nodeDefaults") so the
  // values survive a reload and carry to the Runner. Existing nodes are not
  // touched — the stamp only applies at creation time.
  nodeDefaults:{ delayBefore:0, delayAfter:0, retryCount:0, retryDelay:0, screenshotOnFail:false },
  edit:{kind:"activity", id:null}, sel:[], selectedNode:null };
let wfSpace=false;  // space held → pan instead of box-select
// A Space press that never panned is a "tap"; two taps in quick succession reset
// the zoom (keyboard.js). Armed on keydown, spent when a Space+drag pan starts.
let wfSpaceArmed=false, wfSpaceUsed=false;
const WF_GRID=20;   // grid step; every card dimension is a whole multiple of it
let wfSnapOn=true;  // snap ON by default — blocks land on the grid unless you opt out
let wfPreviewAll=false;   // global: show image thumbnail on every image block
let wfMinimapOn=false;    // minimap is opt-in (default off)
let wfAlignOn=true;       // Figma-style edge/centre magnetism + guides (Alt = pause)
// Live runtime variable values pushed from the engine during a test run.
// Keyed by var name -> current value (stringified for display).
let wfLiveVars={};
let wfFreshVar=null;       // name of the most-recently-changed var (brief highlight)
// Corner-panel collapse states persist locally so the canvas reopens as left.
// (The dock card's open tab — wfDockTab — persists alongside, in render.js.)
let wfActCollapsed=false;
let wfSideCollapsed=false, wfInspCollapsed=false;
let wfActH=0;              // manual ceiling for the Activities list; 0 = CSS default
try{ wfActCollapsed=localStorage.getItem("wfActCollapsed")==="1"; }catch{}
function wfPersistPanelState(){
  try{ localStorage.setItem("wfActCollapsed", wfActCollapsed?"1":"0"); }catch{}
}
const wfSnap=v=> wfSnapOn ? Math.round(v/WF_GRID)*WF_GRID : Math.round(v);
function wfSaveSettings(){ try{ const lc=$("log-card"), sd=$("wf-side"), insp=$("wf-inspector");
  const logH = lc && !lc.classList.contains("collapsed") ? lc.offsetHeight : (lc && lc.dataset.openH ? parseInt(lc.dataset.openH,10) : undefined);
  const sideW=sd?(wfSideCollapsed?(parseInt(sd.dataset.openW,10)||272):sd.offsetWidth):undefined;
  const inspW=insp?(wfInspCollapsed?(parseInt(insp.dataset.openW,10)||304):insp.offsetWidth):undefined;
  api().save_settings({snap:wfSnapOn, snapMigrated:true, previewAll:wfPreviewAll, minimap:wfMinimapOn, alignGuides:wfAlignOn, previewHz: (typeof wfPvHz!=="undefined"?wfPvHz:undefined), logOpen: !(lc&&lc.classList.contains("collapsed")), logH: logH||undefined, sideW, inspW, actH: wfActH||null, sideCollapsed:wfSideCollapsed, inspCollapsed:wfInspCollapsed}); }catch{} }
function wfSyncToggleBtns(){
  // Icon buttons: state shows as colour (.on) + tooltip, never overwrite the SVG.
  const s=$("wf-snap-btn"); if(s){ s.title="Snap to grid: "+(wfSnapOn?"On":"Off")+" - Smart align overrides the grid only on matched axes (hold Alt for free placement)"; s.classList.toggle("on",wfSnapOn); }
  const p=$("wf-preview-btn"); if(p){ p.title="Image preview: "+(wfPreviewAll?"On":"Off"); p.classList.toggle("on",wfPreviewAll); }
  const a=$("wf-align-btn"); if(a){ a.title="Smart align: "+(wfAlignOn?"On":"Off")+" - edges, centres, and ports override grid snapping only when matched (hold Alt to pause both)"; a.classList.toggle("on",wfAlignOn); }
  const m=$("wf-minimap-btn"); if(m){ m.title="Minimap: "+(wfMinimapOn?"On":"Off")+" - bird's-eye view of the graph, click to jump the camera"; m.classList.toggle("on",wfMinimapOn); }
  if(typeof wfSyncLinkModeBtn==="function") wfSyncLinkModeBtn();
  if(typeof wfSyncFocusBtn==="function") wfSyncFocusBtn();
  if(typeof wfSyncDebugOverlayBtn==="function") wfSyncDebugOverlayBtn();
  wfSyncSpeedUI();
}
function wfToggleAlign(){
  wfAlignOn=!wfAlignOn; wfSyncToggleBtns(); wfSaveSettings();
  if(!wfAlignOn && typeof wfHideAlignGuides==="function") wfHideAlignGuides();
}
function wfToggleMinimap(){
  wfMinimapOn=!wfMinimapOn; wfSyncToggleBtns(); wfSaveSettings();
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();   // shows or hides on next frame
}
// ── Workflow package (ADB) — project-level; edited in Project settings popup ─
function wfPackageFromUI(){
  const el=$("wf-package"); if(!el) return;
  WF.package=(el.value||"").trim();
}
function wfSyncPackageUI(){
  const el=$("wf-package"); if(!el) return;
  if(document.activeElement!==el) el.value=WF.package||"";
}
// Best-effort package: workflow field, else the first "Launch app" node's package.
function wfAutoPackage(){
  const top=(WF.package||"").trim(); if(top) return top;
  const graphs=[...WF.activities.map(a=>a.graph), ...WF.functions.map(f=>f.graph)];
  for(const g of graphs){ for(const n of (g&&g.nodes||[])){
    if(n.type==="launch_app"){ const p=((n.params||{}).package||"").trim(); if(p) return p; } } }
  return "";
}

// ── Speed hack — a standalone manual tool, decoupled from "Test run" ────────
// The ⚡ toggle enables the feature (still saved into the flow for the Runner GUI)
// and reveals a separate ▶ button; pressing ▶ is what actually injects Frida here.
// Uses WF.package (workflow-level). ADB-only — hidden in Win32 mode.
let wfSpeedRunning=false;   // is the standalone injection currently on?
function wfSpeedPopToggle(e){
  if(e){ e.preventDefault(); e.stopPropagation(); }
  const pop=$("wf-speed-pop"); if(!pop) return;
  const open = pop.style.display==="none" || !pop.style.display;
  pop.style.display = open ? "flex" : "none";
  const cb=$("wf-speed-chip-btn"); if(cb) cb.setAttribute("aria-expanded", String(open));
}
function wfSpeedPopClose(){
  const pop=$("wf-speed-pop"); if(!pop || pop.style.display==="none" || !pop.style.display) return;
  pop.style.display="none";
  const cb=$("wf-speed-chip-btn"); if(cb) cb.setAttribute("aria-expanded","false");
}
function wfSyncSpeedUI(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0});
  const win32=(WF.controller==="win32");
  // Hide the entire speed-hack cluster in Win32 mode — no Frida, no cheat DLL.
  const grp=$("wf-speed-group");
  if(grp) grp.style.display = win32 ? "none" : "";
  if(win32){ wfSpeedPopClose(); return; }
  const b=$("wf-speed-btn");
  if(b){
    b.title = "Speed hack: "+(sh.enabled?"On":"Off")+" (accelerate the game with Frida - root required · set package in Project settings)";
    b.classList.toggle("on",sh.enabled);
    b.textContent = sh.enabled ? "Disable" : "Enable";
  }
  const chip=$("wf-speed-chip"); if(chip) chip.textContent=(sh.speed||1)+"×";
  const spState=$("wf-speed-state");
  if(spState){ spState.textContent = sh.enabled ? (wfSpeedRunning?"Live":"On") : "Off"; spState.classList.toggle("on", sh.enabled); }
  const v=$("wf-speed-val"); if(v && document.activeElement!==v) v.value=sh.speed;
  const nat=$("wf-speed-native");
  if(nat){
    nat.checked=!!sh.native;
    // Swapping the hook flavour needs a fresh injection, so lock it while live.
    nat.disabled=wfSpeedRunning;
  }
  if(grp) grp.classList.toggle("on", sh.enabled);
  const rb=$("wf-speed-run-btn");
  if(rb){
    rb.style.display = sh.enabled ? "inline-flex" : "none";
    rb.innerHTML = wfSpeedRunning ? WF_ICO_STOP : WF_ICO_PLAY;
    rb.title = wfSpeedRunning ? "Disable speed hack" : "Enable speed hack now (uses workflow package · independent of Test run)";
    rb.classList.toggle("ok", !wfSpeedRunning); rb.classList.toggle("err", wfSpeedRunning);
  }
}
function wfSpeedFromUI(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,native:false});
  const el=$("wf-speed-val");
  const v=el?parseFloat(el.value):sh.speed; sh.speed=(isNaN(v)||v<=0)?1:v;
  const nat=$("wf-speed-native"); if(nat) sh.native=!!nat.checked;
  wfPackageFromUI();
}
// Speed value edited: persist, and if the hack is live, push the new scale.
// Debounced: the number spinner fires change on every arrow click, and each call
// costs a round of adb work (and a full re-injection if the pipe went stale).
let wfSpeedPushT=null;
function wfSpeedChanged(){
  wfSpeedFromUI();
  wfSyncSpeedUI();
  if(!wfSpeedRunning) return;
  if(wfSpeedPushT) clearTimeout(wfSpeedPushT);
  wfSpeedPushT=setTimeout(()=>{
    wfSpeedPushT=null;
    const sh=WF.speedhack;
    api().speedhack_start(sh.speed, wfAutoPackage(), !!sh.native);
  }, 350);
}
function wfToggleSpeed(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,native:false});
  wfSpeedFromUI(); sh.enabled=!sh.enabled;
  if(!sh.enabled && wfSpeedRunning){ api().speedhack_stop(); wfSpeedRunning=false; }  // disabling stops it
  wfSyncSpeedUI();
}
// The ▶/⏹ button: actually inject (or stop) the speed hack, on its own.
// ADB-only (Frida). Win32 mode hides the whole cluster, so this never fires there.
async function wfSpeedRun(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0,native:false});
  wfSpeedFromUI();
  if(wfSpeedRunning){ await api().speedhack_stop(); return; }
  const pkg=wfAutoPackage();
  if(!pkg){ uiToast("Set the app package in Project settings (gear next to the title), or add a Launch app block.","warning"); return; }
  const ok=await api().speedhack_start(sh.speed, pkg, !!sh.native);
  if(!ok){ wfSpeedRunning=false; wfSyncSpeedUI(); }
}

// ── Project settings popup (package · controller · OCR · advanced Win32 target) ─
// Frequent Win32 target/input controls also stay visible beside the title.
let wfOcrBackendsCache=WF_OCR_MODELS.slice();
function wfSyncOcrUI(){
  const sel=$("wf-ocr-select"); if(sel) sel.value=wfNormalizeOcrBackend(WF.ocrBackend);
}
function wfOcrChanged(){
  const sel=$("wf-ocr-select");
  WF.ocrBackend=wfNormalizeOcrBackend(sel?sel.value:WF.ocrBackend);
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
  setStatus("OCR model: "+wfOcrModelLabel(WF.ocrBackend));
}
function wfFillOcrSelect(sel){
  if(!sel) return;
  const models=wfOcrBackendsCache&&wfOcrBackendsCache.length?wfOcrBackendsCache:WF_OCR_MODELS;
  sel.innerHTML="";
  models.forEach(model=>{ const id=typeof model==="string"?model:model.id; const o=document.createElement("option"); o.value=id; o.textContent=(typeof model==="string"?wfOcrModelLabel(id):model.label)||id; sel.appendChild(o); });
  sel.value=wfNormalizeOcrBackend(WF.ocrBackend);
}
// Cache backends from the host; fill the select if the settings form is open.
function wfPopulateOcrBackends(backs){
  if(backs&&backs.length) wfOcrBackendsCache=backs.slice();
  const sel=$("wf-ocr-select"); if(sel){ wfFillOcrSelect(sel); }
}
// ── Project controller (ADB vs Win32) ────────────────────────────────────────
const WF_WIN_MATCH_MODES=new Set(["title","class","pid","exe"]);
const WF_WIN_INPUT_MODES=new Set(["background","background_sync","background_cursor",
  "background_window","anchored_touch","unity_bridge","foreground"]);
function wfNormWinMatchBy(value){
  const mode=String(value||"").trim().toLowerCase();
  return WF_WIN_MATCH_MODES.has(mode)?mode:"title";
}
function wfNormWinInputMode(value){
  const mode=String(value||"").trim().toLowerCase();
  return WF_WIN_INPUT_MODES.has(mode)?mode:"background";
}
function wfSyncBackendChrome(){
  const isWin32=WF.controller==="win32";
  const adbTools=$("tb-adb-tools"), barTools=$("wf-bar-win32");
  if(adbTools) adbTools.style.display=isWin32?"none":"flex";
  if(barTools) barTools.style.display=isWin32?"inline-flex":"none";
  const cfg=WF.win32||{};
  const target=String(cfg.window||"").trim();
  const targetEl=$("wf-bar-win32-label");
  if(targetEl){ targetEl.textContent=target||"Choose window"; targetEl.title=target||"No fixed target - choose an open window"; }
  const dot=$("wf-bar-win32-dot"); if(dot) dot.classList.toggle("configured",!!target);
  const matchBy=wfNormWinMatchBy(cfg.matchBy);
  const matchEl=$("wf-bar-win32-matchby"); if(matchEl && document.activeElement!==matchEl) matchEl.value=matchBy;
  const mode=wfNormWinInputMode(cfg.inputMode);
  const modeEl=$("wf-bar-win32-mode"); if(modeEl && document.activeElement!==modeEl) modeEl.value=mode;
  const bridgeRow=$("wf-unity-bridge-row"); if(bridgeRow) bridgeRow.style.display=mode==="unity_bridge"?"":"none";
  const footerDeviceDot=$("footer-dot"); if(footerDeviceDot) footerDeviceDot.style.display=isWin32?"none":"";
  // Preview action testers: mouse button / wheel are Win32-only; the Android
  // keycode strip only makes sense for ADB (Win32 takes VK numbers).
  const show=(id,on)=>{ const el=$(id); if(el) el.style.display=on?"flex":"none"; };
  show("pv-win-click-row", isWin32);
  show("pv-win-wheel-row", isWin32);
  show("pv-key-strip-adb", !isWin32);
  show("pv-key-strip-win", isWin32);
  const keyInp=$("pv-key-custom");
  if(keyInp){
    keyInp.placeholder=isWin32?"VK number e.g. 13":"KEYCODE or number";
    keyInp.setAttribute("aria-label",isWin32?"Custom Windows virtual-key code":"Custom Android keycode");
  }
  // Device details and Android key tools do not apply to a Win32 capture.
  const deviceTab=document.querySelector('#pv-tabs-bar .tab-btn[data-tab="device"]');
  if(deviceTab) deviceTab.style.display=isWin32?"none":"";
  if(isWin32 && deviceTab&&deviceTab.classList.contains("active") && typeof pvSwitchTab==="function") pvSwitchTab("inspect");
}
function wfSyncControllerUI(){
  const sel=$("wf-controller"); if(sel) sel.value=WF.controller||"adb";
  const w=WF.win32||(WF.win32={window:"",matchBy:"title",inputMode:"background"});
  const win32=(WF.controller==="win32");
  const adbSec=$("wf-proj-adb-sec"); if(adbSec) adbSec.style.display=win32?"none":"";
  const winSec=$("wf-proj-win32-sec"); if(winSec) winSec.style.display=win32?"":"none";
  const win=$("wf-win32-window"); if(win && document.activeElement!==win) win.value=w.window||"";
  const gp=$("wf-win32-path"); if(gp && document.activeElement!==gp) gp.value=w.path||"";
  const mb=$("wf-win32-matchby"); if(mb) mb.value=wfNormWinMatchBy(w.matchBy);
  const md=$("wf-win32-mode"); if(md) md.value=wfNormWinInputMode(w.inputMode);
  // A project created by the Hub can already be on the bridge without ever
  // passing through a change handler — offer the deploy here too.
  wfWinInputModeSwitched(null, wfNormWinInputMode(w.inputMode));
  const inSel=$("wf-input-select");
  if(inSel && document.activeElement!==inSel) inSel.value=(WF.inputBackend==="scrcpy")?"scrcpy":"adb";
  wfSyncPackageUI();
  wfSyncSpeedUI();   // speed-hack visibility depends on the controller
  wfSyncBackendChrome();
  wfPushCaptureSource();
}
// Tell the Python side which source the Preview tab should capture from, so the
// preview/crop/colour-inspect follow the project's controller (ADB vs Win32).
function wfPushCaptureSource(){
  try{ api().set_capture_source(WF.controller||"adb", WF.win32||{}); }catch{}
}
function wfControllerChanged(){
  const sel=$("wf-controller");
  WF.controller=(sel&&sel.value==="win32")?"win32":"adb";
  wfSyncControllerUI();
  if(typeof wfRenderPalette==="function") wfRenderPalette();
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
}
// Window picker: a dropdown of currently-open windows so the user chooses the
// game window instead of typing its title. Reuses the .wf-varmenu styling.
let wfWinMenuEl=null;
function wfCloseWinMenu(){ if(wfWinMenuEl){ wfWinMenuEl.remove(); wfWinMenuEl=null; document.removeEventListener("mousedown",wfWinMenuOutside,true); } }
function wfWinMenuOutside(e){ if(wfWinMenuEl && !e.target.closest(".wf-varmenu") && !e.target.closest("#wf-win32-pick") && !e.target.closest("#wf-bar-win32-pick")) wfCloseWinMenu(); }
async function wfPickWindow(ev, source){
  if(ev) ev.stopPropagation();
  let wins=[]; try{ wins=await api().list_windows()||[]; }catch{}
  wfCloseWinMenu();
  const fromBar=source==="bar";
  const anchor=fromBar?$("wf-bar-win32-pick"):$("wf-win32-window"); if(!anchor) return;
  const menu=document.createElement("div"); menu.className="wf-varmenu";
  // Sit above the project-settings modal (--z-modal is 70).
  menu.style.zIndex="80";
  wfWinMenuEl=menu;
  const search=document.createElement("input"); search.type="text"; search.className="wf-varmenu-search";
  search.placeholder="Find window…"; search.spellcheck=false; search.autocomplete="off"; menu.appendChild(search);
  const list=document.createElement("div"); list.className="wf-varmenu-list"; menu.appendChild(list);
  function render(filter){
    list.innerHTML="";
    const f=(filter||"").trim().toLowerCase();
    const shown=wins.filter(w=>!f||w.title.toLowerCase().includes(f)||(w.cls||"").toLowerCase().includes(f)||String(w.pid||"").includes(f)||(w.exe||"").toLowerCase().includes(f));
    if(!shown.length){ const e=document.createElement("div"); e.className="wf-varmenu-empty"; e.textContent=wins.length?"No match.":"No windows found."; list.appendChild(e); return; }
    shown.forEach(w=>{
      const row=document.createElement("button"); row.type="button"; row.className="wf-varmenu-item";
      const meta=[w.exe||"", w.pid?("pid "+w.pid):"", w.cls||""].filter(Boolean).join(" · ");
      row.innerHTML=`<span class="vn">${escHtml(w.title)}</span><span class="vt">${escHtml(meta)}</span>`;
      row.title=`Title: ${w.title}\nEXE: ${w.exe||"?"}\nClass: ${w.cls||""}\nPID: ${w.pid||"?"}`;
      row.onclick=()=>{
        const cfg=WF.win32||(WF.win32={});
        const by=wfNormWinMatchBy(($("wf-win32-matchby")&&$("wf-win32-matchby").value)||cfg.matchBy);
        const value=(by==="pid") ? String(w.pid||"") : (by==="class") ? (w.cls||w.title) : (by==="exe") ? (w.exe||w.title) : w.title;
        if(fromBar){
          cfg.window=value; cfg.matchBy=by;
          const modalInput=$("wf-win32-window"); if(modalInput) modalInput.value=value;
          wfSyncBackendChrome(); wfPushCaptureSource();
          if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
        }else{
          anchor.value=value; wfWin32FromUI();
        }
        wfCloseWinMenu();
      };
      list.appendChild(row);
    });
  }
  render("");
  document.body.appendChild(menu);
  const trigger=fromBar?anchor:($("wf-win32-pick")||anchor);
  const r=trigger.getBoundingClientRect();
  const mw=Math.max(300, anchor.getBoundingClientRect().width||280);
  menu.style.width=mw+"px";
  let left=Math.min(r.left, window.innerWidth-mw-8);
  let top=r.bottom+4; if(top+300>window.innerHeight) top=Math.max(8, r.top-304);
  menu.style.left=Math.max(8,left)+"px"; menu.style.top=top+"px";
  search.oninput=()=>render(search.value);
  setTimeout(()=>{ search.focus(); document.addEventListener("mousedown",wfWinMenuOutside,true); },0);
}
function wfWin32FromUI(){
  const w=WF.win32||(WF.win32={});
  const win=$("wf-win32-window"), mb=$("wf-win32-matchby"), md=$("wf-win32-mode");
  const prevMode=wfNormWinInputMode(w.inputMode);
  if(win) w.window=(win.value||"").trim();
  if(mb) w.matchBy=wfNormWinMatchBy(mb.value);
  if(md) w.inputMode=wfNormWinInputMode(md.value);
  wfSyncBackendChrome();
  wfPushCaptureSource();
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
  wfWinInputModeSwitched(prevMode, w.inputMode);
}
// Project game path (win32.path). Launch program summaries follow it live; the
// undo snapshot + status line only on commit (change / picker).
function wfWin32PathSet(value, commit){
  const w=WF.win32||(WF.win32={});
  const next=String(value||"").trim();
  if(commit && next!==(w.path||"") && typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
  w.path=next;
  if(typeof wfRenderCanvas==="function") wfRenderCanvas();
  if(commit) setStatus(next?("Game path: "+next):"Game path cleared");
}
function wfBarWinMatchChanged(value){
  const w=WF.win32||(WF.win32={});
  w.matchBy=wfNormWinMatchBy(value);
  const modalMatch=$("wf-win32-matchby"); if(modalMatch) modalMatch.value=w.matchBy;
  wfSyncBackendChrome(); wfPushCaptureSource();
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
}
function wfBarWinInputChanged(value){
  const w=WF.win32||(WF.win32={});
  const prevMode=wfNormWinInputMode(w.inputMode);
  w.inputMode=wfNormWinInputMode(value);
  const modalMode=$("wf-win32-mode"); if(modalMode) modalMode.value=w.inputMode;
  wfSyncBackendChrome(); wfPushCaptureSource();
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
  wfWinInputModeSwitched(prevMode, w.inputMode);
}
// ── Unity Bridge: offer to deploy the in-game plugin when the mode is chosen ──
// The last mode this document was on, so a re-sync (which passes prev=null) can
// still tell a real switch — into the bridge, or already sitting on it — from a
// no-op. Kept here rather than at the call sites so every path stays in step.
let wfLastWinMode=null;
function wfWinInputModeSwitched(prev, next){
  const before=prev||wfLastWinMode;
  wfLastWinMode=next;
  if(next==="unity_bridge" && before!=="unity_bridge") wfOfferUnityBridgeDeploy();
}
let wfUnityBridgeBusy=false;
// opts.force: skip the "already running / already installed" shortcuts and
// always show the deploy dialog (the Project settings button).
async function wfOfferUnityBridgeDeploy(opts){
  opts=opts||{};
  if(wfUnityBridgeBusy) return;
  wfUnityBridgeBusy=true;
  try{
    const cfg=WF.win32||{};
    let st=null;
    try{ st=await api().unity_bridge_status(cfg, ""); }catch{}
    if(!opts.force && st && st.bridgeRunning){
      uiToast("Unity Bridge đang chạy trong game ("+st.bridge+")","success"); return;
    }
    if(!st || !st.exe){
      const pick=await uiConfirm({title:"Unity Bridge",
        message:"Chưa xác định được game từ cửa sổ mục tiêu (chưa chọn cửa sổ hoặc game chưa mở). Chọn file .exe của game Unity để triển khai plugin?",
        ok:"Chọn file exe…", cancel:"Để sau"});
      if(!pick) return;
      let exe="";
      try{ exe=await api().pick_file("")||""; }catch{}
      if(!exe) return;
      try{ st=await api().unity_bridge_status(cfg, exe); }catch{ st=null; }
      if(!st){ uiToast("Không kiểm tra được game","error"); return; }
    }
    const list=items=>`<ul style="margin:8px 0 8px 18px">${items.map(s=>`<li>${escHtml(s)}</li>`).join("")}</ul>`;
    if(st.problems && st.problems.length){
      await uiModal({title:"Không thể triển khai Unity Bridge",
        body:`<div class="ui-modal-msg">${escHtml(st.exe||"")}</div>`+list(st.problems),
        buttons:[{label:"OK", value:true, kind:"accent"}]});
      return;
    }
    const steps=[
      "Không copy file nào vào thư mục game - Macro2k nạp Macro2kBridge thẳng vào tiến trình game đang chạy"
      +(st.backend==="IL2CPP" ? " (DLL native, LoadLibrary)" : " (DLL managed, qua Mono runtime)"),
      "Tự nạp lại mỗi khi workflow gắn vào game (không cần thao tác lại sau khi restart game)",
    ];
    if(st.legacyBepinex) steps.push("Dọn các file BepInEx cũ còn sót trong thư mục game (từ bản Macro2k trước)");
    if(st.bridgeRunning) steps.push("Bridge đang chạy: "+st.bridge);
    const ok=await uiModal({title:"Triển khai Unity Bridge?",
      body:`<div class="ui-modal-msg">Game: <b>${escHtml(st.gameDir||"")}</b><br>Unity ${escHtml(st.backend||"")} · ${escHtml(st.arch||"?")}</div>`+
        list(steps)+
        `<div class="ui-modal-msg" style="opacity:.75">Plugin chạy trong game và nhận lệnh tap/swipe qua 127.0.0.1:${escHtml(String(st.port||17820))}. `+
        `Cần game đang mở để nạp được ngay; nếu chưa mở, Macro2k sẽ tự nạp khi workflow gắn vào game. `+
        `Game online có anti-cheat có thể phát hiện việc nạp DLL - tự cân nhắc rủi ro.</div>`,
      buttons:[{label:"Để sau", value:false}, {label:"Triển khai", value:true, kind:"accent"}]});
    if(!ok) return;
    let res=null;
    try{ res=await api().unity_bridge_deploy(st.exe); }catch(e){ res={ok:false, error:String(e)}; }
    if(res && res.ok){
      uiToast(res.injected ? "Đã nạp Unity Bridge vào game đang chạy"
                           : "Unity Bridge sẽ được nạp khi workflow gắn vào game - hãy mở game trước","success",{dur:6000});
      setStatus("Unity Bridge: "+(res.actions||[]).join(" · "));
    }else{
      uiToast("Triển khai thất bại: "+((res&&res.error)||"unknown"),"error",{dur:8000});
    }
  }finally{
    wfUnityBridgeBusy=false;
  }
}

// Open the project settings dialog (gear left of the title).
function wfOpenProjectSettings(){
  if(typeof uiModal!=="function") return;
  return uiModal({
    title:"Project settings",
    width:"440px",
    body:(bd)=>{
      const form=document.createElement("div"); form.className="wf-proj-form";

      // ── Controller ────────────────────────────────────────────────────────
      const secCtrl=document.createElement("div"); secCtrl.className="wf-proj-sec";
      secCtrl.innerHTML=`<div class="wf-proj-sec-lbl">Controller</div>`;
      const rowCtrl=document.createElement("div"); rowCtrl.className="wf-proj-row";
      rowCtrl.innerHTML=
        `<label for="wf-controller">Project type</label>`+
        `<select id="wf-controller" title="ADB device/emulator or Win32 PC window">`+
          `<option value="adb">ADB - Android device / emulator</option>`+
          `<option value="win32">Win32 - PC program window</option>`+
        `</select>`+
        `<div class="hint">Chooses capture + input backend for the whole workflow.</div>`;
      secCtrl.appendChild(rowCtrl);
      form.appendChild(secCtrl);

      // ── ADB package ───────────────────────────────────────────────────────
      const secAdb=document.createElement("div"); secAdb.className="wf-proj-sec"; secAdb.id="wf-proj-adb-sec";
      secAdb.innerHTML=`<div class="wf-proj-sec-lbl">Android package</div>`;
      const rowPkg=document.createElement("div"); rowPkg.className="wf-proj-row";
      rowPkg.innerHTML=
        `<label for="wf-package">Package name</label>`+
        `<input id="wf-package" class="mono" type="text" placeholder="com.game.package" spellcheck="false" autocomplete="off" title="Target Android package">`+
        `<div class="hint">Used by speed hack and as a default for Launch / Stop app blocks.</div>`;
      secAdb.appendChild(rowPkg);
      const rowInput=document.createElement("div"); rowInput.className="wf-proj-row";
      rowInput.innerHTML=
        `<label for="wf-input-select">Input method</label>`+
        `<select id="wf-input-select" title="How taps/swipes reach the device">`+
          `<option value="adb">ADB shell - compatible</option>`+
          `<option value="scrcpy">scrcpy control - fast</option>`+
        `</select>`+
        `<div class="hint">scrcpy control injects input over the existing mirror socket (much lower latency); falls back to ADB shell automatically.</div>`;
      secAdb.appendChild(rowInput);
      // Shared emulator choice — the ADB equivalent of the Win32 game path.
      // Launch / Resize / Kill / Restart emulator blocks use this by default;
      // a block can opt out with its own Emulator = Custom.
      const rowEmuKind=document.createElement("div"); rowEmuKind.className="wf-proj-row";
      rowEmuKind.innerHTML=
        `<label for="wf-emulator-kind">Emulator</label>`+
        `<select id="wf-emulator-kind" title="Emulator family used by emulator blocks set to “Project emulator setting”">`+
          `<option value="ldplayer">LDPlayer</option>`+
          `<option value="mumu">MuMu</option>`+
          `<option value="nox">Nox</option>`+
          `<option value="memu">MEmu</option>`+
          `<option value="bluestacks">BlueStacks</option>`+
        `</select>`+
        `<div class="hint">Shared by Launch / Resize / Kill / Restart emulator blocks unless a block chooses “Custom”.</div>`;
      secAdb.appendChild(rowEmuKind);
      const rowEmuPath=document.createElement("div"); rowEmuPath.className="wf-proj-row";
      rowEmuPath.innerHTML=
        `<label for="wf-emulator-path">Install folder</label>`+
        `<div class="wf-proj-inline">`+
          `<input id="wf-emulator-path" class="mono" type="text" placeholder="C:\\LDPlayer\\LDPlayer9" spellcheck="false" autocomplete="off">`+
          `<button type="button" class="btn sm ico" id="wf-emulator-path-pick" title="Choose the emulator install folder" aria-label="Choose the emulator install folder">${wfIco("folder")}</button>`+
        `</div>`+
        `<div class="hint">Used by emulator blocks set to “Project emulator setting”. Players can re-point it in the Runner's Settings tab.</div>`;
      secAdb.appendChild(rowEmuPath);
      form.appendChild(secAdb);

      // ── Win32 target ──────────────────────────────────────────────────────
      const secWin=document.createElement("div"); secWin.className="wf-proj-sec"; secWin.id="wf-proj-win32-sec";
      secWin.style.display="none";
      secWin.innerHTML=`<div class="wf-proj-sec-lbl">Win32 game</div>`;
      const rowPath=document.createElement("div"); rowPath.className="wf-proj-row";
      rowPath.innerHTML=
        `<label for="wf-win32-path">Game path (.exe)</label>`+
        `<div class="wf-proj-inline">`+
          `<input id="wf-win32-path" class="mono" type="text" placeholder="C:\\Games\\MyGame\\Game.exe" spellcheck="false" autocomplete="off">`+
          `<button type="button" class="btn sm ico" id="wf-win32-path-pick" title="Choose the game .exe" aria-label="Choose the game .exe">${wfIco("folder")}</button>`+
        `</div>`+
        `<div class="hint">Used by Launch program blocks set to “Project game path”. Players can re-point it in the Runner's Settings tab.</div>`;
      secWin.appendChild(rowPath);
      const rowWin=document.createElement("div"); rowWin.className="wf-proj-row";
      rowWin.innerHTML=
        `<label for="wf-win32-window">Target window</label>`+
        `<div class="wf-proj-inline">`+
          `<input id="wf-win32-window" type="text" placeholder="Title, class, PID, or EXE (e.g. game.exe)" spellcheck="false" autocomplete="off">`+
          `<button type="button" class="btn sm ico" id="wf-win32-pick" title="Pick an open window">`+
            `<svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/></svg>`+
          `</button>`+
        `</div>`;
      secWin.appendChild(rowWin);
      const rowWinOpts=document.createElement("div"); rowWinOpts.className="wf-proj-grid2";
      rowWinOpts.innerHTML=
        `<div class="wf-proj-row">`+
          `<label for="wf-win32-matchby">Match by</label>`+
          `<select id="wf-win32-matchby"><option value="title">Title</option><option value="class">Class</option><option value="pid">PID</option><option value="exe">Name / EXE</option></select>`+
        `</div>`+
        `<div class="wf-proj-row">`+
          `<label for="wf-win32-mode">Input mode</label>`+
          `<select id="wf-win32-mode" title="How input is delivered to the window">`+
            `<option value="background">Background - PostMessage</option>`+
            `<option value="background_sync">Background sync - SendMessage</option>`+
            `<option value="background_cursor">Background + cursor - Unity / Unreal</option>`+
            `<option value="background_window">Window-pos - no cursor move</option>`+
            `<option value="anchored_touch">Anchored touch - WM_POINTER</option>`+
            `<option value="unity_bridge">Unity bridge - in-game plugin</option>`+
            `<option value="foreground">Foreground - real mouse</option>`+
          `</select>`+
        `</div>`+
        `<div class="wf-proj-row" id="wf-unity-bridge-row" style="display:none">`+
          `<label for="wf-unity-bridge-deploy">Unity Bridge</label>`+
          `<button type="button" class="btn" id="wf-unity-bridge-deploy" title="Check the in-game plugin and deploy BepInEx + Macro2kBridge into the game folder">Kiểm tra / triển khai…</button>`+
        `</div>`;
      secWin.appendChild(rowWinOpts);
      form.appendChild(secWin);

      // ── OCR ───────────────────────────────────────────────────────────────
      const secOcr=document.createElement("div"); secOcr.className="wf-proj-sec";
      secOcr.innerHTML=`<div class="wf-proj-sec-lbl">OCR</div>`;
      const rowOcr=document.createElement("div"); rowOcr.className="wf-proj-row";
      rowOcr.innerHTML=
        `<label for="wf-ocr-select">Text model</label>`+
        `<select id="wf-ocr-select" title="Recognition model for Wait text / If text / Read → variable / Parse"></select>`+
        `<div class="hint">Auto = first available backend. Saved into the workflow JSON.</div>`;
      secOcr.appendChild(rowOcr);
      form.appendChild(secOcr);

      // ── Appearance ────────────────────────────────────────────────────────
      const secApp=document.createElement("div"); secApp.className="wf-proj-sec";
      secApp.innerHTML=`<div class="wf-proj-sec-lbl">Appearance</div>`;
      const rowApp=document.createElement("div"); rowApp.className="wf-proj-grid2";
      rowApp.innerHTML=
        `<div class="wf-proj-row">`+
          `<label for="wf-theme">Theme</label>`+
          `<select id="wf-theme"><option value="light">Light</option><option value="dark">Dark</option></select>`+
        `</div>`+
        `<div class="wf-proj-row">`+
          `<label for="wf-density">Density</label>`+
          `<select id="wf-density"><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select>`+
        `</div>`;
      secApp.appendChild(rowApp);
      form.appendChild(secApp);

      bd.appendChild(form);
      // Query inside `form` — the modal is not in document yet during body().
      const q=(id)=>form.querySelector("#"+id);

      // Wire events + seed values. Prefer live `input` so closing without blur
      // still keeps the latest package / window text (modal DOM is destroyed on close).
      const ctrl=q("wf-controller"); if(ctrl) ctrl.onchange=()=>wfControllerChanged();
      const pkg=q("wf-package");
      if(pkg){
        pkg.addEventListener("input",()=>{
          WF.package=(pkg.value||"").trim();
          // Node summaries that use Project package refresh live.
          if(typeof wfRenderCanvas==="function") wfRenderCanvas();
        });
        pkg.addEventListener("change",()=>{ if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced(); setStatus(WF.package?("Package: "+WF.package):"Package cleared"); });
      }
      const ocr=q("wf-ocr-select"); if(ocr){ wfFillOcrSelect(ocr); ocr.onchange=()=>wfOcrChanged(); }
      const inSel=q("wf-input-select");
      if(inSel) inSel.onchange=()=>{ if(typeof onInputBackendChange==="function") onInputBackendChange(inSel.value); };
      const emuKind=q("wf-emulator-kind"), emuPath=q("wf-emulator-path");
      const emuSet=(patch)=>{ WF.emulator=Object.assign({kind:"ldplayer",path:""},WF.emulator,patch); };
      if(emuKind) emuKind.onchange=()=>{ emuSet({kind:emuKind.value}); if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced(); setStatus("Emulator: "+(emuKind.options[emuKind.selectedIndex]||{}).text); };
      if(emuPath){
        emuPath.addEventListener("input",()=>emuSet({path:(emuPath.value||"").trim()}));
        emuPath.addEventListener("change",()=>{ if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced(); });
      }
      const emuPick=q("wf-emulator-path-pick");
      if(emuPick) emuPick.onclick=async()=>{
        let p=""; try{ p=await api().pick_folder(emuPath?emuPath.value:""); }catch{}
        if(p){ if(emuPath) emuPath.value=p; emuSet({path:p}); if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced(); }
      };
      const winEl=q("wf-win32-window");
      if(winEl){
        winEl.addEventListener("input",()=>{ const w=WF.win32||(WF.win32={}); w.window=(winEl.value||"").trim(); });
        winEl.addEventListener("change",()=>wfWin32FromUI());
      }
      const pathEl=q("wf-win32-path");
      if(pathEl){
        pathEl.addEventListener("input",()=>wfWin32PathSet(pathEl.value,false));
        pathEl.addEventListener("change",()=>wfWin32PathSet(pathEl.value,true));
      }
      const pathPick=q("wf-win32-path-pick");
      if(pathPick) pathPick.onclick=async()=>{
        let p=""; try{ p=await api().pick_file(pathEl?pathEl.value:""); }catch{}
        if(p){ if(pathEl) pathEl.value=p; wfWin32PathSet(p,true); }
      };
      const mb=q("wf-win32-matchby"); if(mb) mb.onchange=()=>wfWin32FromUI();
      const md=q("wf-win32-mode"); if(md) md.onchange=()=>wfWin32FromUI();
      const pick=q("wf-win32-pick"); if(pick) pick.onclick=(e)=>wfPickWindow(e);
      const bridgeBtn=q("wf-unity-bridge-deploy"); if(bridgeBtn) bridgeBtn.onclick=()=>wfOfferUnityBridgeDeploy({force:true});

      // Appearance — applies immediately and persists via shared/theme.js.
      const thSel=q("wf-theme"), dSel=q("wf-density");
      const curT=(window.uiTheme&&window.uiTheme.current())||{theme:"light",density:"comfortable"};
      if(thSel){ thSel.value=curT.theme; thSel.onchange=()=>window.uiTheme&&window.uiTheme.setTheme(thSel.value); }
      if(dSel){ dSel.value=curT.density; dSel.onchange=()=>window.uiTheme&&window.uiTheme.setDensity(dSel.value); }

      // Seed values immediately (form not in document yet — don't rely on $()).
      if(ctrl) ctrl.value=WF.controller||"adb";
      if(pkg) pkg.value=WF.package||"";
      const w=WF.win32||{};
      if(winEl) winEl.value=w.window||"";
      if(pathEl) pathEl.value=w.path||"";
      if(mb) mb.value=wfNormWinMatchBy(w.matchBy);
      if(md) md.value=wfNormWinInputMode(w.inputMode);
      if(inSel) inSel.value=(WF.inputBackend==="scrcpy")?"scrcpy":"adb";
      const emuSeed=(WF.emulator||{});
      if(emuKind) emuKind.value=emuSeed.kind||"ldplayer";
      if(emuPath) emuPath.value=emuSeed.path||"";
      const win32=(WF.controller==="win32");
      const adbSec=q("wf-proj-adb-sec"); if(adbSec) adbSec.style.display=win32?"none":"";
      const winSec=q("wf-proj-win32-sec"); if(winSec) winSec.style.display=win32?"":"none";

      // After mount, refresh helpers that also touch speed-hack / capture source.
      setTimeout(()=>{ wfSyncControllerUI(); },0);
    },
    buttons:[{label:"Done", value:true, kind:"accent"}],
  }).then(()=>{
    wfCloseWinMenu();
    if(typeof wfPushCaptureSource==="function") wfPushCaptureSource();
    wfSyncSpeedUI();
  });
}
function wfToggleSnap(){ wfSnapOn=!wfSnapOn; wfSyncToggleBtns(); wfSaveSettings(); }
function wfTogglePreview(){ wfPreviewAll=!wfPreviewAll; wfSyncToggleBtns(); wfRenderCanvas(); wfSaveSettings(); }
let wfRunning=false;
let wfPan={x:0,y:0};
let wfZoom=1;           // canvas zoom factor
// The dot grid is painted on #wf-canvas (outside the transformed world), so it
// must be re-synced to the camera by hand: position follows the pan, spacing
// AND dot radius scale with the zoom — the grid is locked to the world instead
// of sliding beneath it. Below ~55% the fine 20px layer drops out so a zoomed-
// out graph sits on a calm 100px anchor grid instead of dot noise.
// Snap a CSS length to the nearest device pixel so compositor layers stay sharp.
// Fractional translate/scale is the usual reason nodes look soft/blurry in
// Chromium/WebView2 (especially on 125%/150% Windows display scaling).
function wfCrispPx(v){
  const dpr=window.devicePixelRatio||1;
  return Math.round(Number(v)*dpr)/dpr;
}
function wfSyncGrid(){
  const c=$("wf-canvas"); if(!c) return;
  const z=wfZoom;
  const px=wfCrispPx(wfPan.x), py=wfCrispPx(wfPan.y);
  // Read the dot color from CSS so the grid follows the active theme.
  const cs=getComputedStyle(c);
  const dotMajor=(cs.getPropertyValue("--grid-dot")||"rgba(20,30,45,.10)").trim();
  const dotMinor=(cs.getPropertyValue("--grid-dot-minor")||"#d9dee6").trim();
  // A radial-gradient paints its dot at the CENTRE of each background tile by
  // default, so the grid dots sat half a cell off from the world's (0,0) — a
  // node corner snapped to x=0 floated between dots. Position each layer at
  // its top-left corner (and off by half a dot so the ink centres exactly on
  // the grid line), and start the tile pattern half a cell back so tile 0's
  // corner — where world origin and node corners live — gets the dot.
  const halfDot=1.6*z;
  const pos=[`${wfCrispPx(px-halfDot)}px ${wfCrispPx(py-halfDot)}px`,
             `${wfCrispPx(px-halfDot-10*z)}px ${wfCrispPx(py-halfDot-10*z)}px`];
  const layers=[`radial-gradient(circle at 0 0, ${dotMajor} ${(1.4*z).toFixed(2)}px, transparent ${(1.6*z).toFixed(2)}px)`];
  const sizes=[`${100*z}px ${100*z}px`];
  if(z>=0.55){
    const r=Math.max(.8, z);
    layers.push(`radial-gradient(circle at 0 0, ${dotMinor} ${r.toFixed(2)}px, transparent ${(r+.2).toFixed(2)}px)`);
    sizes.push(`${20*z}px ${20*z}px`);
  }
  c.style.backgroundImage=layers.join(",");
  c.style.backgroundSize=sizes.join(",");
  c.style.backgroundPosition=pos.join(",");
}
// Temporarily promote #wf-world to a compositor layer while the camera is in
// motion (tween / wheel burst), then demote it once it settles. A promoted
// layer keeps its old raster and just GPU-stretches the texture, so leaving
// will-change:transform on permanently is exactly what makes every node blurry
// at any zoom ≠ 100% (and randomly sharp again after unrelated repaints).
// Demoting forces a re-raster at the final scale → crisp at every zoom level.
let wfWorldHintT=null;
function wfWorldMotionHint(){
  const w=$("wf-world"); if(!w) return;
  w.style.willChange="transform";
  clearTimeout(wfWorldHintT);
  wfWorldHintT=setTimeout(()=>{ w.style.willChange="auto"; wfWorldHintT=null; },160);
}
function wfApplyTransform(){
  const w=$("wf-world"); if(!w) return;
  // Collapse near-100% zoom to exactly 1 — scale(0.99…1.01) is the worst blur
  // case (GPU bilinear filter on text) for almost no visual change.
  if(Math.abs(wfZoom-1)<0.008) wfZoom=1;
  // Keep pan on device-pixel boundaries so the layer isn't half-pixel blurred.
  wfPan.x=wfCrispPx(wfPan.x);
  wfPan.y=wfCrispPx(wfPan.y);
  // Pan via left/top (layout, not compositor translate) and only apply scale()
  // when zoom ≠ 100%. will-change is handled by wfWorldMotionHint — never set
  // permanently here (see comment above).
  w.style.left=wfPan.x+"px";
  w.style.top=wfPan.y+"px";
  w.style.transform = wfZoom===1 ? "none" : `scale(${wfZoom})`;
  wfSyncGrid();
  wfSyncLod();
  const connection=wfGesture?.connection || (wfGesture?.mode==="connect" ? wfGesture : null);
  if(connection && Number.isFinite(connection.mx)) wfDrawTempWire(connection.mx,connection.my);
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();
  const lbl=$("wf-zoom-lbl"); if(lbl) lbl.textContent=Math.round(wfZoom*100)+"%";
  wfSyncZoomBadge();
}
// Corner readout of the graph zoom (top-right of the canvas). Accent-coloured
// whenever the view is not at 100%.
function wfSyncZoomBadge(){
  const b=$("wf-zoom-badge"); if(!b) return;
  const pct=Math.round(wfZoom*100);
  b.textContent=pct+"%";
  b.classList.toggle("zoomed",pct!==100);
  b.title=pct===100?"Zoom 100%":`Zoom ${pct}% - click or double-tap Space to reset to 100%`;
}
// Level of detail. Zoomed out far enough, 9px slot labels, flow markers and
// timing chips stop being information and turn into speckle — the same call
// every node editor makes. Two steps: "far" drops the fine print, "tiny" leaves
// blocks as coloured plates you navigate by shape. Driven by a data attribute
// so the whole decision lives in CSS next to the styles it turns off.
const WF_LOD_FAR=0.65, WF_LOD_TINY=0.45;
function wfSyncLod(){
  const c=$("wf-canvas"); if(!c) return;
  const lod = wfZoom<WF_LOD_TINY ? "tiny" : wfZoom<WF_LOD_FAR ? "far" : "near";
  if(c.dataset.lod!==lod) c.dataset.lod=lod;
}
// ── Camera animation ─────────────────────────────────────────────────────────
// One shared tween for every programmatic camera move (fit view, zoom buttons,
// centre-on-node, focus-follow): ease-out-quart over ~250ms so the graph glides
// instead of teleporting. Direct manipulation (wheel, drag-pan) stays instant
// and cancels any tween in flight. Reduced motion → jump cut.
let wfCamAnim=null;
function wfCancelCamAnim(){ if(wfCamAnim){ cancelAnimationFrame(wfCamAnim); wfCamAnim=null; } }
function wfAnimateCamera(tx,ty,tz,ms){
  wfCancelCamAnim();
  ms=ms===undefined?250:ms;
  const reduce=window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Snap the destination so the settle frame is crisp (not left mid-subpixel).
  if(Math.abs(tz-1)<0.008) tz=1;
  tx=wfCrispPx(tx); ty=wfCrispPx(ty);
  if(reduce||ms<=0){ wfPan.x=tx; wfPan.y=ty; wfZoom=tz; wfApplyTransform(); return; }
  const sx=wfPan.x, sy=wfPan.y, sz=wfZoom, t0=performance.now();
  const step=now=>{
    const t=Math.min(1,(now-t0)/ms), e=1-Math.pow(1-t,4);
    if(t>=1){ wfPan.x=tx; wfPan.y=ty; wfZoom=tz; }
    else { wfPan.x=sx+(tx-sx)*e; wfPan.y=sy+(ty-sy)*e; wfZoom=sz+(tz-sz)*e; }
    wfWorldMotionHint();
    wfApplyTransform();
    wfCamAnim = t<1 ? requestAnimationFrame(step) : null;
  };
  wfCamAnim=requestAnimationFrame(step);
}
function wfSetZoom(z, cx, cy){
  wfCancelCamAnim();
  z=Math.max(0.3, Math.min(2.5, z));
  if(Math.abs(z-1)<0.008) z=1;
  const canvas=$("wf-canvas"); if(!canvas) { wfZoom=z; wfApplyTransform(); return; }
  // Keep the point (cx,cy) — relative to the canvas — fixed while zooming.
  if(cx===undefined){ const r=canvas.getBoundingClientRect(); cx=r.width/2; cy=r.height/2; }
  const wx=(cx-wfPan.x)/wfZoom, wy=(cy-wfPan.y)/wfZoom;
  wfZoom=z;
  wfPan.x=cx-wx*wfZoom; wfPan.y=cy-wy*wfZoom;
  wfWorldMotionHint();
  wfApplyTransform();
  const lbl=$("wf-zoom-lbl"); if(lbl) lbl.textContent=Math.round(wfZoom*100)+"%";
}
// Zoom buttons / shortcuts glide around the canvas centre.
function wfZoomBy(f){
  const c=$("wf-canvas"); if(!c){ wfSetZoom(wfZoom*f); return; }
  const z=Math.max(0.3, Math.min(2.5, wfZoom*f));
  const cx=c.clientWidth/2, cy=c.clientHeight/2;
  const wx=(cx-wfPan.x)/wfZoom, wy=(cy-wfPan.y)/wfZoom;
  wfAnimateCamera(cx-wx*z, cy-wy*z, z, 140);
}
function wfZoomReset(){
  const c=$("wf-canvas"); if(!c){ wfSetZoom(1); return; }
  const cx=c.clientWidth/2, cy=c.clientHeight/2;
  const wx=(cx-wfPan.x)/wfZoom, wy=(cy-wfPan.y)/wfZoom;
  wfAnimateCamera(cx-wx, cy-wy, 1, 200);
}
function wfSidebarLayoutChanged(){
  requestAnimationFrame(()=>{
    if(typeof wfDrawWires==="function") wfDrawWires();
    if(typeof wfMinimapQueue==="function") wfMinimapQueue();
    if(typeof wfPvResize==="function" && typeof wfPvActive!=="undefined" && wfPvActive) wfPvResize();
  });
}
function wfApplySidebarState(save){
  const view=$("workflow-view"), side=$("wf-side"), insp=$("wf-inspector");
  if(!view) return;
  view.classList.toggle("wf-left-collapsed",wfSideCollapsed);
  view.classList.toggle("wf-right-collapsed",wfInspCollapsed);
  const leftBtn=$("wf-side-toggle"), rightBtn=$("wf-insp-toggle");
  if(leftBtn){
    leftBtn.title=wfSideCollapsed?"Expand node sidebar":"Collapse node sidebar";
    leftBtn.setAttribute("aria-label",leftBtn.title);
    leftBtn.setAttribute("aria-expanded",String(!wfSideCollapsed));
  }
  if(rightBtn){
    rightBtn.title=wfInspCollapsed?"Expand properties sidebar":"Collapse properties sidebar";
    rightBtn.setAttribute("aria-label",rightBtn.title);
    rightBtn.setAttribute("aria-expanded",String(!wfInspCollapsed));
  }
  if(side&&!wfSideCollapsed&&side.dataset.openW) side.style.width=side.dataset.openW+"px";
  if(insp&&!wfInspCollapsed&&insp.dataset.openW) insp.style.width=insp.dataset.openW+"px";
  wfSidebarLayoutChanged();
  if(save!==false) wfSaveSettings();
}
function wfToggleSidebar(which){
  const side=$("wf-side"), insp=$("wf-inspector");
  if(which==="left"){
    if(!wfSideCollapsed&&side) side.dataset.openW=String(side.offsetWidth);
    wfSideCollapsed=!wfSideCollapsed;
  }else{
    if(!wfInspCollapsed&&insp) insp.dataset.openW=String(insp.offsetWidth);
    wfInspCollapsed=!wfInspCollapsed;
  }
  wfApplySidebarState(true);
}
// Drag-to-resize the left sidebar; width persists in settings.
function wfInitSideResizer(){
  const side=$("wf-side"), rez=$("wf-side-resizer"); if(!side||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  const setW=w=>{ w=Math.max(220,Math.min(480,w)); side.style.width=w+"px"; side.dataset.openW=String(w); rez.setAttribute("aria-valuenow",String(Math.round(w))); };
  setW(side.offsetWidth);
  rez.addEventListener("mousedown",e=>{ if(e.target.closest(".wf-sidebar-toggle")||wfSideCollapsed) return; e.preventDefault(); drag={x:e.clientX, w:side.offsetWidth}; rez.classList.add("drag"); document.body.style.cursor="col-resize"; });
  rez.addEventListener("keydown",e=>{ if(!["ArrowLeft","ArrowRight"].includes(e.key)||wfSideCollapsed) return; e.preventDefault(); setW(side.offsetWidth+(e.key==="ArrowRight"?10:-10)); wfSaveSettings(); });
  window.addEventListener("mousemove",e=>{ if(!drag) return; setW(drag.w+(e.clientX-drag.x)); });
  window.addEventListener("mouseup",()=>{ if(!drag) return; drag=null; rez.classList.remove("drag"); document.body.style.cursor=""; wfSaveSettings(); });
}
// Drag-to-resize the right inspector; width persists in settings.
function wfInitInspResizer(){
  const insp=$("wf-inspector"), rez=$("wf-insp-resizer"); if(!insp||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  const setW=w=>{ w=Math.max(240,Math.min(520,w)); insp.style.width=w+"px"; insp.dataset.openW=String(w); rez.setAttribute("aria-valuenow",String(Math.round(w))); };
  setW(insp.offsetWidth);
  rez.addEventListener("mousedown",e=>{ if(e.target.closest(".wf-sidebar-toggle")||wfInspCollapsed) return; e.preventDefault(); drag={x:e.clientX, w:insp.offsetWidth}; rez.classList.add("drag"); document.body.style.cursor="col-resize"; });
  rez.addEventListener("keydown",e=>{ if(!["ArrowLeft","ArrowRight"].includes(e.key)||wfInspCollapsed) return; e.preventDefault(); setW(insp.offsetWidth+(e.key==="ArrowLeft"?10:-10)); wfSaveSettings(); });
  window.addEventListener("mousemove",e=>{ if(!drag) return; setW(drag.w-(e.clientX-drag.x)); });
  window.addEventListener("mouseup",()=>{ if(!drag) return; drag=null; rez.classList.remove("drag"); document.body.style.cursor=""; wfSaveSettings(); });
}
// Drag-to-resize the bottom log drawer; height persists in settings.
function wfInitLogResizer(){
  const card=$("log-card"), rez=$("log-resizer"); if(!card||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  const clampH=h=>Math.max(80, Math.min(Math.floor(window.innerHeight*0.55), Math.min(480, h)));
  const setH=h=>{ h=clampH(h); card.style.height=h+"px"; card.dataset.openH=String(h); rez.setAttribute("aria-valuenow",String(Math.round(h))); };
  setH(card.offsetHeight);
  rez.addEventListener("keydown",e=>{ if(!["ArrowUp","ArrowDown"].includes(e.key)||card.classList.contains("collapsed")) return; e.preventDefault(); setH(card.offsetHeight+(e.key==="ArrowUp"?10:-10)); wfSaveSettings(); });
  rez.addEventListener("mousedown",e=>{
    e.preventDefault(); e.stopPropagation();
    if(card.classList.contains("collapsed")) return;
    drag={y:e.clientY, h:card.offsetHeight};
    card.classList.add("resizing");
    rez.classList.add("drag");
    document.body.style.cursor="row-resize";
  });
  window.addEventListener("mousemove",e=>{
    if(!drag) return;
    // Dragging the top edge up increases height.
    setH(drag.h-(e.clientY-drag.y));
  });
  window.addEventListener("mouseup",()=>{
    if(!drag) return;
    drag=null;
    card.classList.remove("resizing");
    rez.classList.remove("drag");
    document.body.style.cursor="";
    if(!card.classList.contains("collapsed")) card.dataset.openH=String(card.offsetHeight);
    wfSaveSettings();
  });
}
// Drag-to-resize the floating Activities list; height persists in settings.
// The card is pinned to the canvas' bottom-right corner, so the handle on its
// top edge grows the list upwards. A drag pins an exact height (--act-h, 1:1
// with the pointer even when the list is shorter than the card); double-click
// clears it and the card goes back to hugging its rows up to seven.
function wfInitActResizer(){
  const panel=$("wf-act-panel"), body=$("wf-act-panel-body"), rez=$("wf-act-resizer");
  if(!panel||!body||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  // Room left in the canvas once the card's own chrome (header, tabs, borders)
  // and its 14px bottom inset plus the same gap above are accounted for.
  const maxH=()=>{
    const host=panel.offsetParent||$("wf-canvas");
    const avail=(host?host.clientHeight:window.innerHeight)-28-(panel.offsetHeight-body.offsetHeight);
    return Math.max(72, Math.min(600, avail));
  };
  const setH=h=>{
    h=Math.max(72, Math.min(maxH(), Math.round(h)));
    wfActH=h; panel.style.setProperty("--act-h", h+"px");
    rez.setAttribute("aria-valuenow",String(h));
    rez.setAttribute("aria-valuemax",String(Math.round(maxH())));
  };
  if(wfActH) setH(wfActH); else rez.setAttribute("aria-valuenow",String(body.offsetHeight));
  rez.addEventListener("mousedown",e=>{
    if(panel.classList.contains("collapsed")||panel.classList.contains("is-max")) return;
    e.preventDefault(); e.stopPropagation();
    // Seed from the rendered height so the first drag continues from what the
    // user sees, even before any height has been pinned.
    drag={y:e.clientY, h:body.offsetHeight};
    panel.classList.add("resizing"); rez.classList.add("drag");
    document.body.style.cursor="row-resize";
  });
  rez.addEventListener("keydown",e=>{
    if(!["ArrowUp","ArrowDown"].includes(e.key)) return;
    if(panel.classList.contains("collapsed")||panel.classList.contains("is-max")) return;
    e.preventDefault(); setH(body.offsetHeight+(e.key==="ArrowUp"?16:-16)); wfSaveSettings();
  });
  // Double-click clears the pinned height: back to hugging the rows, capped at seven.
  rez.addEventListener("dblclick",e=>{
    e.preventDefault(); wfActH=0; panel.style.removeProperty("--act-h");
    rez.setAttribute("aria-valuenow",String(body.offsetHeight)); wfSaveSettings();
  });
  window.addEventListener("mousemove",e=>{ if(!drag) return; setH(drag.h-(e.clientY-drag.y)); });
  window.addEventListener("mouseup",()=>{
    if(!drag) return;
    drag=null; panel.classList.remove("resizing"); rez.classList.remove("drag");
    document.body.style.cursor=""; wfSaveSettings();
  });
}
// Fit & center all blocks of the current graph into the canvas. Uses the live DOM
// node bounds (world coords), so it's exact regardless of node heights.
// Glides there by default; pass animate=false for an instant frame (the
// auto-layout pre-fit needs a stable camera before it animates the nodes).
function wfFit(animate, selectionOnly=false){
  const canvas=$("wf-canvas"); if(!canvas) return;
  const els=[...document.querySelectorAll("#wf-world .wf-node")]
    .filter(el=>!selectionOnly||WF.sel.includes(el.dataset.node));
  if(selectionOnly&&!els.length) return;
  if(!els.length){ wfPan={x:0,y:0}; wfSetZoom(1); return; }
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  els.forEach(el=>{ const x=el.offsetLeft,y=el.offsetTop,w=el.offsetWidth,h=el.offsetHeight;
    if(x<minX)minX=x; if(y<minY)minY=y; if(x+w>maxX)maxX=x+w; if(y+h>maxY)maxY=y+h; });
  // Reserve the toolbar, breadcrumb and floating dock before framing nodes.
  const frame={left:68,top:60,right:canvas.clientWidth-24,bottom:canvas.clientHeight-64};
  const dock=$("wf-act-panel");
  if(dock&&dock.offsetParent!==null&&!dock.classList.contains("is-max")){
    const cr=canvas.getBoundingClientRect(),dr=dock.getBoundingClientRect();
    frame.bottom=Math.min(frame.bottom,dr.top-cr.top-24);
  }
  const cw=Math.max(80,frame.right-frame.left),ch=Math.max(80,frame.bottom-frame.top);
  const z=Math.max(0.2,Math.min(cw/((maxX-minX)+40),ch/((maxY-minY)+40),1));
  const tx=frame.left+(cw-(minX+maxX)*z)/2,ty=frame.top+(ch-(minY+maxY)*z)/2;
  if(animate===false){ wfCancelCamAnim(); wfZoom=z; wfPan.x=tx; wfPan.y=ty; wfApplyTransform(); }
  else wfAnimateCamera(tx,ty,z,280);
}
function wfFitSelection(){
  if(typeof wfPvActive!=="undefined"&&wfPvActive) return;
  wfFit(undefined,true);
}
