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
  clock:      '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 15"/>',
  hourglass:  '<path d="M6 3h12"/><path d="M6 21h12"/><path d="M6 3c0 5 6 6 6 9s-6 4-6 9"/><path d="M18 3c0 5-6 6-6 9s6 4 6 9"/>',
  alarm:      '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5"/><path d="M5 3 2 6"/><path d="M22 6l-3-3"/>',
  calendar:   '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="16" y1="2" x2="16" y2="6"/>',
  smartphone: '<rect x="6" y="2" width="12" height="20" rx="2"/><line x1="10" y1="18" x2="14" y2="18"/>',
  monitor:    '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  power:      '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
  battery:    '<rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/>',
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
  // color
  droplet:    '<path d="M12 2s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  pipette:    '<path d="m2 22 1-1h2l9-9"/><path d="M3 21v-2l9-9"/><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4z"/>',
  // logic
  pin:        '<path d="M12 17v5"/><path d="M7 3h10l-2 7h4l-7 7-7-7h4L7 3z"/>',
  calculator: '<rect x="4" y="3" width="16" height="18" rx="2"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="12" x2="8" y2="12"/><line x1="12" y1="12" x2="12" y2="12"/><line x1="16" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="12" y1="16" x2="12" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/>',
  hash:       '<line x1="9" y1="3" x2="7" y2="21"/><line x1="17" y1="3" x2="15" y2="21"/><line x1="4" y1="9" x2="20" y2="9"/><line x1="3" y1="15" x2="19" y2="15"/>',
  git_branch: '<line x1="6" y1="3" x2="6" y2="21"/><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M18 11.5a6 6 0 0 1-6 6"/>',
  git_merge:  '<circle cx="18" cy="18" r="2.5"/><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><line x1="6" y1="8.5" x2="6" y2="15.5"/><path d="M6 8.5a9 9 0 0 0 9 9"/>',
  // skip-forward: abandon current try_chain arm → try next branch
  skip:       '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/>',
  bell:       '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  scroll:     '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M9 7h6M9 11h6M9 15h4"/><path d="M17 14l2.5 2.5L17 19"/>',
  // misc
  rocket:     '<path d="M5 13c-2 1-3 4-3 7 3 0 6-1 7-3"/><path d="M14 4c3 1 6 4 6 8-2 2-5 3-9 3l-4-4c0-4 1-7 3-9z"/><circle cx="15" cy="9" r="1.4"/>',
  camera:     '<path d="M4 7h3l2-2h6l2 2h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"/><circle cx="12" cy="13" r="3.5"/>',
  edit:       '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>',
  message:    '<path d="M21 11.5a8.5 8.5 0 0 1-12 7.7L3 21l1.8-6A8.5 8.5 0 1 1 21 11.5z"/>',
  function:   '<path d="M15 4h-1a3 3 0 0 0-3 3v10a3 3 0 0 1-3 3"/><line x1="8" y1="11.5" x2="16" y2="11.5"/>',
  // win32 window controls
  maximize:   '<rect x="4" y="4" width="16" height="16" rx="2"/><polyline points="9 4 4 4 4 9"/>',
  minimize:   '<rect x="4" y="4" width="16" height="16" rx="2"/><line x1="8" y1="16" x2="16" y2="16"/>',
  move:       '<polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/>',
  // ui chrome
  x:          '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  check:      '<polyline points="4 12.5 9.5 18 20 6"/>',
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
  folder:     '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
};
  function wfIco(name){
    const inner = WF_ICONS[name];
    if(!inner) return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/></svg>';
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
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

// Node catalog: UI source of truth (icon, kind, output ports, param fields).
// Mirrors src/workflow/engine.py NODE_TYPES. kind: start|end|action|condition|loop.
const WF_NODES = {
  start:      {label:"Start",   ico:"play", kind:"start", cat:null,    outs:["out"], fields:[]},
  end:        {label:"End",  ico:"square", kind:"end",   cat:"flow",  outs:[],      fields:[]},
  tap:        {label:"Tap",      ico:"pointer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},{k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"}], sum:p=>(p.target==="found"?"↳ last found image":`(${p.x}, ${p.y})`)+(p.taps=="2"?" ×2":"")},
  // Hidden from the palette — superseded by tap(taps=2); old files still open/run fine.
  double_tap: {label:"Double tap",  ico:"hand",kind:"action",cat:"basic", hidden:true, outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},{k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}}], sum:p=>(p.target==="found"?"↳ last found image":`(${p.x}, ${p.y})`)+" ×2"},
  tap_random: {label:"Random tap",ico:"dice",kind:"action",cat:"basic", outs:["out"], fields:[{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:100},{k:"h",t:"num",d:100}], sum:p=>`region (${p.x},${p.y}) ${p.w}×${p.h}`},
  long_press: {label:"Long press",       ico:"timer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"target",t:"select",opts:[{v:"pos",t:"Coordinates"},{v:"found",t:"Last found image"}],d:"pos"},{k:"x",t:"num",showWhen:{target:"pos"}},{k:"y",t:"num",showWhen:{target:"pos"}},{k:"duration",lbl:"Duration (ms)",t:"num",d:800}], sum:p=>(p.target==="found"?"↳ last found image":`(${p.x},${p.y})`)+` ${p.duration}ms`},
  swipe:      {label:"Swipe",      ico:"arrow_down",kind:"action",cat:"basic", outs:["out"], fields:[{k:"x1",t:"num"},{k:"y1",t:"num"},{k:"x2",t:"num"},{k:"y2",t:"num"},{k:"duration",t:"num",d:300}], sum:p=>`(${p.x1},${p.y1})→(${p.x2},${p.y2})`},
  swipe_dir:  {label:"Swipe direction",ico:"arrow_down",kind:"action",cat:"basic", outs:["out"], fields:[{k:"direction",t:"select",opts:[{v:"up",t:"↑ Up"},{v:"down",t:"↓ Down"},{v:"left",t:"← Left"},{v:"right",t:"→ Right"}],d:"up"},{k:"distance",lbl:"Distance (px)",t:"num",d:400},{k:"duration",lbl:"Duration (ms)",t:"num",d:300}], sum:p=>`${({up:"↑",down:"↓",left:"←",right:"→"})[p.direction]||"↑"} ${p.distance}px`},
  wait:       {label:"Wait",       ico:"timer",kind:"action",cat:"basic", outs:["out"], fields:[{k:"seconds",t:"num",d:1,step:.5}], sum:p=>`${p.seconds}s`},
  wait_random:{label:"Random wait",ico:"hourglass",kind:"action",cat:"basic", outs:["out"], fields:[{k:"min",t:"num",d:.5,step:.5},{k:"max",t:"num",d:2,step:.5}], sum:p=>`${p.min}-${p.max}s`},
  send_text:  {label:"Input text", ico:"keyboard",kind:"action",cat:"input", outs:["out"], fields:[{k:"text",t:"text",insertVar:true}], sum:p=>`"${p.text||""}"`},
  key:        {label:"Key",      ico:"disc",kind:"action",cat:"input", outs:["out"], fields:[{k:"keycode",t:"text",d:"BACK"}], sum:p=>`${p.keycode}`},
  back:       {label:"Back",      ico:"back",kind:"action",cat:"input", outs:["out"], fields:[], sum:()=>"Back key"},
  home:       {label:"Home",      ico:"home",kind:"action",cat:"input", outs:["out"], fields:[], sum:()=>"Home key"},
  tap_image:  {label:"Tap image",  ico:"target",kind:"condition",cat:"image", outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>wfBase(p.template)+(p.taps=="2"?" ×2":"")+((p.offsetX||p.offsetY)?` +(${p.offsetX||0},${p.offsetY||0})`:"")},
  wait_image: {label:"Wait image",   ico:"timer",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"negate",lbl:"Negate — wait until it DISAPPEARS",t:"bool",d:false},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>(p.negate?"until gone ":"")+wfBase(p.template)},
  if_image:   {label:"If image",   ico:"help",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"template",t:"tpl"},{k:"threshold",t:"num",d:.85,step:.05},{k:"negate",t:"bool",d:false},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${p.negate?"not ":""}found ${wfBase(p.template)}`},
  // "…_any" = OR over several images: true when ANY listed template matches.
  tap_image_any: {label:"Tap any image", ico:"target",kind:"condition",cat:"image", outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"mode",lbl:"Search mode",t:"select",opts:[{v:"sequential",t:"Sequential"},{v:"parallel",t:"Parallel"}],d:"sequential"},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>wfBaseAny(p.templates)+(p.taps=="2"?" ×2":"")+(p.mode==="parallel"?" //":"")},
  wait_image_any:{label:"Wait any image",  ico:"timer",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"threshold",t:"num",d:.85,step:.05},{k:"timeout",t:"num",d:10},{k:"mode",lbl:"Search mode",t:"select",opts:[{v:"sequential",t:"Sequential"},{v:"parallel",t:"Parallel"}],d:"sequential"},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>wfBaseAny(p.templates)+(p.mode==="parallel"?" //":"")},
  if_image_any:  {label:"If any image",  ico:"layers",kind:"condition",cat:"image",outs:["true","false"], fields:[{k:"templates",t:"tpls"},{k:"threshold",t:"num",d:.85,step:.05},{k:"negate",t:"bool",d:false},{k:"mode",lbl:"Search mode",t:"select",opts:[{v:"sequential",t:"Sequential"},{v:"parallel",t:"Parallel"}],d:"sequential"},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${p.negate?"not ":""}found ${wfBaseAny(p.templates)}${p.mode==="parallel"?" //":""}`},
  wait_text:  {label:"Wait text",   ico:"scan_text",kind:"condition",cat:"ocr",  outs:["true","false"], fields:[{k:"text",t:"text",varRef:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"timeout",t:"num",d:10},{k:"negate",lbl:"Negate — wait until it DISAPPEARS",t:"bool",d:false},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}], sum:p=>(p.negate?"until gone ":"")+`"${p.text||""}"`},
  if_text:    {label:"If text",   ico:"type",kind:"condition",cat:"ocr",outs:["true","false"], fields:[{k:"text",t:"text",varRef:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"negate",t:"bool",d:false},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}], sum:p=>`${p.negate?"not ":""}contains "${p.text||""}"`},
  read_var:   {label:"Read → variable",ico:"search",kind:"action",cat:"ocr",  outs:["out"], fields:[{k:"name",t:"text",d:"val",var:true},{k:"x",t:"num"},{k:"y",t:"num"},{k:"w",t:"num",d:200},{k:"h",t:"num",d:80},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:""}], sum:p=>`→ ${p.name||"?"}`},
  parse_var:  {label:"Parse → variable",ico:"scissors",kind:"action",cat:"ocr",  outs:["out"], fields:[{k:"name",t:"text",d:"out",var:true},{k:"source",t:"select",opts:[{v:"region",t:"OCR region"},{v:"var",t:"From variable"}],d:"region"},{k:"fromVar",lbl:"Source variable",t:"text",d:"",var:true,showWhen:{source:"var"}},{k:"pattern",t:"text",d:"(\\d+)/(\\d+)"},{k:"group",t:"num",d:1},{k:"x",t:"num",showWhen:{source:"region"}},{k:"y",t:"num",showWhen:{source:"region"}},{k:"w",t:"num",d:200,showWhen:{source:"region"}},{k:"h",t:"num",d:80,showWhen:{source:"region"}},{k:"whitelist",lbl:"OCR whitelist (allowed characters)",t:"text",d:"",showWhen:{source:"region"}}], sum:p=>`${p.name||"?"} = /${p.pattern||""}/g${p.group||1}`},
  // ── Color (pixel) nodes — compare screen pixels against a #RRGGBB colour.
  // Tolerance = max per-channel difference (same rule as DevScope's Inspect color).
  tap_color:  {label:"Tap color", ico:"droplet",kind:"condition",cat:"color", outs:["true","false"], fields:[{k:"color",t:"color",d:"#ff0000"},{k:"tolerance",lbl:"Tolerance",t:"num",d:10},{k:"timeout",t:"num",d:10},{k:"taps",t:"select",opts:[{v:"1",t:"Tap"},{v:"2",t:"Double tap"}],d:"1"},{k:"offsetX",lbl:"Offset X",t:"num",d:0},{k:"offsetY",lbl:"Offset Y",t:"num",d:0},{k:"_region",lbl:"Search region",t:"region"}], sum:p=>`${p.color||"?"} ±${p.tolerance??10}`+(p.taps=="2"?" ×2":"")},
  wait_color: {label:"Wait color",ico:"droplet",kind:"condition",cat:"color", outs:["true","false"], fields:[{k:"color",t:"color",d:"#ff0000"},{k:"tolerance",lbl:"Tolerance",t:"num",d:10},{k:"x",t:"num"},{k:"y",t:"num"},{k:"timeout",t:"num",d:10},{k:"negate",lbl:"Negate — wait until the color is GONE",t:"bool",d:false}], sum:p=>(p.negate?"until gone ":"")+`(${p.x||0},${p.y||0}) = ${p.color||"?"}`},
  if_color:   {label:"If color",  ico:"droplet",kind:"condition",cat:"color", outs:["true","false"], fields:[{k:"color",t:"color",d:"#ff0000"},{k:"tolerance",lbl:"Tolerance",t:"num",d:10},{k:"x",t:"num"},{k:"y",t:"num"},{k:"negate",t:"bool",d:false}], sum:p=>`${p.negate?"not ":""}(${p.x||0},${p.y||0}) ≈ ${p.color||"?"}`},
  read_color: {label:"Read color → variable",ico:"pipette",kind:"action",cat:"color", outs:["out"], fields:[{k:"name",lbl:"Target variable",t:"text",d:"color",var:true},{k:"x",t:"num"},{k:"y",t:"num"}], sum:p=>`${p.name||"?"} = px(${p.x||0},${p.y||0})`},
  loop:       {label:"Repeat",   ico:"loop",kind:"loop", cat:"flow",   ins:["in","loop"], outs:["body","done"], fields:[{k:"infinite",t:"bool",d:true},{k:"count",lbl:"Repeat count",t:"num",varRef:true,d:3,showWhen:{infinite:false}}], sum:p=>p.infinite?"∞ infinite":`${p.count}×`},
  parallel:   {label:"Parallel", ico:"parallel",kind:"parallel",cat:"flow", outs:[], fields:[{k:"count",lbl:"Thread count",t:"num",d:3,refresh:true}], sum:p=>`${p.count||3} parallel threads`},
  try_chain:  {label:"Try in order",ico:"git_branch",kind:"try_chain",cat:"flow", outs:[], fields:[], sum:p=>`${p.count||3} branches · on fail try next branch`, pair:"try"},
  // Inside a Try in order arm: stop this branch and advance to the next numbered
  // port (or fail if none left). Like Break loop, but for try_chain.
  try_next:   {label:"Next branch",ico:"skip",kind:"try_next",cat:"flow", outs:[], fields:[], sum:()=>"skip → next try_chain branch", pair:"try"},
  join:       {label:"Join",       ico:"git_merge",kind:"join",  cat:"flow", outs:["out"], fields:[], sum:()=>"wait for all threads → continue"},
  and:        {label:"And",        ico:"git_merge",kind:"and",   cat:"flow", outs:["out"], fields:[{k:"count",lbl:"Branch count",t:"num",d:2,refresh:true}], sum:p=>`${p.count||2} branches · all must succeed`},
  "break":    {label:"Break loop",ico:"octagon",kind:"action",cat:"flow",  outs:["out"], fields:[], sum:()=>"break"},
  stop:       {label:"Stop all",ico:"octagon",kind:"stop", cat:"flow",  outs:[],      fields:[], sum:()=>"stop session"},
  set_var:    {label:"Set variable",  ico:"pin",kind:"action",cat:"logic", outs:["out"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"value",t:"text",varRef:true,d:"0"}], sum:p=>`${p.name||"?"} = ${p.value}`},
  calc_var:   {label:"Calculate variable", ico:"calculator",kind:"action",cat:"logic", outs:["out"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"op",t:"select",opts:[{v:"+",t:"+ Add"},{v:"-",t:"− Subtract"},{v:"*",t:"× Multiply"},{v:"/",t:"÷ Divide"},{v:"=",t:"= Assign"}],d:"+"},{k:"value",t:"text",varRef:true,d:"1"}], sum:p=>`${p.name} ${p.op}= ${p.value}`},
  if_var:     {label:"If variable",  ico:"hash",kind:"condition",cat:"logic",outs:["true","false"], fields:[{k:"name",t:"text",d:"i",var:true},{k:"op",t:"select",opts:[{v:"==",t:"= equals"},{v:"!=",t:"≠ not equal"},{v:">",t:"> greater"},{v:"<",t:"< less"},{v:">=",t:"≥ at least"},{v:"<=",t:"≤ at most"}],d:"=="},{k:"value",t:"text",varRef:true,d:"0"}], sum:p=>`${p.name} ${p.op} ${p.value}`},
  // Multi-way branch: each case is its own condition; first true case wins its
  // own output port "c{i}", else the "default" port. Ports are dynamic (one per
  // case + default) — see wfNodeEl. Cases edited by wfSwitchCasesEditor.
  "switch":   {label:"Switch",  ico:"git_branch",kind:"switch",cat:"logic",outs:["default"], fields:[], sum:p=>`${(p.cases||[]).length} branches`},
  // ── App lifecycle (ADB package · Win32 window title where noted) ───────────
  // pkgSrc: "project" = workflow package from Project settings; "custom" = free text / var.
  launch_app: {label:"Launch app",    ico:"rocket",kind:"action",cat:"app",  outs:["out"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"wait",lbl:"Launch wait (s)",t:"num",d:0}
  ], sum:p=>wfPkgLabel(p)+(p.wait?` ·wait ${p.wait}s`:"")},
  // Force-stop an app (optionally clear its data) — pairs with Launch app for restart-game flows. ADB-only at runtime.
  app_stop: {label:"Stop app", ico:"octagon", kind:"action", cat:"app", outs:["out"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"clearData",lbl:"Clear app data (pm clear)",t:"bool",d:false}
  ], sum:p=>`⛔ ${wfPkgLabel(p)}`+(p.clearData?" +clear":"")},
  // Exit the current app — no package needed (ADB: force-stop foreground · Win32: close the window).
  app_exit: {label:"Exit current app", ico:"x", kind:"action", cat:"app", outs:["out"], fields:[], sum:()=>"exit current app"},
  // Uninstall an app (pm uninstall; -k = keep data). ADB-only at runtime.
  app_uninstall: {label:"Uninstall app", ico:"trash", kind:"action", cat:"app", outs:["out"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"keepData",lbl:"Keep data & cache (-k)",t:"bool",d:false}
  ], sum:p=>`🗑 ${wfPkgLabel(p)}`+(p.keepData?" ·keep":"")},
  // Does the current app package / window title contain a string? (ADB: package · Win32: window title)
  if_app: {label:"If app running", ico:"smartphone", kind:"condition", cat:"app", outs:["true","false"], fields:[
    {k:"pkgSrc",lbl:"Package source",t:"select",opts:[{v:"project",t:"Project package"},{v:"custom",t:"Custom…"}],d:"project"},
    {k:"package",lbl:"Package / title contains",t:"text",varRef:true,showWhen:{pkgSrc:"custom"}},
    {k:"negate",t:"bool",d:false}
  ], sum:p=>`${p.negate?"not ":""}app ~ "${wfPkgLabel(p)}"`},
  // ── Utilities ──────────────────────────────────────────────────────────────
  screenshot: {label:"Screenshot",      ico:"camera",kind:"action",cat:"basic", outs:["out"], fields:[], sum:()=>"take screenshot"},
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
  // Launch the emulator PROCESS on the PC (not an app inside it). Optional "at"
  // waits until a clock time first → "sit idle until 07:00, then boot LDPlayer".
  launch_emulator:{label:"Launch emulator", ico:"monitor", kind:"action", cat:"device", outs:["out"], fields:[
    {k:"emulator",lbl:"Emulator",t:"select",opts:[{v:"ldplayer",t:"LDPlayer"},{v:"mumu",t:"MuMu"},{v:"nox",t:"Nox"},{v:"memu",t:"MEmu"},{v:"bluestacks",t:"BlueStacks"},{v:"custom",t:"Custom command"}],d:"ldplayer"},
    {k:"index",lbl:"Instance index",t:"num",d:0},
    {k:"instance",lbl:"Instance name (BlueStacks)",t:"text",d:"",showWhen:{emulator:"bluestacks"}},
    {k:"path",lbl:"Install folder / console .exe (blank = auto)",t:"text",d:"",pickFolder:true},
    {k:"command",lbl:"Custom command ({index})",t:"text",d:"",showWhen:{emulator:"custom"}},
    {k:"at",lbl:"Schedule at (blank = now)",t:"time",d:""},
    {k:"nextDay",lbl:"If time passed → wait next day",t:"bool",d:true},
    {k:"wait",lbl:"Wait for ADB ready (s)",t:"num",d:60},
    {k:"port",lbl:"ADB port override (blank = auto)",t:"num"},
  ], sum:p=>`▶ ${p.emulator||"ldplayer"}${(p.index?(" #"+p.index):"")}${p.at?(" ⏰"+p.at):""}`},
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
  // ── Win32 (PC program window control) ────────────────────────────────────────
  // Only used when the project's Controller = Win32. The tap/swipe/image/color/
  // OCR nodes still work on Win32 through the shared screen-capture pipeline.
  win_launch:   {label:"Launch program", ico:"rocket", kind:"action", cat:"win32", outs:["out"], fields:[
    {k:"path",lbl:"Program (.exe) path",t:"text",d:"",pickFolder:false},
    {k:"args",lbl:"Arguments (optional)",t:"text",d:""},
    {k:"window",lbl:"Wait for window title (optional)",t:"text",d:""},
    {k:"wait",lbl:"Wait for window (s)",t:"num",d:30},
  ], sum:p=>`▶ ${(p.path||"(program)").split(/[\\/]/).pop()}`},
  win_activate: {label:"Activate window", ico:"monitor", kind:"action", cat:"win32", outs:["out"], fields:[], sum:()=>"bring window to front"},
  win_close:    {label:"Close window", ico:"x", kind:"action", cat:"win32", outs:["out"], fields:[], sum:()=>"close target window"},
  win_resize:   {label:"Resize window", ico:"maximize", kind:"action", cat:"win32", outs:["out"], fields:[{k:"width",lbl:"Width",t:"num",d:1280},{k:"height",lbl:"Height",t:"num",d:720}], sum:p=>`${p.width||1280}×${p.height||720}`},
  win_move:     {label:"Move window", ico:"move", kind:"action", cat:"win32", outs:["out"], fields:[{k:"x",lbl:"Screen X",t:"num",d:0},{k:"y",lbl:"Screen Y",t:"num",d:0}], sum:p=>`(${p.x||0}, ${p.y||0})`},
  win_minimize: {label:"Minimize window", ico:"minimize", kind:"action", cat:"win32", outs:["out"], fields:[], sum:()=>"minimize"},
  win_maximize: {label:"Maximize window", ico:"maximize", kind:"action", cat:"win32", outs:["out"], fields:[], sum:()=>"maximize"},
  win_restore:  {label:"Restore window", ico:"monitor", kind:"action", cat:"win32", outs:["out"], fields:[], sum:()=>"restore"},
  win_always_on_top: {label:"Always on top", ico:"pin", kind:"action", cat:"win32", outs:["out"], fields:[{k:"enabled",lbl:"Enabled",t:"bool",d:true}], sum:p=>p.enabled?"📌 on top":"📌 normal"},
  win_set_title: {label:"Set window title", ico:"type", kind:"action", cat:"win32", outs:["out"], fields:[{k:"title",lbl:"New title",t:"text",d:"Game"}], sum:p=>`"${p.title||"?"}"`},
  win_style:    {label:"Set window style", ico:"settings", kind:"action", cat:"win32", outs:["out"], fields:[{k:"style",lbl:"Style",t:"select",opts:[{v:"windowed",t:"Windowed (with frame)"},{v:"borderless",t:"Borderless"},{v:"popup",t:"Popup"}],d:"windowed"}], sum:p=>`${p.style||"windowed"}`},
};
// `ctrl` restricts a category to one project controller: the Device/emulator
// nodes are ADB-only, the Win32 window nodes are PC-only. Untagged categories
// (basic/image/app/color/ocr/flow/logic/…) work on both and always show.
// Order follows real usage frequency (across 12 workflows: image/basic/flow/
// logic make up ~95% of nodes). Never-used groups (`closed:true`) collapse by
// default — a fresh palette shows only the ~15 common node types; whichever
// group the user opens is remembered in localStorage (wfPalCollapsed) as before.
const WF_CATS = [
  {key:"basic", label:"Basic"},
  {key:"image", label:"Image"},
  {key:"flow",  label:"Flow"},
  {key:"logic", label:"Variables / Conditions"},
  {key:"ocr",   label:"Text (OCR)"},
  {key:"input", label:"Keys & Input"},
  {key:"app",   label:"App",     closed:true},
  {key:"color", label:"Color",   closed:true},
  {key:"time",  label:"Time",    closed:true},
  {key:"device",label:"Device",  ctrl:"adb",   closed:true},
  {key:"win32", label:"Win32 (PC)", ctrl:"win32"},
  {key:"misc",  label:"Other",   closed:true},
];
// Palette pairs: related nodes rendered as one framed unit so the relationship
// is obvious (e.g. Try in order + Next branch). Order of `types` = display order.
// Search: if any member matches, the whole pair still shows (all members).
const WF_PAL_PAIRS = [
  { id:"try", types:["try_chain","try_next"], label:"Try pair",
    hint:"Try arms 1→2→… · Next branch skips to the next arm" },
];
const WF_PORT_LBL = { out:"", "true":"T", "false":"F", body:"loop", done:"done", found:"found", fail:"fail", "1":"1", "2":"2", "3":"3" };
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

