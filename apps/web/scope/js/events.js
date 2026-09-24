// ── Python events ─────────────────────────────────────────────────────────
window.__recv = function(raw){
  let ev; try{ev=JSON.parse(raw);}catch{return;}
  const{type,data}=ev;
  if(type==="log"){
    appendLog(data);
    if(["error","warning","success"].includes(data.level)){
      setOperation(data.msg,data.level==="error"?"failed":data.level);
    }
    return;
  }
  if(type==="log_cleared"){$("log-body").innerHTML="";updateLogCount();return;}
  if(type==="devices_update"){S.devices=data.devices||[];rebuildDeviceSelect(S.devices,S.connectedSerial,null);return;}
  if(type==="device_status"){S.connectedSerial=data.connected?(data.serial||null):null;setConnected(!!data.connected);rebuildDeviceSelect(S.devices,S.connectedSerial,data.serial);return;}
  if(type==="device_info"){INFO_KEYS.forEach(k=>{if(INFO_DOM[k])$(INFO_DOM[k]).textContent=data[k]||"-";});return;}
  if(type==="auto_refresh"){
    S.autoRefresh=!!data.enabled;
    $("auto-cb").classList.toggle("on",S.autoRefresh);
    document.querySelector(".pill-wrap")?.setAttribute("aria-checked",String(S.autoRefresh));
    renderCaptureTelemetry();
    return;
  }
  if(type==="capture_failed"){S.capturePending=false;setOperation(`Capture failed: ${data.error}`,"failed");return;}
  if(type==="captured"){
    // Metadata is not evidence that the image has decoded or been displayed.
    return;
  }
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
    renderCaptureSource();
    return;
  }
};
window.__recvFrame = function(dataUrl,w,h){
  const sequence=++S.frameSequence;
  const receivedAt=performance.now();
  const img=new Image();
  img.onload=()=>{
    if(sequence<S.displayedFrameSequence) return;
    S.displayedFrameSequence=sequence;
    S.img=img;S.imgW=w;S.imgH=h;S.lastFrameAt=receivedAt;
    $("res-label").textContent=`${w} × ${h}`;
    renderCaptureTelemetry();
    if(S.capturePending){S.capturePending=false;setOperation(`Frame displayed · ${w} × ${h}`,"success");}
    recomputeLayout();draw();
  };
  img.onerror=()=>{
    if(sequence<S.displayedFrameSequence) return;
    S.capturePending=false;
    setOperation("Frame decode failed · previous image retained","failed");
  };
  img.src=dataUrl;
};
setInterval(renderCaptureTelemetry,1000);
