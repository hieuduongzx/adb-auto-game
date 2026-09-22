from html.parser import HTMLParser
from pathlib import Path
import re


SCOPE_DIR = Path(__file__).parents[1] / "apps" / "web" / "scope"
HTML_PATH = SCOPE_DIR / "index.html"
CSS_PATH = SCOPE_DIR / "css" / "style.css"
JS_DIR = SCOPE_DIR / "js"


class ScopeHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": "", "parents": tuple(self.stack)}
        self.elements.append(node)
        if tag not in {"meta", "link", "input", "img", "br"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data

    def by_id(self, element_id):
        return next(node for node in self.elements if node["attrs"].get("id") == element_id)


def document():
    parsed = ScopeHTML()
    parsed.feed(HTML_PATH.read_text(encoding="utf-8"))
    return parsed


def test_scope_has_one_instrument_shell_and_named_status_regions():
    doc = document()
    app = doc.by_id("app")
    toolbar = doc.by_id("toolbar")
    stage = doc.by_id("main")
    footer = doc.by_id("footer")

    assert "workbench-shell" in app["attrs"].get("class", "").split()
    assert toolbar["tag"] == "header"
    assert "workbench-bar" in toolbar["attrs"].get("class", "").split()
    assert toolbar["attrs"].get("aria-label") == "Capture controls"
    assert "workbench-main" in stage["attrs"].get("class", "").split()
    assert footer["tag"] == "footer"
    assert "workbench-status" in footer["attrs"].get("class", "").split()
    assert doc.by_id("status-text")["attrs"].get("role") == "status"


def test_inspection_tasks_are_named_and_grouped():
    doc = document()
    titles = {
        node["text"].strip()
        for node in doc.elements
        if "grp-title" in node["attrs"].get("class", "").split()
    }
    assert {"Capture", "Select", "Match", "OCR", "Input"}.issubset(titles)


def test_scope_keeps_every_javascript_id_hook_in_markup():
    html = HTML_PATH.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    sources = "\n".join(path.read_text(encoding="utf-8") for path in JS_DIR.glob("*.js"))
    referenced = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", sources))
    assert referenced - ids == set()


def test_scope_docked_regions_are_flat_and_page_does_not_scroll_sideways():
    css = CSS_PATH.read_text(encoding="utf-8")
    assert "#preview-card, #tools-card, #log-card { border-radius:0; box-shadow:none; }" in css
    assert "#main {" in css and "min-width: 0" in css
    assert "body {" in css and "overflow: hidden" in css
