"""Build a standalone **single-workflow Runner** .exe.

Produces ``dist/<Name>-Runner/`` containing just the Runner GUI, the one
workflow (bundled into the exe), and only the ``vendor/`` pieces that workflow
actually needs — no Designer, no Hub, no DevScope. This is the lean counterpart
to ``packaging/build.ps1`` (which builds the full Macro2k suite).

Usage (from the project root, with the dev Python that has PyInstaller)::

    python packaging/build_runner.py --workflow workflows/BrownDust2
    python packaging/build_runner.py --workflow workflows/BrownDust2 --version 1.2.0
    python packaging/build_runner.py --workflow workflows/BrownDust2 --version 1.2.0 --publish

The Hub's **Build** button and the Designer's **Build EXE** button shell out to
exactly this script.

Preflight
---------
Everything a build needs is checked *before* PyInstaller starts (:func:`preflight`)
— the workflow JSON, the spec, PyInstaller itself, the ``vendor/`` tools the
workflow's graph actually requires, the workflow's own icon, the shared icon set
(:mod:`packaging.check_icons`), and — when publishing — ``gh``, its login and a
free release tag. The same report feeds the CLI, the Hub's build dialog and the
Designer's, so all three refuse the same builds for the same reason, in a second
instead of after minutes of PyInstaller.

Versions and self-update
------------------------
Every Runner carries its own version and update feed in a bundled
``runner_build.json`` (see :mod:`src.runner_update`). ``--publish`` zips the
finished folder and creates a GitHub Release tagged
``runner-<AppName>-v<version>`` in ``--repo`` (default: the repo in
``src/version.py``) with ``--latest=false``, so several games share one repo
without touching each other's — or the Hub installer's — releases. Publishing
uses the ``gh`` CLI and its existing login.

Icon
----
Each Runner's exe carries its game's own icon, from the first of
``assets/icon.(ico|png|jpg|jpeg|webp)``, a square cut from
``assets/cover.*``, or — with neither — the game's initials on a tinted tile
(the same initials and hue as the Hub's blank cover slot). Needs Pillow; without
it the build falls back to the Macro2k icon.

Vendor trimming
---------------
The workflow JSON is scanned to decide which vendor tools ship:

* ``adb``       — ADB controller, an ``adb`` capture source, or any emulator node
* ``scrcpy``    — ADB projects using the scrcpy capture source
* ``tesseract`` — any OCR text node (``if_text`` / ``wait_text`` / ``read_var`` /
                  ``parse_var``)
* ``frida``     — an enabled ADB speed hack only (``vendor/frida`` is the Android
                  frida-inject binary; Win32 input uses Win32 messaging, not
                  frida, so Win32 workflows never need it)

Game requirements
-----------------
Files the *player* must put into the game's own install folder (a BepInEx loader,
an in-game plugin, a config…) live in ``workflows/<Name>/vendor/``. That folder is
not bundled into the exe; it ships beside it::

    dist/<Name>-Runner/
        requirements/        <- a copy of workflows/<Name>/vendor/
        REQUIREMENTS.txt     <- how to install them (copy into the game folder)

The Runner points at it on load and offers Settings → Game files → *Copy into
game folder*. No ``vendor/`` (or an empty one) → neither is produced.

Output protocol
---------------
Lines a caller (Hub / Designer / the Designer's own build panel) can parse, all
prefixed ``>>``:

* ``>> PROGRESS <0-100> <stage>`` — overall progress and the current stage
* ``>> CHECK <ok|warn|fail> <code>: <message>`` — one preflight result
* ``>> PREFLIGHT OK`` / ``>> PREFLIGHT FAILED: <summary>``
* ``>> DONE: <exe path>`` / ``>> RELEASE: <url>`` / ``>> BUILD FAILED: <why>``
* ``>> REQUIREMENTS: <folder>`` — the build ships game requirements to copy
* any other ``>> …`` line is a milestone for the log

With ``--verbose`` every PyInstaller line is echoed too, prefixed ``..``.
"""
from __future__ import annotations

import argparse
import base64
import colorsys
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "runner_build.spec")
VENDOR_SRC = os.path.join(ROOT, "vendor")

# The vendor sub-tools we know how to trim to.
VENDOR_TOOLS = ("adb", "scrcpy", "tesseract", "frida")
OCR_NODES = {"if_text", "wait_text", "read_var", "parse_var"}
EMULATOR_NODES = {"launch_emulator", "if_emulator", "wait_emulator"}
# Folders a running Runner writes into; never shipped in an update zip.
USER_DIRS = ("data", "out", "logs")
# Game requirements: <workflow>/vendor/ ships beside the exe as requirements/.
REQUIREMENTS_SRC = "vendor"
REQUIREMENTS_DIR = "requirements"
REQUIREMENTS_NOTE = "REQUIREMENTS.txt"
REQUIREMENTS_SKIP = (".gitkeep", "Thumbs.db", "desktop.ini", ".DS_Store")

# PyInstaller milestones → overall progress while PyInstaller runs (6..84 %).
PYINSTALLER_STAGES = (
    ("Building Analysis", 12, "Analysing imports"),
    ("Looking for dynamic libraries", 42, "Collecting libraries"),
    ("Building PYZ", 64, "Bundling Python code"),
    ("Building PKG", 70, "Packing archive"),
    ("Building EXE", 74, "Building the exe"),
    ("Building COLLECT", 80, "Collecting files"),
)


