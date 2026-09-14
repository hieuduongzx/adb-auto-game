// ── Library tab — the workflow's template folder, audited ─────────────────────
//
// Templates are this project's real currency (a `tap_image` block is ~30% of
// the nodes in a mature flow), and the folder grows by hand-cropping: the same
// button gets cropped twice, a node is deleted and its image stays behind. On
// the real GirlWars flow that left 149 of 269 files unreferenced, and nothing
// in the tool said so.
//
// So this view answers three questions at a glance:
//   · what does this workflow actually use?      → Used / Orphan filters
//   · what does it use that is not there?        → Missing
//   · which of these are the same crop twice?    → Duplicates
//
// The listing comes from `list_templates`, which pairs the files on disk with
// the nodes that reference them using the same walk the save-time bundler uses
// — so the Library and the bundle can never disagree about what is used.

let wfLibState = null;      // last list_templates() payload
let wfLibFlowSig = "";      // the flow JSON wfLibState was built from
let wfLibFilterMode = "all";
let wfLibQuery = "";
let wfLibSelected = "";     // path of the selected template
let wfLibOverlay = null;    // "dupes" | "trash" | null — which side view is open

// ── Data ─────────────────────────────────────────────────────────────────────

// The live flow travels to Python, so the Library reflects the canvas as it is
// now — unsaved edits included. Deleting a block should make its template show
// up as an orphan immediately, not after the next save.
function wfLibFlowJson(){
  try{ return JSON.stringify(wfSerialize()); }
  catch{ return ""; }
}

async function wfLibOpen(){
  // Reuse the last index only while the canvas still matches the flow it was
  // built from: edit a block, come back here, and the counts must not be stale.
  if(wfLibState && !wfLibOverlay && wfLibFlowJson()===wfLibFlowSig){ wfLibRender(); return; }
  await wfLibRefresh();
}

async function wfLibRefresh(){
  const grid=$("wf-lib-grid");
  if(grid) wfLibPlaceholder(grid, "Đang đọc thư mục template…");
  const sig=wfLibFlowJson();
  let data=null;
  try{ data=await api().list_templates(sig); }catch(e){}
  if(!data){ if(grid) wfLibPlaceholder(grid, "Không đọc được thư mục template."); return; }
  wfLibState=data;
  wfLibFlowSig=sig;
  wfLibOverlay=null;
  // Drop a selection whose file is gone (deleted, renamed, or the workflow
  // changed under us) rather than leaving a stale detail panel open.
  const paths=(data.templates||[]).map(t=>t.path);
  if(wfLibSelected && !paths.includes(wfLibSelected)) wfLibSelected="";
  wfLibRender();
}

function wfLibPlaceholder(host, text){
  host.innerHTML="";
  const d=document.createElement("div");
  d.className="wf-lib-empty"; d.textContent=text;
  host.appendChild(d);
}

// A template passes when it satisfies the chip AND the search box, so narrowing
// by "Orphan" and then typing part of a name both work at once.
function wfLibMatches(t){
  if(wfLibQuery && !t.name.toLowerCase().includes(wfLibQuery)) return false;
  if(wfLibFilterMode==="used")   return t.usedCount>0;
  if(wfLibFilterMode==="orphan") return t.usedCount===0;
  return true;
}

// Missing references are not files, so they are a separate list from `templates`
// — which is why that filter is handled by its own renderer rather than by
// wfLibMatches.
function wfLibMissingRows(){
  const rows=(wfLibState&&wfLibState.missing)||[];
  if(!wfLibQuery) return rows;
  return rows.filter(m=>String(m.name).toLowerCase().includes(wfLibQuery));
}

// ── Render ───────────────────────────────────────────────────────────────────

function wfLibRender(){
  if(!wfLibState) return;
  wfLibRenderBar();
  if(wfLibOverlay==="dupes"){ wfLibRenderDupes(); return; }
  if(wfLibOverlay==="trash"){ wfLibRenderTrash(); return; }
  if(wfLibFilterMode==="missing"){ wfLibRenderMissing(); return; }
  wfLibRenderGrid();
}

