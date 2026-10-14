"""Version, changelog and self-update of a standalone Runner build."""
from __future__ import annotations

from typing import List, Optional

from src import runner_update
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    get_capture_backend,
    set_capture_backend,
)
from src.utils import (
    log_success,
)

from runner.common import (
    RUNTIME_PATH_PARAMS,
)


class UpdateMixin:
    """Version, changelog and self-update of a standalone Runner build."""

    # ── Version + self-update (standalone Runner builds) ─────────────────────

    def _runner_payload(self) -> dict:
        info = self._runner_info
        return {
            "version": str(info.get("version") or ""),
            "appName": str(info.get("appName") or ""),
            "repo": str(info.get("repo") or ""),
            "builtAt": str(info.get("builtAt") or ""),
            "supported": runner_update.updates_supported(info),
            "update": dict(self._update),
            "changelog": self._changelog_payload(),
        }

    def _changelog_auto_show_enabled(self) -> bool:
        with self._runner_config_lock:
            raw = (self._runner_config or {}).get("autoShowChangelog", True)
        return raw is not False

    def _changelog_payload(self, refresh: bool = False) -> dict:
        info = self._runner_info
        history = runner_update.refresh_history(info) if refresh else runner_update.load_history(info)
        pending = runner_update.read_pending(info)
        if pending and not any(row.get("version") == pending.get("version") for row in history):
            history = [pending] + history
        history.sort(key=lambda row: runner_update.parse_version(row.get("version")), reverse=True)
        current = str(info.get("version") or "")
        with self._runner_config_lock:
            shown = str((self._runner_config or {}).get("shownChangelogVersion") or "")
        auto = self._changelog_auto_show_enabled()
        notes = (pending or {}).get("markdown") or ""
        should = bool(
            pending and pending.get("version") == current and str(notes).strip()
            and pending.get("autoShow") is True and auto and shown != current
        )
        return {
            "history": history,
            "pending": pending,
            "autoShowEnabled": auto,
            "shownVersion": shown,
            "shouldAutoShow": should,
        }

    def changelog_refresh(self) -> dict:
        return self._changelog_payload(refresh=True)

    def set_changelog_auto_show(self, enabled: bool) -> dict:
        with self._runner_config_lock:
            self._runner_config["autoShowChangelog"] = bool(enabled)
            self._save_runner_config()
        return self._changelog_payload()

    def acknowledge_changelog(self, version: str) -> dict:
        version = str(version or "")
        current = str(self._runner_info.get("version") or "")
        if version and version == current:
            with self._runner_config_lock:
                self._runner_config["shownChangelogVersion"] = version
                self._save_runner_config()
            runner_update.acknowledge_pending(self._runner_info, version)
        return self._changelog_payload()

    def open_external_url(self, url: str) -> bool:
        """Open an https link from a changelog. Rejects every other scheme."""
        from urllib.parse import urlparse
        import webbrowser
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        try:
            return bool(webbrowser.open(parsed.geturl()))
        except Exception:
            return False

    def _auto_check_update(self) -> None:
        result = runner_update.check(self._runner_info)
        self._update = result
        try:
            runner_update.refresh_history(self._runner_info)
        except Exception:
            pass
        if result.get("available"):
            log_success(f"Update available: v{result.get('version')}")
            self._push("update_available", result)

    def update_check(self) -> dict:
        """Ask GitHub for a newer release of this Runner."""
        result = runner_update.check(self._runner_info)
        self._update = result
        try:
            runner_update.refresh_history(self._runner_info)
        except Exception:
            pass
        result["changelog"] = self._changelog_payload()
        return result

    def update_apply(self) -> dict:
        """Download + install the newest release and restart. Returns only on
        failure or when already up to date."""
        if self.engine.is_running():
            return {"applied": False, "error": "Stop the run before updating", "upToDate": False}
        return runner_update.apply(
            self._runner_info,
            on_progress=lambda pct, stage: self._push("update_progress", {"pct": pct, "stage": stage}),
            before_exit=self._close,
        )

    def _controller(self) -> str:
        raw = str((self.flow or {}).get("controller") or "adb").strip().lower()
        return "win32" if raw == "win32" else "adb"

    def set_capture_backend(self, backend: str) -> dict:
        selected = str(backend or "").strip().lower()
        if selected not in CAPTURE_BACKENDS:
            selected = get_capture_backend()
        with self._runner_config_lock:
            if self.flow and not self._persist_runner_config({("capture",): selected}):
                return {"ok": False, "backend": get_capture_backend(), "backends": list(CAPTURE_BACKENDS)}
            selected = set_capture_backend(selected)
        self._push("capture_backend", {"backend": selected})
        return {"ok": True, "backend": selected, "backends": list(CAPTURE_BACKENDS)}

    def _find_node(self, node_id: str) -> Optional[dict]:
        """Find a node across activity and function graphs by its stable id."""
        owners = list(self.flow.get("activities", []) or []) + list(self.flow.get("functions", []) or [])
        for owner in owners:
            for node in ((owner.get("graph") or {}).get("nodes") or []):
                if node.get("id") == node_id:
                    return node
        return None

    def _runtime_settings_for_activity(self, activity: dict) -> List[dict]:
        """Generate runner controls for runtime-selectable node paths.

        Function calls are traversed too, so a Launch program inside a reusable
        function automatically appears on every activity that can invoke it.
        """
        functions = {f.get("id"): f for f in (self.flow.get("functions") or []) if f.get("id")}
        labels = {
            "win_launch": ("Launch program", "Program path (.exe)"),
            "launch_emulator": ("Launch emulator", "Install folder / console .exe"),
            "app_install": ("Install app", "APK file"),
        }
        kinds = {"launch_emulator": "folder", "win_launch": "file", "app_install": "file"}
        # Params holding a machine-specific absolute path: each one becomes a
        # runner control so a built .exe can be re-pointed without editing JSON.
        found: List[dict] = []
        seen_nodes: set = set()
        seen_functions: set = set()

        def scan(graph: dict) -> None:
            for node in (graph or {}).get("nodes", []) or []:
                node_id = node.get("id")
                if not node_id or node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                params = node.get("params") or {}
                node_type = str(node.get("type") or "")
                # Every serialized path-like parameter gets a generated setting;
                # known node types only refine its label and picker kind.
                for param in RUNTIME_PATH_PARAMS:
                    if param not in params:
                        continue
                    # A Launch program on the project path is set once in the
                    # Settings tab (Game path), not per activity.
                    if param == "path" and self._launch_uses_project_path(node):
                        continue
                    # Emulator nodes on the shared project setting (Settings →
                    # Emulator) likewise don't need a per-activity control.
                    if param == "path" and self._emulator_uses_project(node):
                        continue
                    node_label, field_label = labels.get(node_type, (node_type or "Action", "Path"))
                    node_label = str(node.get("note") or node_label)
                    found.append({
                        "id": f"{node_id}:{param}", "nodeId": node_id, "param": param,
                        "nodeLabel": node_label, "label": field_label,
                        "kind": kinds.get(node_type, "file"),
                        "value": str(params.get(param) or ""),
                    })
                if node_type == "call":
                    fn_id = str(params.get("fn") or "")
                    if fn_id and fn_id not in seen_functions and fn_id in functions:
                        seen_functions.add(fn_id)
                        scan(functions[fn_id].get("graph") or {})

        scan(activity.get("graph") or {})
        return found

    def _activities_payload(self) -> List[dict]:
        out = []
        for a in self.flow.get("activities", []) or []:
            graph = a.get("graph", {}) or {}
            out.append({
                "id": a.get("id"),
                "name": a.get("name") or a.get("id"),
                "type": a.get("type", "sequence"),
                "enabled": a.get("enabled", True),
                "status": self._act_status.get(str(a.get("id")), "pending"),
                "pollInterval": a.get("pollInterval", 1.0),
                "maxRetries": a.get("maxRetries", 1),
                "nodeCount": len(graph.get("nodes", []) or []),
                "vars": [self._var_payload(v) for v in (a.get("vars") or [])],
                "runtimeSettings": self._runtime_settings_for_activity(a),
            })
        return out