def log(msg: str) -> None:
    """Emit a milestone line the caller (Hub / Designer) can parse + display."""
    print(f">> {msg}", flush=True)


def progress(pct: int, stage: str) -> None:
    print(f">> PROGRESS {int(pct)} {stage}", flush=True)


def _issue(code: str, level: str, message: str, hint: str = "") -> dict:
    """One preflight result: ``level`` is ``fail`` (blocks) or ``warn``."""
    return {"code": code, "level": level, "message": " ".join(str(message).split()),
            "hint": hint}


class PreflightError(RuntimeError):
    """Raised by :func:`build` when the preflight found a blocking problem.

    Carries the full :func:`preflight` report so a caller that started the build
    itself (the Hub, the Designer) can show every problem, not just the first.
    """

    def __init__(self, report: dict) -> None:
        self.report = report
        problems = list(report.get("blocking") or []) or ["build preflight failed"]
        summary = problems[0] if len(problems) == 1 else f"{len(problems)} problems — " + "; ".join(problems)
        super().__init__(summary)
        self.summary = summary


# Preflight commands (gh, the icon guard) must never hang the caller's UI.
PREFLIGHT_TIMEOUT = 20.0


def _sanitize(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", (raw or "").strip())
    return cleaned.strip("._-") or "Workflow"


def tag_prefix(app_name: str) -> str:
    """Release tag prefix of one Runner: ``runner-<AppName>-v``."""
    return f"runner-{app_name}-v"


def default_repo() -> str:
    """``owner/name`` of the update repo declared in ``src/version.py``."""
    try:
        with open(os.path.join(ROOT, "src", "version.py"), "r", encoding="utf-8") as fh:
            match = re.search(r'"https://github\.com/([^"/]+/[^"/]+?)(?:\.git)?/?"', fh.read())
        return match.group(1) if match else ""
    except OSError:
        return ""


def find_workflow_json(folder: str) -> str | None:
    """Pick the primary JSON in a workflow folder (workflow.json preferred)."""
    if not os.path.isdir(folder):
        return None
    names = [n for n in os.listdir(folder) if n.lower().endswith(".json")]
    if not names:
        return None
    lower = {n.lower(): n for n in names}
    if "workflow.json" in lower:
        return os.path.join(folder, lower["workflow.json"])
    base = os.path.basename(folder.rstrip("/\\"))
    if f"{base}.json".lower() in lower:
        return os.path.join(folder, lower[f"{base}.json".lower()])
    names.sort(key=str.lower)
    return os.path.join(folder, names[0])


def resolve_flow_path(workflow_dir: str, flow_path: str = "") -> str:
    """The workflow JSON this build bundles and version-stamps.

    An explicit *flow_path* — the file the Hub or the Designer has open — always
    wins. Without it the folder is guessed at (:func:`find_workflow_json`), which
    is right for the CLI but wrong for an editor: a folder holding more than one
    JSON would bundle one workflow and write ``--save-version`` into another.
    Returns "" when nothing was found, so the caller can explain why.
    """
    if flow_path:
        path = os.path.abspath(flow_path)
        return path if os.path.isfile(path) else ""
    return find_workflow_json(workflow_dir) or ""


def compute_vendor_needs(flow: dict) -> set[str]:
    """Which vendor sub-tools this workflow requires at runtime."""
    controller = str(flow.get("controller") or "adb").strip().lower()
    capture = str(flow.get("capture") or "scrcpy").strip().lower()
    speedhack = flow.get("speedhack") or {}

    node_types: set[str] = set()
    for coll in ("activities", "functions"):
        for item in flow.get(coll) or []:
            for node in ((item.get("graph") or {}).get("nodes") or []):
                t = node.get("type")
                if t:
                    node_types.add(str(t))

    is_adb = controller == "adb"
    has_emulator = bool(node_types & EMULATOR_NODES)

    needs: set[str] = set()
    # adb.exe — any ADB device work (device controller, adb capture, emulator).
    if is_adb or has_emulator or capture == "adb":
        needs.add("adb")
    # scrcpy — only ADB projects using the scrcpy frame source.
    if (is_adb or has_emulator) and capture == "scrcpy":
        needs.add("scrcpy")
    # tesseract — any OCR text node.
    if node_types & OCR_NODES:
        needs.add("tesseract")
    # frida — ADB speed hack ONLY. vendor/frida is the Android frida-inject
    # binary; Win32 input uses Win32 messaging (PostMessage/SendMessage), never
    # frida, so a Win32 workflow never needs this ~107 MB tree.
    if is_adb and bool(speedhack.get("enabled")):
        needs.add("frida")
    return needs


# ── Game icon ─────────────────────────────────────────────────────────────────
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
ICON_NAMES = ("icon.ico", "icon.png", "icon.jpg", "icon.jpeg", "icon.webp")
COVER_NAMES = ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp")
# Hues of the Hub's blank cover slots — keep in step with TONES in hub.js.
TONES = (214, 158, 256, 32, 346, 190)
_ICON_SS = 8  # supersample factor for drawn frames


def find_icon_source(workflow_dir: str) -> tuple[str, str]:
    """``("icon" | "cover" | "generated", path)`` for this workflow's exe icon."""
    assets = os.path.join(workflow_dir, "assets")
    for kind, names in (("icon", ICON_NAMES), ("cover", COVER_NAMES)):
        for name in names:
            path = os.path.join(assets, name)
            if os.path.isfile(path):
                return kind, path
    return "generated", ""


def describe_icon_source(workflow_dir: str) -> str:
    kind, path = find_icon_source(workflow_dir)
    if kind == "icon":
        return f"assets/{os.path.basename(path)}"
    if kind == "cover":
        return f"cut from assets/{os.path.basename(path)}"
    return "initials — add assets/icon.png to use your own"


def tone_for(key: str) -> int:
    """Same hash as ``toneFor`` in hub.js, so a game keeps its hue everywhere."""
    h = 0
    for ch in str(key or ""):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return TONES[h % len(TONES)]


def initials_for(name: str) -> str:
    """``"BrownDust2"`` → ``"BD"``, ``"Cherry_Tale"`` → ``"CT"`` (as hub.js)."""
    spaced = re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", str(name or ""))
    words = [w for w in re.split(r"[\s_\-.]+", spaced) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _hsl(hue: int, sat: float, light: float) -> tuple[int, int, int, int]:
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, light, sat)
    return round(r * 255), round(g * 255), round(b * 255), 255


def _icon_font(px: int):
    from PIL import ImageFont

    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in ("segoeuisb.ttf", "segoeuib.ttf", "arialbd.ttf"):
        path = os.path.join(fonts, name)
        if os.path.isfile(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default(size=px)


def _monogram_frame(size: int, initials: str, tone: int):
    """Initials on a tinted rounded tile; tiny frames keep only the first letter."""
    from PIL import Image, ImageDraw

    px = size * _ICON_SS
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = round(px * (0.16 if size <= 24 else 0.22))
    draw.rounded_rectangle((0, 0, px - 1, px - 1), radius, fill=_hsl(tone, 0.40, 0.30))
    text = initials[:1] if size <= 20 else initials
    font = _icon_font(round(px * (0.60 if len(text) == 1 else 0.44)))
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((px - (right - left)) / 2 - left, (px - (bottom - top)) / 2 - top),
              text, font=font, fill=_hsl(tone, 0.45, 0.93))
    return img.resize((size, size), Image.LANCZOS)


def _square_art(path: str, from_cover: bool):
    """A 512 px square from an icon image (centred) or a 3:4 cover (subject
    usually sits above centre, so the cut leans up; corners get rounded)."""
    from PIL import Image, ImageChops, ImageDraw

    with Image.open(path) as src:
        img = src.convert("RGBA")
    width, height = img.size
    side = min(width, height)
    left = (width - side) // 2
    if from_cover:
        top = min(height - side, max(0, round(height * 0.42 - side / 2)))
    else:
        top = (height - side) // 2
    art = img.crop((left, top, left + side, top + side)).resize((512, 512), Image.LANCZOS)
    if from_cover:
        mask = Image.new("L", (512, 512), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 511, 511), round(512 * 0.2), fill=255)
        art.putalpha(ImageChops.multiply(art.getchannel("A"), mask))
    return art