function wfLibRenderBar(){
  const c=wfLibState.counts||{};
  const el=$("wf-lib-counts");
  if(el){
    const bits=[`${c.total||0} template`];
    if(c.orphan) bits.push(`${c.orphan} không dùng`);
    if(c.missing) bits.push(`${c.missing} thiếu file`);
    el.textContent=bits.join(" · ");
    el.classList.toggle("has-warn", !!c.missing);
  }
  const p=$("wf-lib-path");
  if(p){ p.textContent="📁 "+(wfLibState.dir||""); p.title=wfLibState.dir||""; }
  document.querySelectorAll("#wf-lib-filters .log-f").forEach(b=>{
    b.classList.toggle("on", !wfLibOverlay && b.dataset.lf===wfLibFilterMode);
    if(b.dataset.lf==="orphan") b.textContent = c.orphan ? `Orphan (${c.orphan})` : "Orphan";
    if(b.dataset.lf==="missing") b.textContent = c.missing ? `Missing (${c.missing})` : "Missing";
  });
}

function wfLibRenderGrid(){
  const grid=$("wf-lib-grid"); if(!grid) return;
  grid.innerHTML="";
  const all=wfLibState.templates||[];
  const shown=all.filter(wfLibMatches);
  if(!shown.length){
    wfLibPlaceholder(grid, all.length
      ? "Không có template nào khớp bộ lọc."
      : "Thư mục template đang trống — crop một vùng ở tab Preview để tạo cái đầu tiên.");
    wfLibRenderSide();
    return;
  }
  const frag=document.createDocumentFragment();
  for(const t of shown) frag.appendChild(wfLibCard(t));
  grid.appendChild(frag);
  wfLibRenderSide();
}

function wfLibCard(t){
  const card=document.createElement("button");
  card.type="button";
  card.className="asset-card wf-lib-card"+(t.path===wfLibSelected?" active":"")
    +(t.usedCount?" is-used":" is-orphan");
  card.dataset.path=t.path;
  card.title=t.usedCount
    ? `${t.name}\n${t.usedCount} block dùng file này`
    : `${t.name}\nKhông block nào dùng file này`;
  const thumb=document.createElement("img");
  thumb.className="asset-thumb"; thumb.alt=t.name; thumb.loading="lazy";
  // Fetch per card, bound to this element: a querySelector pass would re-scan
  // 269 cards for every thumbnail, which is O(n²) on the stress-case flow.
  api().template_thumbnail(t.path).then(src=>{ if(src) thumb.src=src; });
  const name=document.createElement("div");
  name.className="asset-name"; name.textContent=t.name;
  const meta=document.createElement("div");
  meta.className="wf-lib-meta";
  const dim=t.w?`${t.w}×${t.h}`:"?";
  meta.textContent=t.usedCount ? `${dim} · ${t.usedCount} block` : `${dim} · không dùng`;
  card.append(thumb, name, meta);
  card.onclick=()=>wfLibSelect(t.path);
  return card;
}

// Selecting repaints only the affected classes and the side panel — a full grid
// re-render would refetch every thumbnail just to move one highlight.
function wfLibSelect(path){
  wfLibSelected=path;
  document.querySelectorAll("#wf-lib-grid .wf-lib-card").forEach(c=>
    c.classList.toggle("active", c.dataset.path===path));
  wfLibRenderSide();
}

// ── Detail panel ─────────────────────────────────────────────────────────────

