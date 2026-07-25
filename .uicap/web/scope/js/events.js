// ── Python events ─────────────────────────────────────────────────────────
window.__recv = function(raw){
  let ev; try{ev=JSON.parse(raw);}catch{return;}
  const{type,data}=ev;
  if(type==="log"){appendLog(data);return;}
  if(type==="log_cleared"){$("log-body").innerHTML="";updateLogCount();return;}
  if(type==="devices_update"){S.devices=data.devices||[];rebuildDeviceSelect(S.devices,S.connectedSerial,null);return;}
  if(type==="device_status"){S.connectedSerial=data.serial||null;setConnected(!!data.connected);rebuildDeviceSelect(S.devices,data.serial,data.serial);return;}
  if(type==="device_info"){INFO_KEYS.forEach(k=>{if(INFO_DOM[k])$(INFO_DOM[k]).textContent=data[k]||"-";});return;}
  if(type==="auto_refresh"){
    S.autoRefresh=!!data.enabled;
    $("auto-cb").classList.toggle("on",S.autoRefresh);
    document.querySelector(".pill-wrap")?.setAttribute("aria-checked",String(S.autoRefresh));
    return;
  }
  if(type==="capture_failed"){setStatus(`Capture failed: ${data.error}`);return;}
  if(type==="captured"){$("res-label").textContent=`${data.w} × ${data.h}`;return;}
  if(type==="overlay"){S.overlay=data.rects||[];draw();return;}
  if(type==="selection_cleared"){S.region=null;S.point=null;S.overlay=[];setRegionBadge(false);draw();return;}
  if(type==="copy_device_info"){
    navigator.clipboard.writeText(INFO_KEYS.map(k=>`${k}: ${$(INFO_DOM[k]).textContent}`).join("\n"));
    setStatus("Device information copied"); return;
  }
  if(type==="out_dir"){updateOutDir(data.path);return;}
  if(type==="capture_backend"){
    S.captureBackend=data.backend||"scrcpy";
    const sel=$("capture-backend"); if(sel) sel.value=S.captureBackend;
    return;
  }
};
window.__recvFrame = function(dataUrl,w,h){
  const img=new Image();
  img.onload=()=>{S.img=img;S.imgW=w;S.imgH=h;recomputeLayout();draw();};
  img.src=dataUrl;
};
