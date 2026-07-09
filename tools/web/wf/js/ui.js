// ── UI kit: toast + modal (thay thế alert/prompt/confirm gốc) ────────────────
// Toast: phản hồi nhanh không chặn (lưu xong, lỗi import, đã copy…).
// Modal: hỏi/xác nhận có chặn — uiConfirm/uiPrompt trả Promise nên call-site
// chuyển từ sync (confirm()) sang .then()/await mà không đổi luồng logic.
// Focus được trap trong modal và trả về đúng chỗ cũ khi đóng — Esc = hủy,
// Enter = nút chính, click nền = hủy.

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
// uiToast("Đã lưu", "success") — level: info | success | warning | error.
function uiToast(msg, level, opts){
  level = UI_TOAST_ICO[level] ? level : "info";
  opts = opts||{};
  const host=uiToastHost();
  const t=document.createElement("div");
  t.className="ui-toast ui-"+level;
  t.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${UI_TOAST_ICO[level]}</svg>`+
    `<span class="ui-toast-msg">${escHtml(String(msg))}</span>`;
  t.title="Bấm để đóng";
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
// Một modal mở tại một thời điểm; mở chồng sẽ đóng cái trước (trả lời "hủy").
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
// → Promise<value của nút bấm | undefined khi Esc/click nền>.
// body: chuỗi HTML hoặc callback (el)=>{} tự dựng nội dung.
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
    // Click nền = hủy (chỉ khi nhấn VÀ nhả trên nền — kéo chọn chữ không đóng).
    wrap.addEventListener("mousedown",e=>{ if(e.target===wrap) wrap.dataset.down="1"; });
    wrap.addEventListener("mouseup",e=>{ if(e.target===wrap && wrap.dataset.down) uiModalClose(undefined); delete wrap.dataset.down; });
    const onKey=e=>{
      if(e.key==="Escape"){ e.preventDefault(); e.stopPropagation(); uiModalClose(undefined); return; }
      if(e.key==="Enter" && primary && !(e.target&&e.target.tagName==="TEXTAREA")){
        e.preventDefault(); e.stopPropagation(); primary.click(); return; }
      if(e.key==="Tab"){ // trap focus trong modal
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

// ── A11y: mọi nút chỉ-icon lấy aria-label từ title (chrome tĩnh, chạy 1 lần) ──
function uiAriaPass(root){
  (root||document).querySelectorAll("button[title]:not([aria-label])")
    .forEach(b=>b.setAttribute("aria-label", b.getAttribute("title").split("—")[0].trim()));
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>uiAriaPass());
else uiAriaPass();

// ── Confirm / Prompt (thay confirm()/prompt() gốc) ───────────────────────────
// uiConfirm({title, message, ok, cancel, danger}) → Promise<boolean>
function uiConfirm(spec){
  spec = typeof spec==="string" ? {message:spec} : (spec||{});
  return uiModal({
    title: spec.title||"Xác nhận",
    body: `<div class="ui-modal-msg">${escHtml(spec.message||"")}</div>`,
    buttons: [
      {label: spec.cancel||"Hủy", value:false},
      {label: spec.ok||"OK", value:true, kind: spec.danger?"err":"accent"},
    ],
  }).then(v=>!!v);
}
// ── Bảng phím tắt (F1 / ?) ───────────────────────────────────────────────────
const UI_SHORTCUTS = [
  ["Tệp & tìm kiếm", [
    ["Ctrl+S","Lưu workflow (Preview: lưu vùng chọn)"],
    ["Ctrl+F","Tìm block trong mọi activity/function"],
    ["F1  /  ?","Bảng phím tắt này"],
  ]],
  ["Canvas", [
    ["Lăn chuột","Zoom (Ctrl+= / Ctrl+− / Ctrl+0)"],
    ["Space / chuột giữa","Kéo canvas (pan)"],
    ["F","Fit — thu toàn bộ block vào khung"],
    ["Tab","Đổi Edit ↔ Preview"],
    ["Chuột phải","Menu ngữ cảnh (block / dây / group)"],
  ]],
  ["Chỉnh sửa", [
    ["Ctrl+Z / Ctrl+Y","Hoàn tác / làm lại"],
    ["Ctrl+C / X / V / D","Copy / cắt / dán / nhân đôi"],
    ["Delete","Xóa block đã chọn"],
    ["Ctrl+A","Chọn tất cả block"],
    ["Mũi tên (Shift = ×10)","Dịch block 1px / 10px"],
    ["Giữ Alt khi kéo","Tắt hít nam châm tạm thời"],
  ]],
  ["Chạy thử", [
    ["Ctrl+Enter","Test 1 block (match overlay trên Preview)"],
    ["Debug overlay","Nút cạnh Focus trên panel Activities — bật để mọi match vẽ lên Preview khi run"],
    ["Esc","Dừng run · đóng panel/bỏ chọn"],
    ["Kéo thả chip lên dây","Chèn block vào giữa dây"],
  ]],
];
function uiShowShortcuts(){
  const rows=UI_SHORTCUTS.map(([grp,items])=>
    `<div class="ui-keys-grp">${escHtml(grp)}</div>`+
    items.map(([k,d])=>`<div class="ui-keys-row"><span class="ui-kbd">${escHtml(k)}</span><span>${escHtml(d)}</span></div>`).join("")
  ).join("");
  return uiModal({ title:"Phím tắt", width:"440px",
    body:`<div class="ui-keys">${rows}</div>`,
    buttons:[{label:"Đóng", value:true, kind:"accent"}] });
}

// uiPrompt({title, label, value, placeholder, ok, cancel}) → Promise<string|null>
function uiPrompt(spec){
  spec=spec||{};
  let inp=null;
  return uiModal({
    title: spec.title||"Nhập giá trị",
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
      {label: spec.cancel||"Hủy", value:false},
      {label: spec.ok||"OK", value:true, kind:"accent"},
    ],
  }).then(v=> v ? inp.value : null);
}
