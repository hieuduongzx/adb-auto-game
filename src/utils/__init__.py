"""
Unified logging utilities for the project.

Provides simple coloured ``log_*`` helpers backed by the standard ``logging``
module so that messages are both printed to the console (with colours) and
captured by any handlers attached to the root logger (e.g. log files).
"""
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from typing import Callable, List, Optional, Sequence

from colorama import init as _colorama_init, Fore, Style

# Initialise colorama once for Windows ANSI support.
_colorama_init()

# Module-level "current state" tag prepended to every message when set.
_current_state: Optional[str] = None

# Subscribers receive every log message ``(level, message)`` where ``level``
# is one of: ``info``, ``success``, ``warning``, ``error``, ``state``,
# ``quest``, ``normal``. Used by the GUI to mirror logs in its log panel.
_subscribers: List[Callable[[str, str], None]] = []
_subscribers_lock = threading.Lock()


def add_log_subscriber(callback: Callable[[str, str], None]) -> None:
    """Register ``callback(level, message)`` to receive every log message."""
    with _subscribers_lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def remove_log_subscriber(callback: Callable[[str, str], None]) -> None:
    """Unregister a previously added subscriber."""
    with _subscribers_lock:
        if callback in _subscribers:
            _subscribers.remove(callback)


def _notify_subscribers(level: str, message: str) -> None:
    """Fan out a message to every subscriber. Failures are swallowed so a
    misbehaving GUI sink can never break console logging.
    """
    with _subscribers_lock:
        subs = list(_subscribers)
    for cb in subs:
        try:
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
    return (
        f"{Fore.CYAN}[{timestamp}]{state}{Style.RESET_ALL} "
        f"{color}{message}{Style.RESET_ALL}"
    )


def log_with_time(message: str, color: str = Fore.WHITE) -> None:
    """Print a message with timestamp and colour."""
    print(_format(message, color))


def log_error(message: str, exc_info: bool = False) -> None:
    """Log an error to stderr/console and the root logger.

    ``exc_info=True`` will append the active exception traceback (only valid
    inside an ``except`` block).
    """
    print(_format(message, Fore.RED))
    if exc_info:
        _root_logger.error(message, exc_info=True)
    _notify_subscribers("error", message)


def log_debug(message: str) -> None:
    """Record a diagnostic message at DEBUG level.

    Unlike the other helpers this does NOT print to the console (to avoid
    spamming during normal operation) and does NOT fan out to GUI subscribers.
    It only reaches the standard logging tree, so it surfaces when a handler is
    configured at DEBUG level. Use for otherwise-swallowed exceptions whose
    detail is useful only when actively debugging.
    """
    _root_logger.debug(message)


def log_warning(message: str) -> None:
    log_with_time(message, Fore.YELLOW)
    _notify_subscribers("warning", message)


def log_success(message: str) -> None:
    log_with_time(message, Fore.GREEN)
    _notify_subscribers("success", message)


def log_info(message: str) -> None:
    log_with_time(message, Fore.CYAN)
    _notify_subscribers("info", message)


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
# These let the same code run from source (``python tools/...``) and from a
# PyInstaller one-dir build. In a frozen build:
#   * ``app_dir()``    -> the folder that contains the .exe (where ``vendor/``,
#                         ``data/`` and ``out/`` live and stay writable);
#   * ``bundle_dir()`` -> PyInstaller's ``_MEIPASS`` (read-only bundled assets
#                         such as the web/ HTML).
# From source both resolve to the project root, so behaviour is unchanged.
# ---------------------------------------------------------------------------

# <root>/src/utils/__init__.py -> up 3 dirnames -> <root>
_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Windows flag that prevents a child console process (adb.exe, frida-inject,
# tesseract, …) from popping up its own black console window. Essential for the
# windowed/frozen build, where the host has no console for children to attach to
# — without it each subprocess call flashes a console window. 0 elsewhere.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) frozen build."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Folder for external, writable resources (``vendor/``, ``data/``, ``out/``).

    Frozen: the directory containing the executable. Source: the project root.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SOURCE_ROOT


def bundle_dir() -> str:
    """Folder for read-only assets bundled into the build (e.g. ``web/``).

    Frozen: PyInstaller's ``_MEIPASS`` extraction dir. Source: project root.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return _SOURCE_ROOT


# Maps a logical tool name to (frozen exe basename, source-tree script path
# relative to the project root). The designer executable also hosts the
# runner GUI via the ``--runner`` switch.
_TOOL_MAP = {
    "designer": ("Workflow2k.exe", os.path.join("tools", "workflow_designer.py")),
    "devhelper": ("DevScope.exe", os.path.join("tools", "dev_helper.py")),
    "runner": ("Workflow2k.exe", os.path.join("tools", "workflow_runner.py")),
}


def launch_tool(tool: str, extra_args: Optional[Sequence[str]] = None) -> None:
    """Launch a sibling tool process, working both frozen and from source.

    Frozen: runs the matching ``*.exe`` next to the current executable (the
    runner is launched as ``designer.exe --runner <args>``). Source: runs
    ``python tools/<script>.py <args>``.
    """
    args = [str(a) for a in (extra_args or [])]
    exe_name, script_rel = _TOOL_MAP[tool]
    if is_frozen():
        target = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), exe_name)
        prefix = ["--runner"] if tool == "runner" else []
        cmd = [target, *prefix, *args]
    else:
        cmd = [sys.executable, os.path.join(_SOURCE_ROOT, script_rel), *args]
    subprocess.Popen(cmd)


__all__ = [
    "Fore",
    "Style",
    "CREATE_NO_WINDOW",
    "is_frozen",
    "app_dir",
    "bundle_dir",
    "launch_tool",
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
]
