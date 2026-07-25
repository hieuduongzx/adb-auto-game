// ── Asset library ──────────────────────────────────────────────────────────
async function onRefreshAssets(){
  const list=await api().list_assets();
  const grid=$("asset-grid"); S.selectedAsset=null; $("btn-del-asset").style.display="none";
  grid.innerHTML="";
  if(!list.length){grid.innerHTML='<div style="font-size:11.5px;color:var(--muted);padding:4px 0;">No images yet.</div>';return;}
  for(const a of list){
    const card=document.createElement("button"); card.type="button"; card.className="asset-card"; card.dataset.path=a.path;
    const thumb=document.createElement("img"); thumb.className="asset-thumb"; thumb.alt=a.name;
    const name=document.createElement("div"); name.className="asset-name"; name.textContent=a.name;
    card.appendChild(thumb); card.appendChild(name);
    card.onclick=()=>{
      document.querySelectorAll(".asset-card").forEach(c=>c.classList.remove("active"));
      card.classList.add("active"); S.selectedAsset=a.path;
      $("btn-del-asset").style.display=""; $("tpl-path").value=a.path;
    };
    card.ondblclick=()=>switchTab("template");
    grid.appendChild(card);
    api().get_asset_thumbnail(a.path).then(src=>{if(src)thumb.src=src;});
  }
}
async function onDeleteAsset(){
  if(!S.selectedAsset||!confirm(`Delete ${S.selectedAsset.split("/").pop()}?`)) return;
  try{await api().delete_asset(S.selectedAsset);}catch{}
  onRefreshAssets();
}