// edit = which graph the canvas is showing: an activity or a function.
// sel = ids of all selected nodes (multi-select); selectedNode = primary (inspector).
const WF = { name:"My Workflow", version:2, templatesDir:"templates", activities:[], functions:[],
  globals:[],
  // Target Android package for this workflow (ADB). Top-level, not part of speedhack.
  package:"",
  // Speed hack toggle + multiplier only; package lives on WF.package.
  speedhack:{enabled:false, speed:2.0},
  // Which backend drives the flow: "adb" (device/emulator) or "win32" (PC window).
  controller:"adb",
  win32:{window:"", matchBy:"title", inputMode:"background"},
  // OCR engine for text-reading blocks (wait_text/if_text/read_var/parse_var…).
  // "" = auto (the engine picks the first available backend). Saved into the
  // flow JSON (key "ocr") so the Runner + test runs use the chosen engine.
  ocrBackend:"",
  // Screen capture source for ADB projects: "scrcpy" (fast/headless) or "adb"
  // (screencap). Saved into the flow JSON (key "capture") per game workflow.
  captureBackend:"scrcpy",
  edit:{kind:"activity", id:null}, sel:[], selectedNode:null };
let wfSpace=false;  // space held → pan instead of box-select
const WF_GRID=20;   // grid step; snapping is opt-in (default off)
let wfSnapOn=false;
let wfPreviewAll=false;   // global: show image thumbnail on every image block
let wfMinimapOn=false;    // minimap is opt-in (default off)
let wfAlignOn=true;       // Figma-style edge/centre magnetism + guides (Alt = pause)
// Live runtime variable values pushed from the engine during a test run.
// Keyed by var name -> current value (stringified for display).
let wfLiveVars={};
let wfFreshVar=null;       // name of the most-recently-changed var (brief highlight)
// Corner-panel collapse states persist locally so the canvas reopens as left.
let wfVarsCollapsed=false, wfActCollapsed=false;
try{ wfVarsCollapsed=localStorage.getItem("wfVarsCollapsed")==="1";
     wfActCollapsed =localStorage.getItem("wfActCollapsed")==="1"; }catch{}
