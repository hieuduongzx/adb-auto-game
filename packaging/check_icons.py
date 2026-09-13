"""Icon-set guard for the Macro2k web apps.

`apps/web/shared/icons.js` is meant to be the only copy of any icon geometry in
the suite. That is easy to state and easy to break by accident — pasting an
<svg> into a template is the path of least resistance — so this script is the
thing that actually holds the line. Run it standalone or from the build:

    python packaging/check_icons.py            # report, exit 1 on regression
    python packaging/check_icons.py --list     # also print every known offender

Three checks:

  1. NAMES   — every uiIco("x") call and data-ico="x" placeholder names an icon
               that exists. An unknown name renders *nothing* (see uiIco), so a
               typo is a silently missing button glyph, not a visible error.
  2. INLINE  — no app file inlines its own <svg> geometry. Files that predate
               this rule are listed in LEGACY with the count they had when the
               list was written; the count may fall, never rise, and a file that
               reaches zero must be deleted from the dict.
  3. LADDER  — the sizes and stroke-widths in shared/icons.css still land the
               rendered stroke in the ~1.0-1.8px band the file's own header
               promises. This is what makes the set read as one weight.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web"
ICONS_JS = WEB / "shared" / "icons.js"
ICONS_CSS = WEB / "shared" / "icons.css"

# ── Check 2 baseline ─────────────────────────────────────────────────────────
# path -> the number of inline <svg> sites present when this list was written
# (2026-09-13). The Hub and the Runner are already migrated and are therefore
# absent: any inline <svg> that appears in them is a hard failure.
#
# These two directories are the ones the icon cleanup covered. The Designer
# (wf/) and DevScope (scope/) still carry verbatim Lucide copies inline — the
# geometry is right and the sizes land on ladder steps, which is why they look
# correct, but it is still a second copy that can drift. Migrating them is
# mechanical and can happen a file at a time; each file's number below is the
# ratchet. Do not raise a number, and delete the entry when a file reaches 0.
CLEAN_APPS = ("hub", "runner")

LEGACY = {
    "wf/index.html": 67,
    "wf/js/render.js": 12,
    "wf/js/inspector.js": 9,
    "wf/js/io.js": 2,
    "wf/js/validate.js": 2,
    "wf/js/workflow.js": 1,
    "wf/js/finder.js": 1,
    "wf/js/cmdpalette.js": 1,
    "scope/index.html": 23,
    "shared/panel.js": 3,
}

# An <svg> that is a drawing surface rather than an icon, and CSS data: URIs
# (a background chevron in base.css/style.css), are not icon geometry.
NOT_AN_ICON = re.compile(r"<svg[^>]*\bid=\"wf-wires\"")
DATA_URI = re.compile(r"url\(\s*[\"']?data:image/svg\+xml")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Check 1: every requested name exists ─────────────────────────────────────

def icon_names() -> set[str]:
    """The keys of the ICO map in shared/icons.js."""
    src = read(ICONS_JS)
    start = src.index("var ICO = {")
    end = src.index("\n  };", start)
    return set(re.findall(r'^\s*"([a-z0-9-]+)":', src[start:end], re.MULTILINE))


# Semantic-name -> shared-name maps resolved at runtime, so the literal scan
# cannot see the values. Every one of these is a place a typo renders nothing.
NAME_MAPS = (
    ("wf/js/workflow.js", "WF_ICONS"),      # node / palette glyphs
    ("wf/js/ui.js", "UI_TOAST_ICO"),        # Designer toasts
    ("hub/js/hub.js", "TOAST_ICO"),         # Hub toasts
)

UIICO_CALL = re.compile(r"""\buiIco\(\s*["']([^"']+)["']""")
DATA_ICO = re.compile(r"""data-ico=["']([^"']+)["']""")
WF_MAP_ENTRY = re.compile(r"""^\s*[A-Za-z_$][\w$]*:\s*["']([a-z0-9-]+)["'],\s*$""", re.MULTILINE)


def check_names(names: set[str]) -> list[str]:
    """Report names an app asks for that the set does not define."""
    problems: list[str] = []

    for path in sorted(WEB.rglob("*.js")) + sorted(WEB.rglob("*.html")):
        if path == ICONS_JS:
            continue
        src = read(path)
        rel = path.relative_to(WEB).as_posix()

        for match in UIICO_CALL.finditer(src):
            if match.group(1) not in names:
                line = src[: match.start()].count("\n") + 1
                problems.append(f"{rel}:{line}: uiIco(\"{match.group(1)}\") — no such icon")
        for match in DATA_ICO.finditer(src):
            if match.group(1) not in names:
                line = src[: match.start()].count("\n") + 1
                problems.append(f"{rel}:{line}: data-ico=\"{match.group(1)}\" — no such icon")

    # Name maps whose values are looked up dynamically, so the literal scan above
    # cannot see them. A wrong value here renders nothing at runtime, which is
    # the failure this whole script exists to catch.
    for rel, mapname in NAME_MAPS:
        src = read(WEB / rel)
        start = src.index(f"const {mapname} = {{")
        block = src[start : src.index("\n};", start)]
        for match in WF_MAP_ENTRY.finditer(block):
            if match.group(1) not in names:
                problems.append(f'{rel}: {mapname} maps to "{match.group(1)}" — no such icon')

    return problems


# ── Check 2: no app draws its own geometry ───────────────────────────────────

COMMENT = re.compile(r"<!--.*?-->|/\*.*?\*/|//[^\n]*", re.DOTALL)


def inline_sites(text: str) -> int:
    """Count icon <svg> elements — the open tag alone, not the geometry.

    Comments are stripped first: more than one file documents the icon system in
    prose ("returns a full <svg>"), and counting those would put the baseline
    out by exactly the number of comments someone is encouraged to write.
    """
    text = COMMENT.sub("", text)
    total = 0
    for match in re.finditer(r"<svg[\s>]", text):
        if NOT_AN_ICON.match(text, match.start()):
            continue
        # A data: URI inside a stylesheet is not a site in the document.
        if DATA_URI.search(text[max(0, match.start() - 200) : match.start()]):
            continue
        total += 1
    return total


def check_inline(verbose: bool) -> list[str]:
    """Fail on geometry in a clean app, or above a legacy file's baseline."""
    problems: list[str] = []
    report: list[str] = []

    for path in sorted(WEB.rglob("*.js")) + sorted(WEB.rglob("*.html")) + sorted(WEB.rglob("*.css")):
        if path == ICONS_JS:
            continue
        rel = path.relative_to(WEB).as_posix()
        if DATA_URI.search(read(path)) and "<svg" not in DATA_URI.sub("", read(path)):
            continue  # a stylesheet whose only <svg> is inside a data: URI

        count = inline_sites(read(path))
        app = rel.split("/", 1)[0]
        allowed = 0 if app in CLEAN_APPS else LEGACY.get(rel, 0)

        if count > allowed:
            hint = (
                "  the Hub and Runner are migrated and must stay that way"
                if app in CLEAN_APPS
                else f"  baseline for this file is {allowed}"
            )
            problems.append(
                f"{rel}: {count} inline <svg> site(s), allowed {allowed}\n"
                f"    Call uiIco(name) or use a <i data-ico=\"name\"> placeholder instead,\n"
                f"    and add the name to shared/icons.js if it is missing.{hint}"
            )
        elif count < allowed:
            report.append(
                f"{rel}: {count} inline <svg> site(s), down from {allowed} — "
                f"lower the baseline in packaging/check_icons.py"
            )

    # A legacy file that no longer exists is a stale baseline, not a failure.
    for rel in LEGACY:
        if not (WEB / rel).exists():
            report.append(f"{rel}: listed in LEGACY but no longer exists — remove it")

    if verbose:
        for line in report:
            print(f"  note: {line}")
    return problems


# ── Check 3: the ladder still holds its optical weight ───────────────────────

STEP = re.compile(r"(\.uico(?:-\d)?)\s*\{[^}]*?width:\s*([\d.]+)px[^}]*?stroke-width:\s*([\d.]+)")


def check_ladder() -> list[str]:
    """Every step must render its stroke inside the band the header promises."""
    problems: list[str] = []
    css = read(ICONS_CSS)

    seen = 0
    for match in STEP.finditer(css):
        cls, size, stroke = match.group(1), float(match.group(2)), float(match.group(3))
        rendered = stroke * size / 24
        seen += 1
        if not 1.0 <= rendered <= 1.8:
            problems.append(
                f"shared/icons.css: {cls} is {size:g}px at stroke-width {stroke:g} "
                f"— renders {rendered:.2f}px, outside the 1.00-1.80px band"
            )
    if seen < 7:
        problems.append(
            f"shared/icons.css: found {seen} ladder step(s), expected at least 7 — "
            f"a step was renamed or dropped"
        )
    return problems


# ── Entry point ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """argv defaults to sys.argv via argparse; the self-test passes []."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print ratchet progress notes")
    args = parser.parse_args(argv)

    names = icon_names()
    name_problems = check_names(names)
    inline_problems = check_inline(args.list)
    ladder_problems = check_ladder()

    print(f"icon set: {len(names)} names in shared/icons.js")
    for title, problems in (
        ("names", name_problems),
        ("inline geometry", inline_problems),
        ("ladder", ladder_problems),
    ):
        if problems:
            print(f"\nFAIL — {title} ({len(problems)}):")
            for problem in problems:
                print(f"  {problem}")

    if name_problems or inline_problems or ladder_problems:
        return 1
    print("\nICONS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
