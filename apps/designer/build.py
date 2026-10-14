"""Build a standalone single-workflow Runner .exe from the Designer."""
from __future__ import annotations

import json
import os
import subprocess
import threading

from src.utils import (
    is_frozen,
    log_error,
    log_info,
    log_success,
    log_warning,
    source_python,
)
from designer.common import (
    _PROJECT_ROOT,
)


class BuildMixin:
    """Build a standalone single-workflow Runner .exe from the Designer."""

    # ── Build a standalone single-workflow Runner .exe ─────────────────────────

    def build_runner_exe(self, flow_json: str, version: str = "1.0.0") -> dict:
        """Package the current workflow into a standalone Runner .exe.

        Saves the flow (bundling its templates), then shells out to
        ``packaging/build_runner.py`` which runs PyInstaller and copies only the
        vendor pieces this workflow needs. Output lands in
        ``dist/<Name>-Runner/``. Progress is streamed to the log; a
        ``build_done`` event is pushed when finished.

        Building requires the dev Python toolchain (PyInstaller), so it is only
        available when running from source — never inside the frozen app.
        """
        if is_frozen():
            msg = ("Building an .exe needs the dev environment (Python + "
                   "PyInstaller). Run the Designer from source to build.")
            log_error(msg)
            self._push("build_done", {"ok": False, "error": msg})
            return {"ok": False, "error": msg}

        # Persist the flow first so the on-disk bundle (json + templates) matches
        # what we ship. Reuse the normal save path.
        try:
            path = self._wf_path
            if not path:
                flow = json.loads(flow_json)
                path = self._default_flow_path(flow.get("name") or "workflow")
            self._write_flow(flow_json, path)
            self._wf_path = path
            self._remember_last_workflow(path)
        except Exception as exc:
            msg = f"Couldn't save the workflow before building: {exc}"
            log_error(msg)
            self._push("build_done", {"ok": False, "error": msg})
            return {"ok": False, "error": msg}

        workflow_dir = os.path.dirname(os.path.abspath(path))
        ver = str(version or "1.0.0").strip() or "1.0.0"
        threading.Thread(
            target=self._build_runner_worker, args=(workflow_dir, ver),
            daemon=True,
        ).start()
        return {"ok": True, "started": True}

    def _build_runner_worker(self, workflow_dir: str, version: str) -> None:
        script = os.path.join(_PROJECT_ROOT, "packaging", "build_runner.py")
        if not os.path.isfile(script):
            # From source _PROJECT_ROOT is the repo root; be defensive anyway.
            script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "packaging", "build_runner.py")
        cmd = [source_python(), script, "--workflow", workflow_dir, "--version", version]
        log_info("Building standalone Runner .exe …")
        out_path = ""
        req_path = ""   # requirements/ beside the exe (from workflows/<Name>/vendor/)
        ok = False
        try:
            proc = subprocess.Popen(
                cmd, cwd=os.path.dirname(os.path.dirname(script)),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if not line:
                    continue
                body = line[3:] if line.startswith(">> ") else line
                if body.startswith("DONE: "):
                    out_path = body[6:].strip()
                    ok = True
                    log_success(f"Build complete: {out_path}")
                elif body.startswith("REQUIREMENTS: "):
                    req_path = body[len("REQUIREMENTS: "):].strip()
                    log_warning(f"Game files for players to copy into the game folder: {req_path}")
                elif body.startswith("BUILD FAILED") or body.startswith("ERROR"):
                    log_error(body)
                else:
                    log_info(body)
            code = proc.wait()
            if code != 0:
                ok = False
        except Exception as exc:
            log_error(f"Build error: {exc}")
            ok = False
        self._push("build_done", {"ok": ok, "path": out_path, "requirements": req_path})

    def reveal_path(self, path: str) -> bool:
        """Open a folder (or a file's parent) in the OS file manager."""
        try:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            if target and os.path.isdir(target):
                os.startfile(target)  # noqa: S606 — local tool, user-initiated
                return True
        except Exception as exc:
            log_warning(f"Couldn't open folder: {exc}")
        return False