function wfPersistPanelState(){
  try{ localStorage.setItem("wfVarsCollapsed", wfVarsCollapsed?"1":"0");
       localStorage.setItem("wfActCollapsed",  wfActCollapsed ?"1":"0"); }catch{}
}
const wfSnap=v=> wfSnapOn ? Math.round(v/WF_GRID)*WF_GRID : Math.round(v);
function wfSaveSettings(){ try{ const lc=$("log-card"), sd=$("wf-side"), insp=$("wf-inspector");
  const logH = lc && !lc.classList.contains("collapsed") ? lc.offsetHeight : (lc && lc.dataset.openH ? parseInt(lc.dataset.openH,10) : undefined);
  api().save_settings({snap:wfSnapOn, previewAll:wfPreviewAll, minimap:wfMinimapOn, alignGuides:wfAlignOn, previewHz: (typeof wfPvHz!=="undefined"?wfPvHz:undefined), logOpen: !(lc&&lc.classList.contains("collapsed")), logH: logH||undefined, sideW: sd?sd.offsetWidth:undefined, inspW: insp?insp.offsetWidth:undefined}); }catch{} }
function wfSyncToggleBtns(){
  // Icon buttons: state shows as colour (.on) + tooltip, never overwrite the SVG.
  const s=$("wf-snap-btn"); if(s){ s.title="Snap to grid: "+(wfSnapOn?"On":"Off"); s.classList.toggle("on",wfSnapOn); }
  const p=$("wf-preview-btn"); if(p){ p.title="Image preview: "+(wfPreviewAll?"On":"Off"); p.classList.toggle("on",wfPreviewAll); }
  const a=$("wf-align-btn"); if(a){ a.title="Smart align: "+(wfAlignOn?"On":"Off")+" — dragged blocks snap to other blocks' edges/ports (hold Alt to pause)"; a.classList.toggle("on",wfAlignOn); }
  const m=$("wf-minimap-btn"); if(m){ m.title="Minimap: "+(wfMinimapOn?"On":"Off")+" — bird's-eye view of the graph, click to jump the camera"; m.classList.toggle("on",wfMinimapOn); }
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
function wfPackageChanged(){
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
  wfPackageFromUI();
  setStatus(WF.package ? ("Package: "+WF.package) : "Package cleared");
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
function wfSyncSpeedUI(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0});
  const win32=(WF.controller==="win32");
  // Hide the entire speed-hack cluster in Win32 mode — no Frida, no cheat DLL.
  const grp=$("wf-speed-group");
  if(grp) grp.style.display = win32 ? "none" : "";
  if(win32) return;
  const b=$("wf-speed-btn");
  if(b){
    b.title = "Speed hack: "+(sh.enabled?"On":"Off")+" (accelerate the game with Frida — root required · set package in Project settings)";
    b.classList.toggle("on",sh.enabled);
  }
  const v=$("wf-speed-val"); if(v && document.activeElement!==v) v.value=sh.speed;
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
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0});
  const el=$("wf-speed-val");
  const v=el?parseFloat(el.value):sh.speed; sh.speed=(isNaN(v)||v<=0)?1:v;
  wfPackageFromUI();
}
// Speed value edited: persist, and if the hack is live, push the new scale.
function wfSpeedChanged(){ wfSpeedFromUI(); if(wfSpeedRunning){ const sh=WF.speedhack; api().speedhack_start(sh.speed, wfAutoPackage()); } }
function wfToggleSpeed(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0});
  wfSpeedFromUI(); sh.enabled=!sh.enabled;
  if(!sh.enabled && wfSpeedRunning){ api().speedhack_stop(); wfSpeedRunning=false; }  // disabling stops it
  wfSyncSpeedUI();
}
// The ▶/⏹ button: actually inject (or stop) the speed hack, on its own.
// ADB-only (Frida). Win32 mode hides the whole cluster, so this never fires there.
async function wfSpeedRun(){
  const sh=WF.speedhack||(WF.speedhack={enabled:false,speed:2.0});
  wfSpeedFromUI();
  if(wfSpeedRunning){ await api().speedhack_stop(); return; }
  const pkg=wfAutoPackage();
  if(!pkg){ uiToast("Set the app package in Project settings (gear next to the title), or add a Launch app block.","warning"); return; }
  const ok=await api().speedhack_start(sh.speed, pkg);
  if(!ok){ wfSpeedRunning=false; wfSyncSpeedUI(); }
}

