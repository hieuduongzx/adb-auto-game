// ── UI-capture harness: stubs the pywebview bridge so the Designer shell ─────
// renders in a plain headless browser for screenshot review. NOT product code.
(function(){
  const demo = {
    name:"farm-daily", version:2, templatesDir:"templates", buildVersion:"1.0.0",
    package:"com.example.game", controller:"adb", ocr:"", capture:"scrcpy",
    win32:{window:"",matchBy:"title",inputMode:"background"},
    speedhack:{enabled:false,speed:2.0},
    globals:[
      {name:"account_idx",label:"",type:"number",value:"1",options:[]},
      {name:"stamina",label:"",type:"number",value:"120",options:[]},
      {name:"keep_farming",label:"",type:"bool",value:true,options:[]},
      {name:"team_name",label:"",type:"text",value:"Alpha",options:[]}
    ],
    functions:[
      {id:"fn1",name:"claim_mail",graph:{nodes:[
        {id:"f0",type:"start",x:48,y:72,params:{}},
        {id:"f1",type:"tap_image",x:300,y:60,params:{template:"templates/btn_mail.png",taps:"1",threshold:0.85,timeout:6,offsetX:0,offsetY:0}},
        {id:"f2",type:"end",x:560,y:72,params:{}}
      ],edges:[
        {from:"f0",fromPort:"out",to:"f1"},
        {from:"f1",fromPort:"true",to:"f2"}
      ],groups:[]}}
    ],
    activities:[
      {id:"a1",name:"Login & claim",type:"sequence",enabled:true,maxRetries:2,vars:[],graph:{
        nodes:[
          {id:"n0",type:"start",x:48,y:200,params:{}},
          {id:"n1",type:"tap_image",x:288,y:72,params:{template:"templates/btn_login.png",taps:"1",threshold:0.85,timeout:10,offsetX:0,offsetY:0},note:"",log:"",delayBefore:0,delayAfter:0.5},
          {id:"n2",type:"if_image",x:576,y:72,params:{template:"templates/popup_event.png",threshold:0.85,negate:false},note:"Pop-up sự kiện có thể xuất hiện sau login",log:""},
          {id:"n3",type:"wait",x:576,y:280,params:{seconds:2},note:"",log:""},
          {id:"n4",type:"loop",x:880,y:72,params:{infinite:false,count:5},note:"",log:""},
          {id:"n5",type:"read_color",x:1160,y:60,params:{name:"stamina_color",x:980,y:64},note:"",log:""},
          {id:"n6",type:"set_var",x:1160,y:224,params:{name:"account_idx",value:"{account_idx}+1"},note:"",log:""},
          {id:"n7",type:"swipe",x:1440,y:72,params:{x1:540,y1:1400,x2:540,y2:700,duration:320},note:"",log:""},
          {id:"n8",type:"end",x:1690,y:200,params:{}},
          {id:"n9",type:"note",x:288,y:300,params:{text:"Farm daily: login → đóng popup → lặp 5 vòng quét map. Nhớ bật auto-battle trong game."},note:"",log:""}
        ],
        edges:[
          {from:"n0",fromPort:"out",to:"n1"},
          {from:"n1",fromPort:"true",to:"n2"},
          {from:"n1",fromPort:"false",to:"n3"},
          {from:"n3",fromPort:"out",to:"n2"},
          {from:"n2",fromPort:"true",to:"n4"},
          {from:"n4",fromPort:"body",to:"n5"},
          {from:"n5",fromPort:"out",to:"n6"},
          {from:"n6",fromPort:"out",to:"n7"},
          {from:"n7",fromPort:"out",to:"n4",toPort:"loop"},
          {from:"n4",fromPort:"done",to:"n8"}
        ],
        groups:[
          {id:"g1",name:"Farm loop",x:840,y:24,w:760,h:330,color:2}
        ]}},
      {id:"a2",name:"Watch stamina (bg)",type:"background",enabled:true,pollInterval:5,vars:[],graph:{nodes:[],edges:[],groups:[]}},
      {id:"a3",name:"Weekly boss",type:"sequence",enabled:false,maxRetries:1,vars:[],graph:{nodes:[],edges:[],groups:[]}}
    ]
  };

  const state = {
    connectedSerial:"emulator-5554", captureBackend:"scrcpy",
    captureBackends:["scrcpy","adb"],
    ocrBackends:["rapidocr","tesseract"],
    log:[]
  };

  const canned = {
    get_state:()=>state,
    get_settings:()=>({}),
    get_last_workflow:()=>({name:"farm-daily", text:JSON.stringify(demo)}),
    image_thumbnail:()=>null,
  };
  window.pywebview = { api:new Proxy({}, { get:(t,k)=>{
    if(canned[k]) return async()=>canned[k]();
    return async()=>null;
  }})};

  // ── Scenario driver (picked via location.hash) ─────────────────────────────
  function push(ev){ if(window.__recv) window.__recv(JSON.stringify(ev)); }
  function seedRuntime(){
    push({type:"devices_update",data:{devices:[
      {serial:"emulator-5554",name:"LDPlayer-9"},
      {serial:"127.0.0.1:5555",name:"MuMu-12"}
    ]}});
    push({type:"device_status",data:{serial:"emulator-5554",connected:true}});
    const now=new Date();
    const ts=i=>{ const d=new Date(now- (9-i)*7000); return d.toTimeString().slice(0,8); };
    [["info","Workflow reopened: farm-daily"],
     ["success","Connected to emulator-5554 (scrcpy)"],
     ["info","Run started · 3 activities enabled"],
     ["warning","Template popup_event.png confidence 0.81 < 0.85 — retake suggested"],
     ["error","Block «If image» timed out after 10s (attempt 2/2)"],
     ["info","Run finished · 42 blocks · 3m 12s"]
    ].forEach((L,i)=>push({type:"log",data:{level:L[0],msg:L[1],ts:ts(i)}}));
  }
  function ready(){ try{ return typeof WF!=="undefined" && WF.activities && WF.activities.length && document.querySelector(".wf-node"); }catch(e){ return false; } }
  function fail(e){
    const d=document.createElement("div");
    d.style.cssText="position:fixed;top:40px;left:40px;z-index:9999;background:#c00;color:#fff;padding:12px 16px;font:14px monospace;border-radius:8px;max-width:70vw;white-space:pre-wrap;";
    d.textContent="UICAP FAIL: "+(e&&e.stack||e);
    document.body.appendChild(d);
  }
  function scenario(){
    const h=(location.hash||"").slice(1);
    if(h==="select"){
      wfSelectOne("n2"); wfRenderInspector();
      const n=document.querySelector('.wf-node[data-node="n2"]'); if(n) n.classList.add("sel");
    } else if(h==="preview"){
      wfSwitchView("preview");
    } else if(h==="layout"){
      const b=$("wf-layout-toggle"); if(b) b.click();
    } else if(h==="ctxmenu"){
      const n=document.querySelector('.wf-node[data-node="n5"]');
      if(n) n.dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,cancelable:true,clientX:innerWidth/2,clientY:300}));
    } else if(h==="validate"){
      wfValidateShow();
    } else if(h==="shortcuts"){
      uiShowShortcuts();
    } else if(h==="runmenu"){
      const b=$("wf-run-menu-btn"); if(b) b.click();
    } else if(h==="devmenu"){
      const b=$("wf-device-menu-btn"); if(b) b.click();
    } else if(h==="speedpop"){
      const b=$("wf-speed-chip-btn"); if(b) b.click();
    } else if(h==="speedon"){
      WF.speedhack.enabled=true; wfSyncSpeedUI();
      const b=$("wf-speed-chip-btn"); if(b) b.click();
    } else if(h==="narrow"){
      // handled by window size only
    }
  }
  let tries=0;
  const iv=setInterval(()=>{
    tries++;
    if(ready()){
      clearInterval(iv);
      try{ seedRuntime(); }catch(e){ fail(e); }
      setTimeout(()=>{ try{ scenario(); }catch(e){ fail(e); } },250);
    } else if(tries>80){ clearInterval(iv); fail(new Error("ready() timeout — WF never became available")); }
  },100);
})();
