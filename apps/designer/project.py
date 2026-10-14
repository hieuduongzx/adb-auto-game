"""Workflow files, UI settings, remembered folders and local variables."""
from __future__ import annotations

import json
import os
from typing import Optional

import webview

from src.workflow import local_vars
from src.utils import (
    load_ui_settings,
    log_error,
    log_info,
    log_success,
    log_warning,
    save_ui_settings,
)
from designer.common import (
    _PROJECT_ROOT,
    _WORKFLOWS_DIR,
    _sanitize_name,
)


class ProjectMixin:
    """Workflow files, UI settings, remembered folders and local variables."""

    # ── Persisted UI settings (snap, global preview, …) ───────────────────────

    def get_settings(self) -> dict:
        return load_ui_settings()

    def save_settings(self, settings: dict) -> bool:
        # Merged, not replaced, so writing UI prefs (theme, snap, previewAll…)
        # from JS never wipes keys another window owns — the Hub's or the
        # Runner's, or the backend's own ``lastWorkflow``.
        return save_ui_settings(settings)

    def _remember_last_workflow(self, path: Optional[str]) -> None:
        """Persist (or clear) the path to reopen on the next launch."""
        save_ui_settings({"lastWorkflow": str(path) if path else None})

    @staticmethod
    def _migrate_open_delay(path: str, text: str) -> str:
        """Upgrade node timing in place on open; leave unrelated waits untouched."""
        flow = json.loads(text)
        changed = False
        items = [flow.get('nodeDefaults')]
        for coll in ('activities', 'functions'):
            for item in flow.get(coll) or []:
                items.extend(((item.get('graph') or {}).get('nodes') or []))
        for item in items:
            if not isinstance(item, dict):
                continue
            if item is not flow.get('nodeDefaults'):
                params = item.get('params')
                if isinstance(params, dict) and 'delay' in params and not isinstance(params['delay'], (dict, list)):
                    if 'delay' not in item and 'delayBefore' not in item:
                        item['delay'] = params['delay']
                    del params['delay']
                    changed = True
            if 'delayBefore' in item:
                if 'delay' not in item:
                    item['delay'] = item['delayBefore']
                del item['delayBefore']
                changed = True
            if 'delayAfter' in item:
                del item['delayAfter']
                changed = True
        if changed:
            import tempfile
            folder = os.path.dirname(os.path.abspath(path))
            fd, tmp = tempfile.mkstemp(dir=folder, suffix='.json.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as out:
                    out.write(json.dumps(flow, ensure_ascii=False, indent=2))
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return json.dumps(flow, ensure_ascii=False, indent=2)
        return text

    def get_last_workflow(self) -> dict:
        """Return the workflow to open on startup.

        Prefers a path passed from the Hub / CLI (``_pending_load``), else the
        remembered ``lastWorkflow`` from settings.

        ``{ok, path, name, text}`` when a file is available, else ``{}``.
        """
        path: Optional[str] = None
        if self._pending_load and os.path.isfile(self._pending_load):
            path = self._pending_load
            self._pending_load = None
        else:
            self._pending_load = None
            raw = (self.get_settings() or {}).get("lastWorkflow")
            if raw and os.path.isfile(str(raw)):
                path = str(raw)
        if not path:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            text = self._migrate_open_delay(path, text)
            name = ""
            try:
                name = (json.loads(text) or {}).get("name", "")
            except Exception:
                pass
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            return {"ok": True, "path": path, "name": name, "text": text}
        except Exception:
            return {}

    # ── Dialog directory memory ────────────────────────────────────────────────

    def _start_dir(self, fallback: str) -> str:
        if self._last_dir and os.path.isdir(self._last_dir):
            return self._last_dir
        return fallback

    def _remember_dir(self, path: str) -> None:
        try:
            d = os.path.dirname(str(path))
            if d and os.path.isdir(d):
                self._last_dir = d
        except Exception:
            pass

    def _win(self):
        wins = webview.windows
        return wins[0] if wins else None

    # ── Local (design/test) variable overrides ────────────────────────────────
    # workflow.json holds the build defaults; local_vars.json (a sibling file)
    # holds design-test values that a test run overlays but a build never ships.

    def get_local_vars(self) -> dict:
        return local_vars.load(self._wf_path)

    def save_local_vars(self, vars_json: str) -> dict:
        if not self._wf_path:
            return {"ok": False, "error": "Save the workflow once before using test values."}
        try:
            data = json.loads(vars_json) if vars_json else {}
        except Exception as exc:
            return {"ok": False, "error": f"Invalid local variables: {exc}"}
        ok = local_vars.save(self._wf_path, data)
        return {"ok": ok, "path": local_vars.sidecar_path(self._wf_path)}

    def _apply_local_vars(self, flow: dict) -> dict:
        """Overlay local_vars.json test values onto *flow* in place (test runs)."""
        try:
            n = local_vars.apply(flow, local_vars.load(self._wf_path))
            if n:
                log_info(f"Applied {n} local test value(s) from {local_vars.LOCAL_VARS_FILENAME}")
        except Exception as exc:
            log_warning(f"Couldn't apply local variables: {exc}")
        return flow

    # ── Workflow file ops ──────────────────────────────────────────────────────

    def workflow_new(self, name: str = "") -> bool:
        """Forget the open file so the next save creates
        ``workflows/<name>/workflow.json``."""
        self._wf_path = None
        self._remember_last_workflow(None)   # a fresh doc shouldn't reopen the old one
        self._scope_refresh_out()
        return True

    def _default_flow_path(self, name: str) -> str:
        """Default save target: ``<workflows>/<name>/workflow.json``.

        Used whenever the user doesn't pick an explicit location. Each workflow
        gets its own folder so ``_write_flow`` can bundle a sibling
        ``templates/`` folder, keeping the pair portable.
        """
        clean = _sanitize_name(name) or "workflow"
        folder = os.path.join(_WORKFLOWS_DIR, clean)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "workflow.json")

    def workflow_export(self, flow_json: str, name: str = "") -> bool:
        os.makedirs(_WORKFLOWS_DIR, exist_ok=True)
        default = f"{_sanitize_name(name) or 'workflow'}.json"
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=self._start_dir(_WORKFLOWS_DIR),
                    save_filename=default,
                    file_types=("JSON (*.json)", "All files (*.*)"),
                )
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
        if not path:
            # No location chosen → default per-workflow folder next to the app.
            path = self._default_flow_path(name)
            log_info(f"Saving by default into workflows/{_sanitize_name(name) or 'workflow'}/")
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self._write_flow(flow_json, path)
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            self._scope_refresh_out()
            log_success(f"Workflow saved: {path}")
            return True
        except Exception as exc:
            log_error(f"Saving workflow failed: {exc}")
            return False

    def workflow_save(self, flow_json: str, name: str = "") -> dict:
        # Save to the open file if there is one; otherwise drop the workflow
        # into its default folder (workflows/<name>/<name>.json) with no dialog.
        path = self._wf_path or self._default_flow_path(name)
        try:
            self._write_flow(flow_json, path)
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            self._scope_refresh_out()
            log_success(f"Saved: {path}")
            return {"ok": True, "path": path}
        except Exception as exc:
            log_error(f"Save failed: {exc}")
            return {"ok": False, "path": self._wf_path}

    def workflow_import(self) -> str:
        win = self._win()
        if win is None:
            return ""
        start_dir = self._start_dir(_WORKFLOWS_DIR if os.path.isdir(_WORKFLOWS_DIR) else _PROJECT_ROOT)
        try:
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                file_types=("JSON (*.json)", "All files (*.*)"),
            )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        try:
            with open(str(path), "r", encoding="utf-8") as fh:
                text = fh.read()
            text = self._migrate_open_delay(str(path), text)
            self._wf_path = str(path)
            self._remember_dir(path)
            self._remember_last_workflow(str(path))
            self._scope_refresh_out()
            log_info(f"Workflow opened: {path}")
            return text
        except Exception as exc:
            log_error(f"Opening workflow failed: {exc}")
            return ""
