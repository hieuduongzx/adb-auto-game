"""Engine log helpers: every engine line is step detail unless a call says otherwise."""
from __future__ import annotations

from src import utils as _utils
from src.utils import LOG_KIND_DETAIL


# Engine output is step-by-step detail unless a call says otherwise: the
# Designer shows every line, the Runner only run / activity / user lines and
# errors. The activity prefix comes from the thread's log context (see
# ``log_activity``), so messages here never carry their own "[...]" tag.
def log_error(message: str, kind: str = LOG_KIND_DETAIL) -> None:
    _utils.log_error(message, kind=kind)


def log_warning(message: str, kind: str = LOG_KIND_DETAIL) -> None:
    _utils.log_warning(message, kind=kind)


def log_success(message: str, kind: str = LOG_KIND_DETAIL) -> None:
    _utils.log_success(message, kind=kind)


def log_info(message: str, kind: str = LOG_KIND_DETAIL) -> None:
    _utils.log_info(message, kind=kind)
