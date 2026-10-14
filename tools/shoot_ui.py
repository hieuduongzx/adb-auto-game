"""Screenshot the Hub, Runner, Designer and DevScope with their real Python APIs.

Each app's ``*API`` class is instantiated without pywebview and served next to
``apps/web`` over a local HTTP server; the page's ``window.pywebview.api`` is a
proxy that forwards every call there. Calls that would touch a device, run a
workflow, write files or reach the network are refused (they resolve to
``null``), so shooting is read-only against the repo's workflows.

    python tools/shoot_ui.py --out out/ui                 # every scene, both themes
    python tools/shoot_ui.py --out out/ui --only hub --theme dark

Requires Playwright with the Edge channel (same as tools/verify_runner_ui.py).
"""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps")]

# Read-only allowlist: anything else resolves to null in the page.
SAFE = {
    "app_version", "build_state", "list_workflows", "get_state", "get_settings",
    "get_last_workflow", "get_local_vars", "list_templates", "template_thumbnail",
    "image_thumbnail", "list_trash", "unity_bridge_status", "get_diagnostics",
    "find_duplicate_templates", "list_windows", "list_assets", "get_asset_thumbnail",
    "get_history", "get_notify", "recent_runs", "get_schedule",
}


class _FakeWindow:
    """Absorbs evaluate_js pushes; the page polls state through the proxy."""

    def evaluate_js(self, *_args, **_kwargs):
        return None

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _apis(flow_path: str):
    from src.core.adb import lifecycle
    lifecycle.acquire_adb_lease = lambda *a, **k: None
    import workflow_hub
    import workflow_runner
    import workflow_designer

    hub = workflow_hub.WorkflowHubAPI()
    hub._window = _FakeWindow()

    runner = workflow_runner.WorkflowRunnerAPI()
    runner._window = _FakeWindow()
    runner._push = lambda *a, **k: None
    runner._load_path(flow_path)

    designer = workflow_designer.WorkflowDesignerAPI()
    designer._window = _FakeWindow()
    designer._remember_dir = lambda *a, **k: None
    designer._remember_last_workflow = lambda *a, **k: None
    designer._pending_load = flow_path

    import devscope
    scope = devscope.DevScopeAPI()
    scope._window = _FakeWindow()
    return {"hub": hub, "runner": runner, "wf": designer, "scope": scope}


def _handler(apis, theme_box):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path.startswith("/__file/"):
                from urllib.parse import unquote, urlsplit
                path = Path(unquote(urlsplit(self.path).path[len("/__file/"):]))
                if path.is_file() and ROOT in path.resolve().parents:
                    data = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", self.guess_type(str(path)))
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)
                return
            super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_POST(self):
            parts = self.path.strip("/").split("/")
            length = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(length) or b"[]")
            result = None
            if len(parts) == 3 and parts[0] == "__api" and parts[2] in SAFE:
                api = apis.get(parts[1])
                fn = getattr(api, parts[2], None)
                if fn is not None:
                    try:
                        result = fn(*args)
                    except Exception as exc:  # surface, don't crash the page
                        result = None
                        print(f"  ! {parts[1]}.{parts[2]}: {exc}")
                if parts[2] == "get_settings":
                    result = dict(result or {}, theme=theme_box[0])
                    if parts[1] == "wf":
                        result.update(sideCollapsed=False, inspCollapsed=False)
            # file:// asset URLs (covers, icons) cannot load from an http page;
            # route them back through this server, still read-only.
            body = json.dumps(result, default=str).replace(
                '"file:///', '"/__file/').encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return functools.partial(Handler, directory=str(ROOT / "apps" / "web"))


class _Server(ThreadingHTTPServer):
    # The Designer requests ~25 scripts at once; the socketserver default
    # backlog of 5 refused some of them on Windows, so a page would load with
    # base.js or groups.js missing ("$ is not defined").
    request_queue_size = 128
    daemon_threads = True


BRIDGE = """(() => {
  const app = location.pathname.split('/')[1];
  const theme = %s;
  try { localStorage.setItem('m2k-theme', theme); } catch (e) {}
  window.pywebview = { api: new Proxy({}, { get: (_, key) => (...args) =>
    fetch('/__api/' + app + '/' + String(key), { method: 'POST', body: JSON.stringify(args) })
      .then(r => r.json()) }) };
})();"""

