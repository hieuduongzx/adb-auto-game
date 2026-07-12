// ── Canvas layout ─────────────────────────────────────────────────────────
function resizeCanvas(){
  const w=$("preview-wrap");
  canvas.width=w.clientWidth; canvas.height=w.clientHeight;
  recomputeLayout(); draw();
}
window.addEventListener("resize", resizeCanvas);

function recomputeLayout(){
  if(!S.img||!S.imgW){S.scale=1;S.ox=0;S.oy=0;return;}
  const cw=Math.max(1,canvas.width), ch=Math.max(1,canvas.height);
  S.scale=Math.min(cw/S.imgW, ch/S.imgH);
  const ef=S.scale*S.zoomLevel;
  S.ox=(cw-S.imgW*ef)/2+S.panX;
  S.oy=(ch-S.imgH*ef)/2+S.panY;
}
function imgToCanvas(x,y){ const ef=S.scale*S.zoomLevel; return[S.ox+x*ef,S.oy+y*ef]; }
function canvasToImg(cx,cy){
  const ef=S.scale*S.zoomLevel; if(!ef) return null;
  const ix=Math.round((cx-S.ox)/ef), iy=Math.round((cy-S.oy)/ef);
  if(ix<0||iy<0||ix>=S.imgW||iy>=S.imgH) return null;
  return [ix,iy];
}

function draw(){
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(!S.img){
    ctx.fillStyle="#9aa3ae"; ctx.font="13px IBM Plex Sans,Segoe UI,sans-serif";
    ctx.textAlign="center";
    ctx.fillText("Chưa có ảnh chụp. Nhấn Chụp (F5).",canvas.width/2,canvas.height/2);
    return;
  }
  const [x0,y0]=imgToCanvas(0,0), [x1,y1]=imgToCanvas(S.imgW,S.imgH);
  ctx.fillStyle="#121316"; ctx.fillRect(x0,y0,x1-x0,y1-y0);
  ctx.imageSmoothingEnabled=true; ctx.drawImage(S.img,x0,y0,x1-x0,y1-y0);

  ctx.strokeStyle="#dc2626"; ctx.lineWidth=2;
  ctx.fillStyle="#dc2626"; ctx.font="11px IBM Plex Mono,monospace"; ctx.textAlign="left";
  for(const[rx,ry,rw,rh,conf] of S.overlay){
    const[cx,cy]=imgToCanvas(rx,ry),[cx2,cy2]=imgToCanvas(rx+rw,ry+rh);
    ctx.strokeRect(cx,cy,cx2-cx,cy2-cy);
    ctx.fillText(conf.toFixed(2),cx+2,cy-4);
  }
  if(S.region){
    const[x,y,w,h]=S.region;
    const[cx,cy]=imgToCanvas(x,y),[cx2,cy2]=imgToCanvas(x+w,y+h);
    ctx.strokeStyle="#06b6d4"; ctx.lineWidth=2; ctx.strokeRect(cx,cy,cx2-cx,cy2-cy);
  }
  if(S.point){
    const[cx,cy]=imgToCanvas(S.point[0],S.point[1]);
    ctx.strokeStyle="#eab308"; ctx.lineWidth=2;
    ctx.beginPath();
    ctx.moveTo(cx-8,cy); ctx.lineTo(cx+8,cy);
    ctx.moveTo(cx,cy-8); ctx.lineTo(cx,cy+8);
    ctx.stroke();
  }
  if(S.dragging&&S.dragStart&&S.dragEnd){
    const r=normRect(S.dragStart,S.dragEnd);
    ctx.strokeStyle="rgba(6,182,212,.8)"; ctx.lineWidth=1;
    ctx.strokeRect(r.x,r.y,r.w,r.h);
  }
}
function normRect(a,b){
  return{x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),w:Math.abs(a[0]-b[0]),h:Math.abs(a[1]-b[1])};
}

// ── Canvas events ──────────────────────────────────────────────────────────
function canvasPos(e){ const r=canvas.getBoundingClientRect(); return[e.clientX-r.left,e.clientY-r.top]; }