def render_icon_frames(workflow_dir: str, display_name: str, sizes=ICON_SIZES) -> list:
    """One RGBA frame per size for this workflow's icon (requires Pillow)."""
    from PIL import Image

    kind, path = find_icon_source(workflow_dir)
    if kind != "generated":
        try:
            art = _square_art(path, from_cover=(kind == "cover"))
            return [art.resize((s, s), Image.LANCZOS) for s in sizes]
        except Exception as exc:
            log(f"WARNING: couldn't use {path} as the icon ({exc}) — using initials")
    tone = tone_for(os.path.basename(os.path.normpath(workflow_dir)))
    initials = initials_for(display_name)
    return [_monogram_frame(s, initials, tone) for s in sizes]


def write_icon(workflow_dir: str, display_name: str, ico_path: str, png_path: str = "") -> None:
    """Write the multi-size ``.ico`` (and a 256 px ``.png``) for this workflow."""
    frames = render_icon_frames(workflow_dir, display_name)
    # Pillow derives every ``sizes`` entry from the base image unless the
    # pre-rendered frames ride along in append_images (keeps the small-size pass).
    frames[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES],
                    append_images=frames[:-1])
    if png_path:
        frames[-1].save(png_path, format="PNG")


def icon_preview_data_uri(workflow_dir: str, display_name: str, size: int = 64) -> str:
    """The icon as a ``data:image/png`` URI (the Hub's Build dialog preview)."""
    frame = render_icon_frames(workflow_dir, display_name, sizes=(size,))[0]
    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _dir_size_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def _trim_build(final: str) -> None:
    """Delete dead weight PyInstaller pulls in but this runner never uses.

    * ``cv2/opencv_videoio_ffmpeg*.dll`` (~54 MB) — OpenCV's bundled ffmpeg for
      ``cv2.VideoCapture``. The engine only does image ops (matchTemplate /
      imread / imdecode / resize / cvtColor); scrcpy video is decoded by PyAV,
      not cv2. Confirmed safe: cv2 still imports + matches without these.
    """
    internal = os.path.join(final, "_internal")
    removed = 0.0
    for dll in glob.glob(os.path.join(internal, "cv2", "opencv_videoio_ffmpeg*.dll")):
        try:
            removed += os.path.getsize(dll) / (1024 * 1024)
            os.remove(dll)
        except OSError:
            pass
    if removed:
        log(f"Trimmed cv2 videoio ffmpeg DLLs (−{removed:.0f} MB, unused)")


