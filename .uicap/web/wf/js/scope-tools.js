// ── Scope tool panel (Preview tab inspector) ────────────────────────────────
// Mirrors DevScope's tool handlers but targets the pv-* elements inside the
// workflow designer's inspector and the live preview canvas (preview.js owns the
// frame + overlays). Shares wfPvPoint / wfPvRegion / wfPvOverlay / wfPvDraw.

function pvCopyText(text, btn){
  navigator.clipboard.writeText(text);
  if(btn){ btn.classList.add("flash"); setTimeout(()=>btn.classList.remove("flash"),700); }
}
function pvCopyEl(id, btn){ pvCopyText($(id).value, btn); }

let pvDeviceInfoCopyReady=false;
function pvInitDeviceInfoCopy(){
  if(pvDeviceInfoCopyReady) return;
  const grid=document.querySelector("#pv-tab-device .info-grid");
  if(!grid) return;
  pvDeviceInfoCopyReady=true;
  grid.addEventListener("click", e=>{
    const cell=e.target.closest(".k,.v");
    if(!cell || !grid.contains(cell)) return;
    const cells=[...grid.children];
    const idx=cells.indexOf(cell);
    const val=cells[idx%2===0?idx+1:idx];
    if(!val) return;
    pvCopyText(val.textContent.trim());
    setStatus("Copied");
  });
}

function pvSetRegionBadge(on){ const b=$("pv-region-badge"); if(b) b.style.display=on?"inline-flex":"none"; }

// Fill the Point & Color readouts from a set_point / set_region result.
function pvFillPoint(r){
  if(!r) return;
  $("pv-pt-x").value=r.x; $("pv-pt-y").value=r.y;
  $("pv-tap-x").value=r.x; $("pv-tap-y").value=r.y;
  $("pv-lp-x").value=r.x;  $("pv-lp-y").value=r.y;
  $("pv-cc-x").value=r.x;  $("pv-cc-y").value=r.y;
  if(r.hex){
    $("pv-pt-hex").value=r.hex; $("pv-pt-rgb").value=r.rgb;
    $("pv-color-swatch").style.background=r.hex;
    $("pv-cc-hex").value=r.hex; $("pv-cc-swatch").style.background=r.hex;
  }
}
function pvFillRegion(r){
  if(!r) return;
  $("pv-rg-x").value=r.x; $("pv-rg-y").value=r.y; $("pv-rg-w").value=r.w; $("pv-rg-h").value=r.h;
  $("pv-tap-x").value=r.centerX; $("pv-tap-y").value=r.centerY;
  $("pv-lp-x").value=r.centerX;  $("pv-lp-y").value=r.centerY;
  $("pv-pt-x").value=r.centerX;  $("pv-pt-y").value=r.centerY;
  $("pv-cc-x").value=r.centerX;  $("pv-cc-y").value=r.centerY;
  if(r.hex){
    $("pv-pt-hex").value=r.hex; $("pv-pt-rgb").value=r.rgb;
    $("pv-color-swatch").style.background=r.hex;
    $("pv-cc-hex").value=r.hex; $("pv-cc-swatch").style.background=r.hex;
  }
}

// ── Tabs + collapsible groups (scope parity) ────────────────────────────────
function pvSwitchTab(tab){
  document.querySelectorAll("#wf-scope-panel .tab-btn").forEach(b=>{const on=b.dataset.tab===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on));});
  document.querySelectorAll("#wf-scope-panel .tab-pane").forEach(p=>p.classList.toggle("active",p.id==="pv-tab-"+tab));
  if(tab==="library") pvRefreshAssets();
}
function toggleGrp(hdr){
  const g = hdr.closest ? hdr.closest(".group") : hdr.parentElement;
  if(g){
    const closed=g.classList.toggle("closed");
    hdr.setAttribute("aria-expanded",String(!closed));
  }
}
function pvToggleCheck(button,id){
  const checked=$(id).classList.toggle("checked");
  button.setAttribute("aria-checked",String(checked));
}

// ── Capture / save ──────────────────────────────────────────────────────────
function pvCapture(){ wfPvCapture(); }
async function pvSaveFull(){ await api().save_full($("pv-full-name").value); }
async function pvTapPoint(){ await api().tap(parseInt($("pv-pt-x").value||"0"),parseInt($("pv-pt-y").value||"0")); }

// ── Color check ─────────────────────────────────────────────────────────────
async function pvCheckColor(){
  const r=await api().check_color(parseInt($("pv-cc-x").value||"0"),parseInt($("pv-cc-y").value||"0"),$("pv-cc-hex").value.trim(),parseInt($("pv-cc-tol").value||"10"));
  const el=$("pv-cc-result"); el.style.display="block";
  if(r.error){ el.className="cc-result bad"; el.textContent=r.error; return; }
  el.className="cc-result "+(r.match?"ok":"bad");
  el.innerHTML=r.match
    ?`✓ Match &nbsp;·&nbsp; actual: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`
    :`✗ No match &nbsp;·&nbsp; actual: <b>${escHtml(r.actual)}</b> &nbsp;·&nbsp; Δ${r.dist}`;
}

// ── Region ──────────────────────────────────────────────────────────────────
// "Capture region" saves the current drag-region crop into the open workflow's
// templates/ folder (resolved by the backend) so it's ready to use as a node
// template. The path comes back from Python so we can confirm where it landed.
async function pvQuickCrop(){
  const path = await api().quick_crop($("pv-crop-name").value);
  if(path){ pvRefreshAssets(); setStatus(`Saved region → ${path}`); }
  else setStatus("No region — drag-select a region on the image first");
}
async function pvClearRegion(){
  $("pv-rg-x").value=$("pv-rg-y").value=$("pv-rg-w").value=$("pv-rg-h").value=0;
  await api().clear_selection();
  wfPvRegion=null; wfPvPoint=null; wfPvOverlay=[]; pvSetRegionBadge(false); wfPvDraw();
}

