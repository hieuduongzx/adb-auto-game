from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[1]
DESIGNER_HTML = ROOT / "apps" / "web" / "wf" / "index.html"
DESIGNER_JS = ROOT / "apps" / "web" / "wf" / "js" / "render.js"
DESIGNER_EVENTS_JS = ROOT / "apps" / "web" / "wf" / "js" / "events.js"


class _DesignerHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "parents": tuple(self.stack)}
        self.elements.append(node)
        if tag not in {"input", "meta", "link", "img", "br"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def by_id(self, element_id):
        return next(node for node in self.elements if node["attrs"].get("id") == element_id)


def _document():
    parser = _DesignerHTML()
    parser.feed(DESIGNER_HTML.read_text(encoding="utf-8"))
    return parser


def test_variables_panel_is_a_collapsed_canvas_overlay():
    doc = _document()
    canvas = doc.by_id("wf-canvas")
    panel = doc.by_id("wf-vars-panel")
    toggle = doc.by_id("wf-vars-toggle")
    body = doc.by_id("wf-vars-body")

    assert canvas in panel["parents"]
    assert panel["attrs"].get("class") == "wf-vars-panel collapsed"
    assert toggle["attrs"].get("aria-expanded") == "false"
    assert toggle["attrs"].get("aria-controls") == "wf-vars-body"
    assert "hidden" in body["attrs"]
    assert panel in body["parents"]


def test_child_variable_titles_refresh_the_corner_panel_while_typing():
    render_source = DESIGNER_JS.read_text(encoding="utf-8")
    inspector_source = (DESIGNER_JS.parent / "inspector.js").read_text(encoding="utf-8")

    # Global/local editor rows and the Properties activity-variable editor must
    # all repaint the compact corner summary after changing a Title.
    assert "function wfRefreshVarTitle" in render_source
    assert render_source.count("v.label=lbl.value; wfRefreshVarTitle(lbl,v);") >= 2
    assert "v.label=lbl.value; wfRenderVarsPanel();" in inspector_source


def test_variables_panel_has_persisted_toggle_and_escape_behavior():
    source = DESIGNER_JS.read_text(encoding="utf-8")
    events_source = DESIGNER_EVENTS_JS.read_text(encoding="utf-8")

    assert 'localStorage.getItem("wfVarsPanelOpen")' in source
    assert "function wfToggleVarsPanel" in source
    assert "body.hidden=!wfVarsPanelOpen" in source
    assert 'e.key==="Escape"' in source
    assert "function wfToggleVarsPanel" not in events_source
