"""Computed-style regression: uv run --no-project --with playwright python tests/check_node_execution_style.py"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        # Isolate the real stylesheet cascade from device/backend startup.
        page.route("**/*.js", lambda route: route.abort())
        page.goto((ROOT / "apps/web/wf/index.html").as_uri())
        page.evaluate("""() => {
            const canvas = document.getElementById('wf-canvas');
            canvas.innerHTML = ['action cat-basic', 'call'].map((kind, i) =>
                `<div id="probe-${i}" class="wf-node ${kind}" style="left:${i * 180}px;top:80px">
                <div class="wf-node-hd"><span class="ico">ƒ</span><span class="wf-node-title">Node</span></div>
                <div class="wf-node-sum">Details</div></div>`).join('');
        }""")
        for theme in ["light", "dark"]:
            page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            for lod in ["normal", "tiny"]:
                page.evaluate("lod => document.getElementById('wf-canvas').dataset.lod = lod", lod)
                for extra in ["", "sel", "ran-ok", "ran-fail", "crashed", "wf-entry", "paused"]:
                    for motion in ["no-preference", "reduce"]:
                        page.emulate_media(reduced_motion=motion)
                        page.evaluate("""extra => {
                            const a = document.getElementById('probe-0'), b = document.getElementById('probe-1');
                            a.className = 'wf-node action cat-basic running ' + extra;
                            b.className = 'wf-node call running-call ' + extra;
                        }""", extra)
                        # Allow the existing header colour transition to settle.
                        page.wait_for_timeout(180)
                        result = page.evaluate("""() => [0,1].map(i => {
                            const el=document.getElementById('probe-'+i), s=getComputedStyle(el);
                            return {bg:s.backgroundColor,border:s.borderColor,shadow:s.boxShadow,
                                header:getComputedStyle(el.querySelector('.wf-node-hd')).backgroundColor,
                                divider:getComputedStyle(el.querySelector('.wf-node-hd')).borderBottomColor,
                                title:getComputedStyle(el.querySelector('.wf-node-title')).color,
                                icon:getComputedStyle(el.querySelector('.ico')).color,
                                animation:getComputedStyle(el,'::after').animationName,
                                markerDisplay:getComputedStyle(el,'::after').display,
                                markerInset:getComputedStyle(el,'::after').top,
                                nodeAnimation:s.animationName,
                                outlineWidth:s.outlineWidth,outlineStyle:s.outlineStyle,outlineOffset:s.outlineOffset,
                                beforeAnimation:getComputedStyle(el,'::before').animationName,
                                width:el.offsetWidth,height:el.offsetHeight};
                        })""")
                        # Node categories keep their own colours; only the live marker is shared.
                        for key in ['nodeAnimation', 'outlineWidth', 'outlineStyle', 'outlineOffset']:
                            assert result[0][key] == result[1][key], (key, result)
                        live = extra != "paused"
                        assert result[0]["nodeAnimation"] == "none", result
                        assert result[0]["animation"] == ("wfExecutionMarch" if live and motion == "no-preference" else "none"), result
                        if live:
                            assert result[0]["markerDisplay"] == "block", result
                            assert result[0]["markerInset"] == "-5px", result
                        assert result[0]["beforeAnimation"] == "none", result
                        assert (result[0]["width"], result[0]["height"]) == (144, 64), result
                        page.evaluate("""() => [0,1].forEach(i =>
                            document.getElementById('probe-'+i).classList.remove('running','running-call'))""")
                        page.wait_for_timeout(180)
                        baseline = page.evaluate("""() => [0,1].map(i => {
                            const el=document.getElementById('probe-'+i), s=getComputedStyle(el);
                            return {bg:s.backgroundColor,border:s.borderColor,
                                header:getComputedStyle(el.querySelector('.wf-node-hd')).backgroundColor,
                                title:getComputedStyle(el.querySelector('.wf-node-title')).color,
                                icon:getComputedStyle(el.querySelector('.ico')).color};
                        })""")
                        for i in range(2):
                            for key, value in baseline[i].items():
                                assert result[i][key] == value, (theme, lod, extra, i, key, result[i], baseline[i])
                        checks += 1
        # Exiting a function drops only its live treatment, restoring its trail.
        page.evaluate("""() => {
            document.getElementById('wf-canvas').dataset.lod = 'normal';
            const el = document.getElementById('probe-1');
            el.className = 'wf-node call ran-ok';
        }""")
        page.wait_for_timeout(180)
        read = """() => {
            const el=document.getElementById('probe-1');
            return [getComputedStyle(el).backgroundColor,
                getComputedStyle(el.querySelector('.wf-node-hd')).backgroundColor];
        }"""
        before = page.evaluate(read)
        page.evaluate("document.getElementById('probe-1').classList.add('running-call', 'running')")
        page.wait_for_timeout(180)
        assert page.evaluate(read) == before
        page.evaluate("document.getElementById('probe-1').classList.remove('running-call', 'running')")
        page.wait_for_timeout(180)
        assert page.evaluate(read) == before
        page.emulate_media(reduced_motion="no-preference")
        blink = page.evaluate("""() => {
            const el=document.getElementById('probe-1');
            el.classList.add('running-call');
            const animation=el.getAnimations({subtree:true}).find(a=>a.animationName==='wfExecutionMarch');
            animation.pause();
            return [0, 500].map(time=>{
                animation.currentTime=time;
                const s=getComputedStyle(el,'::after');
                return {position:s.backgroundPosition,image:s.backgroundImage,opacity:s.opacity,width:el.offsetWidth,height:el.offsetHeight};
            });
        }""")
        assert blink[0]["position"] != blink[1]["position"], blink
        assert blink[0]["image"] == blink[1]["image"], blink
        assert blink[0]["opacity"] == blink[1]["opacity"] == "1", blink
        assert (blink[0]["width"], blink[0]["height"]) == (blink[1]["width"], blink[1]["height"]), blink
        browser.close()
    print(f"PASS: {checks} computed-style cases (themes, zoom LOD, selection/history/pause, motion)")


if __name__ == "__main__":
    main()