// ── Project settings popup (package · controller · OCR · Win32 target) ───────
// Bar only shows the gear + title; everything project-wide lives here.
let wfOcrBackendsCache=["tesseract","easyocr","paddleocr"];
function wfSyncOcrUI(){
  const sel=$("wf-ocr-select"); if(sel) sel.value=WF.ocrBackend||"";
}
function wfOcrChanged(){
  const sel=$("wf-ocr-select");
  WF.ocrBackend=sel?((sel.value||"").trim()):(WF.ocrBackend||"");
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
  setStatus("OCR engine: "+(WF.ocrBackend||"auto"));
}
function wfFillOcrSelect(sel){
  if(!sel) return;
  const backs=wfOcrBackendsCache&&wfOcrBackendsCache.length?wfOcrBackendsCache:["tesseract","easyocr","paddleocr"];
  sel.innerHTML='<option value="">Auto</option>';
  backs.forEach(b=>{ const o=document.createElement("option"); o.value=b; o.textContent=b; sel.appendChild(o); });
  sel.value=WF.ocrBackend||"";
}
// Cache backends from the host; fill the select if the settings form is open.
function wfPopulateOcrBackends(backs){
  if(backs&&backs.length) wfOcrBackendsCache=backs.slice();
  const sel=$("wf-ocr-select"); if(sel){ wfFillOcrSelect(sel); }
}
// ── Project controller (ADB vs Win32) ────────────────────────────────────────
function wfSyncControllerUI(){
  const sel=$("wf-controller"); if(sel) sel.value=WF.controller||"adb";
  const w=WF.win32||(WF.win32={window:"",matchBy:"title",inputMode:"background"});
  const win32=(WF.controller==="win32");
  const adbSec=$("wf-proj-adb-sec"); if(adbSec) adbSec.style.display=win32?"none":"";
  const winSec=$("wf-proj-win32-sec"); if(winSec) winSec.style.display=win32?"":"none";
  const win=$("wf-win32-window"); if(win && document.activeElement!==win) win.value=w.window||"";
  const mb=$("wf-win32-matchby"); if(mb) mb.value=w.matchBy||"title";
  const md=$("wf-win32-mode"); if(md) md.value=w.inputMode||"background";
  wfSyncPackageUI();
  wfSyncSpeedUI();   // speed-hack visibility depends on the controller
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
function wfWinMenuOutside(e){ if(wfWinMenuEl && !e.target.closest(".wf-varmenu") && !e.target.closest("#wf-win32-pick")) wfCloseWinMenu(); }
async function wfPickWindow(ev){
  if(ev) ev.stopPropagation();
  let wins=[]; try{ wins=await api().list_windows()||[]; }catch{}
  wfCloseWinMenu();
  const anchor=$("wf-win32-window"); if(!anchor) return;
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
    const shown=wins.filter(w=>!f||w.title.toLowerCase().includes(f)||(w.cls||"").toLowerCase().includes(f)||String(w.pid||"").includes(f));
    if(!shown.length){ const e=document.createElement("div"); e.className="wf-varmenu-empty"; e.textContent=wins.length?"No match.":"No windows found."; list.appendChild(e); return; }
    shown.forEach(w=>{
      const row=document.createElement("button"); row.type="button"; row.className="wf-varmenu-item";
      const meta=[w.pid?("pid "+w.pid):"", w.cls||""].filter(Boolean).join(" · ");
      row.innerHTML=`<span class="vn">${escHtml(w.title)}</span><span class="vt">${escHtml(meta)}</span>`;
      row.title=`Title: ${w.title}\nClass: ${w.cls||""}\nPID: ${w.pid||"?"}`;
      row.onclick=()=>{
        const by=($("wf-win32-matchby")&&$("wf-win32-matchby").value)||"title";
        anchor.value = (by==="pid") ? String(w.pid||"") : (by==="class") ? (w.cls||w.title) : w.title;
        wfWin32FromUI(); wfCloseWinMenu();
      };
      list.appendChild(row);
    });
  }
  render("");
  document.body.appendChild(menu);
  const r=($("wf-win32-pick")||anchor).getBoundingClientRect();
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
  if(win) w.window=(win.value||"").trim();
  if(mb) w.matchBy=mb.value||"title";
  if(md) w.inputMode=md.value||"background";
  wfPushCaptureSource();
  if(typeof wfPushUndoDebounced==="function") wfPushUndoDebounced();
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
          `<option value="adb">ADB — Android device / emulator</option>`+
          `<option value="win32">Win32 — PC program window</option>`+
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
      form.appendChild(secAdb);

      // ── Win32 target ──────────────────────────────────────────────────────
      const secWin=document.createElement("div"); secWin.className="wf-proj-sec"; secWin.id="wf-proj-win32-sec";
      secWin.style.display="none";
      secWin.innerHTML=`<div class="wf-proj-sec-lbl">Win32 window</div>`;
      const rowWin=document.createElement("div"); rowWin.className="wf-proj-row";
      rowWin.innerHTML=
        `<label for="wf-win32-window">Target window</label>`+
        `<div class="wf-proj-inline">`+
          `<input id="wf-win32-window" type="text" placeholder="Title, class, or PID (e.g. Genshin*)" spellcheck="false" autocomplete="off">`+
          `<button type="button" class="btn sm ico" id="wf-win32-pick" title="Pick an open window">`+
            `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></svg>`+
          `</button>`+
        `</div>`;
      secWin.appendChild(rowWin);
      const rowWinOpts=document.createElement("div"); rowWinOpts.className="wf-proj-grid2";
      rowWinOpts.innerHTML=
        `<div class="wf-proj-row">`+
          `<label for="wf-win32-matchby">Match by</label>`+
          `<select id="wf-win32-matchby"><option value="title">Title</option><option value="class">Class</option><option value="pid">PID</option></select>`+
        `</div>`+
        `<div class="wf-proj-row">`+
          `<label for="wf-win32-mode">Input mode</label>`+
          `<select id="wf-win32-mode" title="How input is delivered to the window">`+
            `<option value="background">Background</option>`+
            `<option value="background_cursor">Background + cursor (Unity)</option>`+
            `<option value="background_frida_api">Background + Frida (API hook)</option>`+
            `<option value="background_frida_engine">Background + Frida Unity (engine)</option>`+
            `<option value="foreground">Foreground</option>`+
          `</select>`+
        `</div>`;
      secWin.appendChild(rowWinOpts);
      form.appendChild(secWin);

      // ── OCR ───────────────────────────────────────────────────────────────
      const secOcr=document.createElement("div"); secOcr.className="wf-proj-sec";
      secOcr.innerHTML=`<div class="wf-proj-sec-lbl">OCR</div>`;
      const rowOcr=document.createElement("div"); rowOcr.className="wf-proj-row";
      rowOcr.innerHTML=
        `<label for="wf-ocr-select">Text engine</label>`+
        `<select id="wf-ocr-select" title="OCR engine for Wait text / If text / Read → variable / Parse"></select>`+
        `<div class="hint">Auto = first available backend. Saved into the workflow JSON.</div>`;
      secOcr.appendChild(rowOcr);
      form.appendChild(secOcr);

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
      const winEl=q("wf-win32-window");
      if(winEl){
        winEl.addEventListener("input",()=>{ const w=WF.win32||(WF.win32={}); w.window=(winEl.value||"").trim(); });
        winEl.addEventListener("change",()=>wfWin32FromUI());
      }
      const mb=q("wf-win32-matchby"); if(mb) mb.onchange=()=>wfWin32FromUI();
      const md=q("wf-win32-mode"); if(md) md.onchange=()=>wfWin32FromUI();
      const pick=q("wf-win32-pick"); if(pick) pick.onclick=(e)=>wfPickWindow(e);

      // Seed values immediately (form not in document yet — don't rely on $()).
      if(ctrl) ctrl.value=WF.controller||"adb";
      if(pkg) pkg.value=WF.package||"";
      const w=WF.win32||{};
      if(winEl) winEl.value=w.window||"";
      if(mb) mb.value=w.matchBy||"title";
      if(md) md.value=w.inputMode||"background";
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
  const layers=[`radial-gradient(circle, rgba(20,30,45,.10) ${(1.4*z).toFixed(2)}px, transparent ${(1.6*z).toFixed(2)}px)`];
  const sizes=[`${100*z}px ${100*z}px`];
  if(z>=0.55){
    const r=Math.max(.8, z);
    layers.push(`radial-gradient(circle, #d9dee6 ${r.toFixed(2)}px, transparent ${(r+.2).toFixed(2)}px)`);
    sizes.push(`${20*z}px ${20*z}px`);
  }
  c.style.backgroundImage=layers.join(",");
  c.style.backgroundSize=sizes.join(",");
  c.style.backgroundPosition=`${px}px ${py}px`;
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
  if(typeof wfMinimapQueue==="function") wfMinimapQueue();
  const lbl=$("wf-zoom-lbl"); if(lbl) lbl.textContent=Math.round(wfZoom*100)+"%";
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
// Drag-to-resize the bottom log drawer; height persists in settings.
function wfInitLogResizer(){
  const card=$("log-card"), rez=$("log-resizer"); if(!card||!rez||rez.__wired) return;
  rez.__wired=true; let drag=null;
  const clampH=h=>Math.max(80, Math.min(Math.floor(window.innerHeight*0.55), Math.min(480, h)));
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
    const h=clampH(drag.h-(e.clientY-drag.y));
    card.style.height=h+"px";
    card.dataset.openH=String(h);
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
// Fit & center all blocks of the current graph into the canvas. Uses the live DOM
// node bounds (world coords), so it's exact regardless of node heights.
// Glides there by default; pass animate=false for an instant frame (the
// auto-layout pre-fit needs a stable camera before it animates the nodes).
function wfFit(animate){
  const canvas=$("wf-canvas"); if(!canvas) return;
  const els=[...document.querySelectorAll("#wf-world .wf-node")];
  if(!els.length){ wfPan={x:0,y:0}; wfSetZoom(1); return; }
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  els.forEach(el=>{ const x=el.offsetLeft,y=el.offsetTop,w=el.offsetWidth,h=el.offsetHeight;
    if(x<minX)minX=x; if(y<minY)minY=y; if(x+w>maxX)maxX=x+w; if(y+h>maxY)maxY=y+h; });
  const pad=70, cw=canvas.clientWidth, ch=canvas.clientHeight;
  const z=Math.max(0.2, Math.min(cw/((maxX-minX)+pad*2), ch/((maxY-minY)+pad*2), 1.5));
  const tx=(cw-(minX+maxX)*z)/2, ty=(ch-(minY+maxY)*z)/2;
  if(animate===false){ wfCancelCamAnim(); wfZoom=z; wfPan.x=tx; wfPan.y=ty; wfApplyTransform(); }
  else wfAnimateCamera(tx,ty,z,280);
}
