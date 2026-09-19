"""
Unified logging utilities for the project.

Provides simple coloured ``log_*`` helpers backed by the standard ``logging``
module so that messages are both printed to the console (with colours) and
captured by any handlers attached to the root logger (e.g. log files).
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Iterator, List, Optional, Sequence

from colorama import init as _colorama_init, Fore, Style

# Re-export the version constants so callers can pull them from the same place
# they already import the other app helpers (``from src.utils import ...``).
from src.version import APP_NAME, APP_VERSION, __version__, titled  # noqa: F401


def _force_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 so log lines containing emoji or
    non-Latin diacritics (e.g. Vietnamese ``ắ``) never raise
    ``UnicodeEncodeError`` under the Windows console/frozen-exe default codec
    (cp1252 / 'charmap'). ``errors='replace'`` guarantees a write can never
    crash.

    A windowed (no-console) frozen build starts with ``sys.stdout``/``stderr``
    set to ``None``. PyWebView's ``webview.http`` module *fills those in* with
    ``open(os.devnull, 'w')`` as soon as it is imported — a stream that encodes
    with the machine's **ANSI code page** (cp1252 on most PCs, UTF-8 only where
    the "Beta: Use Unicode UTF-8" setting is on). Every log line a workflow
    prints in Vietnamese then dies with a 'charmap' error, which is invisible on
    a UTF-8 developer machine and breaks on everyone else's. Installing our own
    UTF-8 sink for the ``None`` case — before PyWebView is imported — both stops
    that substitution and keeps ``print`` a harmless no-op."""
    for _name in ("stdout", "stderr"):
        _stream = getattr(sys, _name, None)
        if _stream is None:
            try:
                setattr(sys, _name, open(os.devnull, "w", encoding="utf-8",
                                         errors="replace"))
            except Exception:
                pass
            continue
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_streams()

# Initialise colorama once for Windows ANSI support.
_colorama_init()

# Module-level "current state" tag prepended to every message when set.
_current_state: Optional[str] = None

# Subscribers receive every log message ``(level, message)`` where ``level``
# is one of: ``info``, ``success``, ``warning``, ``error``, ``state``,
# ``quest``, ``normal``. Used by the GUI to mirror logs in its log panel.
_subscribers: List[Callable[..., None]] = []
# Subscribers that also want the log context as a third ``meta`` argument.
_meta_subscribers: List[Callable[..., None]] = []
_subscribers_lock = threading.Lock()

# ── Log context ─────────────────────────────────────────────────────────────
# Which activity the *current thread* is running. The workflow engine sets it
# for the sequence thread, each parallel branch and each background worker, so
# every line logged on that thread — including ones from src/core helpers —
# can be prefixed with ``[<activity>]``.
#
# ``kind`` classifies a line so each app can pick its own verbosity:
#   run      — whole-run events (started, paused, stopped, finished)
#   activity — an activity started / finished / failed / retried
#   user     — text the workflow author wrote (a block's log line, Log block)
#   detail   — engine step-by-step output (taps, matches, branches taken)
#   None     — not from the engine (app, device, speed hack…)
LOG_KIND_RUN = "run"
LOG_KIND_ACTIVITY = "activity"
LOG_KIND_USER = "user"
LOG_KIND_DETAIL = "detail"

# Which *block* the current thread is executing, as the graph node's id. Set by
# the engine's walk loop, it rides along in ``meta`` so the GUI can attach a log
# line to the node that produced it and offer "jump to this block". The id is
# what the designer keys its canvas elements by; the human name is not needed
# here, since only the app that knows the workflow can resolve it.
_log_ctx = threading.local()


def set_log_activity(name: Optional[str]) -> None:
    """Set (or clear with ``None``) the activity name for this thread's logs."""
    _log_ctx.activity = str(name) if name else None


def get_log_activity() -> Optional[str]:
    """The activity this thread is running, or ``None``."""
    return getattr(_log_ctx, "activity", None)


def set_log_node(node_id: Optional[str]) -> None:
    """Set (or clear with ``None``) the graph node id for this thread's logs."""
    _log_ctx.node = str(node_id) if node_id else None


def get_log_node() -> Optional[str]:
    """The graph node this thread is inside, or ``None``."""
    return getattr(_log_ctx, "node", None)


