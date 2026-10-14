"""Per-workflow run history: one JSON line per finished Runner run.

The Runner appends a record when a run ends (completed / stopped / failed);
the Runner's History tab lists them and the Hub shows the newest one on each
game's card. Records live next to the Runner config of the same workflow::

    data/runner/<slug>/history.jsonl

Each line is self-contained, so a crash mid-write costs at most that line and
readers skip anything that does not parse. The file is trimmed to the newest
``MAX_RECORDS`` once it grows past ``TRIM_AT``.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

from src.utils import data_root, slugify_workflow_name

HISTORY_FILE = "history.jsonl"
MAX_RECORDS = 200
TRIM_AT = 260
# Bytes read from the end of the file to find the newest record; one record is
# well under 4 KB even with dozens of activities.
_TAIL_BYTES = 64 * 1024

_LOCK = threading.Lock()


def runner_dir(flow_name: str, flow_path: str = "") -> str:
    """``data/runner/<slug>`` for a workflow — the Runner's per-workflow folder.

    The slug comes from the workflow's display name (falling back to the file
    name), so the Hub, the Runner and a rebuilt Runner all land on one folder.
    """
    raw = str(flow_name or "").strip()
    if not raw:
        raw = os.path.splitext(os.path.basename(flow_path or "workflow"))[0]
    return os.path.join(data_root(), "data", "runner", slugify_workflow_name(raw))


def history_path(flow_name: str, flow_path: str = "") -> str:
    return os.path.join(runner_dir(flow_name, flow_path), HISTORY_FILE)


def _parse(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        return None
    return record if isinstance(record, dict) else None


def append(path: str, record: Dict[str, Any]) -> bool:
    """Add *record* as the newest line; trims old lines now and then."""
    try:
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return False
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            _trim(path)
            return True
        except OSError:
            return False


def _trim(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    if len(lines) <= TRIM_AT:
        return
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(lines[-MAX_RECORDS:])
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def load(path: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Newest-first records, at most *limit* of them."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in reversed(lines):
        record = _parse(line)
        if record is not None:
            out.append(record)
            if len(out) >= max(1, int(limit)):
                break
    return out


def last(path: str) -> Optional[Dict[str, Any]]:
    """The newest record, reading only the end of the file."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - _TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        record = _parse(line)
        if record is not None:
            return record
    return None


def clear(path: str) -> bool:
    with _LOCK:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False