def _copy_vendor(needs: set[str], dest_root: str) -> None:
    dest_vendor = os.path.join(dest_root, "vendor")
    for tool in sorted(needs):
        src = os.path.join(VENDOR_SRC, tool)
        if not os.path.isdir(src):
            log(f"WARNING: vendor/{tool} not found — skipping (runtime may fail)")
            continue
        dst = os.path.join(dest_vendor, tool)
        log(f"Copying vendor/{tool} …")
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)


def find_requirements(workflow_dir: str) -> list[str]:
    """Files under ``<workflow>/vendor/`` (relative, ``/``-separated): what the
    player must copy into the game folder. ``[]`` when there is nothing to ship."""
    src = os.path.join(workflow_dir, REQUIREMENTS_SRC)
    found: list[str] = []
    for root, dirs, files in os.walk(src):
        dirs.sort(key=str.lower)
        for name in sorted(files, key=str.lower):
            if name not in REQUIREMENTS_SKIP:
                found.append(os.path.relpath(os.path.join(root, name), src).replace("\\", "/"))
    return found


def describe_requirements(workflow_dir: str) -> str:
    files = find_requirements(workflow_dir)
    if not files:
        return "(none — add workflows/<Name>/vendor/ for files the game folder needs)"
    return f"{len(files)} file(s) from vendor/ → {REQUIREMENTS_DIR}/"


# ── Build preflight ───────────────────────────────────────────────────────────
# What a build needs, checked *before* the slow part. The CLI, the Hub
# (build_info → build_runner) and the Designer (build_runner_preflight →
# build_runner_exe) all run this one function, so the three surfaces agree about
# what may be built and why not.

def preflight(workflow_dir: str, *, flow: dict | None = None, app_name: str = "",
              version: str = "", repo: str = "", publish: bool = False,
              dry_run: bool = False, allow_missing_vendor: bool = False,
              emit: bool = False) -> dict:
    """Check everything a build needs and report what is missing.

    *flow* may be handed in (the Hub / Designer already have it parsed and the
    page may hold edits the file doesn't have yet); otherwise the workflow JSON
    in *workflow_dir* is read. *version* / *repo* follow the same fallbacks a
    build uses — the argument, then the workflow's own record, then
    :func:`default_repo` — and are echoed back resolved.

    Returns a JSON-friendly report::

        {"ok": bool, "issues": [{"code", "level", "message", "hint"}],
         "blocking": [str], "warnings": [str],
         "appName": str, "version": str, "repo": str, "tag": str,
         "vendor": [str], "missingVendor": [str],
         "iconSource": str, "requirements": [str]}

    *emit* prints one ``>> CHECK <level> <code>: <message>`` line per check plus
    a ``>> PREFLIGHT OK`` / ``>> PREFLIGHT FAILED: …`` summary, so a subprocess
    caller (the Hub's build worker, the Designer's log) shows the same reasoning
    the in-process callers put in their dialogs.
    """
    issues: list[dict] = []
    workflow_dir = os.path.abspath(workflow_dir or ".")

    if not isinstance(flow, dict):
        path = find_workflow_json(workflow_dir)
        flow = {}
        if not path:
            issues.append(_issue("workflow", "fail",
                                 f"No workflow JSON in {workflow_dir}",
                                 "Save the workflow first."))
        else:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    flow = json.load(fh) or {}
            except Exception as exc:
                issues.append(_issue("workflow", "fail",
                                     f"Couldn't read {os.path.basename(path)}: {exc}"))
    if not flow:
        issues.append(_issue("workflow", "fail", "The workflow is empty",
                             "Add an activity, then build again."))

    display_name = str(flow.get("name") or os.path.basename(workflow_dir) or "workflow")
    app = _sanitize(app_name or display_name)
    ver = str(version or flow.get("buildVersion") or "1.0.0").strip() or "1.0.0"
    update = flow.get("runnerUpdate") if isinstance(flow.get("runnerUpdate"), dict) else {}
    slug = (str(repo or "").strip() or str(update.get("repo") or "").strip()
            or default_repo()).strip()
    tag = f"{tag_prefix(app)}{ver}"

    # ── The build inputs themselves ──────────────────────────────────────────
    for code, filename, why in (
        ("spec", os.path.join("packaging", "runner_build.spec"),
         "The PyInstaller spec that describes the Runner."),
        ("entry", os.path.join("packaging", "entry_runner_single.py"),
         "The Runner entry script the spec analyses."),
    ):
        if not os.path.isfile(os.path.join(ROOT, filename)):
            issues.append(_issue(code, "fail", f"{filename} is missing",
                                 f"{why} Building needs a source checkout."))

    pyi = pyinstaller_version()
    if pyi:
        issues.append(_issue("pyinstaller", "ok", f"PyInstaller {pyi}"))
    else:
        issues.append(_issue("pyinstaller", "fail",
                             f"PyInstaller is not installed for {sys.executable}",
                             "python -m pip install pyinstaller"))

    # ── The vendor tools this workflow's graph actually uses ─────────────────
    needs = compute_vendor_needs(flow)
    missing = [t for t in sorted(needs) if not os.path.isdir(os.path.join(VENDOR_SRC, t))]
    if missing:
        listed = ", ".join(f"vendor/{t}" for t in missing)
        issues.append(_issue(
            "vendor", "warn" if allow_missing_vendor else "fail",
            f"this workflow needs {listed}, which {'is' if len(missing) == 1 else 'are'} not in this checkout",
            "Fetch the tool into vendor/ (see packaging/build.md) — the build would "
            "copy it into the Runner, and without it the Runner fails at runtime."))
    elif needs:
        issues.append(_issue("vendor", "ok", "vendors: " + ", ".join(sorted(needs))))

    # ── Icons: the shared set (fatal) and this game's own (a fallback) ───────
    guard_ok, guard_out = icon_guard()
    if not guard_ok:
        first = _first_problem(guard_out)
        issues.append(_issue(
            "icons", "fail",
            "the shared icon set has a problem — an unknown name ships as a blank glyph"
            + (f": {first}" if first else ""),
            "Run: python packaging/check_icons.py"))
    kind, icon_path = find_icon_source(workflow_dir)
    icon_source = describe_icon_source(workflow_dir)
    icon_why = icon_asset_problem(kind, icon_path)
    if icon_why:
        issues.append(_issue("icon", "warn",
                             f"{icon_source} can't be used ({icon_why}) — drawn initials "
                             "will be used instead"))
    else:
        issues.append(_issue("icon", "ok", f"icon: {icon_source}"))

    # ── Publishing (only when this build will actually publish) ──────────────
    if publish or dry_run:
        pub_issues = publish_checks(slug, app, ver, dry_run=dry_run)
        issues.extend(pub_issues)
        if not pub_issues:
            issues.append(_issue("publish", "ok",
                                 f"publish: {tag} → {slug}" if publish
                                 else f"publish (dry run): {tag} → {slug}"))

    # ── Report ───────────────────────────────────────────────────────────────
    fails = [i for i in issues if i["level"] == "fail"]
    warns = [i for i in issues if i["level"] == "warn"]
    report = {
        "ok": not fails,
        "issues": issues,
        "blocking": [i["message"] for i in fails],
        "warnings": [i["message"] for i in warns],
        "appName": app,
        "name": display_name,
        "version": ver,
        "repo": slug,
        "tag": tag,
        "vendor": sorted(needs),
        "missingVendor": missing,
        "iconSource": icon_source,
        "requirements": find_requirements(workflow_dir),
    }
    if emit:
        for issue in issues:
            if issue["level"] != "ok":
                log(f"CHECK {issue['level']} {issue['code']}: {issue['message']}")
        if report["ok"]:
            log(f"PREFLIGHT OK — {display_name}, {', '.join(sorted(needs)) or 'no vendor'}")
        else:
            log(f"PREFLIGHT FAILED: {PreflightError(report).summary}")
    return report


