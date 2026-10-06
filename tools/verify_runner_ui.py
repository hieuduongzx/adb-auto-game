"""Verify Runner's actual DOM in Edge with a mocked Python bridge.

python tools/verify_runner_ui.py --output out/runner-audit-browser.json
"""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading


BRIDGE = """window.__calls={start:0,stop:0,solo:0};
window.pywebview={api:new Proxy({}, {get:(_,key)=>async(...args)=>{
 if(key==='get_state') return {loaded:true,name:'Audit',controller:'adb',activities:[
 {id:'a',name:'A',type:'sequence',enabled:true,status:'failed',nodeCount:2,vars:[],runtimeSettings:[]},
 {id:'bg',name:'Watch',type:'background',enabled:true,status:'pending',pollInterval:1,nodeCount:2,vars:[],runtimeSettings:[]}],
 running:false,paused:false,outcome:'failed',outcomeReason:'Audit failure',runScope:['a'],
 captureBackend:'scrcpy',captureBackends:['scrcpy','adb'],runner:{version:'audit'},log:[]};
 if(key==='start'){window.__calls.start++;return new Promise(resolve=>window.__releaseStart=resolve);}
 if(key==='run_activity'){window.__calls.solo++;return true;}
 if(key==='stop'){window.__calls.stop++;return true;}
 if(key==='toggle_activity')return false;
 if(key==='get_settings')return {theme:'light'};
 return {};
}})};"""


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log-benchmark", action="store_true")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright
    root = Path(__file__).resolve().parents[1]
    handler = functools.partial(Handler, directory=str(root / "apps/web"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks, errors, measurements = [], [], []
    def check(ok, label):
        if not ok:
            raise AssertionError(label)
        checks.append(label)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(BRIDGE)
            page.goto(f"http://127.0.0.1:{server.server_port}/runner/index.html")
            page.wait_for_function('S.loaded && S.outcome === "failed"')
            check(page.locator("#status-text").inner_text() == "FAILED", "hydrate terminal outcome")
            check(page.locator('.task-row[data-id="a"] [data-dot]').get_attribute("aria-label") == "Status: Failed",
                  "hydrate activity status")
            page.locator("#btn-primary").click()
            page.evaluate('onStart(); onRunActivity("a");')
            check(page.evaluate("window.__calls.start===1 && window.__calls.solo===0")
                  and page.locator("#btn-primary").is_disabled(), "one pending Start request")
            page.evaluate('window.__recv(JSON.stringify({type:"running_state",data:{running:true,paused:false,startedAt:Date.now()/1000,runScope:null}}));')
            check(page.locator("#btn-primary").is_enabled(), "Stop remains enabled during Start response")
            page.locator("#btn-primary").click()
            check(page.evaluate("window.__calls.stop===1"), "Stop button sends Stop")
            page.evaluate('window.__releaseStart(true); window.__recv(JSON.stringify({type:"running_state",data:{running:false,paused:false,outcome:"completed"}}));')
            page.locator('.task-row[data-id="a"] .cb').click()
            page.wait_for_function("!S.activities[0].savingEnabled")
            check(page.locator('.task-row[data-id="a"] .cb').get_attribute("aria-pressed") == "true",
                  "failed checkbox save retains value")
            page.evaluate("() => { onStart=()=>window.__calls.start++; }")
            page.evaluate('switchMobileView("log", false); switchRTab("log", false);')
            page.locator("#log-search").focus()
            check(page.evaluate('document.activeElement.id === "log-search"'), "text input has focus")
            page.keyboard.press("Control+Enter")
            check(page.evaluate("window.__calls.start===1"), "Ctrl+Enter ignored in text input")
            log_state = page.evaluate("""async () => {
              clearLog();
              for(let i=0;i<1000;i++) appendLog({ts:'10:00:00',level:'info',text:'Line '+i});
              await new Promise(requestAnimationFrame);
              return {total:S.logTotal,retained:S.logCount,first:$('log-body').firstChild.querySelector('.log-msg').textContent,
                      last:$('log-body').lastChild.querySelector('.log-msg').textContent};
            }""")
            check(log_state == {"total": 1000, "retained": 500, "first": "Line 500", "last": "Line 999"},
                  "log burst retains newest 500 and total count")
            visible = page.evaluate("""async () => {
              setLogLevel('warning');
              appendLog({ts:'10:00:00',level:'warning',text:'<b>Warning</b>'});
              await new Promise(requestAnimationFrame);
              return [...$('log-body').children].filter(line=>!line.classList.contains('hidden')).map(line=>line.querySelector('.log-msg').textContent);
            }""")
            check(visible == ["<b>Warning</b>"], "batched log keeps filtering and escapes markup")
            retained = page.evaluate("""async () => {
              appendLog({text:'Pending'});clearLog();await new Promise(requestAnimationFrame);
              setLogLevel('all');return $('log-body').children.length;
            }""")
            check(retained == 0, "Clear cancels a queued log frame")
            for width in [440, 1280]:
                page.set_viewport_size({"width": width, "height": 800})
                page.wait_for_function("innerWidth === " + str(width))
                # Layout can change on the next animation frame after resizing.
                page.evaluate("() => new Promise(requestAnimationFrame)")
                bounds = page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth})")
                check(bounds["scroll"] <= bounds["width"], f"no horizontal overflow at {width}px: {bounds}")
            if args.log_benchmark:
                measurements = page.evaluate("""() => [100,500,1000].map(count=>{
                  clearLog();const t=performance.now();
                  for(let i=0;i<count;i++) appendLog({ts:'10:00:00',level:'info',text:'Audit node '+i,scope:'A'});
                  cancelAnimationFrame(_logFrame);flushLog();document.body.offsetHeight;
                  return {lines:count,ms:performance.now()-t,retained:$('log-body').children.length};
                })""")
            check(not errors, "no JavaScript page errors")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        report = {"checks": checks, "page_errors": errors, "log_benchmark": measurements}
        output = json.dumps(report, indent=2)
        print(output)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