# A run in progress: two activities done, one failed, one live, and a few log
# lines of each level — pushed through the page's own message entry point.
RUNNER_LIVE = """(() => {
  const send = (type, data) => window.__recv(JSON.stringify({type, data}));
  const ids = S.activities.filter(a => a.type !== 'background' && a.enabled).map(a => a.id);
  send('running_state', {running: true, paused: false, startedAt: Date.now() / 1000 - 754, runScope: null});
  ids.forEach(id => send('activity_update', {id, status: 'pending'}));
  send('activity_update', {id: ids[0], status: 'completed'});
  send('activity_update', {id: ids[1], status: 'completed'});
  send('activity_update', {id: ids[2], status: 'failed'});
  send('activity_update', {id: ids[3], status: 'running'});
  const t = '22:41:0';
  [['info', 'run', 'Run started: 12 activities'],
   ['info', 'activity', 'Auto Perform: started'],
   ['success', 'activity', 'Auto Perform: completed in 41s'],
   ['info', 'app', 'Tap image c_88_50.png matched 0.97 at (612, 344)'],
   ['warning', 'app', 'Claim VIP: template not found within 10s, retrying (1/2)'],
   ['error', 'activity', 'Claim VIP: failed after 2 attempts'],
   ['info', 'activity', 'Friend: started']].forEach(([level, kind, text], i) =>
     send('log', {ts: t + i, level, kind, scope: i ? 'Girl Wars' : 'Runner', text}));
})()"""

# A repeating Start resting between rounds 2 and 3 of 5.
RUNNER_ROUNDS = """(() => {
  applyRounds({count: 5, rest: 600});
  const send = (type, data) => window.__recv(JSON.stringify({type, data}));
  const ids = S.activities.filter(a => a.type !== 'background' && a.enabled).map(a => a.id);
  send('running_state', {running: true, paused: false, startedAt: Date.now() / 1000 - 3754, runScope: null,
                         round: {round: 2, total: 5, phase: 'resting', restUntil: Date.now() / 1000 + 272}});
  ids.forEach(id => send('activity_update', {id, status: 'completed'}));
})()"""

# Run history: a week of finished runs, one expanded.
RUNNER_HISTORY = """(() => {
  const now = Date.now() / 1000, acts = S.activities.filter(a => a.type !== 'background').slice(0, 6);
  const tally = (bad) => acts.map((a, i) => ({id: a.id, name: a.name, completed: i === bad ? 0 : 3,
    failed: i === bad ? 2 : 0, stopped: 0, seconds: 40 + i * 23, ...(i === bad ? {shot: 'x.jpg'} : {})}));
  H.items = [
    {start: now - 3900, end: now - 120, seconds: 3780, outcome: 'completed', rounds: 3,
     reason: '3 rounds · 36 activities completed', activities: tally(-1)},
    {start: now - 30000, end: now - 27000, seconds: 3000, outcome: 'failed', rounds: 3,
     reason: '3 rounds · 2 of 36 activities failed', activities: tally(2)},
    {start: now - 90000, end: now - 89000, seconds: 1000, outcome: 'stopped', rounds: 0,
     reason: 'Stopped by you', activities: tally(-1).slice(0, 2)},
    {start: now - 180000, end: now - 179200, seconds: 812, outcome: 'completed', rounds: 0,
     reason: '12 activities completed', activities: tally(-1)},
    {start: now - 260000, end: now - 259950, seconds: 50, outcome: 'completed', rounds: 0, scope: 'Arena',
     reason: '1 activity completed', activities: tally(-1).slice(4, 5)},
  ];
  H.loaded = true; H.open = String(H.items[1].end);
  switchRTab('hist');
})()"""

# A finished run that failed: the header keeps the result.
RUNNER_DONE = """(() => {
  const send = (type, data) => window.__recv(JSON.stringify({type, data}));
  const ids = S.activities.filter(a => a.type !== 'background' && a.enabled).map(a => a.id);
  send('running_state', {running: true, paused: false, startedAt: Date.now() / 1000 - 812, runScope: null});
  ids.forEach((id, i) => send('activity_update', {id, status: i === 2 ? 'failed' : 'completed'}));
  send('running_state', {running: false, paused: false, outcome: 'failed', runScope: null});
})()"""

# A test run part-way through: two blocks done, one live, one failed.
DESIGNER_LIVE = """(() => {
  wfSetRunning(true);
  const ns = [...document.querySelectorAll('#wf-world .wf-node:not(.start):not(.end)')];
  ns[0] && ns[0].classList.add('ran-ok');
  ns[1] && ns[1].classList.add('ran-ok');
  ns[2] && ns[2].classList.add('running');
  ns[3] && ns[3].classList.add('ran-fail');
})()"""

