"""Measure the real Designer DOM in Chromium (requires Python playwright).

python tools/benchmark_designer.py --verify --output out/designer-performance.json
"""

import argparse
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


MEASURE = r"""async ({count, samples}) => {
  wfResetRunViz(); wfResetHistory();
  const nodes=Array.from({length:count},(_,i)=>({
    id:'bench_'+i, type:i===0?'start':i===count-1?'end':i%5===0?'if_image':'tap',
    x:48+(i%20)*192, y:80+Math.floor(i/20)*112,
    params:i%5===0?{template:'templates/benchmark.png',threshold:.85}:{x:100,y:200},
    showPreview:false,
  }));
  const edges=nodes.slice(1).map((n,i)=>({
    from:nodes[i].id, fromPort:nodes[i].type==='if_image'?'true':'out',
    to:n.id,toPort:'in',
  }));
  const g={nodes,edges,groups:[]};
  WF.activities=[{id:'benchmark',name:'Benchmark',type:'sequence',enabled:true,vars:[],graph:g}];
  WF.functions=[]; WF.globals=[]; WF.edit={kind:'activity',id:'benchmark'};
  WF.sel=[]; WF.selectedNode=null; wfPan={x:0,y:0}; wfZoom=1; wfMinimapOn=false;
  wfInitCanvas();
  window.__thumbCalls=0;
  const timed=fn=>{ const t=performance.now();fn(); $('wf-world').offsetHeight;return performance.now()-t; };
  const coldRender=timed(wfRenderCanvas);
  const thumbnailCalls=window.__thumbCalls;
  const median=xs=>xs.sort((a,b)=>a-b)[Math.floor(xs.length/2)];
  const sample=async fn=>{
    const times=[];
    for(let i=0;i<samples+2;i++){
      await new Promise(requestAnimationFrame);
      const ms=timed(()=>fn(i)); if(i>=2) times.push(ms);
    }
    return {median_ms:median(times),max_ms:Math.max(...times)};
  };
  const redraw=await sample(()=>wfDrawWires());
  const render=await sample(wfRenderCanvas);
  const lead=nodes[1], leadEl=wfNodeElById(lead.id);
  wfStartMove({button:0,target:leadEl,clientX:0,clientY:0,stopPropagation(){}},lead);
  const drag=await sample(i=>{
    const e=new MouseEvent('mousemove',{bubbles:true,clientX:32+i*16,clientY:24+i*8});
    document.dispatchEvent(e);
    if(typeof wfFlushCanvasMove==='function') wfFlushCanvasMove();
  });
  document.dispatchEvent(new MouseEvent('mouseup',{button:0,clientX:400,clientY:240}));
  WF.sel=nodes.map(n=>n.id);
  const selection=await sample(wfMarkSel);
  const minimap=await sample(()=>{wfMinimapOn=true;wfMinimapDraw();});
  wfMinimapOn=false;
  const fullRunTrail=await sample(()=>{
    for(const n of nodes) wfRan[n.id]='ok',wfRanPort[n.id]='out';
    wfReapplyRunViz();
  });
  return {nodes:count,edges:edges.length,cold_render_ms:coldRender,hidden_thumbnail_calls:thumbnailCalls,
    render,wire_redraw:redraw,drag,select_all:selection,minimap,full_run_trail:fullRunTrail};
}"""