// ── OCR ─────────────────────────────────────────────────────────────────────
async function pvOcrBackendChange(name){
  const r=await api().set_ocr_backend(name);
  const el=$("pv-ocr-engine");
  el.textContent=r.engine+(r.available?" · ready":" · unavailable");
  el.className=r.available?"":"unavailable";
}
async function pvReadText(){ $("pv-ocr-result").value=await api().read_text($("pv-ocr-wl").value); }

// ── Actions ─────────────────────────────────────────────────────────────────
async function pvSendTap(){ await api().tap(parseInt($("pv-tap-x").value||"0"),parseInt($("pv-tap-y").value||"0")); }
async function pvSendLongPress(){ await api().long_press(parseInt($("pv-lp-x").value||"0"),parseInt($("pv-lp-y").value||"0"),parseInt($("pv-lp-dur").value||"800")); }
async function pvSendSwipe(){ await api().swipe(parseInt($("pv-sw-x1").value||"0"),parseInt($("pv-sw-y1").value||"0"),parseInt($("pv-sw-x2").value||"0"),parseInt($("pv-sw-y2").value||"0"),parseInt($("pv-sw-dur").value||"300")); }
async function pvSendText(){ const t=$("pv-inp-text").value; if(t){ await api().input_text(t); $("pv-inp-text").value=""; } }

// ── Template matching ───────────────────────────────────────────────────────
async function pvBrowseTpl(){ const p=await api().pick_template(); if(p) $("pv-tpl-path").value=p; }
async function pvRunMatch(all){
  const r=await api().match_template($("pv-tpl-path").value,parseFloat($("pv-tpl-thr").value||".85"),$("pv-cb-gray").classList.contains("checked"),$("pv-cb-multiscale").classList.contains("checked"),all);
  const el=$("pv-tpl-result");
  if(r.error){ el.textContent=r.error; el.className="tpl-result empty"; return; }
  el.textContent=r.summary; el.className="tpl-result";
  // DevScope match_template returns [x,y,w,h,conf] — treat as ok hits.
  wfPvOverlay=(r.rects||[]).map(rect=>{
    if(Array.isArray(rect) && rect.length===5) return rect.concat([1,""]);
    return rect;
  });
  wfPvMatchRegion=null; wfPvOverlayMeta=r;
  wfPvDraw();
}
async function pvClearOverlay(){ await api().clear_overlay(); wfPvOverlay=[]; wfPvMatchRegion=null; wfPvOverlayMeta=null; wfPvDraw(); }

// ── Asset library ───────────────────────────────────────────────────────────
async function pvRefreshAssets(){
  const list=await api().list_assets();
  const grid=$("pv-asset-grid");
  $("pv-btn-del-asset").style.display="none";
  let sel=null;
  grid.innerHTML="";
  if(!list.length){ grid.innerHTML='<div style="font-size:11.5px;color:var(--muted);padding:4px 0;">No images.</div>'; return; }
  for(const a of list){
    const card=document.createElement("button"); card.type="button"; card.className="asset-card"; card.dataset.path=a.path;
    const thumb=document.createElement("img"); thumb.className="asset-thumb"; thumb.alt=a.name;
    const name=document.createElement("div"); name.className="asset-name"; name.textContent=a.name;
    card.appendChild(thumb); card.appendChild(name);
    card.onclick=()=>{
      document.querySelectorAll("#pv-asset-grid .asset-card").forEach(c=>c.classList.remove("active"));
      card.classList.add("active"); sel=a.path;
      $("pv-btn-del-asset").style.display=""; $("pv-tpl-path").value=a.path;
    };
    card.ondblclick=()=>pvSwitchTab("template");
    grid.appendChild(card);
    api().get_asset_thumbnail(a.path).then(src=>{ if(src) thumb.src=src; });
  }
  // Track selection locally for delete (closure-scoped).
  pvSelAsset=()=>sel;
}
let pvSelAsset=()=>null;
async function pvDeleteAsset(){
  const path=pvSelAsset(); if(!path) return;
  const ok=await uiConfirm({title:"Delete image?", message:`Delete "${path.split("/").pop()}" from disk? This can't be undone.`, ok:"Delete", danger:true});
  if(!ok) return;
  try{ await api().delete_asset(path); }catch{}
  pvRefreshAssets();
}

// ── Output dir label ─────────────────────────────────────────────────────────
function pvUpdateOutDir(p){
  const norm=String(p).replace(/\\/g,'/');
  const parts=norm.split('/').filter(Boolean);
  const short=parts.length>1?'…/'+parts.slice(-2).join('/')+'/' : (norm.endsWith('/')?norm:norm+'/');
  const lbl=$("pv-out-dir-label"); if(lbl){ lbl.textContent=short; lbl.title=p; }
  const lib=$("pv-lib-out-label"); if(lib){ lib.textContent=short; lib.title=p; }
}

// ── Populate OCR backend dropdown from get_state ───────────────────────────
async function pvInitOcrBackends(){
  const sel=$("pv-ocr-backend"); if(!sel) return;
  let backs=[];
  try{ const st=await api().get_state(); backs=st.ocrBackends||[]; }catch{}
  if(!backs.length) backs=["tesseract","easyocr","paddleocr"];
  sel.innerHTML="";
  backs.forEach(b=>{ const o=document.createElement("option"); o.value=b; o.textContent=b; sel.appendChild(o); });
  if(sel.options.length){ await pvOcrBackendChange(sel.value); }
}
