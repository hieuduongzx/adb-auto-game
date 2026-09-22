from html.parser import HTMLParser
from pathlib import Path
import re


WEB = Path(__file__).parents[1] / "apps" / "web"
APPS = {
    "hub": WEB / "hub" / "index.html",
    "runner": WEB / "runner" / "index.html",
    "scope": WEB / "scope" / "index.html",
    "wf": WEB / "wf" / "index.html",
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
INTERACTIVE = {"button", "select", "textarea"}


class _Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": "", "parents": tuple(self.stack)}
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data


def _document(path):
    doc = _Document()
    doc.feed(path.read_text(encoding="utf-8-sig"))
    return doc


def _is_interactive(node):
    if node["tag"] in INTERACTIVE:
        return True
    if node["tag"] == "a" and node["attrs"].get("href"):
        return True
    if node["tag"] == "input" and node["attrs"].get("type") != "hidden":
        return True
    return node["attrs"].get("role") in {"button", "checkbox", "link", "switch", "tab"}


def test_every_surface_loads_shared_styles_in_dependency_order_and_theme_controller():
    expected = ["../shared/tokens.css", "../shared/base.css", "../shared/panel.css", "../shared/icons.css"]
    for name, path in APPS.items():
        doc = _document(path)
        styles = [node["attrs"].get("href") for node in doc.nodes if node["tag"] == "link" and node["attrs"].get("rel") == "stylesheet"]
        shared = [href for href in styles if href and "../shared/" in href]
        assert shared[:4] == expected, f"{name} shared CSS order is {shared[:4]}"
        scripts = [node["attrs"].get("src") for node in doc.nodes if node["tag"] == "script"]
        assert "../shared/theme.js" in scripts, f"{name} must apply data-theme and data-density before app code"


def test_every_surface_has_one_main_application_landmark():
    for name, path in APPS.items():
        doc = _document(path)
        mains = [node for node in doc.nodes if node["tag"] == "main"]
        assert len(mains) == 1, f"{name} has {len(mains)} main landmarks"
        assert mains[0]["attrs"].get("aria-label") or mains[0]["attrs"].get("aria-labelledby"), name


def test_static_markup_never_nests_interactive_controls():
    for name, path in APPS.items():
        doc = _document(path)
        for node in doc.nodes:
            if not _is_interactive(node):
                continue
            parent = next((candidate for candidate in reversed(node["parents"]) if _is_interactive(candidate)), None)
            assert parent is None, f"{name}: <{node['tag']}> is nested in interactive <{parent['tag']}>"


def test_icon_only_buttons_have_an_accessible_name():
    for name, path in APPS.items():
        doc = _document(path)
        for node in doc.nodes:
            if node["tag"] != "button":
                continue
            text = " ".join(node["text"].split())
            if text:
                continue
            attrs = node["attrs"]
            assert attrs.get("aria-label") or attrs.get("title") or attrs.get("aria-labelledby"), (
                f"{name}: icon-only button {attrs.get('id') or attrs.get('onclick') or attrs.get('class')} has no name"
            )


def test_theme_controller_owns_both_theme_and_density_hooks():
    source = (WEB / "shared" / "theme.js").read_text(encoding="utf-8")
    assert 'setAttribute("data-theme"' in source
    assert 'setAttribute("data-density"' in source
    assert "setDensity" in source
    assert 'querySelectorAll("[data-theme-toggle]")' in source
    assert 'setAttribute("aria-pressed"' in source


def test_shared_tokens_expose_primitive_semantic_and_component_layers():
    source = (WEB / "shared" / "tokens.css").read_text(encoding="utf-8")
    assert "--primitive-neutral-0:" in source
    assert re.search(r"--semantic-app-bg:\s*var\(--primitive-", source)
    assert re.search(r"--component-control-radius:\s*[012]px", source)
    assert re.search(r"--component-panel-radius:\s*0px", source)
    assert "--bg: var(--semantic-app-bg)" in source


def test_shared_foundation_defines_square_shell_bar_and_status_primitives():
    source = (WEB / "shared" / "base.css").read_text(encoding="utf-8")
    for selector in (".workbench-shell", ".workbench-bar", ".workbench-main", ".workbench-status"):
        assert selector in source
    assert ":focus-visible" in source
    assert "@media (prefers-reduced-motion: reduce)" in source


def test_each_surface_uses_the_shared_workbench_shell_and_status_vocabulary():
    required = {"workbench-shell", "workbench-main", "workbench-status"}
    for name, path in APPS.items():
        doc = _document(path)
        classes = {
            value
            for node in doc.nodes
            for value in node["attrs"].get("class", "").split()
        }
        assert required.issubset(classes), f"{name} is missing {required - classes}"


def test_shared_css_has_no_gradients_or_decorative_surface_shadows():
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (WEB / "shared").glob("*.css")
    }
    combined = "\n".join(sources.values()).lower()
    assert "linear-gradient(" not in combined
    assert "radial-gradient(" not in combined

    shadow_selectors = []
    for name, source in sources.items():
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", source):
            declarations = match.group(2)
            values = re.findall(r"box-shadow\s*:\s*([^;]+)", declarations)
            if values and any(value.strip() != "none" for value in values):
                shadow_selectors.append(f"{name}:{match.group(1).strip()}")
    allowed = (".skip-link", ".ui-toast", ".ui-modal", ".pnl.is-max")
    assert all(any(token in selector for token in allowed) for selector in shadow_selectors), shadow_selectors
