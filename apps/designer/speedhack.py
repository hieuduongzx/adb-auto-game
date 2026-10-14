"""The Designer's manual speed hack, independent of test runs."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

from src.core.frida_speedhack import FridaSpeedhackManager
from src.utils import (
    launch_tool,
    log_error,
    log_info,
    log_success,
    log_warning,
)
from designer.common import (
    _RUN_TMP_DIR,
    _TEMPLATES_DIRNAME,
)


class SpeedhackMixin:
    """The Designer's manual speed hack, independent of test runs."""

    # ── Standalone speed hack (manual ▶, independent of the test run) ──────────

    def _sh_push(self, active: bool, running: bool) -> None:
        self._push("speedhack_state", {"active": active, "running": running})

    def speedhack_start(self, speed=2.0, package: str = "", native=False) -> bool:
        """Start (or live-adjust) the speed hack on its own — no workflow needed.

        ADB-only: uses Frida. Win32 projects have no speed hack (the old
        cheat.dll injection was removed) — refuse there with a clear message.
        ``native`` selects the compiled-C clock hook; it only applies to a fresh
        injection, so toggling it while one is live changes nothing until stop.
        """
        if self._capture_kind == "win32":
            log_error("[speedhack] not supported in Win32 mode (ADB/Frida only).")
            return False
        try:
            scale = float(speed)
        except (TypeError, ValueError):
            scale = 2.0
        if self.controller.device is None:
            log_error("[speedhack] no device selected")
            return False
        if scale <= 0 or scale == 1.0:
            log_warning("[speedhack] speed must differ from 1.0 to accelerate")
            return False
        # Already running → just push the new scale live (no re-inject, no package).
        if self._sh_mgr is not None:
            ok = self._sh_mgr.set_scale(scale)
            self._sh_push(bool(self._sh_mgr.active), True)
            return ok
        pkg = (package or "").strip()
        if not pkg:
            log_error("[speedhack] a game package is required to enable the speed hack")
            return False
        mgr = FridaSpeedhackManager(package=pkg, use_cmodule=bool(native))
        mgr.adb_controller = self.controller
        if not mgr.available:
            log_warning("[speedhack] frida-inject not found in vendor/frida/")
            return False
        self._sh_mgr = mgr
        self._sh_stop = threading.Event()
        self._sh_push(False, True)
        threading.Thread(target=self._sh_loop, args=(scale,), daemon=True).start()
        return True

    def _sh_loop(self, scale: float) -> None:
        """Inject in the background, then keep the injection alive.

        Retries until the game process exists, and afterwards keeps watching: a
        game restart takes the hook with the old PID, so the agent has to be
        re-injected or the UI would keep claiming "Live" at normal speed.
        """
        stop_ev = self._sh_stop
        mgr = self._sh_mgr
        if mgr is None:
            return
        log_info(f"[speedhack] will accelerate '{mgr.package}' x{scale} once the game runs…")
        armed = False
        while mgr is not None and stop_ev is not None and not stop_ev.is_set():
            try:
                if not armed:
                    if mgr.set_scale(scale):
                        armed = True
                        log_success(f"[speedhack] enabled x{scale}")
                        self._sh_push(True, True)
                elif not mgr.ensure_alive():
                    armed = False
                    self._sh_push(False, True)
            except Exception as e:
                log_warning(f"[speedhack] retrying: {e}")
            for _ in range(50):  # ~5s, stay responsive to stop
                if stop_ev.is_set():
                    return
                time.sleep(0.1)

    def speedhack_stop(self) -> bool:
        ev = self._sh_stop
        if ev is not None:
            ev.set()
        self._sh_stop = None
        mgr = self._sh_mgr
        self._sh_mgr = None
        if mgr is not None:
            try:
                mgr.detach()
            except Exception as e:
                log_warning(f"[speedhack] error while disabling: {e}")
        self._sh_push(False, False)
        return True

    def _workflow_templates_dir(self, flow_json: str = "") -> Optional[str]:
        """Best-effort path to the current workflow's ``templates/`` folder.

        Captures from DevScope should land where the workflow will bundle its
        images, so they're picked up by ``_write_flow`` on save. Uses the open
        file's folder when saved; otherwise the default ``workflows/<name>/``.
        Returns ``None`` if it can't be resolved.
        """
        name, tdir = "", _TEMPLATES_DIRNAME
        try:
            if flow_json:
                flow = json.loads(flow_json)
                name = flow.get("name") or ""
                tdir = (flow.get("templatesDir") or _TEMPLATES_DIRNAME).strip().strip("/\\") \
                    or _TEMPLATES_DIRNAME
        except Exception:
            pass
        try:
            if self._wf_path:
                base = os.path.dirname(os.path.abspath(self._wf_path))
            else:
                base = os.path.dirname(self._default_flow_path(name))
            dest = os.path.join(base, tdir)
            os.makedirs(dest, exist_ok=True)
            return dest
        except Exception as exc:
            log_warning(f"Couldn't resolve the templates folder: {exc}")
            return None

    def open_devscope(self, flow_json: str = "") -> bool:
        """Launch DevScope, pointing its output at this workflow's ``templates/``
        folder so region crops / screenshots save alongside the flow."""
        try:
            out_dir = self._workflow_templates_dir(flow_json)
            launch_tool("devscope", [out_dir] if out_dir else None)
            if out_dir:
                log_success(f"DevScope opened · images save to: {out_dir}")
            else:
                log_success("DevScope opened")
            return True
        except Exception as exc:
            log_error(f"Opening DevScope failed: {exc}")
            return False

    # Back-compat alias for any old JS / callers.
    open_dev_helper = open_devscope

    def open_runner(self, flow_json: str) -> bool:
        """Launch the Runner GUI (separate process) preloaded with this flow.

        The runner resolves template images relative to the file it loads, so we
        can't just dump the raw JSON next to it — its ``templates/<file>`` paths
        point at the *original* workflow bundle. ``_write_flow`` re-bundles the
        templates into a sibling ``templates/`` folder (pulling from the original
        ``self._wf_path`` bundle / absolute picker paths) and rewrites the paths,
        so the temp run file is self-contained and the runner finds every image.
        """
        try:
            os.makedirs(_RUN_TMP_DIR, exist_ok=True)
            tmp = os.path.join(_RUN_TMP_DIR, "_designer_run.json")
            # A Runner opened from the Designer is a test run: overlay the
            # design-test values so it behaves exactly like the in-app Test run.
            try:
                flow = json.loads(flow_json)
                self._apply_local_vars(flow)
                flow_json = json.dumps(flow, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self._write_flow(flow_json, tmp)
            launch_tool("runner", [tmp])
            log_success("Runner GUI opened with the current workflow")
            return True
        except Exception as exc:
            log_error(f"Opening Runner failed: {exc}")
            return False