VERIFY = r"""async () => {
  const checks=[];
  const check=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
  wfResetRunViz();wfResetHistory();wfPreviewAll=false;
  const types=['start','if_image_any','loop','tap','end'];
  const nodes=types.map((type,i)=>wfNewNode(type,80+i*208,144+i*96));
  const [start,image,loop,tap,end]=nodes;
  image.params.templates=['templates/one.png','templates/two.png'];
  const edge=(a,p,b,q='in')=>({from:a.id,fromPort:p,to:b.id,toPort:q});
  const g={nodes,edges:[edge(start,'out',image),edge(image,'true',loop),edge(image,'false',end),
    edge(loop,'body',tap),edge(tap,'out',loop,'loop'),edge(loop,'done',end)],groups:[]};
  WF.activities=[{id:'verify',name:'Verify',type:'sequence',enabled:true,vars:[],graph:g}];
  WF.edit={kind:'activity',id:'verify'};WF.sel=[];WF.selectedNode=null;wfZoom=1;wfPan={x:0,y:0};
  window.__thumbCalls=0;wfRenderCanvas();
  check(window.__thumbCalls===0,'hidden image lists do not request thumbnails');
  const hit=$('wf-wires').querySelector('.wire-hit');hit.focus();wfDrawWires();
  check(document.activeElement===hit,'wire keyboard focus survives redraw');
  for(const n of [image,loop]){
    n.x+=48;n.y+=32;const el=wfNodeElById(n.id);el.style.left=n.x+'px';el.style.top=n.y+'px';
  }
  wfDrawWires([image.id,loop.id]);
  const paths=()=>[...$('wf-wires').querySelectorAll('.wire')].map(p=>p.getAttribute('d')).join('|');
  const fast=paths();wfDrawWires();check(paths()===fast,'multi-node incremental paths match full geometry');
  wfMarkNodeResult(image.id,'ok','false');wfDrawWires();
  const outgoing=[...$('wf-wires').querySelectorAll('.wire')].filter(p=>p.dataset.from===image.id);
  check(outgoing.find(p=>p.dataset.fromport==='false').classList.contains('took-wire') &&
    outgoing.find(p=>p.dataset.fromport==='true').classList.contains('nottook-wire'),'run branch colours survive redraw');
  image.showPreview=true;wfRenderCanvas();await Promise.resolve();
  check(window.__thumbCalls===2,'enabled image lists request their two thumbnails');
  $('wf-world').style.display='none';wfRenderCanvas();check(wfWiresStale,'hidden canvas defers wire measurements');
  $('wf-world').style.display='';wfDrawWires();
  check(!wfWiresStale && $('wf-wires').querySelectorAll('.wire').length===g.edges.length,'returning to canvas restores wires');
  wfResetHistory();const before={x:tap.x,y:tap.y};
  wfStartMove({button:0,target:wfNodeElById(tap.id),clientX:0,clientY:0,stopPropagation(){}},tap);
  document.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:48,clientY:32,altKey:true}));
  document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0,clientX:48,clientY:32}));
  check(tap.x===before.x+48 && tap.y===before.y+32,'mouseup flushes pending drag');
  wfUndo();check(wfNode(tap.id).x===before.x && wfNode(tap.id).y===before.y,'undo restores original drag position');
  wfRedo();check(wfNode(tap.id).x===before.x+48,'redo restores drag result');
  WF.edit.id=null;wfRenderCanvas();
  check(wfWireGroups.size===0 && wfWireGroupsByFrom.size===0 && wfNodeEls.size===0,'empty canvas releases render caches');
  return checks;
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", nargs="+", type=int, default=[100, 500, 1000])
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true", help="Also verify real browser rendering and drag history")
    args = parser.parse_args()
    if any(count < 3 for count in args.nodes) or args.samples < 1:
        parser.error("node counts must be at least 3 and samples must be positive")
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parents[1]
    handler = functools.partial(QuietHandler, directory=str(root / "apps" / "web"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""window.pywebview={api:new Proxy({}, {get:(_,key)=>async()=>{
              if(key==='image_thumbnail') window.__thumbCalls=(window.__thumbCalls||0)+1;
              return '';
            }})};""")
            page.goto(f"http://127.0.0.1:{server.server_port}/wf/index.html")
            results = [page.evaluate(MEASURE, {"count": count, "samples": args.samples}) for count in args.nodes]
            checks = page.evaluate(VERIFY) if args.verify else []
            report = {"browser": browser.version, "viewport": "1600x1000", "samples": args.samples,
                      "results": results, "browser_checks": checks, "page_errors": errors}
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    output = json.dumps(report, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    if report["page_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
