// ── Helpers ───────────────────────────────────────────────────────────────
function setStatus(msg){ $("status-text").textContent=msg; }
function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function api(){ return window.pywebview.api; }
function setRegionBadge(on){ $("region-badge").style.display=on?"inline-flex":"none"; }
function setConnected(on){ $("device-dot").className=$("footer-dot").className=on?"connected":""; }

function copyText(text, btn){
  navigator.clipboard.writeText(text);
  if(btn){ btn.classList.add("flash"); setTimeout(()=>btn.classList.remove("flash"),700); }
}
function copyEl(id, btn){ copyText($(id).value, btn); }

function rebuildDeviceSelect(devices, connected, selected){
  const sel=$("device-select"), prev=sel.value;
  sel.innerHTML="";
  if(!devices||!devices.length){
    const o=document.createElement("option"); o.value=""; o.textContent="Không có thiết bị";
    sel.appendChild(o); sel.disabled=true; return;
  }
  sel.disabled=false;
  devices.forEach(d=>{
    const o=document.createElement("option");
    o.value=d.serial||"";
    o.textContent=(d.name||d.serial)+(d.serial?` (${d.serial})`:"");
    sel.appendChild(o);
  });
  sel.value=connected||selected||prev||(devices[0]&&devices[0].serial)||"";
}

function appendLog(entry){
  const body=$("log-body"), line=document.createElement("div");
  line.className="log-line fade-in";
  line.innerHTML=`<span class="log-ts">${entry.ts}</span>`+
    `<span class="log-tag log-${entry.level}">${LOG_TAG[entry.level]||"INF"}</span>`+
    `<span class="log-msg">${escHtml(entry.msg)}</span>`;
  body.appendChild(line);
  while(body.children.length>500) body.removeChild(body.firstChild);
  body.scrollTop=body.scrollHeight;
  updateLogCount();
}
// ── Log drawer (collapsible + copyable) ─────────────────────────────────────
function updateLogCount(){ const c=$("log-count"), b=$("log-body"); if(c&&b) c.textContent = b.children.length? String(b.children.length):""; }
function toggleLog(ev){
  if(ev && ev.target.closest(".btn-log-clear")) return;   // let header buttons act without toggling
  const c=$("log-card"); if(c) c.classList.toggle("collapsed");
}
function onCopyLog(ev){
  if(ev) ev.stopPropagation();
  const b=$("log-body"); if(!b) return;
  const text=[...b.children].map(l=>l.innerText.replace(/\s+/g," ").trim()).join("\n");
  copyText(text, ev&&ev.currentTarget);
}