# name, page, viewport, settle action (JS run after load, may be empty)
SCENES = [
    ("hub", "hub", (1280, 800), ""),
    ("hub-narrow", "hub", (820, 760), ""),
    ("hub-lastrun", "hub", (1280, 800),
     "(() => { const now = Date.now() / 1000;"
     " const runs = [{outcome: 'completed', end: now - 7300, seconds: 3790, rounds: 3, reason: '3 rounds'},"
     " {outcome: 'failed', end: now - 90000, seconds: 812, rounds: 0, reason: '1 of 16 failed'},"
     " {outcome: 'stopped', end: now - 400, seconds: 95, rounds: 0, reason: 'Stopped by you', scope: 'Arena'}];"
     " GAMES.slice(0, 3).forEach((g, i) => { g.lastRun = runs[i]; }); render(); })()"),
    ("hub-recent", "hub", (1280, 800),
     "(() => { const now = Date.now() / 1000;"
     " RECENT = {today: {runs: 4, completed: 3, failed: 1, stopped: 0}, runs: ["
     " {workflow: 'Girl Wars', outcome: 'completed', end: now - 600, seconds: 3790, rounds: 3, reason: '3 rounds · 36 activities completed'},"
     " {workflow: 'BrownDust2', outcome: 'failed', end: now - 7400, seconds: 812, rounds: 0, reason: '1 of 16 activities failed'},"
     " {workflow: 'Girl Wars', outcome: 'completed', end: now - 30000, seconds: 3600, rounds: 3, reason: '3 rounds · 36 activities completed'},"
     " {workflow: 'Cherry Tale', outcome: 'stopped', end: now - 90000, seconds: 95, rounds: 0, reason: 'Stopped by you', scope: 'Guild'},"
     " {workflow: 'Girl Wars', outcome: 'completed', end: now - 170000, seconds: 3540, rounds: 3, reason: '3 rounds · 36 activities completed'}]};"
     " renderRecent(); })()"),
    ("hub-focus", "hub", (1280, 800), "document.querySelectorAll('.game-cover')[1].focus()"),
    ("hub-new", "hub", (1280, 800), "createWorkflow()"),
    ("hub-nomatch", "hub", (1280, 800),
     "(() => { const s = document.getElementById('search'); s.value = 'zelda'; s.dispatchEvent(new Event('input', {bubbles: true})); })()"),
    ("hub-toasts", "hub", (1280, 800),
     "toast('Opened Girl Wars in the Designer', 'success'); toast('Refreshing the library…', 'info');"
     " toast('Build failed: PyInstaller is not installed', 'error'); toast('Cover art is missing', 'warning')"),
    ("hub-settings", "hub", (1280, 800), "openSettings()"),
    ("hub-build", "hub", (1280, 800), "buildWorkflow(GAMES[0].path)"),
    ("runner", "runner", (440, 820), ""),
    ("runner-wide", "runner", (1100, 760), ""),
    ("runner-settings", "runner", (440, 820),
     "typeof switchMobileView==='function' && switchMobileView('settings', false)"),
    ("runner-running", "runner", (1100, 760), RUNNER_LIVE),
    ("runner-running-narrow", "runner", (440, 820), RUNNER_LIVE),
    ("runner-actset", "runner", (1100, 760),
     "openActivitySettings((S.activities.find(a => (a.vars||[]).length > 2) || S.activities[0]).id)"),
    ("runner-actset-narrow", "runner", (440, 820),
     "openActivitySettings((S.activities.find(a => (a.vars||[]).length > 2) || S.activities[0]).id)"),
    ("runner-pop-settings", "runner", (1100, 760), "openHeaderPop('settings')"),
    ("runner-history", "runner", (1100, 760), RUNNER_HISTORY),
    ("runner-history-narrow", "runner", (440, 820), RUNNER_HISTORY),
    ("runner-done", "runner", (1100, 760), RUNNER_DONE),
    ("runner-actset-results", "runner", (1100, 760),
     RUNNER_HISTORY + "; openActivitySettings(S.activities.filter(a => a.type !== 'background')[2].id)"),
    ("runner-rounds-idle", "runner", (1100, 760),
     "applyRounds({count: 5, rest: 600}); openHeaderPop('settings')"),
    ("runner-rounds-live", "runner", (1100, 760), RUNNER_ROUNDS),
    ("runner-schedule", "runner", (1100, 760),
     "applySchedule({enabled: true, times: ['05:05', '17:05'], next: Date.now() / 1000 + 3 * 3600 + 600});"
     " openHeaderPop('settings');"
     " const pop = document.querySelector('#settings-pop .rpane-scroll'); pop && (pop.scrollTop = 200);"),
    ("runner-notify", "runner", (1100, 760),
     "S.notify = {when: 'all', desktop: true, discord: 'https://discord.com/api/webhooks/1/x'};"
     " openHeaderPop('settings'); renderNotify();"
     " const pop = document.querySelector('#settings-pop .rpane-scroll'); pop && (pop.scrollTop = 250 - 160);"),
    ("runner-rounds-narrow", "runner", (440, 820), RUNNER_ROUNDS),
    ("runner-pop-notes", "runner", (1100, 760), "openHeaderPop('notes')"),
    ("designer", "wf", (1480, 920), ""),
    ("designer-node", "wf", (1480, 920),
     "(()=>{const n=document.querySelector('.wf-node:not(.start):not(.end)')||document.querySelector('.wf-node');"
     "if(n){n.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,clientX:n.getBoundingClientRect().x+20,clientY:n.getBoundingClientRect().y+20}));"
     "document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0}));}})()"),
    ("designer-small", "wf", (1100, 720), ""),
    ("designer-preview", "wf", (1480, 920), "wfSwitchView('preview')"),
    ("designer-library", "wf", (1480, 920), "wfSwitchView('library')"),
    ("designer-project", "wf", (1480, 920), "wfOpenProjectSettings()"),
    ("designer-keys", "wf", (1480, 920), "uiShowShortcuts()"),
    ("designer-cmd", "wf", (1480, 920), "wfCmdShow()"),
    ("designer-find", "wf", (1480, 920), "wfFindShow()"),
    ("designer-validate", "wf", (1480, 920), "wfValidateShow()"),
    ("designer-runmenu", "wf", (1480, 920), "wfShowRunMenu(document.getElementById('wf-run-menu-btn'))"),
    ("designer-qc", "wf", (1480, 920), "wfShowQuickConnectMenu(760, 380, null, null)"),
    ("designer-vars", "wf", (1480, 920), "document.getElementById('wf-vars-toggle').click()"),
    ("designer-layout", "wf", (1480, 920), "document.getElementById('wf-layout-toggle').click()"),
    ("designer-ctx", "wf", (1480, 920),
     "(() => { const n = document.querySelectorAll('#wf-world .wf-node')[2]; const r = n.getBoundingClientRect();"
     " n.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: r.x + 30, clientY: r.y + 20})); })()"),
    ("designer-live", "wf", (1480, 920), DESIGNER_LIVE),
    ("designer-breakpoint", "wf", (1480, 920),
     "(() => { const ns = wfGraph().nodes.filter(n => n.type !== 'start');"
     " ns[1].breakpoint = true; ns[3] && (ns[3].breakpoint = true); wfRenderCanvas(); wfSetRunning(true);"
     " const el = wfNodeElById(ns[0].id); el && el.classList.add('ran-ok');"
     " wfOnBreakpointHit(ns[1].id); })()"),
    ("designer-palette-filter", "wf", (1480, 920), "wfPaletteFilter('image')"),
    ("designer-toasts", "wf", (1480, 920),
     "uiToast('Saved', 'success'); uiToast('Template not found: crop_88_50.png', 'error');"
     " uiToast('No device connected - Preview is idle', 'warning'); uiToast('Copied 3 blocks', 'info')"),
    ("designer-empty", "wf", (1480, 920),
     "(() => { WF.activities = []; WF.edit = {kind: 'activity', id: null}; wfRenderAll(); })()"),
    ("devscope", "scope", (1280, 800), ""),
    ("devscope-narrow", "scope", (900, 760), ""),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "ui")
    parser.add_argument("--flow", default=str(ROOT / "workflows" / "GirlWars" / "GirlWars.json"))
    parser.add_argument("--only", help="comma-separated scene name prefixes")
    parser.add_argument("--theme", choices=["light", "dark", "both"], default="both")
    parser.add_argument("--wait", type=float, default=1.6, help="seconds to settle after load")
    parser.add_argument("--scale", type=float, default=1, help="device scale factor (2 for crisp crops)")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    apis = _apis(os.path.abspath(args.flow))
    theme_box = ["light"]
    server = _Server(("127.0.0.1", 0), _handler(apis, theme_box))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    args.out.mkdir(parents=True, exist_ok=True)
    only = [s.strip() for s in (args.only or "").split(",") if s.strip()]
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            for theme in themes:
                theme_box[0] = theme
                for name, page_dir, (w, h), settle in SCENES:
                    if only and not any(name.startswith(o) for o in only):
                        continue
                    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=args.scale)
                    errors = []
                    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                    page.add_init_script(BRIDGE % json.dumps(theme))
                    page.goto(f"{base}/{page_dir}/index.html")
                    time.sleep(args.wait)
                    if settle:
                        # Fire and forget: a dialog's promise only settles on close.
                        page.evaluate("s => setTimeout(() => (0, eval)(s), 0)", settle)
                        time.sleep(0.5)
                    path = args.out / f"{name}-{theme}.png"
                    page.screenshot(path=str(path))
                    print(f"{path.name}" + (f"  errors: {errors}" if errors else ""))
                    page.close()
            browser.close()
    finally:
        server.shutdown()
    os._exit(0)  # API worker threads (device polls) are daemons but may hold the loop


if __name__ == "__main__":
    main()