function wfLibRenderSide(){
  const side=$("wf-lib-side"); if(!side) return;
  side.innerHTML="";
  const t=(wfLibState.templates||[]).find(x=>x.path===wfLibSelected);
  if(!t){
    const hint=document.createElement("div");
    hint.className="wf-lib-empty";
    hint.textContent="Chọn một template để xem block nào đang dùng nó.";
    side.appendChild(hint);
    return;
  }
  const head=document.createElement("div");
  head.className="wf-lib-side-hd";
  const title=document.createElement("div");
  title.className="wf-lib-side-name"; title.textContent=t.name; title.title=t.name;
  head.appendChild(title);
  const sub=document.createElement("div");
  sub.className="wf-lib-side-sub";
  sub.textContent=[t.w&&t.h?`${t.w}×${t.h}`:null, wfLibFmtSize(t.size)].filter(Boolean).join(" · ");
  head.appendChild(sub);
  side.appendChild(head);

  if(!t.usedCount){
    const warn=document.createElement("div");
    warn.className="wf-lib-note";
    warn.textContent="Không block nào trong workflow dùng file này.";
    side.appendChild(warn);
  } else {
    const lbl=document.createElement("div");
    lbl.className="wf-lib-side-lbl";
    lbl.textContent=`Dùng bởi ${t.usedCount} block`;
    side.appendChild(lbl);
    const list=document.createElement("div");
    list.className="wf-lib-uses";
    for(const u of t.used){
      const row=document.createElement("button");
      row.type="button"; row.className="wf-lib-use";
      row.title="Nhảy tới block này trên canvas";
      const a=document.createElement("span");
      a.className="wf-lib-use-act"; a.textContent=(u.ownerKind==="function"?"ƒ ":"")+u.activity;
      const b=document.createElement("span");
      b.className="wf-lib-use-node"; b.textContent=u.nodeLabel;
      row.append(a, b);
      row.onclick=()=>{ if(!wfJumpToNode(u.nodeId)) uiToast("Không tìm thấy block này","warning"); };
      list.appendChild(row);
    }
    side.appendChild(list);
  }

  const acts=document.createElement("div");
  acts.className="wf-lib-acts";
  const ren=document.createElement("button");
  ren.type="button"; ren.className="btn sm"; ren.textContent="Đổi tên";
  ren.title="Đổi tên file và cập nhật mọi block đang trỏ tới nó";
  ren.onclick=()=>wfLibRename(t);
  const del=document.createElement("button");
  del.type="button"; del.className="btn sm err"; del.textContent="Xoá";
  del.title="Chuyển file vào _trash/ (vẫn khôi phục được)";
  del.onclick=()=>wfLibDelete(t);
  acts.append(ren, del);
  side.appendChild(acts);
}

function wfLibFmtSize(n){
  if(!n) return "";
  if(n<1024) return n+" B";
  if(n<1024*1024) return (n/1024).toFixed(1)+" KB";
  return (n/1048576).toFixed(1)+" MB";
}

// ── Missing references ───────────────────────────────────────────────────────

function wfLibRenderMissing(){
  const grid=$("wf-lib-grid"); if(!grid) return;
  grid.innerHTML="";
  const rows=wfLibMissingRows();
  if(!rows.length){
    wfLibPlaceholder(grid, "Mọi template mà block tham chiếu đều có trên đĩa.");
    wfLibRenderSide();
    return;
  }
  const note=document.createElement("div");
  note.className="wf-lib-empty";
  note.textContent="Các block dưới đây trỏ tới file không có trong thư mục — chúng sẽ fail khi chạy.";
  grid.appendChild(note);
  for(const m of rows){
    const row=document.createElement("button");
    row.type="button"; row.className="wf-lib-miss";
    const n=document.createElement("span");
    n.className="wf-lib-miss-name"; n.textContent=m.name;
    const w=document.createElement("span");
    w.className="wf-lib-miss-where";
    w.textContent=`${m.nodeLabel} · ${(m.ownerKind==="function"?"ƒ ":"")+m.activity} · ${m.raw}`;
    row.append(n, w);
    row.onclick=()=>{ if(!wfJumpToNode(m.nodeId)) uiToast("Không tìm thấy block này","warning"); };
    grid.appendChild(row);
  }
  wfLibRenderSide();
}

// ── Duplicates ───────────────────────────────────────────────────────────────

async function wfLibShowDupes(){
  const grid=$("wf-lib-grid"); if(!grid) return;
  wfLibSelected="";
  wfLibOverlay="dupes";
  wfLibRenderBar();
  wfLibPlaceholder(grid, "Đang so sánh ảnh…");
  let out=null;
  try{ out=await api().find_duplicate_templates(4); }catch(e){}
  if(wfLibOverlay!=="dupes") return;                 // user navigated away
  if(!out){ wfLibPlaceholder(grid, "Không quét được ảnh."); return; }
  wfLibRenderDupes(out);
}

