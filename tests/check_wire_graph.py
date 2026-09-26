"""Audit actual rendered SVG paths against DOM card bounds for the supplied graph.
Run: uv run --no-project --with playwright python tests/check_wire_graph.py
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
workflow = json.loads((ROOT / 'workflows/GirlWars/GirlWars.json').read_text(encoding='utf-8'))
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1500, 'height': 1000})
    page.goto((ROOT / 'apps/web/wf/index.html').as_uri())
    page.evaluate('''data => {
      Object.assign(WF,data);
      WF.edit={kind:'activity',id:'sequence_y0b1'}; WF.sel=[];
      // Render real cards with the production renderer, CSS and port layout.
      const world=document.getElementById('wf-world');
      document.body.appendChild(world);
      world.style.cssText='display:block;position:absolute;left:0;top:0;transform:none';
      world.querySelectorAll('.wf-node').forEach(n=>n.remove());
      wfGraph().nodes.forEach(n=>world.appendChild(wfNodeEl(n)));
    }''', workflow)
    failures = []
    for mode, zoom in [(m, z) for z in [0.5, 1, 1.5] for m in ['spline', 'linear', 'straight']]:
        result = page.evaluate('''({mode,zoom}) => {
          document.getElementById('wf-world').style.transform=`scale(${zoom})`;
          wfLinkMode=mode; const start=performance.now();wfDrawWires();
          const ms=performance.now()-start;
          const cards=[...document.querySelectorAll('#wf-world .wf-node')].map(el=>({
            id:el.dataset.node,l:el.offsetLeft,r:el.offsetLeft+el.offsetWidth,
            t:el.offsetTop,b:el.offsetTop+el.offsetHeight}));
          const hits=[];
          for(const group of document.querySelectorAll('#wf-wires .wire-grp')){
            const edge=group.__edge,path=group.querySelector('.wire'),len=path.getTotalLength();
            const collided=new Set();
            for(let d=0;d<=len;d+=1){
              const pt=path.getPointAtLength(d);
              for(const card of cards){
                // Only the first/last 8px may sit inside endpoint sockets.
                if(card.id===edge.from&&d<8 || card.id===edge.to&&len-d<8)continue;
                if(pt.x>card.l+1&&pt.x<card.r-1&&pt.y>card.t+1&&pt.y<card.b-1)
                  collided.add(card.id);
              }
            }
            if(collided.size)hits.push({from:edge.from,port:edge.fromPort,to:edge.to,cards:[...collided]});
          }
          return {mode,zoom,ms,nodes:cards.length,edges:document.querySelectorAll('#wf-wires .wire').length,
            expected:wfGraph().edges.length,hits};
        }''', {'mode': mode, 'zoom': zoom})
        print(json.dumps(result, ensure_ascii=False))
        if result['hits'] or result['edges'] != result['expected']:
            failures.append(result)
    browser.close()
    assert not failures, 'Rendered wires still intersect cards; see reports above'
