"""Dev-only: build a self-contained preview of the workflow designer UI.

Inlines wf/css + wf/js into wf/index.html, then injects a stub
`window.pywebview.api` so the page boots without the Python backend, and seeds
a sample workflow so the canvas/sidebar render real nodes. Used only to
screenshot the layout during UI work; safe to delete.
"""
import sys, os, re

HERE   = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(HERE, "wf")
SRC    = os.path.join(WF_DIR, "index.html")
OUT    = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "wf_preview.html")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


STUB = """<script>
window.pywebview = { api: new Proxy({}, { get:(t,k)=> (...a)=> Promise.resolve(
  k==='get_state'? {connectedSerial:'127.0.0.1:5555',selectedSerial:'127.0.0.1:5555',log:[
    {ts:'12:00:01',level:'info',msg:'[workflow] Loaded \\'CherryTale\\' (2 activities), templates@ out'},
    {ts:'12:00:02',level:'success',msg:'ADB server restarted'},
    {ts:'12:00:03',level:'warning',msg:'tap_image miss: btn_claim.png'}
  ]} :
  k==='get_settings'? {} :
  k==='workflow_node_types'? {} : "" ) }) };
</script>
"""

SEED = """<script>
// Runs synchronously at parse-end (after the main script defines everything,
// before the load event) so a plain headless screenshot captures real content.
(function(){
  try{
    if(!WF.activities.length){ wfAddActivity('sequence'); }
    var g = WF.activities[0].graph;
    if(g.nodes.length<=1){
      function mk(type,x,y,params){var n=wfNewNode(type,x,y); if(params)Object.assign(n.params,params); g.nodes.push(n); return n;}
      var s=g.nodes[0]; s.x=60; s.y=90;
      var a=mk('launch_app',300,90,{package:'com.cherrytale'});
      var b=mk('wait_image',300,210,{template:'out/btn_start.png'});
      var c=mk('tap',540,210,{target:'found'});
      var l=mk('loop',540,360,{count:5});
      var d=mk('end',780,360,{});
      g.edges.push({from:s.id,fromPort:'out',to:a.id});
      g.edges.push({from:a.id,fromPort:'out',to:b.id});
      g.edges.push({from:b.id,fromPort:'true',to:c.id});
      g.edges.push({from:c.id,fromPort:'out',to:l.id});
      g.edges.push({from:l.id,fromPort:'done',to:d.id});
      WF.functions.push({id:'fn_home',name:'Ve Home',graph:wfNewGraph()});
      WF.functions.push({id:'fn_claim',name:'Nhan thuong',graph:wfNewGraph()});
      wfAddActivity('background');
      WF.edit={kind:'activity',id:WF.activities[0].id};
      WF.sel=[c.id]; WF.selectedNode=c.id;
    }
    [{ts:'12:00:01',level:'info',msg:"[workflow] Loaded 'CherryTale' (2 activities), templates@ out"},
     {ts:'12:00:02',level:'success',msg:'ADB server restarted'},
     {ts:'12:00:03',level:'warning',msg:'tap_image miss: btn_claim.png'}].forEach(appendLog);
    setConnected(true);
    wfInitCanvas();
    wfRenderAll();
  }catch(e){ document.title='SEEDERR '+e.message; }
})();
</script>
"""

html = _read(SRC)

# Inline every <link rel="stylesheet" href="..."> and <script src="...">.
html = re.sub(r'<link rel="stylesheet" href="([^"]+)">',
              lambda m: "<style>\n" + _read(os.path.join(WF_DIR, m.group(1))) + "\n</style>",
              html)
html = re.sub(r'<script src="([^"]+)">\s*</script>',
              lambda m: "<script>\n" + _read(os.path.join(WF_DIR, m.group(1))) + "\n</script>",
              html)

html = html.replace("<script>", STUB + "<script>", 1)
html = html.replace("</body>", SEED + "</body>", 1)
open(OUT, "w", encoding="utf-8").write(html)
print(OUT)