function wfLibRenderDupes(out){
  const grid=$("wf-lib-grid"); if(!grid) return;
  grid.innerHTML="";
  out = out || wfLibState.dupes;
  if(!out){ wfLibPlaceholder(grid, "Không quét được ảnh."); return; }
  wfLibState.dupes=out;
  const groups=out.groups||[];
  const head=document.createElement("div");
  head.className="wf-lib-empty";
  head.textContent=groups.length
    ? `${groups.length} nhóm ảnh giống nhau (đã quét ${out.scanned} file). Giữ một cái, xoá phần còn lại.`
    : `Không tìm thấy ảnh trùng nhau (đã quét ${out.scanned} file).`;
  grid.appendChild(head);
  for(const g of groups){
    const box=document.createElement("div");
    box.className="wf-lib-dupgroup";
    const t=document.createElement("div");
    t.className="wf-lib-dup-hd";
    t.textContent=`${g.w}×${g.h} · ${g.files.length} file`;
    box.appendChild(t);
    for(const f of g.files){
      const row=document.createElement("div");
      row.className="wf-lib-dup-row";
      const img=document.createElement("img");
      img.className="asset-thumb wf-lib-dup-thumb"; img.alt=f.name;
      api().template_thumbnail(f.path).then(src=>{ if(src) img.src=src; });
      const nm=document.createElement("span");
      nm.className="wf-lib-dup-name"; nm.textContent=f.name; nm.title=f.name;
      const sz=document.createElement("span");
      sz.className="wf-lib-dup-size"; sz.textContent=wfLibFmtSize(f.size);
      const del=document.createElement("button");
      del.type="button"; del.className="btn sm err"; del.textContent="Xoá";
      del.onclick=()=>wfLibDelete({name:f.name, path:f.path, usedCount:0});
      row.append(img, nm, sz, del);
      box.appendChild(row);
    }
    grid.appendChild(box);
  }
  wfLibRenderSide();
}

// ── Trash ────────────────────────────────────────────────────────────────────

async function wfLibShowTrash(){
  const grid=$("wf-lib-grid"); if(!grid) return;
  wfLibSelected="";
  wfLibOverlay="trash";
  wfLibRenderBar();
  wfLibPlaceholder(grid, "Đang đọc _trash/…");
  let items=[];
  try{ items=await api().list_trash(); }catch(e){}
  if(wfLibOverlay!=="trash") return;
  wfLibRenderTrash(items);
}

