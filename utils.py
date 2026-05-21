"""
Backward-compatibility shim for the legacy top-level ``utils`` module.

When ``src/`` is added to ``sys.path``, ``from utils import ...`` resolves
here. We forward to the canonical implementation in :mod:`src.utils` to keep a
single source of truth.
"""
from src.utils import (  # noqa: F401
    Fore,
    Style,
    setup_logger,
    set_current_state,
    log_with_time,
    log_error,
    log_warning,
    log_success,
    log_info,
    log_state,
    log_quest,
    log_normal,
)

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
]
