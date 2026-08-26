"""Cross-process ADB server lifecycle management.

Hub / Designer / Runner / DevScope run as *sibling processes* sharing one ADB
server. Closing one app must not ``adb kill-server`` out from under the others,
so every app holds a small "lease" file while it runs. On close the app drops
its lease and only kills the shared server when no other live lease remains.
Leases whose PID is no longer alive are treated as stale and pruned, so a
crashed app never blocks cleanup forever.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional

from src.utils import data_root


def _lease_dir(lease_dir: Optional[str] = None) -> str:
    return lease_dir or os.path.join(data_root(), "data", "run", "adb_leases")


def _pid_alive(pid: int) -> bool:
    """Best-effort PID liveness probe. When unsure, assume alive (never kill
    the shared server on a guess)."""
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        STILL_ACTIVE = 259
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lease_filename(tag: str, pid: int) -> str:
    clean = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(tag or "app").strip()) or "app"
    return f"{clean}-{int(pid)}.json"


def acquire_adb_lease(tag: str, lease_dir: Optional[str] = None) -> Optional[str]:
    """Record this process as a live ADB client. Returns the lease path (or
    ``None`` when the lease dir isn't writable — cleanup then falls back to
    always killing, matching the old behaviour)."""
    directory = _lease_dir(lease_dir)
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, _lease_filename(tag, os.getpid()))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "tag": tag, "started": time.time()},
                      fh, ensure_ascii=False)
        return path
    except Exception:
        return None


def release_adb_lease(tag: str, lease_dir: Optional[str] = None,
                      pid: Optional[int] = None) -> None:
    """Remove this process's lease file (no-op when missing)."""
    directory = _lease_dir(lease_dir)
    path = os.path.join(directory, _lease_filename(tag, pid if pid is not None else os.getpid()))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def live_leases(lease_dir: Optional[str] = None) -> List[Dict]:
    """Return leases held by *other* live processes, pruning stale ones."""
    directory = _lease_dir(lease_dir)
    live: List[Dict] = []
    try:
        names = os.listdir(directory)
    except OSError:
        return live
    for name in names:
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                info = json.load(fh) or {}
            pid = int(info.get("pid") or 0)
        except Exception:
            pid = 0
        if pid == os.getpid() or _pid_alive(pid):
            live.append({"pid": pid, "tag": str(info.get("tag") or ""),
                         "path": path})
            continue
        try:
            os.remove(path)
        except OSError:
            pass
    return live


def release_adb_and_kill_if_last(tag: str, lease_dir: Optional[str] = None) -> bool:
    """Drop our lease, then stop the shared ADB server only when no other
    Macro2k process still holds one. Returns ``True`` when killed."""
    release_adb_lease(tag, lease_dir)
    if live_leases(lease_dir):
        return False
    from .scanner import kill_adb_server
    kill_adb_server()
    return True