@contextmanager
def log_activity(name: Optional[str]) -> Iterator[None]:
    """Scope this thread's logs to ``name``, restoring the previous one after."""
    prev = get_log_activity()
    set_log_activity(name)
    try:
        yield
    finally:
        set_log_activity(prev)


@contextmanager
def log_node(node_id: Optional[str]) -> Iterator[None]:
    """Scope this thread's logs to one graph node, restoring the previous one."""
    prev = get_log_node()
    set_log_node(node_id)
    try:
        yield
    finally:
        set_log_node(prev)


def add_log_subscriber(callback: Callable[..., None], with_meta: bool = False) -> None:
    """Register ``callback(level, message)`` to receive every log message.

    With ``with_meta=True`` it is called as ``callback(level, message, meta)``
    where ``meta`` is ``{"activity": str | None, "kind": str | None,
    "node": str | None}``."""
    with _subscribers_lock:
        if callback not in _subscribers:
            _subscribers.append(callback)
        if with_meta and callback not in _meta_subscribers:
            _meta_subscribers.append(callback)


def remove_log_subscriber(callback: Callable[..., None]) -> None:
    """Unregister a previously added subscriber."""
    with _subscribers_lock:
        if callback in _subscribers:
            _subscribers.remove(callback)
        if callback in _meta_subscribers:
            _meta_subscribers.remove(callback)


def _notify_subscribers(level: str, message: str, kind: Optional[str] = None) -> None:
    """Fan out a message to every subscriber. Failures are swallowed so a
    misbehaving GUI sink can never break console logging.
    """
    with _subscribers_lock:
        subs = list(_subscribers)
        with_meta = set(_meta_subscribers)
    meta = {"activity": get_log_activity(), "kind": kind, "node": get_log_node()}
    for cb in subs:
        try:
            if cb in with_meta:
                cb(level, message, meta)
            else:
                cb(level, message)
        except Exception:
            pass


# Root logger configured exactly once with a console handler.
_root_logger = logging.getLogger()
if not _root_logger.handlers:
    _root_logger.setLevel(logging.INFO)
    _formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _console = logging.StreamHandler()
    _console.setFormatter(_formatter)
    _root_logger.addHandler(_console)


