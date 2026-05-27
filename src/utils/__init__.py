"""
Unified logging utilities for the project.

Provides simple coloured ``log_*`` helpers backed by the standard ``logging``
module so that messages are both printed to the console (with colours) and
captured by any handlers attached to the root logger (e.g. log files).
"""
import logging
import os
import threading
from datetime import datetime
from typing import Callable, List, Optional

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
    _root_logger.setLevel(logging.DEBUG)
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
    logger.setLevel(logging.DEBUG)

    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log_file = os.path.join(
        log_dir,
        f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
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


__all__ = [
    "Fore",
    "Style",
    "setup_logger",
    "set_current_state",
    "log_with_time",
    "log_error",
    "log_warning",
    "log_success",
    "log_info",
    "log_state",
    "log_quest",
    "log_normal",
    "add_log_subscriber",
    "remove_log_subscriber",
]