def _requirements_note(display_name: str, entries: list[str]) -> str:
    listing = "\n".join(f"  {e}" for e in entries)
    title = f"{display_name} — required game files"
    return (
        f"{title}\n{'=' * len(title)}\n\n"
        "Tiếng Việt\n----------\n"
        "Game này cần thêm file để Runner hoạt động. Hãy copy TOÀN BỘ nội dung thư mục\n"
        f"\"{REQUIREMENTS_DIR}\" vào thư mục cài đặt game (nơi có file .exe của game),\n"
        "chọn ghi đè nếu được hỏi, rồi khởi động lại game.\n"
        "Hoặc trong Runner: Settings → Game path chọn file .exe của game, rồi\n"
        "Settings → Game files → \"Copy into game folder\".\n\n"
        "English\n-------\n"
        "This game needs extra files for the Runner to work. Copy EVERYTHING inside the\n"
        f"\"{REQUIREMENTS_DIR}\" folder into the game's install folder (where the game's .exe\n"
        "is), overwrite if asked, then restart the game.\n"
        "Or in the Runner: set Settings → Game path to the game's .exe, then\n"
        "Settings → Game files → \"Copy into game folder\".\n\n"
        f"Contents of {REQUIREMENTS_DIR}\\:\n{listing}\n"
    )


def _copy_requirements(workflow_dir: str, final: str, display_name: str) -> str:
    """Copy ``<workflow>/vendor/`` → ``<final>/requirements/`` and write the
    install note beside the exe. Returns the requirements folder, or ""."""
    if not find_requirements(workflow_dir):
        return ""
    src = os.path.join(workflow_dir, REQUIREMENTS_SRC)
    dst = os.path.join(final, REQUIREMENTS_DIR)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*REQUIREMENTS_SKIP))
    entries = [n + ("\\" if os.path.isdir(os.path.join(dst, n)) else "")
               for n in sorted(os.listdir(dst), key=str.lower)]
    with open(os.path.join(final, REQUIREMENTS_NOTE), "w", encoding="utf-8-sig") as fh:
        fh.write(_requirements_note(display_name, entries))
    return dst