def setup_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    """Create (or reuse) a per-module file logger that also propagates to the
    root logger's console handler.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    os.makedirs(log_dir, exist_ok=True)
    logger.setLevel(logging.INFO)

    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log_file = os.path.join(
        log_dir,
        f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    return logger


def set_current_state(state: Optional[str]) -> None:
    """Set or clear the current-state tag prepended to log messages."""
    global _current_state
    _current_state = state


def _format(message: str, color: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    state = f"[{_current_state}]" if _current_state else ""
    activity = get_log_activity()
    if activity:
        state += f"[{activity}]"
    return (
        f"{Fore.CYAN}[{timestamp}]{state}{Style.RESET_ALL} "
        f"{color}{message}{Style.RESET_ALL}"
    )


def log_with_time(message: str, color: str = Fore.WHITE) -> None:
    """Print a message with timestamp and colour."""
    print(_format(message, color))


def log_error(message: str, exc_info: bool = False, kind: Optional[str] = None) -> None:
    """Log an error to stderr/console and the root logger.

    ``exc_info=True`` will append the active exception traceback (only valid
    inside an ``except`` block). ``kind`` — see the log context notes above.
    """
    print(_format(message, Fore.RED))
    if exc_info:
        _root_logger.error(message, exc_info=True)
    _notify_subscribers("error", message, kind)


def log_debug(message: str) -> None:
    """Record a diagnostic message at DEBUG level.

    Unlike the other helpers this does NOT print to the console (to avoid
    spamming during normal operation) and does NOT fan out to GUI subscribers.
    It only reaches the standard logging tree, so it surfaces when a handler is
    configured at DEBUG level. Use for otherwise-swallowed exceptions whose
    detail is useful only when actively debugging.
    """
    _root_logger.debug(message)


def log_warning(message: str, kind: Optional[str] = None) -> None:
    log_with_time(message, Fore.YELLOW)
    _notify_subscribers("warning", message, kind)


def log_success(message: str, kind: Optional[str] = None) -> None:
    log_with_time(message, Fore.GREEN)
    _notify_subscribers("success", message, kind)


def log_info(message: str, kind: Optional[str] = None) -> None:
    log_with_time(message, Fore.CYAN)
    _notify_subscribers("info", message, kind)


def log_state(message: str) -> None:
    """Log a state-change message (blue)."""
    log_with_time(message, Fore.BLUE)
    _notify_subscribers("state", message)


def log_quest(message: str) -> None:
    log_with_time(message, Fore.MAGENTA)
    _notify_subscribers("quest", message)


def log_normal(message: str) -> None:
    log_with_time(message, Fore.WHITE)
    _notify_subscribers("normal", message)


# ---------------------------------------------------------------------------
# Frozen / packaged-build helpers
#
# These let the same code run from source (``python apps/...``) and from a
# PyInstaller one-dir build. In a frozen build:
#   * ``app_dir()``    -> the folder that contains the .exe (where the shipped,
#                         read-only ``vendor/`` lives — adb/frida);
#   * ``data_root()``  -> writable user data (``workflows/``, ``data/``, ``out/``,
#                         ``logs/``). Same as app_dir() for a
#                         plain/portable build, but redirected OUT of the install
#                         folder under a Velopack install so auto-updates (which
#                         replace ``current/`` wholesale) never wipe user data;
#   * ``bundle_dir()`` -> PyInstaller's ``_MEIPASS`` (read-only bundled assets
#                         such as the web/ HTML).
# From source all three resolve to the project root, so behaviour is unchanged.
# ---------------------------------------------------------------------------

# <root>/src/utils/__init__.py -> up 3 dirnames -> <root>
_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Windows flag that prevents a child console process (adb.exe, frida-inject,
# command-line helpers from popping up their own black console window. Essential for the
# windowed/frozen build, where the host has no console for children to attach to
# — without it each subprocess call flashes a console window. 0 elsewhere.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) frozen build."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Install folder — holds the shipped, read-only ``vendor/`` tree.

    Frozen: the directory containing the executable (under a Velopack install
    this is ``…\\<AppId>\\current``, replaced on every update — which is exactly
    why *writable* data must use :func:`data_root` instead). Source: repo root.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SOURCE_ROOT


def is_portable_build() -> bool:
    """True for a frozen build explicitly marked portable — a ``portable.txt``
    (or ``.portable``) file sitting next to the executable. Portable builds keep
    all writable data beside the .exe instead of under the user profile."""
    if not is_frozen():
        return False
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    return any(os.path.isfile(os.path.join(exe_dir, m))
               for m in ("portable.txt", ".portable"))


def _dir_writable(path: str) -> bool:
    """Real write test (not ``os.access``, which lies on Windows): try to create
    and delete a probe file in ``path``. False if it doesn't exist or is
    read-only (e.g. ``C:/Program Files`` without elevation)."""
    probe = os.path.join(path, ".write_probe")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except Exception:
        return False


def data_root() -> str:
    """Writable root for user data (``workflows/``, ``data/``, ``out/`` …).

    Kept **next to the app** whenever that folder is writable — a per-user or
    custom (e.g. ``D:/Macro2k``) install, or a portable copy — so everything
    lives in one place. Falls back to ``%LOCALAPPDATA%/<AppName>`` only when the
    install dir is read-only (an all-users ``C:/Program Files`` install, which a
    non-elevated app can't write to). Source runs use the repo root."""
    if not is_frozen():
        return _SOURCE_ROOT
    exe_dir = app_dir()
    if is_portable_build() or _dir_writable(exe_dir):
        return exe_dir
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def bundle_dir() -> str:
    """Folder for read-only assets bundled into the build (e.g. ``web/``).

    Frozen: PyInstaller's ``_MEIPASS`` extraction dir. Source: project root.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return _SOURCE_ROOT


# ---------------------------------------------------------------------------
# Mark-of-the-Web
#
# A released build is normally *downloaded* (GitHub Releases zip), and Windows
# stamps a ``Zone.Identifier`` stream onto every file Explorer extracts from
# it. The .NET Framework then refuses to load the assemblies inside — so
# Python.NET, pywebview's Windows backend, dies at startup with
#
#     RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize
#                   from ...\_internal\pythonnet\runtime\Python.Runtime.dll
#
# on every machine except the one that built it (its copies were never
# downloaded, so they carry no mark). Deleting the stream is exactly what the
# file's *Unblock* checkbox does, and it has to happen before the first .NET
# assembly is loaded — hence the call at the top of each frozen entry point.
# ---------------------------------------------------------------------------

# ERROR_ACCESS_DENIED — a file we were allowed to see but not to modify (an
# all-users ``C:/Program Files`` install without elevation).
_ERROR_ACCESS_DENIED = 5


def _frozen_bundle_roots() -> List[str]:
    """Folders holding a frozen build's own files: the install folder (the exe,
    ``vendor/``, ``requirements/`` …) and — when PyInstaller extracted the
    bundle somewhere else, as a onefile build does into ``%TEMP%`` — its
    ``_MEIPASS`` folder too."""
    if not is_frozen():
        return []
    roots: List[str] = []
    install = app_dir()
    if os.path.isdir(install):
        roots.append(install)
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass and os.path.isdir(meipass):
        inside_install = os.path.abspath(meipass).startswith(
            os.path.abspath(install) + os.sep)
        if not inside_install:   # onedir: _MEIPASS *is* <install>/_internal
            roots.append(meipass)
    return roots


def unblock_bundled_files(roots: Optional[Sequence[str]] = None) -> int:
    """Clear the Mark-of-the-Web from a downloaded build's own files.

    Windows tags files extracted from an internet-downloaded archive with a
    ``Zone.Identifier`` stream, and the .NET Framework will not load the .NET
    assemblies among them — which is how a released Runner ends up with
    ``Failed to resolve Python.Runtime.Loader.Initialize`` on every machine but
    the developer's. Removing the stream is what *Properties → Unblock* does,
    and it must happen before the first assembly is loaded, so the frozen entry
    points call this before ``webview.start()`` (:mod:`packaging.entry_designer`,
    :mod:`packaging.entry_runner_single`, :mod:`packaging.entry_devscope`).

    ``roots`` defaults to the frozen bundle's own folders; a source run, another
    platform, or no bundles at all is a no-op. Never raises — an install we
    can't write to just keeps its marks, and is reported. Returns the number of
    files unblocked.
    """
    if roots is None:
        roots = _frozen_bundle_roots()
    if sys.platform != "win32" or not roots:
        return 0

    import ctypes

    try:
        delete_file = ctypes.WinDLL("kernel32", use_last_error=True).DeleteFileW
    except Exception:
        return 0
    delete_file.argtypes = (ctypes.c_wchar_p,)
    delete_file.restype = ctypes.c_int

    cleared = 0
    denied = 0
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                # DeleteFileW takes the "file:stream" syntax and fails with
                # ERROR_FILE_NOT_FOUND for the usual, unmarked file — so this
                # is one cheap syscall per file, no prior existence check.
                if delete_file(os.path.join(dirpath, name) + ":Zone.Identifier"):
                    cleared += 1
                elif ctypes.get_last_error() == _ERROR_ACCESS_DENIED:
                    denied += 1

    if cleared:
        log_info(f"Unblocked {cleared} file(s) downloaded from the internet.")
    if denied:
        log_warning(
            f"{denied} file(s) are still blocked by Windows (they came from a "
            f"downloaded .zip) and the app folder is not writable. Right-click "
            f"the app's folder → Properties → Unblock, or re-extract the .zip "
            f"with 7-Zip."
        )
    return cleared


def file_url(path: str) -> str:
    """Absolute ``file://`` URL for a local path (spaces / unicode encoded).

    WebView2 rejects or truncates bare ``file:///C:/path with spaces/...``
    URLs, which yields an empty window. ``Path.as_uri()`` percent-encodes
    correctly (e.g. ``Dev Tool`` → ``Dev%20Tool``).
    """
    from pathlib import Path

    return Path(os.path.abspath(path)).as_uri()


def sanitize_name(raw: str) -> str:
    """Reduce *raw* to a safe folder/file stem (``A-Z a-z 0-9 _ -`` only)."""
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", (raw or "").strip())
    return cleaned.strip("._-")


def ts_stamp() -> str:
    """Filename-friendly timestamp, e.g. ``20260821_143005``."""
    return time.strftime("%Y%m%d_%H%M%S")


def slugify_workflow_name(raw: str, max_len: int = 80) -> str:
    """Filesystem-safe slug for a workflow name (used for per-workflow config
    folders). Collapses whitespace/punctuation to ``_`` and appends a short
    hash of the original name so distinct names ("A B" vs "A_B") never map to
    the same folder."""
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(raw or "").strip())
    base = re.sub(r"_+", "_", re.sub(r"\s+", "_", base)).strip(" ._-")[:max_len] or "workflow"
    reserved = {"CON", "PRN", "AUX", "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if base.upper() in reserved:
        base = "_" + base
    digest = hashlib.sha1(str(raw or "").encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


def confined_path(root: str, candidate: str, extensions: Sequence[str] = ()) -> Optional[str]:
    """Resolve *candidate* only when it remains below *root*.

    This is intended for paths received from WebView code. Resolving real paths
    also prevents a symlink inside the asset directory from escaping it.
    """
    if not root or not candidate:
        return None
    try:
        root_real = os.path.realpath(os.path.abspath(root))
        candidate_real = os.path.realpath(os.path.abspath(candidate))
        common = os.path.commonpath([root_real, candidate_real])
        if os.path.normcase(common) != os.path.normcase(root_real):
            return None
        if os.path.normcase(candidate_real) == os.path.normcase(root_real):
            return None
    except (OSError, ValueError, TypeError):
        return None
    if extensions:
        allowed = {ext.lower() if ext.startswith(".") else "." + ext.lower() for ext in extensions}
        if os.path.splitext(candidate_real)[1].lower() not in allowed:
            return None
    return candidate_real


def webview_storage_path(app_key: str) -> str:
    """Per-app WebView2 user-data folder under the project ``data/`` tree.

    Hub / Designer / Runner / DevScope often run as *separate processes* at
    the same time. With ``private_mode=False`` they would otherwise share
    ``%AppData%/pywebview`` and WebView2 fails to init the second window
    (HRESULT ``0x8007139F``) — empty chrome, no HTML.
    """
    key = (app_key or "app").strip().lower() or "app"
    path = os.path.join(data_root(), "data", "webview", key)
    os.makedirs(path, exist_ok=True)
    return path


# ── Shared UI settings ────────────────────────────────────────────────────────
# One file backs the whole suite. Hub / Designer / Runner run as separate
# processes with separate WebView2 stores (see ``webview_storage_path``), so
# localStorage alone cannot keep a preference in sync between them: a theme
# picked in the Designer has to be what the Hub opens with. Every window reads
# and writes these helpers, and ``web/shared/theme.js`` reconciles against them
# through ``pywebview.api.get_settings()``.
_UI_SETTINGS_LOCK = threading.Lock()

# Window chrome painted before the first frame, per theme. Keep in step with
# ``--bg`` in ``apps/web/shared/tokens.css`` — otherwise a dark-theme window
# flashes light while the WebView boots.
_THEME_BACKGROUNDS = {"light": "#e9edf2", "dark": "#161a20"}


def ui_settings_path() -> str:
    """Path of the suite-wide settings file (``data/designer_settings.json``).

    Named for the app that first owned it; it now holds every window's UI
    preferences (theme, density, snap, previewAll, lastWorkflow, …).
    """
    return os.path.join(data_root(), "data", "designer_settings.json")


def load_ui_settings() -> dict:
    """Settings dict, or ``{}`` when the file is missing or unreadable."""
    try:
        with open(ui_settings_path(), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def save_ui_settings(patch: Optional[dict]) -> bool:
    """Merge ``patch`` into the settings file and write it back.

    Merging (rather than replacing) is what lets one window save a single key
    without clobbering the ones another window owns. A ``None`` value deletes
    its key. The lock keeps two saves inside the same process from
    interleaving; cross-process writes are rare enough (a human toggling a
    preference) not to need file locking.
    """
    if not patch:
        return False
    with _UI_SETTINGS_LOCK:
        merged = load_ui_settings()
        for key, value in patch.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        try:
            path = ui_settings_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(merged, fh, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            log_warning(f"Saving UI settings failed: {exc}")
            return False


def theme_background() -> str:
    """``background_color`` for ``webview.create_window`` under the saved theme."""
    theme = str((load_ui_settings() or {}).get("theme", "light")).strip().lower()
    return _THEME_BACKGROUNDS.get(theme, _THEME_BACKGROUNDS["light"])


def push_webview_event(window, event_type: str, data: dict) -> None:
    """Deliver a JSON event to a WebView ``window.__recv`` handler safely.

    The outer ``json.dumps`` produces a quoted JavaScript string literal.
    Workflow names and log messages may contain backticks or ``${...}``, and
    neither must be interpreted as JavaScript template-literal syntax.
    """
    payload = json.dumps(
        {"type": event_type, "data": data}, ensure_ascii=False,
    )
    js_arg = json.dumps(payload, ensure_ascii=True)
    window.evaluate_js(f"window.__recv({js_arg})")


# Maps a logical app name to (frozen exe basename, source-tree script path
# relative to the project root). Macro2k.exe hosts Hub + Designer + Runner
# via CLI switches (default = hub, ``--designer``, ``--runner``).
#
# Packaging ships only Macro2k.exe. DevScope is source-only unless you add
# it back to packaging/apps_build.spec.
_APP_MAP = {
    "hub": ("Macro2k.exe", os.path.join("apps", "workflow_hub.py")),
    "designer": ("Macro2k.exe", os.path.join("apps", "workflow_designer.py")),
    "devscope": ("DevScope.exe", os.path.join("apps", "devscope.py")),
    "runner": ("Macro2k.exe", os.path.join("apps", "workflow_runner.py")),
}

# Frozen CLI flags so one exe can host hub / designer / runner.
_FROZEN_PREFIX = {
    "hub": [],
    "designer": ["--designer"],
    "runner": ["--runner"],
}


def source_python() -> str:
    """Use this checkout's virtualenv when launching sibling source apps."""
    parts = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    project_python = os.path.join(_SOURCE_ROOT, ".venv", *parts)
    return project_python if os.path.isfile(project_python) else sys.executable


