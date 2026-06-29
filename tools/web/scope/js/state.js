// ── State ────────────────────────────────────────────────────────────────────
const S = {
  imgW:0, imgH:0, img:null,
  scale:1, ox:0, oy:0,
  zoomLevel:1, panX:0, panY:0,
  dragging:false, dragStart:null, dragEnd:null,
  panning:false,  panStart:null, panBase:null,
  point:null, region:null, overlay:[],
  autoRefresh:true, devices:[], connectedSerial:null,
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
