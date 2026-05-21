"""
Backward-compatibility shim.

Older code imports ``from src.utils.logging import setup_logger, log_*``.
The canonical implementation now lives in :mod:`src.utils`; this module just
re-exports those symbols.
"""
from src.utils import (  # noqa: F401
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
