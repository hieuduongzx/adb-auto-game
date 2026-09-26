"""Browser regression for designer wire hover: uv run --no-project --with playwright python tests/check_wire_hover.py"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 900, 'height': 700})
    page.route('**/*.js', lambda route: route.abort())
    page.goto((ROOT / 'apps/web/wf/index.html').as_uri())
    page.evaluate('''() => {
      const svg=document.getElementById('wf-wires');
      svg.style.cssText='position:fixed;left:0;top:0;width:900px;height:700px;z-index:9999';
      svg.innerHTML=`<g class="wire-grp" id="probe-wire"><path class="wire-halo" d="M100,100 L600,100"/><path class="wire-hit" d="M100,100 L600,100"/><path class="wire" d="M100,100 L600,100"/></g><g class="wire-grp" id="other-wire"><path class="wire-halo" d="M100,100 L600,100"/><path class="wire-hit" d="M100,100 L600,100"/><path class="wire" d="M100,100 L600,100"/></g>`;
    }''')
    page.add_script_tag(path=str(ROOT / 'apps/web/wf/js/wires.js'))
    # The topmost of two overlapping hit paths must remain highlighted, not
    # oscillate between groups when a pointerover handler changes paint order.
    page.evaluate("document.getElementById('other-wire').remove()")
    page.mouse.move(280, 150)
    page.mouse.move(280, 100)
    page.wait_for_timeout(300)
    result=page.evaluate('''() => {
      const group=document.getElementById('probe-wire');
      const hit=group.querySelector('.wire-hit');
      const line=group.querySelector('.wire');
      return {target:document.elementFromPoint(280,100)?.getAttribute('class'),
        hovered:group.matches(':hover'), stroke:getComputedStyle(line).stroke,
        width:getComputedStyle(line).strokeWidth, hit:getComputedStyle(hit).pointerEvents};
    }''')
    assert result['target']=='wire-hit', result
    assert result['hovered'] and result['width']=='2px', result
    page.evaluate('''() => {
      const svg=document.getElementById('wf-wires');
      svg.insertAdjacentHTML('beforeend', '<g class="wire-grp" id="other-wire"><path class="wire-halo" d="M100,100 L600,100"/><path class="wire-hit" d="M100,100 L600,100"/><path class="wire" d="M100,100 L600,100"/></g>');
    }''')
    page.mouse.move(280, 150)
    page.mouse.move(280, 100)
    page.wait_for_timeout(300)
    result=page.evaluate('''() => {
      const top=document.getElementById('other-wire');
      return {hovered:top.matches(':hover'), width:getComputedStyle(top.querySelector('.wire')).strokeWidth};
    }''')
    assert result == {'hovered':True,'width':'2px'}, result
    print('PASS: single and overlapping wires retain hover highlight')
    browser.close()
