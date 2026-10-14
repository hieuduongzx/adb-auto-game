"""Runner config, preflight checks, diagnostics and the page's state snapshot."""
from __future__ import annotations

import copy
import datetime
import json
import os
import tempfile
import time
from typing import List, Optional

import webview

from src import run_history
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    get_capture_backend,
)
from src.utils import (
    app_dir,
    bundle_dir,
    data_root,
    file_url,
    is_frozen,
    log_error,
    log_warning,
)
from src.version import APP_VERSION
from src.workflow import WorkflowEngine, NODE_TYPES

from runner.common import (
    EMULATOR_NODE_TYPES,
    RUNTIME_PATH_PARAMS,
)


class StateMixin:
    """Runner config, preflight checks, diagnostics and the page's state snapshot."""

    # ── State ────────────────────────────────────────────────────────────────

    def _config_path_for_flow(self, flow: dict, flow_path: str) -> str:
        """Readable per-workflow config: data/runner/<slug>_<hash>/config.json.

        The slug comes from ``slugify_workflow_name`` — it appends a short hash
        of the original name so distinct names ("A B" vs "A_B") can never
        collide on one config folder."""
        return os.path.join(run_history.runner_dir(str(flow.get("name") or ""), flow_path),
                            "config.json")

    def _load_runner_config(self, flow: dict, flow_path: str) -> None:
        with self._runner_config_lock:
            self._runner_config_path = self._config_path_for_flow(flow, flow_path)
            try:
                with open(self._runner_config_path, encoding="utf-8") as fh:
                    cfg = json.load(fh) or {}
                self._runner_config = cfg if isinstance(cfg, dict) else {}
            except Exception:
                self._runner_config = {}

    def _save_runner_config(self) -> bool:
        with self._runner_config_lock:
            if not self._runner_config_path:
                return False
            cfg = self._runner_config
            cfg["version"] = 1
            cfg["workflow"] = str(self.flow.get("name") or "")
            tmp = ""
            try:
                folder = os.path.dirname(self._runner_config_path)
                os.makedirs(folder, exist_ok=True)
                fd, tmp = tempfile.mkstemp(
                    prefix="config.", suffix=".tmp", dir=folder,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(cfg, fh, ensure_ascii=False, indent=2, allow_nan=False)
                os.replace(tmp, self._runner_config_path)
                return True
            except Exception as exc:
                if tmp:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                log_warning(f"Couldn't save Runner config: {exc}")
                return False

    def _persist_runner_config(self, changes: dict, remove=()) -> bool:
        """Commit overrides before applying them to the live workflow.

        Keys are paths into the config, e.g. ("activities", id, "enabled").
        A failed atomic write restores the previous config too, so a later
        successful edit cannot accidentally save an earlier refused edit.
        """
        with self._runner_config_lock:
            previous = copy.deepcopy(self._runner_config)
            for path, value in changes.items():
                target = self._runner_config
                for key in path[:-1]:
                    if not isinstance(target.get(key), dict):
                        target[key] = {}
                    target = target[key]
                target[path[-1]] = copy.deepcopy(value)
            for key in remove:
                self._runner_config.pop(key, None)
            if self._save_runner_config():
                return True
            self._runner_config = previous
            return False

    def _apply_runner_config(self) -> None:
        """Overlay only values explicitly edited in Runner onto workflow data."""
        cfg = self._runner_config or {}
        acts = self.flow.get("activities") or []
        by_id = {str(a.get("id")): a for a in acts if a.get("id")}
        act_cfg = cfg.get("activities") or {}
        if not isinstance(act_cfg, dict):
            act_cfg = {}
        for act_id, saved in act_cfg.items():
            act = by_id.get(str(act_id))
            if not act or not isinstance(saved, dict):
                continue
            if "enabled" in saved:
                act["enabled"] = bool(saved["enabled"])
            if "pollInterval" in saved:
                try:
                    act["pollInterval"] = max(0.05, float(saved["pollInterval"]))
                except (TypeError, ValueError):
                    pass
            saved_vars = saved.get("vars") or {}
            if isinstance(saved_vars, dict):
                for full, var in self._each_activity_var(act.get("vars") or []):
                    if full in saved_vars:
                        var["value"] = saved_vars[full]
        for act in acts:
            for _full, var in self._each_activity_var(act.get("vars") or []):
                if var.get("type") == "select":
                    options = var.get("options") or []
                    if var.get("display") == "toggle-group" and var.get("multiple"):
                        values = var.get("value")
                        values = values if isinstance(values, list) else [values]
                        var["value"] = [o for o in options if o in values]
                    elif isinstance(var.get("value"), list):
                        var["value"] = next((o for o in var["value"] if o in options), options[0] if options else "")
                    elif var.get("value") not in options:
                        var["value"] = options[0] if options else ""
        # Retry count: the workflow's own ``maxRetries`` is the default the Runner
        # shows, and a Runner override (saved in this Runner's config) beats it.
        # Only the override is written to flow, in memory — the workflow file is
        # never written back.
        for act in acts:
            saved = act_cfg.get(str(act.get("id"))) if isinstance(act_cfg, dict) else None
            if isinstance(saved, dict) and saved.get("retries") is not None:
                try:
                    act["maxRetries"] = max(1, int(float(saved["retries"])))
                    continue
                except (TypeError, ValueError):
                    pass
            try:
                act["maxRetries"] = max(1, int(act.get("maxRetries", 1) or 1))
            except (TypeError, ValueError):
                act["maxRetries"] = 1
        order = cfg.get("order") or []
        if not isinstance(order, list):
            order = []
        if order:
            rank = {str(value): i for i, value in enumerate(order)}
            acts.sort(key=lambda a: rank.get(str(a.get("id")), len(rank)))
        node_cfg = cfg.get("nodes") or {}
        if not isinstance(node_cfg, dict):
            node_cfg = {}
        for node_id, values in node_cfg.items():
            node = self._find_node(str(node_id))
            if not node or not isinstance(values, dict):
                continue
            params = node.setdefault("params", {})
            for param in RUNTIME_PATH_PARAMS:
                if param in values and param in params:
                    params[param] = str(values[param] or "")
        speed = cfg.get("speedhack") or {}
        if isinstance(speed, dict) and speed:
            merged = dict(self.flow.get("speedhack") or {})
            if "enabled" in speed:
                merged["enabled"] = bool(speed["enabled"])
            if "speed" in speed:
                try:
                    merged["speed"] = float(speed["speed"])
                except (TypeError, ValueError):
                    pass
            self.flow["speedhack"] = merged
        if cfg.get("capture") in CAPTURE_BACKENDS:
            self.flow["capture"] = cfg["capture"]
        rounds = cfg.get("rounds") if isinstance(cfg.get("rounds"), dict) else {}
        self.engine.configure_rounds(rounds.get("count", 1), rounds.get("rest", 0))
        # Project game path (Win32): the Settings tab override beats the path
        # chosen in the Designer; an empty override keeps the workflow's own.
        win = self.flow.get("win32")
        if not isinstance(win, dict):
            win = self.flow["win32"] = {}
        self._flow_game_path = str(win.get("path") or "").strip()
        override = str(cfg.get("win32Path") or "").strip()
        if override:
            win["path"] = override
        # Shared emulator setting (ADB): the Settings tab override beats the
        # workflow's own kind/folder; empty fields keep the workflow's own.
        emu = self.flow.get("emulator")
        if not isinstance(emu, dict):
            emu = self.flow["emulator"] = {}
        # Older files kept the emulator install folder on each node. Seed the
        # shared setting from the first one so consolidating doesn't lose it and
        # the Settings → Emulator card can re-point it.
        if not str(emu.get("path") or "").strip():
            for node in self._graph_nodes():
                if str(node.get("type") or "") not in EMULATOR_NODE_TYPES:
                    continue
                params = node.get("params") or {}
                if not str(params.get("path") or "").strip():
                    continue
                emu["path"] = str(params.get("path")).strip()
                kind = str(params.get("emulator") or "").strip().lower()
                if kind and kind not in ("custom", "last"):
                    emu["kind"] = kind
                break
        if not str(emu.get("kind") or "").strip():
            emu["kind"] = "ldplayer"
        # Instance index joined the shared setting later — normalize a missing /
        # malformed shipped value before snapshotting the workflow default.
        try:
            emu["index"] = max(0, int(float(emu.get("index", 0) or 0)))
        except (TypeError, ValueError):
            emu["index"] = 0
        self._flow_emulator = dict(emu)
        saved_emu = cfg.get("emulator")
        if isinstance(saved_emu, dict):
            if str(saved_emu.get("kind") or "").strip():
                emu["kind"] = str(saved_emu.get("kind")).strip()
            if str(saved_emu.get("path") or "").strip():
                emu["path"] = str(saved_emu.get("path")).strip()
            if saved_emu.get("index") is not None:
                try:
                    emu["index"] = max(0, int(float(saved_emu.get("index"))))
                except (TypeError, ValueError):
                    pass

    @staticmethod
    def _launch_uses_project_path(node: dict) -> bool:
        """True when a win_launch node takes the project game path rather than
        its own ``path`` (same rule as WorkflowEngine._win_launch_path)."""
        if str(node.get("type") or "") != "win_launch":
            return False
        params = node.get("params") or {}
        src = str(params.get("pathSrc") or "").strip().lower()
        if src:
            return src == "project"
        return not str(params.get("path") or "").strip()

    @staticmethod
    def _emulator_uses_project(node: dict) -> bool:
        """True when an emulator node takes the shared project emulator install
        folder rather than its own ``path``. Only an explicit "custom" source
        keeps a per-activity control; legacy nodes without ``pathSrc`` follow the
        shared setting (their old path is seeded into it on load)."""
        if str(node.get("type") or "") not in EMULATOR_NODE_TYPES:
            return False
        params = node.get("params") or {}
        return str(params.get("pathSrc") or "").strip().lower() != "custom"

    def _graph_nodes(self, activity_ids: Optional[List[str]] = None,
                     *, reachable_only: bool = False) -> List[dict]:
        """Scan activity graphs and called functions without recursive calls.

        Settings include all nodes. Preflight uses only paths from Start,
        respecting terminal nodes and the engine's first-wire-per-port rule.
        Branch conditions are evaluated at runtime, so all possible exits count.
        """
        functions = {str(f.get("id")): f for f in (self.flow.get("functions") or []) if f.get("id")}
        acts = list(self.flow.get("activities") or [])
        if activity_ids is not None:
            wanted = {str(a) for a in activity_ids}
            acts = [a for a in acts if str(a.get("id")) in wanted]
        found: List[dict] = []
        seen_functions: set = set()

        pending = [act.get("graph") or {} for act in reversed(acts)]
        while pending:
            graph = pending.pop()
            graph_nodes = graph.get("nodes", []) or []
            if reachable_only:
                by_id = {n.get("id"): n for n in graph_nodes}
                start = next((n for n in by_id.values() if n.get("type") == "start"), None)
                edges = WorkflowEngine._build_adjacency(graph.get("edges", []) or [])
                outgoing = {}
                for (source, port), targets in edges.items():
                    if targets:
                        outgoing.setdefault(source, []).append(targets[0])
                reachable, queue = set(), [start.get("id")] if start else []
                while queue:
                    nid = queue.pop()
                    if nid in reachable or nid not in by_id:
                        continue
                    reachable.add(nid)
                    node = by_id[nid]
                    kind = NODE_TYPES.get(node.get("type"), {}).get("kind")
                    if kind in ("end", "stop"):
                        continue
                    queue.extend(outgoing.get(nid, []))
                graph_nodes = [n for n in by_id.values() if n.get("id") in reachable]
            for node in graph_nodes:
                found.append(node)
                if node.get("type") == "call":
                    fn_id = str((node.get("params") or {}).get("fn") or "")
                    if fn_id in functions and fn_id not in seen_functions:
                        seen_functions.add(fn_id)
                        pending.append(functions[fn_id].get("graph") or {})
        return found

    def _game_path_status(self) -> dict:
        """Whether this game needs the project game path, and if it is usable.

        Needed by a Win32 game whose Launch program uses the project path, or
        that ships requirements to copy into the game folder."""
        path = str((self.flow.get("win32") or {}).get("path") or "").strip()
        needed = bool(self.flow) and self._controller() == "win32" and (
            any(self._launch_uses_project_path(n) for n in self._graph_nodes())
            or bool(self._requirements_dir()))
        return {"needed": needed, "path": path, "exists": bool(path) and os.path.isfile(path)}

    def _launch_preflight(self, activity_ids: Optional[List[str]]) -> List[dict]:
        """Launch program nodes that would stop the run: no path, or nothing at
        it. Checked before Start so a missing game shows up front, not minutes
        into a run. A path held in a variable is only known at run time — the
        node itself stops the run then."""
        if not self.flow or self._controller() != "win32":
            return []
        if activity_ids is None:
            activity_ids = [str(a.get("id")) for a in (self.flow.get("activities") or [])
                            if a.get("enabled", True)]
        var_names = {str(v.get("name")) for v in (self.flow.get("globals") or []) if v.get("name")}
        for act in self.flow.get("activities") or []:
            var_names |= {str(v.get("name")) for v in (act.get("vars") or []) if v.get("name")}
        game = str((self.flow.get("win32") or {}).get("path") or "").strip()
        problems: List[dict] = []
        seen: set = set()
        for node in self._graph_nodes(activity_ids, reachable_only=True):
            if node.get("type") != "win_launch" or node.get("id") in seen:
                continue
            seen.add(node.get("id"))
            label = str(node.get("note") or "Launch program")
            if self._launch_uses_project_path(node):
                if not game:
                    message = f"{label}: no game path — choose the game's .exe in Settings → Game"
                elif not os.path.isfile(game):
                    message = f"{label}: game not found at {game} — choose the game's .exe again"
                else:
                    continue
                problems.append({"message": message, "gamePath": True})
                continue
            raw = str((node.get("params") or {}).get("path") or "").strip()
            if raw in var_names or ("{" in raw and "}" in raw):
                continue
            if not raw:
                message = f"{label}: no program path — set it in the activity's settings"
            elif not os.path.isfile(raw):
                message = f"{label}: program not found at {raw} — fix it in the activity's settings"
            else:
                continue
            problems.append({"message": message, "gamePath": False})
        # One line per distinct problem (several nodes can share the project path).
        unique = {p["message"]: p for p in problems}
        return list(unique.values())

    def _blocked_by_launch_paths(self, activity_ids: Optional[List[str]]) -> bool:
        """Refuse to start when a Launch program can't find its program; the
        page shows the problems and offers to choose the game path."""
        problems = self._launch_preflight(activity_ids)
        if not problems:
            return False
        for problem in problems:
            log_error(f"Can't start: {problem['message']}")
        # A refused Start is still an ending the operator has to see — the page
        # would otherwise sit on the previous run's outcome.
        self._stop_intent = False
        self._run_failed = True
        self._outcome = {"kind": "failed", "label": self._OUTCOME_LABELS["failed"],
                         "reason": "Start blocked — " + "; ".join(p["message"] for p in problems),
                         "at": datetime.datetime.now().strftime("%H:%M:%S"),
                         "epoch": time.time(), "runId": self._run_id,
                         "counts": dict(self._run_counts)}
        self._push("running_state", self._running_payload())
        self._push("launch_blocked", {
            "problems": [p["message"] for p in problems],
            "needsGamePath": any(p["gamePath"] for p in problems),
            "gamePath": self._game_path_status(),
            "outcome": self._outcome_fields(),
        })
        return True

    def _activity_runner_config(self, activity_id: str) -> dict:
        acts = self._runner_config.get("activities")
        if not isinstance(acts, dict):
            acts = {}
            self._runner_config["activities"] = acts
        saved = acts.get(str(activity_id))
        if not isinstance(saved, dict):
            saved = {}
            acts[str(activity_id)] = saved
        return saved

    def get_diagnostics(self) -> dict:
        """Return safe, read-only environment facts useful for support."""
        workflow_path = os.path.abspath(self.flow_path) if self.flow_path else ""
        req = self._requirements_payload()
        config = self._runner_config_path or ""
        return {
            "ok": True,
            "version": {"app": APP_VERSION, "appName": "Macro2k", "runner": self._runner_payload(),
                        "builtAt": self._runner_info.get("builtAt", ""),
                        "repo": self._runner_info.get("repo", ""), "frozen": is_frozen()},
            "mode": "packaged" if is_frozen() else "source",
            "controller": self._controller(),
            "capture": {"backend": get_capture_backend(), "backends": list(CAPTURE_BACKENDS)},
            "config": {"path": config, "exists": bool(config and os.path.isfile(config))},
            "workflow": {"path": workflow_path, "name": self.flow.get("name", ""),
                         "loaded": bool(self.flow), "exists": bool(workflow_path and os.path.isfile(workflow_path))},
            "data": {"root": data_root(), "folder": os.path.dirname(config) if config else data_root(),
                     "exists": os.path.isdir(os.path.dirname(config) if config else data_root())},
            "requirements": {"folder": req.get("folder", ""), "exists": bool(req.get("exists")),
                             "fileCount": len(req.get("files", []) or []),
                             "gameDir": req.get("gameDir", ""), "missing": req.get("missing", []),
                             "installed": req.get("installed", False)},
            "paths": {"app": app_dir(), "data": data_root(), "bundle": bundle_dir(),
                      "web": os.path.join(bundle_dir(), "web"), "config": config,
                      "workflow": workflow_path, "requirements": req.get("folder", "")},
            "log": {"entries": len(self._log_buffer), "max": 2000},
            "running": self._run_live(),
        }

    def export_log(self, path: str = "") -> dict:
        """Save retained Runner log as UTF-8, using the native dialog by default."""
        if not path:
            try:
                chosen = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename="macro2k-run.log", file_types=("Log files (*.log)", "Text files (*.txt)", "All files (*.*)")) if self._window else None
                path = chosen[0] if chosen else ""
            except Exception as exc:
                return {"ok": False, "path": "", "error": str(exc), "cancelled": False}
        if not path:
            return {"ok": False, "path": "", "error": "", "cancelled": True}
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for entry in self._log_buffer:
                    fh.write(str(entry.get("text", entry.get("message", ""))) + "\n")
            return {"ok": True, "path": os.path.abspath(path), "error": "", "cancelled": False}
        except Exception as exc:
            return {"ok": False, "path": path, "error": str(exc), "cancelled": False}

    def open_data_folder(self) -> dict:
        """Open the fixed per-runner data folder without accepting arbitrary paths."""
        folder = os.path.dirname(self._runner_config_path) if self._runner_config_path else data_root()
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
            return {"ok": True, "path": folder, "error": ""}
        except Exception as exc:
            return {"ok": False, "path": folder, "error": str(exc)}

    def get_state(self) -> dict:
        # "running"/"paused" plus the terminal-outcome keys, so the page reads
        # one shape whether it just opened or a run_activity event arrived.
        return {
            "title": "Macro2k Runner",
            "name": self.flow.get("name", ""),
            "loaded": bool(self.flow),
            "activities": self._activities_payload(),
            "log": self._log_buffer[-300:],
            **self._running_payload(),
            "speedhack": self.engine.speedhack_info(),
            "rounds": self._rounds_payload(),
            "schedule": self._schedule_payload(),
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
            "captureBackend": get_capture_backend(),
            "captureBackends": list(CAPTURE_BACKENDS),
            "controller": self._controller(),
            "win32": dict(self.flow.get("win32") or {}),
            "gamePathDefault": self._flow_game_path,
            "emulator": dict(self.flow.get("emulator") or {}),
            "emulatorDefault": self._flow_emulator,
            "requirements": self._requirements_payload(),
            "gamePath": self._game_path_status(),
            "configPath": self._runner_config_path or "",
            "runner": self._runner_payload(),
            "icon": self._icon_url(),
            "iconKey": self._icon_key(),
        }

    def _icon_url(self) -> str:
        """The game icon for the header: a built Runner's own icon, else the
        workflow's assets/icon.* or assets/cover.* (\"\" → the page draws initials)."""
        bundled = os.path.join(bundle_dir(), "runner_icon.png")
        if is_frozen() and os.path.isfile(bundled):
            return file_url(bundled)
        if self.flow_path:
            assets = os.path.join(os.path.dirname(os.path.abspath(self.flow_path)), "assets")
            for name in ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.ico",
                         "cover.png", "cover.jpg", "cover.jpeg", "cover.webp"):
                path = os.path.join(assets, name)
                if os.path.isfile(path):
                    return file_url(path)
        return ""

    def _icon_key(self) -> str:
        """Workflow folder name — the key the Hub hashes a game's hue from."""
        if self._runner_info.get("folder"):
            return str(self._runner_info["folder"])
        return os.path.basename(os.path.dirname(os.path.abspath(self.flow_path))) if self.flow_path else ""
