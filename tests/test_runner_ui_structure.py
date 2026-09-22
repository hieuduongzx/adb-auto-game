from html.parser import HTMLParser
from pathlib import Path


RUNNER_DIR = Path(__file__).parents[1] / "apps" / "web" / "runner"
RUNNER_HTML = RUNNER_DIR / "index.html"
RUNNER_CSS = RUNNER_DIR / "css" / "runner.css"
RUNNER_JS = RUNNER_DIR / "js" / "runner.js"
RUNNER_BACKEND = Path(__file__).parents[1] / "apps" / "workflow_runner.py"


class _RunnerHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": "", "parents": tuple(self.stack)}
        self.elements.append(node)
        if tag not in {"input", "meta", "link", "img", "br"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()

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


def _document():
    parser = _RunnerHTML()
    parser.feed(RUNNER_HTML.read_text(encoding="utf-8"))
    return parser


def test_narrow_runner_exposes_one_primary_view_at_a_time():
    doc = _document()
    nav = doc.by_id("mobile-tabs")
    tabs = [node for node in doc.elements if nav in node["parents"] and node["attrs"].get("role") == "tab"]

    assert nav["attrs"]["role"] == "tablist"
    assert [tab["text"].strip() for tab in tabs] == ["Activities", "Log", "Settings"]
    assert [tab["attrs"].get("data-mobile-view") for tab in tabs] == ["activities", "log", "settings"]
    assert [tab["attrs"].get("aria-controls") for tab in tabs] == ["pane-left", "r-log", "mobile-settings"]
    assert sum(tab["attrs"].get("aria-selected") == "true" for tab in tabs) == 1

    settings = doc.by_id("mobile-settings")
    assert settings["attrs"].get("role") == "tabpanel"


def test_mobile_settings_reuses_one_mounted_settings_tree():
    source = RUNNER_JS.read_text(encoding="utf-8")

    assert 'const allowed = ["activities", "activity", "log", "settings"]' in source
    assert "let _runnerSettingsRoot = null" in source
    assert "if(!_runnerSettingsRoot)" in source
    assert "host.appendChild(_runnerSettingsRoot)" in source


def test_secondary_settings_use_progressive_disclosure_with_live_summaries():
    doc = _document()

    for element_id in ("runtime-section", "updates-section", "diagnostics-section"):
        section = doc.by_id(element_id)
        assert section["tag"] == "details"
        summaries = [node for node in doc.elements if section in node["parents"] and node["tag"] == "summary"]
        assert len(summaries) == 1
        assert any(node["attrs"].get("data-section-state") for node in doc.elements if section in node["parents"])


def test_activity_settings_announces_save_state():
    doc = _document()
    status = doc.by_id("activity-save-status")

    assert status["attrs"].get("role") == "status"
    assert status["attrs"].get("aria-live") == "polite"


def test_compact_pro_log_remains_a_dark_console_in_light_theme():
    css = RUNNER_CSS.read_text(encoding="utf-8")

    assert "--runner-log-bg: #202730" in css
    assert ".log-body" in css and "background: var(--runner-log-bg)" in css
    assert ".log-msg" in css and "color: var(--runner-log-ink)" in css


def test_loading_a_workflow_does_not_add_a_redundant_runner_log_line():
    source = RUNNER_BACKEND.read_text(encoding="utf-8")

    assert "Loaded workflow:" not in source