def launch_tool(tool: str, extra_args: Optional[Sequence[str]] = None) -> None:
    """Launch a sibling app process, working both frozen and from source.

    Frozen: runs the matching ``*.exe`` next to the current executable
    (``Macro2k.exe``, ``Macro2k.exe --designer <args>``,
    ``Macro2k.exe --runner <args>``). Source: runs
    ``python apps/<script>.py <args>``.

    Raises ``FileNotFoundError`` if the frozen target exe is missing
    (e.g. DevScope is not in the default packaging output).
    """
    args = [str(a) for a in (extra_args or [])]
    if tool not in _APP_MAP:
        raise KeyError(f"Unknown app '{tool}'. Known: {', '.join(sorted(_APP_MAP))}")
    exe_name, script_rel = _APP_MAP[tool]
    if is_frozen():
        target = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), exe_name)
        if not os.path.isfile(target):
            raise FileNotFoundError(
                f"{exe_name} not found next to this build. "
                f"From source: python {script_rel}"
            )
        prefix = list(_FROZEN_PREFIX.get(tool, []))
        cmd = [target, *prefix, *args]
    else:
        cmd = [source_python(), os.path.join(_SOURCE_ROOT, script_rel), *args]
    subprocess.Popen(cmd)


__all__ = [
    "Fore",
    "Style",
    "CREATE_NO_WINDOW",
    "is_frozen",
    "app_dir",
    "data_root",
    "is_portable_build",
    "bundle_dir",
    "file_url",
    "APP_NAME",
    "APP_VERSION",
    "titled",
    "sanitize_name",
    "ts_stamp",
    "slugify_workflow_name",
    "webview_storage_path",
    "push_webview_event",
    "launch_tool",
    "source_python",
    "setup_logger",
    "set_current_state",
    "log_with_time",
    "log_error",
    "log_warning",
    "log_success",
    "log_info",
    "log_debug",
    "log_state",
    "log_quest",
    "log_normal",
    "add_log_subscriber",
    "remove_log_subscriber",
    "LOG_KIND_RUN",
    "LOG_KIND_ACTIVITY",
    "LOG_KIND_USER",
    "LOG_KIND_DETAIL",
    "set_log_activity",
    "get_log_activity",
    "log_activity",
]
