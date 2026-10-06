"""Designer-local variable overrides (``local_vars.json``).

A workflow's ``value`` fields are the **defaults** a build ships: they are what
a packaged Runner seeds a fresh install with. While designing, though, you often
want a *different* value for testing (a test account, a debug flag, one level
instead of a loop) — and you must not bake that into the shipped default.

So the Designer keeps a sibling file next to ``workflow.json``::

    workflows/<Name>/workflow.json      # values = build defaults
    workflows/<Name>/local_vars.json    # design/test overrides (never shipped)

Test runs (:meth:`apply`) overlay the local values on top of the defaults;
a build never reads this file, and it is excluded from the bundled workflow
folder, so a local value can never leak into a shipped .exe.

The override map is **flat, keyed by dotted variable path** — the same key the
engine already uses to flatten children (``parent.child``) and select-option
children (``parent.<option>.<child>``)::

    {
      "version": 1,
      "globals":    {"isFirstGoHome": false, "cfg.speed": 5},
      "activities": {"act_home": {"acc.user": "test01"}}
    }

Flat keys survive a variable being added/renamed/removed (an unknown key is
simply ignored), so the sidecar never has to be migrated in lock-step with the
flow.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Dict, Iterable, Tuple

LOCAL_VARS_FILENAME = "local_vars.json"

_LOCK = threading.RLock()


def sidecar_path(flow_path: str) -> str:
    """``local_vars.json`` beside the workflow file ("" for no path)."""
    if not flow_path:
        return ""
    return os.path.join(os.path.dirname(os.path.abspath(flow_path)),
                        LOCAL_VARS_FILENAME)


def load(flow_path: str) -> Dict[str, Any]:
    """The override map, or an empty map when the file is missing/unreadable."""
    path = sidecar_path(flow_path)
    if not path:
        return {}
    with _LOCK:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception:
            return {}
    return clean(data)


def clean(data: Any) -> Dict[str, Any]:
    """Reduce *data* to ``{globals:{str:val}, activities:{id:{str:val}}}``.

    Anything malformed is dropped rather than raising, so a hand-edited or
    partially-written sidecar can never break a run.
    """
    out: Dict[str, Any] = {"globals": {}, "activities": {}}
    if not isinstance(data, dict):
        return out
    globals_map = data.get("globals")
    if isinstance(globals_map, dict):
        out["globals"] = {str(k): v for k, v in globals_map.items()}
    acts = data.get("activities")
    if isinstance(acts, dict):
        packed: Dict[str, Dict[str, Any]] = {}
        for act_id, m in acts.items():
            if isinstance(m, dict):
                packed[str(act_id)] = {str(k): v for k, v in m.items()}
        out["activities"] = packed
    return out


def save(flow_path: str, data: Any) -> bool:
    """Atomically write the override map beside the workflow. Returns ok."""
    path = sidecar_path(flow_path)
    if not path:
        return False
    payload = clean(data)
    payload["version"] = 1
    with _LOCK:
        tmp = ""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="local_vars.", suffix=".tmp",
                                       dir=os.path.dirname(path))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except Exception:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False


def _iter_vars(vars: Iterable, prefix: str = "") -> Iterable[Tuple[str, dict]]:
    """Yield ``(dotted name, var)`` for a variable tree.

    Children flatten to ``parent.child`` and a select option's own children to
    ``parent.<option>.<child>`` — the exact keys the engine seeds with.
    """
    for v in vars or []:
        if not isinstance(v, dict):
            continue
        name = str(v.get("name") or "").strip()
        if not name:
            continue
        full = f"{prefix}.{name}" if prefix else name
        yield full, v
        yield from _iter_vars(v.get("children") or [], full)
        option_children = v.get("optionChildren") or {}
        if isinstance(option_children, dict):
            for option, kids in option_children.items():
                opt = str(option).strip()
                if opt and isinstance(kids, list):
                    yield from _iter_vars(kids, f"{full}.{opt}")


def apply(flow: Dict[str, Any], data: Any) -> int:
    """Overlay local values onto *flow* in place; returns how many were applied.

    Reads the map as :func:`clean` normalizes it, so an inactive select-option
    child simply never matches a seeded key and is harmless.
    """
    if not isinstance(flow, dict):
        return 0
    payload = clean(data)
    applied = 0
    gmap = payload["globals"]
    if gmap:
        for full, var in _iter_vars(flow.get("globals") or []):
            if full in gmap:
                var["value"] = gmap[full]
                applied += 1
    amap = payload["activities"]
    if amap:
        for act in flow.get("activities") or []:
            if not isinstance(act, dict):
                continue
            m = amap.get(str(act.get("id") or ""))
            if not isinstance(m, dict):
                continue
            for full, var in _iter_vars(act.get("vars") or []):
                if full in m:
                    var["value"] = m[full]
                    applied += 1
    return applied