function wfLibRenderTrash(items){
  const grid=$("wf-lib-grid"); if(!grid) return;
  grid.innerHTML="";
  const list=Array.isArray(items) ? items : (wfLibState.trash||[]);
  wfLibState.trash=list;
  if(!list.length){
    wfLibPlaceholder(grid, "_trash/ đang trống.");
    wfLibRenderSide(); return;
  }
  const head=document.createElement("div");
  head.className="wf-lib-empty";
  head.textContent=`${list.length} file đã xoá — vẫn nằm trên đĩa trong _trash/.`;
  grid.appendChild(head);
  for(const it of list){
    const row=document.createElement("div");
    row.className="wf-lib-dup-row";
    const img=document.createElement("img");
    img.className="asset-thumb wf-lib-dup-thumb"; img.alt=it.name;
    api().template_thumbnail(it.path).then(src=>{ if(src) img.src=src; });
    const nm=document.createElement("span");
    nm.className="wf-lib-dup-name"; nm.textContent=it.name; nm.title=it.name;
    const sz=document.createElement("span");
    sz.className="wf-lib-dup-size"; sz.textContent=wfLibFmtSize(it.size);
    const back=document.createElement("button");
    back.type="button"; back.className="btn sm"; back.textContent="Khôi phục";
    back.onclick=async()=>{
      const r=await api().template_restore(it.path);
      if(r && r.ok){ uiToast(`Đã khôi phục ${r.name}`,"success"); wfLibShowTrash(); }
      else uiToast((r&&r.error)||"Không khôi phục được","error");
    };
    row.append(img, nm, sz, back);
    grid.appendChild(row);
  }
  wfLibRenderSide();
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function wfLibDelete(t){
  const used=t.usedCount||0;
  const ok=await uiConfirm({
    title:"Xoá template?",
    message: used
      ? `"${t.name}" đang được ${used} block dùng. Xoá thì các block đó sẽ fail khi chạy.\n\nFile được chuyển vào _trash/ nên vẫn khôi phục được.`
      : `Chuyển "${t.name}" vào _trash/? File vẫn nằm trên đĩa và khôi phục được từ nút Trash.`,
    ok:"Xoá", danger:true,
  });
  if(!ok) return;
  const back=wfLibOverlay;               // stay in the dedupe/trash view if we were there
  const r=await api().template_delete(t.path);
  if(!r || !r.ok){ uiToast((r&&r.error)||"Không xoá được","error"); return; }
  uiToast(`Đã chuyển ${r.name} vào _trash/`,"success");
  wfLibState.dupes=null;                 // the cached duplicate groups are now stale
  await wfLibRefresh();
  // Deleting is how you work through a duplicate set, so return the user to the
  // groups they were pruning rather than to the full grid.
  if(back==="dupes") await wfLibShowDupes();
}

async function wfLibRename(t){
  const newName=await uiPrompt({
    title:"Đổi tên template",
    label:`Mọi block đang trỏ tới "${t.name}" sẽ được cập nhật theo.`,
    value: t.name.replace(/\.[^.]+$/,""),
    placeholder:"tên file mới (không cần .png)",
    ok:"Đổi tên",
  });
  if(!newName || !String(newName).trim()) return;
  const flowJson=wfLibFlowJson();
  // One undo snapshot before the rename lands, so Ctrl+Z restores the file's
  // references and the block params together.
  if(typeof wfPushUndo==="function") wfPushUndo();
  const r=await api().rename_template(flowJson, t.path, String(newName).trim());
  if(!r || !r.ok){ uiToast((r&&r.error)||"Không đổi tên được","error"); return; }
  if(r.flow) wfLibApplyRename(r.flow);
  uiToast(`Đã đổi tên thành ${r.new} (${r.nodes} block cập nhật)`,"success");
  await wfLibRefresh();
}

// The rewrite happened Python-side on JSON we produced, so the only thing that
// can differ from the live canvas is the template params themselves. Patching
// them in by node id keeps the camera, the selection and the open activity —
// re-hydrating the whole flow for a filename change would throw away all three.
function wfLibApplyRename(flowJson){
  let flow=null;
  try{ flow=JSON.parse(flowJson); }catch{ return false; }
  const patched=new Map();
  const scan=g=>((g&&g.nodes)||[]).forEach(n=>{
    const p=n&&n.params; if(!p) return;
    const keep={};
    if(p.template!==undefined)  keep.template=p.template;
    if(p.templates!==undefined) keep.templates=p.templates;
    if(Object.keys(keep).length) patched.set(n.id, keep);
  });
  (flow.activities||[]).forEach(a=>scan(a.graph));
  (flow.functions||[]).forEach(f=>scan(f.graph));
  if(!patched.size) return false;
  let touched=0;
  const apply=g=>((g&&g.nodes)||[]).forEach(n=>{
    const keep=patched.get(n.id);
    if(!keep || !n.params) return;
    Object.assign(n.params, keep);
    touched++;
  });
  WF.activities.forEach(a=>apply(a.graph));
  WF.functions.forEach(f=>apply(f.graph));
  if(!touched) return false;
  if(typeof wfMarkDirty==="function") wfMarkDirty();   // the new paths need saving
  if(typeof wfRenderCanvas==="function") wfRenderCanvas();
  return true;
}

// ── Wiring ───────────────────────────────────────────────────────────────────

function wfLibFilter(mode, ev){
  if(ev) ev.stopPropagation();
  wfLibFilterMode=mode||"all";
  wfLibOverlay=null;                    // a chip always returns to the file grid
  wfLibRender();
}
function wfLibSearch(q){
  wfLibQuery=(q||"").trim().toLowerCase();
  wfLibRender();
}
