// ── State ────────────────────────────────────────────────────────────────────
const S = {
  imgW:0, imgH:0, img:null,
  scale:1, ox:0, oy:0,
  zoomLevel:1, panX:0, panY:0,
  dragging:false, dragStart:null, dragEnd:null,
  panning:false,  panStart:null, panBase:null,
  point:null, region:null, overlay:[],
  autoRefresh:true, devices:[], connectedSerial:null,
  connectionState:"unknown",
  lastFrameAt:null,
  frameSequence:0,
  displayedFrameSequence:0,
  capturePending:false,
  refreshHz:5,
  captureBackend:"scrcpy",
  selectedAsset:null,
};
const $ = id => document.getElementById(id);
const LOG_TAG = {info:"INF",success:"OK ",warning:"WRN",error:"ERR"};
const INFO_DOM = {
  status:"i-status",serial:"i-serial",model:"i-model",brand:"i-brand",
  android:"i-android",abi:"i-abi",screen_size:"i-screen",
  screen_density:"i-density",app:"i-app",battery:"i-battery",
  ip:"i-ip",uptime:"i-uptime",
};
const INFO_KEYS = Object.keys(INFO_DOM);

const canvas = $("preview-canvas");
const ctx    = canvas.getContext("2d");

// Age is time since frontend receipt, not camera timestamp (not in payload).
function renderCaptureTelemetry(){
  const age=S.lastFrameAt===null?null:Math.max(0,performance.now()-S.lastFrameAt);
  const staleAfter=Math.max(2000,3000/Math.max(.1,S.refreshHz));
  const state=age===null?"empty":!S.autoRefresh?"held":age>staleAfter?"stale":"fresh";
  const text={empty:"No frame received",held:"Held frame · auto paused",stale:"Stale frame · updates overdue",fresh:"Frame received"}[state];
  const el=$("capture-state");
  if(el.textContent!==text) el.textContent=text;
  el.dataset.state=state;
  el.title="Stale after the greater of 2 seconds or 3 configured capture intervals. This is not a connection check.";
  $("capture-age").textContent=age===null?"—":`${Math.floor(age/1000)} s since receipt`;
}

function renderCaptureSource(){
  $("capture-source-state").textContent=`Configured · ${S.captureBackend==="adb"?"ADB screencap":S.captureBackend}`;
  $("capture-source-state").title="Configured device capture backend. Frame payloads do not report their source or capture timestamp; opened files are not live device frames.";
}
