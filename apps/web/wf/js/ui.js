// ── UI kit: toast + modal (replaces native alert/prompt/confirm) ─────────────
// Toast: quick non-blocking feedback (saved, import error, copied…).
// Modal: blocking question/confirm — uiConfirm/uiPrompt return a Promise so a
// call-site moves from sync confirm() to .then()/await without changing flow.
// Focus is trapped inside the modal and restored on close — Esc = cancel,
// Enter = primary button, backdrop click = cancel.

// ── Toast ────────────────────────────────────────────────────────────────────
const UI_TOAST_ICO = {
  success: '<polyline points="4 12.5 9.5 18 20 6"/>',
  error:   '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  warning: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 2.5 18a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  info:    '<circle cx="12" cy="12" r="9"/><line x1="12" y1="10.5" x2="12" y2="16"/><circle cx="12" cy="7.6" r="0.7"/>',
};
function uiToastHost(){
  let h=document.getElementById("ui-toasts");
  if(!h){ h=document.createElement("div"); h.id="ui-toasts"; h.setAttribute("role","status"); h.setAttribute("aria-live","polite"); document.body.appendChild(h); }
  return h;
}
// uiToast("Saved", "success") — level: info | success | warning | error.
function uiToast(msg, level, opts){
  level = UI_TOAST_ICO[level] ? level : "info";
  opts = opts||{};
  const host=uiToastHost();
  const t=document.createElement("div");
  t.className="ui-toast ui-"+level;
  t.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${UI_TOAST_ICO[level]}</svg>`+
    `<span class="ui-toast-msg">${escHtml(String(msg))}</span>`;
  t.title="Click to dismiss";
  host.appendChild(t);
  while(host.children.length>5) host.removeChild(host.firstChild);
  const dur = opts.dur || (level==="error" ? 5200 : level==="warning" ? 4200 : 2800);
  let gone=false;
  const dismiss=()=>{ if(gone) return; gone=true;
    t.classList.add("out");
    t.addEventListener("animationend",()=>t.remove(),{once:true});
    setTimeout(()=>t.remove(),300);   // reduced-motion fallback
  };
  t.onclick=dismiss;
  setTimeout(dismiss,dur);
  return t;
}

// ── Modal core ───────────────────────────────────────────────────────────────
// One modal at a time; opening another closes the previous one (resolving "cancel").
let _uiModal=null;
function uiModalClose(result){
  if(!_uiModal) return;
  const m=_uiModal; _uiModal=null;
  document.removeEventListener("keydown",m.onKey,true);
  m.wrap.remove();
  if(m.prevFocus && m.prevFocus.focus) try{ m.prevFocus.focus(); }catch{}
  m.resolve(result);
}
// uiModal({title, body, buttons:[{label, value, kind:"accent"|"err"|"", autofocus}]})
// → Promise<value of the pressed button | undefined on Esc/backdrop click>.
// body: an HTML string, or a callback (el)=>{} that builds the content itself.
function uiModal(spec){
  return new Promise(resolve=>{
    if(_uiModal) uiModalClose(undefined);
    const wrap=document.createElement("div"); wrap.className="ui-modal-wrap";
    const box=document.createElement("div"); box.className="ui-modal";
    box.setAttribute("role","dialog"); box.setAttribute("aria-modal","true");
    if(spec.width) box.style.width=spec.width;
    if(spec.title){
      const hd=document.createElement("div"); hd.className="ui-modal-hd";
      hd.textContent=spec.title; box.appendChild(hd);
      box.setAttribute("aria-label",spec.title);
    }
    const bd=document.createElement("div"); bd.className="ui-modal-bd";
    if(typeof spec.body==="function") spec.body(bd);
    else if(spec.body!=null) bd.innerHTML=spec.body;
    box.appendChild(bd);
    const ft=document.createElement("div"); ft.className="ui-modal-ft";
    let primary=null;
    (spec.buttons||[{label:"OK",value:true,kind:"accent"}]).forEach(b=>{
      const btn=document.createElement("button");
      btn.className="btn"+(b.kind?" "+b.kind:"");
      btn.textContent=b.label;
      btn.onclick=()=>uiModalClose(b.value);
      if(b.kind==="accent"||b.kind==="err"||b.autofocus) primary=btn;
      ft.appendChild(btn);
    });
    box.appendChild(ft);
    wrap.appendChild(box);
    // Backdrop click = cancel (only when press AND release land on the backdrop
    // — dragging to select text doesn't close).
    wrap.addEventListener("mousedown",e=>{ if(e.target===wrap) wrap.dataset.down="1"; });
    wrap.addEventListener("mouseup",e=>{ if(e.target===wrap && wrap.dataset.down) uiModalClose(undefined); delete wrap.dataset.down; });
    const onKey=e=>{
      if(e.key==="Escape"){ e.preventDefault(); e.stopPropagation(); uiModalClose(undefined); return; }
      if(e.key==="Enter" && primary && !(e.target&&e.target.tagName==="TEXTAREA")){
        e.preventDefault(); e.stopPropagation(); primary.click(); return; }
      if(e.key==="Tab"){ // trap focus inside the modal
        const f=box.querySelectorAll("button, input, textarea, select, a[href], [tabindex]:not([tabindex='-1'])");
        if(!f.length) return;
        const first=f[0], last=f[f.length-1];
        if(e.shiftKey && document.activeElement===first){ e.preventDefault(); last.focus(); }
        else if(!e.shiftKey && document.activeElement===last){ e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown",onKey,true);
    _uiModal={wrap, resolve, onKey, prevFocus:document.activeElement};
    document.body.appendChild(wrap);
    const auto=bd.querySelector("input,textarea")||primary||box.querySelector("button");
    if(auto) setTimeout(()=>auto.focus(),0);
  });
}

// ── A11y: every icon-only button gets an aria-label from its title (static chrome, runs once) ──
function uiAriaPass(root){
  (root||document).querySelectorAll("button[title]:not([aria-label])")
    .forEach(b=>b.setAttribute("aria-label", b.getAttribute("title").split("—")[0].trim()));
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>uiAriaPass());
else uiAriaPass();

// ── Confirm / Prompt (replace native confirm()/prompt()) ─────────────────────
// uiConfirm({title, message, ok, cancel, danger}) → Promise<boolean>
function uiConfirm(spec){
  spec = typeof spec==="string" ? {message:spec} : (spec||{});
  return uiModal({
    title: spec.title||"Confirm",
    body: `<div class="ui-modal-msg">${escHtml(spec.message||"")}</div>`,
    buttons: [
      {label: spec.cancel||"Cancel", value:false},
      {label: spec.ok||"OK", value:true, kind: spec.danger?"err":"accent"},
    ],
  }).then(v=>!!v);
}
// ── Shortcuts cheat-sheet (F1 / ?) ───────────────────────────────────────────
const UI_SHORTCUTS = [
  ["File & search", [
    ["Ctrl+S","Save the workflow (Preview: save the selected region)"],
    ["Ctrl+F","Find a block across every activity/function"],
    ["F1  /  ?","This shortcuts sheet"],
  ]],
  ["Canvas", [
    ["Mouse wheel","Zoom (Ctrl+= / Ctrl+− / Ctrl+0)"],
    ["Space / middle mouse","Pan the canvas"],
    ["F","Fit — frame every block in the view"],
    ["Tab","Switch Edit ↔ Preview"],
    ["Right click","Context menu (block / wire / group)"],
  ]],
  ["Editing", [
    ["Ctrl+Z / Ctrl+Y","Undo / redo"],
    ["Ctrl+C / X / V / D","Copy / cut / paste / duplicate"],
    ["Delete","Delete the selected blocks"],
    ["Ctrl+A","Select every block"],
    ["Arrows (Shift = ×10)","Nudge blocks 1px / 10px"],
    ["Hold Alt while dragging","Temporarily disable snap magnetism"],
  ]],
  ["Test runs", [
    ["Ctrl+Enter","Test one block (match overlay on Preview)"],
    ["Debug overlay","Button beside Focus on the Activities panel — on = every match draws on Preview during a run"],
    ["Esc","Stop the run · close panel / clear selection"],
    ["Drop a chip onto a wire","Splice the block into that wire"],
  ]],
];
function uiShowShortcuts(){
  const rows=UI_SHORTCUTS.map(([grp,items])=>
    `<div class="ui-keys-grp">${escHtml(grp)}</div>`+
    items.map(([k,d])=>`<div class="ui-keys-row"><span class="ui-kbd">${escHtml(k)}</span><span>${escHtml(d)}</span></div>`).join("")
  ).join("");
  return uiModal({ title:"Shortcuts", width:"440px",
    body:`<div class="ui-keys">${rows}</div>`,
    buttons:[{label:"Close", value:true, kind:"accent"}] });
}

// uiPrompt({title, label, value, placeholder, ok, cancel}) → Promise<string|null>
function uiPrompt(spec){
  spec=spec||{};
  let inp=null;
  return uiModal({
    title: spec.title||"Enter a value",
    body: el=>{
      if(spec.label){ const l=document.createElement("label"); l.className="ui-modal-lbl"; l.textContent=spec.label; el.appendChild(l); }
      inp=document.createElement("input");
      inp.type="text"; inp.className="ui-modal-inp";
      inp.value=spec.value||""; inp.placeholder=spec.placeholder||"";
      inp.spellcheck=false; inp.autocomplete="off";
      el.appendChild(inp);
      setTimeout(()=>{ inp.focus(); inp.select(); },0);
    },
    buttons: [
      {label: spec.cancel||"Cancel", value:false},
      {label: spec.ok||"OK", value:true, kind:"accent"},
    ],
  }).then(v=> v ? inp.value : null);
}
