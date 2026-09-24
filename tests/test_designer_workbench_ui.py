"""Designer-only workbench chrome; graph geometry is covered by Node tests."""
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1] / 'apps/web/wf'

class Chrome(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_designer_chrome_names_zones_and_selection_without_replacing_runtime_ids():
    doc = Chrome()
    doc.feed((ROOT / 'index.html').read_text(encoding='utf-8'))
    ids = {attrs['id']: attrs for _, attrs in doc.elements if 'id' in attrs}
    assert ids['wf-side']['aria-label'] == 'Node palette'
    assert ids['wf-inspector']['aria-label'] == 'Inspector'
    assert ids['wf-selection-state']['role'] == 'status'
    assert ids['wf-save-state']['role'] == 'status'
    assert ids['status-text']['aria-live'] == 'polite'
    tabs = [attrs for _, attrs in doc.elements if 'data-view' in attrs]
    assert len(tabs) == 3
    assert [t['aria-selected'] for t in tabs] == ['true', 'false', 'false']
    assert [t['tabindex'] for t in tabs] == ['0', '-1', '-1']
    for tab in tabs:
        assert tab['role'] == 'tab'
        assert ids[tab['aria-controls']]['role'] == 'tabpanel'
        assert ids[tab['aria-controls']]['aria-labelledby'] == tab['id']
    assert len(ids) == sum('id' in attrs for _, attrs in doc.elements)


def test_designer_zoning_keeps_canvas_geometry_out_of_chrome_rules():
    css = (ROOT / 'css/wf.css').read_text(encoding='utf-8')
    assert '.wf-zone-heading' in css
    assert '.wf-insp-context' in css
    assert '.wf-view-tab.sel::after' in css
    assert '#wf-selection-state' in css