def _zip_runner(folder: str, zip_path: str) -> None:
    """Zip the Runner folder's contents (not the folder itself) for an update."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(folder):
            rel_root = os.path.relpath(root, folder)
            if rel_root == ".":
                dirs[:] = [d for d in dirs if d not in USER_DIRS]
            for name in files:
                path = os.path.join(root, name)
                zf.write(path, os.path.relpath(path, folder))


def _gh(args: list[str], timeout: float = PREFLIGHT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run ``gh`` and never raise: a missing CLI, a timeout or a crash all come
    back as a non-zero result, so callers only look at ``returncode``."""
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(["gh", *args], 127, "", str(exc))


def gh_available() -> bool:
    """Is the GitHub CLI on PATH? (Publishing is impossible without it.)"""
    return shutil.which("gh") is not None


def pyinstaller_version() -> str:
    """Version of the PyInstaller this interpreter can import, or ""."""
    try:
        import PyInstaller
    except Exception:
        return ""
    return str(getattr(PyInstaller, "__version__", "") or "installed")


def icon_guard() -> tuple[bool, str]:
    """``(ok, output)`` from :mod:`packaging.check_icons` — the shared icon set.

    A name the set doesn't define renders as *nothing* at runtime, which is
    exactly the kind of failure a build must refuse to ship, so this runs before
    PyInstaller rather than after it.
    """
    script = os.path.join(ROOT, "packaging", "check_icons.py")
    if not os.path.isfile(script):
        return True, ""        # trimmed checkout — nothing to guard
    try:
        proc = subprocess.run(
            [sys.executable, script], cwd=ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"(the icon guard couldn't run: {exc})"
    return proc.returncode == 0, (proc.stdout or proc.stderr or "").strip()


def _first_problem(output: str) -> str:
    """A one-line gist of the icon guard's output: the first failing check plus
    the first detail under it (which names the file and the line)."""
    lines = [ln.rstrip() for ln in (output or "").splitlines()]
    header = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("icon set:", "note:")):
            continue
        if line.startswith("  ") and header:
            return f"{header} — {stripped}"
        if not line.startswith("  "):
            header = stripped
            continue
    return header


def icon_asset_problem(kind: str, path: str) -> str:
    """Why this workflow's own icon can't be used, or "" when it can.

    Only inspects the file the build would actually use, so the answer matches
    what :func:`render_icon_frames` will do a minute later (it falls back to
    drawn initials, which is why this is a warning and not a refusal).
    """
    if kind == "generated" or not path:
        return ""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return "Pillow isn't installed"
    try:
        _square_art(path, from_cover=(kind == "cover"))
    except Exception as exc:
        return str(exc)
    return ""


def publish_checks(repo: str, app_name: str, version: str,
                   dry_run: bool = False) -> list[dict]:
    """Everything that stops a publish, as preflight issues.

    Shared by :func:`preflight` (before the build) and :func:`publish` (right
    before the upload) so there is exactly one set of rules about what may be
    published — and so the user hears about a taken tag before PyInstaller runs,
    not three minutes later.
    """
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        return [_issue("repo", "fail",
                       f"Invalid update repo '{repo}' (expected owner/name)",
                       "Set the repo in the workflow's runnerUpdate, or with --repo.")]
    if dry_run:
        return []
    if not gh_available():
        return [_issue("gh", "fail", "GitHub CLI (gh) is not installed — https://cli.github.com",
                       "Install gh, or build without publishing.")]
    if _gh(["auth", "status"]).returncode != 0:
        return [_issue("gh-auth", "fail", "gh is not signed in — run 'gh auth login' once")]
    tag = f"{tag_prefix(app_name)}{version}"
    if _gh(["release", "view", tag, "--repo", repo]).returncode == 0:
        return [_issue("tag", "fail",
                       f"{tag} is already published in {repo} — build a newer version")]
    return []


def publish(final: str, app_name: str, display_name: str, version: str,
            repo: str, dry_run: bool = False) -> str:
    """Zip ``final`` and publish it as a GitHub Release. Returns the release URL.

    The rules about what may be published live in :func:`publish_checks` and are
    re-run here, right before the upload: the preflight checked them minutes ago,
    and a release published in between must not be silently overwritten.
    """
    problems = publish_checks(repo, app_name, version, dry_run=dry_run)
    if problems:
        raise RuntimeError("; ".join(p["message"] for p in problems))
    tag = f"{tag_prefix(app_name)}{version}"
    zip_path = os.path.join(os.path.dirname(final), f"{app_name}-Runner-{version}.zip")

    progress(90, "Zipping the Runner")
    log(f"Zipping → {zip_path}")
    _zip_runner(final, zip_path)
    log(f"Update package: {os.path.getsize(zip_path) / (1024 * 1024):.0f} MB")

    url = f"https://github.com/{repo}/releases/tag/{tag}"
    if dry_run:
        log(f"(dry run) would publish {tag} to {repo}")
        return url

    progress(95, "Uploading to GitHub")
    log(f"Publishing {tag} to {repo} …")
    result = _gh([
        "release", "create", tag, zip_path, "--repo", repo,
        "--title", f"{display_name} Runner {version}",
        "--notes", f"Standalone Runner for {display_name}, version {version}.",
        "--latest=false",
    ])
    if result.returncode != 0:
        raise RuntimeError(f"gh release create failed: {(result.stderr or result.stdout).strip()}")
    return url


