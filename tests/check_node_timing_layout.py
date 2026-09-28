"""Browser regression: uv run --no-project --with playwright python tests/check_node_timing_layout.py"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "apps/web/wf/js"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.route("**/*.js", lambda route: route.abort())
        page.goto((ROOT / "apps/web/wf/index.html").as_uri())
        page.add_script_tag(content="const WF_NODES={wait_image:{fields:[{k:'timeout'}]}};")
        render = (JS / "render.js").read_text(encoding="utf-8")
        page.add_script_tag(content=render[render.index("function wfDelaySecs"):render.index("// Card geometry")])
        inspector = (JS / "inspector.js").read_text(encoding="utf-8")
        page.add_script_tag(content=inspector[inspector.index("function wfUpdNodeTiming"):inspector.index("function wfRetryField")])
        # Use production node markup, not a test-owned timing layout.
        start = render.index("  const timingHtml =")
        end = render.index("  const rp=[]", start)
        markup = render[start:end]
        page.evaluate("""markup => {
            window.mount = (delay, timeout) => {
                const n={id:'probe',type:'wait_image',delay,params:{timeout}};
                const html = new Function('n', markup + '\\nreturn timingHtml;')(n);
                document.getElementById('wf-canvas').innerHTML =
                    '<div class="wf-node action cat-basic" data-node="probe" style="left:100px;top:80px">'+
                    '<div class="wf-node-hd">Wait image</div>'+html+'</div>';
                return n;
            };
        }""", markup)
        checks = 0
        for theme in ["light", "dark"]:
            page.evaluate("theme => document.documentElement.dataset.theme=theme", theme)
            for delay, timeout in [(2, 10), (0, 10), (123.5, 1000), (2, "{limit}")]:
                page.evaluate("([d,t]) => { window.node=mount(d,t); }", [delay, timeout])
                for edited in [False, True]:
                    if edited:
                        page.evaluate("node.delay=4; wfUpdNodeTiming(node); node.params.timeout=20; wfUpdNodeTimeoutChip(node);")
                    result = page.evaluate("""() => {
                        const node=document.querySelector('[data-node="probe"]');
                        const rect=el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};};
                        return {node:rect(node),timeout:rect(node.querySelector('.wf-node-timeout')),
                            delay:node.querySelector('.wf-node-delay') && rect(node.querySelector('.wf-node-delay'))};
                    }""")
                    gap = result["timeout"]["top"] - result["node"]["bottom"]
                    assert 1 <= gap <= 3, ("timeout must sit below the node with a 2px gap", result)
                    if result["delay"]:
                        assert abs(result["delay"]["top"] - result["timeout"]["top"]) <= 1, result
                        assert result["timeout"]["left"] - result["delay"]["right"] >= 3, result
                    checks += 1
        # Inspector delay edits must not replace the active timeout countdown.
        page.evaluate("""() => {
            const chip=document.querySelector('.wf-node-timeout');
            chip.classList.add('counting'); chip.querySelector('.wf-timeout-label').textContent='1.2s';
            node.delay=8; wfUpdNodeTiming(node); wfUpdNodeTimeoutChip(node);
        }""")
        assert page.locator('.wf-node-timeout.counting .wf-timeout-label').inner_text() == '1.2s'
        base = (JS / "base.js").read_text(encoding="utf-8")
        page.add_script_tag(content="function wfNodeElById(){return document.querySelector('[data-node=probe]');} function wfNode(){return window.node;}")
        page.add_script_tag(content=base[base.index("// ── Live pre-block delay"):base.index("function appendLog")])
        page.evaluate("node=mount(0,10); wfStartNodeDelay('probe','before',3);")
        live = page.locator('.wf-node-delay-live').bounding_box()
        timeout = page.locator('.wf-node-timeout').bounding_box()
        assert timeout['x'] >= live['x'] + live['width'] + 3, (live, timeout)
        page.evaluate("wfClearNodeDelay(); wfStartNodeTimeout('probe');")
        assert page.locator('.wf-node-timeout.counting').count() == 1
        page.evaluate("wfClearNodeDelay();")
        assert page.locator('.wf-node-timeout .wf-timeout-label').inner_text() == '10s'
        assert page.locator('.wf-node-delay-live').count() == 0
        # A new retry row must stay in the card, not inside the timing footer.
        page.add_script_tag(content="function wfIco(){return '';}")
        page.add_script_tag(content=inspector[inspector.index("function wfUpdNodeRetry"):inspector.index("// Failure screenshot")])
        page.evaluate("node=mount(2,10); node.retryCount=2; wfUpdNodeRetry(node);")
        assert page.locator('.wf-node > .wf-node-retry').count() == 1
        assert page.locator('.wf-node-timing .wf-node-retry').count() == 0
        browser.close()
    print(f"PASS: {checks} timing layout cases, inspector updates, countdown/fallback, retry placement")


if __name__ == "__main__":
    main()