canvas.onmousedown = e => {
  if(e.button===1){e.preventDefault();S.panning=true;S.panStart=canvasPos(e);S.panBase=[S.panX,S.panY];canvas.style.cursor="grab";return;}
  if(!S.img||e.button!==0) return;
  S.dragging=true; S.dragStart=canvasPos(e); S.dragEnd=S.dragStart.slice();
};
canvas.onmousemove = e => {
  const[cx,cy]=canvasPos(e);
  if(S.panning){S.panX=S.panBase[0]+cx-S.panStart[0];S.panY=S.panBase[1]+cy-S.panStart[1];recomputeLayout();draw();return;}
  const p=canvasToImg(cx,cy);
  $("hover-pos").textContent=p?`${p[0]}, ${p[1]}`:"—";
  if(S.dragging){S.dragEnd=[cx,cy];draw();}
};
canvas.onmouseup = async e => {
  if(e.button===1){S.panning=false;canvas.style.cursor="crosshair";return;}
  if(e.button!==0||!S.dragging){S.dragging=false;return;}
  S.dragging=false;
  const start=S.dragStart, end=S.dragEnd=canvasPos(e);
  S.dragStart=S.dragEnd=null;
  const dx=Math.abs(end[0]-start[0]),dy=Math.abs(end[1]-start[1]);
  if(dx+dy<5){
    const p=canvasToImg(end[0],end[1]); if(!p){draw();return;}
    S.point=p; S.region=null; setRegionBadge(false);
    const r=await api().set_point(p[0],p[1]);
    $("pt-x").value=r.x; $("pt-y").value=r.y;
    $("tap-x").value=r.x; $("tap-y").value=r.y;
    $("lp-x").value=r.x;  $("lp-y").value=r.y;
    $("cc-x").value=r.x;  $("cc-y").value=r.y;
    if(r.hex){
      $("pt-hex").value=r.hex; $("pt-rgb").value=r.rgb;
      $("color-swatch").style.background=r.hex;
      $("cc-hex").value=r.hex; $("cc-swatch").style.background=r.hex;
    }
    setStatus(`Đã chọn (${r.x}, ${r.y})`);
  } else {
    const p1=canvasToImg(start[0],start[1]),p2=canvasToImg(end[0],end[1]);
    if(!p1||!p2){draw();return;}
    const x=Math.min(p1[0],p2[0]),y=Math.min(p1[1],p2[1]);
    const w=Math.abs(p2[0]-p1[0]),h=Math.abs(p2[1]-p1[1]);
    if(w<=1||h<=1){draw();return;}
    S.region=[x,y,w,h]; S.point=null; setRegionBadge(true);
    const r=await api().set_region(x,y,w,h);
    $("rg-x").value=r.x; $("rg-y").value=r.y; $("rg-w").value=r.w; $("rg-h").value=r.h;
    $("tap-x").value=r.centerX; $("tap-y").value=r.centerY;
    $("lp-x").value=r.centerX;  $("lp-y").value=r.centerY;
    $("pt-x").value=r.centerX;  $("pt-y").value=r.centerY;
    $("cc-x").value=r.centerX;  $("cc-y").value=r.centerY;
    if(r.hex){
      $("pt-hex").value=r.hex; $("pt-rgb").value=r.rgb;
      $("color-swatch").style.background=r.hex;
      $("cc-hex").value=r.hex; $("cc-swatch").style.background=r.hex;
    }
    setStatus(`Vùng ${x},${y} · ${w}×${h} — chạm=(${r.centerX},${r.centerY})`);
  }
  draw();
};
canvas.onmouseleave = () => {
  if(S.dragging){S.dragging=false;draw();}
  if(S.panning){S.panning=false;canvas.style.cursor="crosshair";}
  $("hover-pos").textContent="—";
};

// Right-click → tap
canvas.addEventListener("contextmenu", async e => {
  e.preventDefault();
  const p=canvasToImg(...canvasPos(e)); if(!p) return;
  await api().tap(p[0],p[1]);
  setStatus(`Tap → (${p[0]}, ${p[1]})`);
});

// Scroll → zoom
canvas.addEventListener("wheel", e => {
  if(!S.img) return; e.preventDefault();
  const[mx,my]=canvasPos(e);
  const ef0=S.scale*S.zoomLevel, ix=(mx-S.ox)/ef0, iy=(my-S.oy)/ef0;
  S.zoomLevel=Math.max(.3,Math.min(10,S.zoomLevel*(e.deltaY<0?1.15:1/1.15)));
  const ef1=S.scale*S.zoomLevel;
  const bx=(canvas.width-S.imgW*ef1)/2+S.panX, by=(canvas.height-S.imgH*ef1)/2+S.panY;
  S.panX+=mx-(bx+ix*ef1); S.panY+=my-(by+iy*ef1);
  recomputeLayout();
  $("zoom-level").textContent=Math.round(S.zoomLevel*100)+"%";
  draw();
},{passive:false});

canvas.addEventListener("dblclick", resetZoom);