def _save_version(flow_path: str, version: str, repo: str) -> None:
    """Record the built version (and update repo) in the workflow JSON."""
    try:
        with open(flow_path, "r", encoding="utf-8") as fh:
            flow = json.load(fh) or {}
        flow["buildVersion"] = version
        update = flow.get("runnerUpdate") if isinstance(flow.get("runnerUpdate"), dict) else {}
        update["lastVersion"] = version
        if repo:
            update["repo"] = repo
        flow["runnerUpdate"] = update
        with open(flow_path, "w", encoding="utf-8") as fh:
            json.dump(flow, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        log(f"Saved version {version} to {os.path.basename(flow_path)}")
    except Exception as exc:
        log(f"WARNING: couldn't save version to the workflow: {exc}")


def build(workflow_dir: str, name: str = "", version: str = "1.0.0",
          out_dir: str = "", repo: str = "", do_publish: bool = False,
          publish_dry_run: bool = False, verbose: bool = False,
          save_version: bool = False, flow_path: str = "",
          allow_missing_vendor: bool = False) -> str:
    """Build the runner exe. Returns the output folder path.

    *flow_path* pins the exact workflow JSON to bundle and version-stamp (the
    file the Hub / Designer has open); without it the folder is guessed at.

    Raises :class:`PreflightError` when the preflight refuses the build, and
    RuntimeError/FileNotFoundError/OSError for anything that fails later.
    """
    progress(2, "Reading workflow")
    workflow_dir = os.path.abspath(workflow_dir)
    pinned = os.path.abspath(flow_path) if flow_path else ""
    resolved = resolve_flow_path(workflow_dir, flow_path)
    if not resolved:
        raise FileNotFoundError(f"Workflow file not found: {pinned}" if pinned
                                else f"No workflow JSON found in {workflow_dir}")

    with open(resolved, "r", encoding="utf-8") as fh:
        flow = json.load(fh) or {}

    display_name = str(flow.get("name") or os.path.basename(workflow_dir))

    # Everything the build needs — spec, PyInstaller, required vendor/, the icon
    # sets, and (when publishing) gh + its login + a free tag — before the slow
    # part. Raises PreflightError, which carries every finding.
    progress(3, "Checking the build environment")
    report = preflight(workflow_dir, flow=flow, app_name=name or display_name,
                       version=version, repo=repo, publish=do_publish,
                       dry_run=publish_dry_run,
                       allow_missing_vendor=allow_missing_vendor, emit=True)
    if not report["ok"]:
        raise PreflightError(report)

    app_name = report["appName"]
    version = report["version"]
    repo = report["repo"]
    needs = set(report["vendor"])

    log(f"Workflow : {display_name}")
    log(f"Exe name : {app_name}.exe   (version {version})")
    log(f"Vendor   : {', '.join(sorted(needs)) or '(none)'}")
    log(f"Icon     : {report['iconSource']}")
    log(f"Game req : {describe_requirements(workflow_dir)}")
    log(f"Updates  : {repo + ' · tag ' + tag_prefix(app_name) + version if repo else '(no update repo)'}")

    stage = os.path.join(ROOT, "build", "_runner_stage")
    work = os.path.join(ROOT, "build", "_runner_work")
    out_root = out_dir or os.path.join(ROOT, "dist")
    final = os.path.join(out_root, f"{app_name}-Runner")

    # Build metadata bundled into the exe: its version + where updates live.
    tmp_dir = tempfile.mkdtemp(prefix="runner_build_")
    info_path = os.path.join(tmp_dir, "runner_build.json")
    with open(info_path, "w", encoding="utf-8") as fh:
        json.dump({
            "appName": app_name,
            "name": display_name,
            "version": version,
            "repo": repo,
            "tagPrefix": tag_prefix(app_name),
            "folder": os.path.basename(workflow_dir),
            "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, fh, ensure_ascii=False, indent=2)

    # The game's own icon: .ico for the exe, 256 px .png for the Runner header.
    # Already checked by the preflight; a failure here still only costs branding.
    icon_ico = os.path.join(tmp_dir, "icon.ico")
    icon_png = os.path.join(tmp_dir, "runner_icon.png")
    try:
        write_icon(workflow_dir, display_name, icon_ico, icon_png)
    except Exception as exc:
        log(f"WARNING: couldn't make the game icon ({exc}) — using the Macro2k icon")
        icon_ico = icon_png = ""

    # Write the build config the spec reads via MACRO2K_RUNNER_BUILD_CFG.
    # PyAV (ffmpeg, ~65 MB) only matters for the scrcpy capture source.
    include_av = "scrcpy" in needs
    if not include_av:
        log("Excluding PyAV/ffmpeg (−~65 MB, no scrcpy capture in this workflow)")
    cfg = {
        "root": ROOT,
        "workflow_dir": workflow_dir,
        "app_name": app_name,
        "version": version,
        "include_av": include_av,
        "build_info": info_path,
        "icon": icon_ico,
        "icon_png": icon_png,
        # Ships beside the exe as requirements/, so keep it out of the bundle.
        "workflow_excludes": [REQUIREMENTS_SRC],
    }
    cfg_path = os.path.join(tmp_dir, "build_cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)

    try:
        # The icon guard + PyInstaller were checked by the preflight above, so
        # nothing between here and PyInstaller can refuse the build.
        env = dict(os.environ)
        env["MACRO2K_RUNNER_BUILD_CFG"] = cfg_path
        env["PYTHONIOENCODING"] = "utf-8"

        progress(6, "Running PyInstaller")
        log("Running PyInstaller … (this can take a minute)")
        cmd = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", stage, "--workpath", work, SPEC,
        ]
        proc = subprocess.Popen(
            cmd, cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert proc.stdout is not None
        reached = 6
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            for marker, pct, label in PYINSTALLER_STAGES:
                if marker in line and pct > reached:
                    reached = pct
                    progress(pct, label)
                    break
            if verbose:
                print(f".. {line}", flush=True)
            elif any(k in line for k in ("ERROR", "Error", "WARNING", "Traceback", "Building")):
                # Surface PyInstaller errors/warnings; keep the rest terse.
                log(line)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"PyInstaller failed (exit {code})")

        staged = os.path.join(stage, f"{app_name}-Runner")
        if not os.path.isdir(staged):
            raise RuntimeError(f"PyInstaller did not produce {staged}")

        # Promote staging -> dist/<Name>-Runner (wipe any previous build).
        # NB: don't ignore_errors on the wipe — a half-deleted folder makes
        # shutil.move nest the new build inside the old one. A locked file here
        # almost always means the built runner is still open.
        progress(84, "Assembling the Runner folder")
        log(f"Assembling {final}")
        if os.path.isdir(final):
            try:
                shutil.rmtree(final)
            except OSError as exc:
                raise RuntimeError(
                    f"Couldn't clear the previous build at {final} ({exc}). "
                    f"Close {app_name}.exe if it's still running, then rebuild."
                )
        os.makedirs(out_root, exist_ok=True)
        shutil.move(staged, final)

        # Drop dead weight, then copy only the vendor pieces this workflow needs.
        _trim_build(final)
        if needs:
            progress(87, "Copying vendor tools")
            _copy_vendor(needs, final)
        progress(88, "Copying game requirements")
        requirements = _copy_requirements(workflow_dir, final, display_name)
        if requirements:
            log(f"Game requirements → {requirements} (see {REQUIREMENTS_NOTE}: "
                "players copy them into the game folder)")

        log(f"Total size: {_dir_size_mb(final):.0f} MB")

        release_url = ""
        if do_publish or publish_dry_run:
            release_url = publish(final, app_name, display_name, version, repo,
                                  dry_run=publish_dry_run)
        if save_version:
            _save_version(flow_path, version, repo)

        progress(100, "Published" if release_url else "Built")
        if release_url:
            log(f"RELEASE: {release_url}")
        if requirements:
            log(f"REQUIREMENTS: {requirements}")
        log(f"DONE: {os.path.join(final, app_name + '.exe')}")
        return final
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a single-workflow Runner exe.")
    ap.add_argument("--workflow", required=True,
                    help="Path to the workflow folder (contains workflow.json).")
    ap.add_argument("--flow-path", default="",
                    help="Exact workflow JSON to bundle and version-stamp "
                         "(default: the folder's workflow.json).")
    ap.add_argument("--name", default="", help="Override the exe base name.")
    ap.add_argument("--version", default="", help="Build version (e.g. 1.0.0).")
    ap.add_argument("--out", default="", help="Output root (default: dist/).")
    ap.add_argument("--repo", default="",
                    help="GitHub owner/name hosting this Runner's updates "
                         "(default: runnerUpdate.repo, else src/version.py).")
    ap.add_argument("--publish", action="store_true",
                    help="Zip the build and publish it as a GitHub Release (uses gh).")
    ap.add_argument("--publish-dry-run", action="store_true",
                    help="Zip the build and print what --publish would do, without uploading.")
    ap.add_argument("--save-version", action="store_true",
                    help="Record the built version in the workflow JSON.")
    ap.add_argument("--preflight", action="store_true",
                    help="Only check what a build needs (and print the report as JSON), "
                         "then exit — nothing is built.")
    ap.add_argument("--allow-missing-vendor", action="store_true",
                    help="Downgrade a missing vendor/<tool> to a warning and build anyway.")
    ap.add_argument("--verbose", action="store_true",
                    help="Echo every PyInstaller line (prefixed '..').")
    args = ap.parse_args()
    try:
        if args.preflight:
            report = preflight(args.workflow, app_name=args.name, version=args.version,
                               repo=args.repo, publish=args.publish,
                               dry_run=args.publish_dry_run,
                               allow_missing_vendor=args.allow_missing_vendor, emit=True)
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            return 0 if report["ok"] else 1
        build(args.workflow, name=args.name, version=args.version, out_dir=args.out,
              repo=args.repo, do_publish=args.publish, publish_dry_run=args.publish_dry_run,
              verbose=args.verbose, save_version=args.save_version,
              flow_path=args.flow_path, allow_missing_vendor=args.allow_missing_vendor)
    except PreflightError:
        # preflight(emit=True) already printed every finding, including the
        # summary line the callers parse — don't bury it under a second one.
        return 1
    except Exception as exc:
        log(f"BUILD FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
