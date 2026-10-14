"""Frida clock speedhack wiring for a flow's ``speedhack`` settings."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict

from src.workflow.logs import log_error, log_info, log_success, log_warning

from src.core.frida_speedhack import FridaSpeedhackManager


class SpeedhackSupport:
    """Owns attaching/detaching the Frida time-scale for a run."""

    # ── Speedhack ────────────────────────────────────────────────────────────

    def _auto_package(self) -> str:
        """Best-effort target package: workflow field, else first ``launch_app`` node.

        Lets a flow that opens the game itself drive speedhack / app helpers
        without retyping the package everywhere.
        """
        pkg = str(getattr(self, "package", "") or "").strip()
        if pkg:
            return pkg
        # Legacy nested package (older workflow JSON).
        pkg = str((self.speedhack_cfg or {}).get("package") or "").strip()
        if pkg:
            return pkg
        graphs = [a.get("graph", {}) or {} for a in self.activities()]
        graphs += [f.get("graph", {}) or {} for f in self._functions.values()]
        for g in graphs:
            for n in g.get("nodes", []) or []:
                if n.get("type") == "launch_app":
                    found = str((n.get("params", {}) or {}).get("package", "")).strip()
                    if found:
                        return found
        return ""

    def _resolve_package(self) -> str:
        """Canonical package for speedhack / app tools."""
        return self._auto_package()

    def _node_package(self, params: Dict[str, Any]) -> str:
        """Resolve package for launch_app / app_stop / app_uninstall / if_app.

        ``pkgSrc``:
          - ``project`` — use the workflow-level package (Project settings)
          - ``custom``  — free text / variable from the node's ``package`` field
          - missing     — legacy: explicit package wins; else fall back to project
        """
        p = params or {}
        src = str(p.get("pkgSrc") or "").strip().lower()
        if src == "project":
            return self._resolve_package()
        if src == "custom":
            return str(self._resolve_value(p.get("package", "")) or "").strip()
        # Legacy nodes (no pkgSrc): keep previous behaviour, but if package is
        # empty borrow the project package so old "blank" blocks still work.
        pkg = str(self._resolve_value(p.get("package", "")) or "").strip()
        if pkg:
            return pkg
        return self._resolve_package()

    def speedhack_info(self) -> Dict[str, Any]:
        """Current speedhack config + runtime state (for the GUI)."""
        cfg = self.speedhack_cfg or {}
        try:
            speed = float(cfg.get("speed", 2.0) or 2.0)
        except (TypeError, ValueError):
            speed = 2.0
        return {
            "enabled": self._truthy(cfg.get("enabled", False)),
            "speed": speed,
            "native": self._truthy(cfg.get("native", False)),
            "package": self._resolve_package(),
            "active": bool(self._speedhack and self._speedhack.active),
        }

    def configure_speedhack(self, enabled=None, speed=None, package=None, native=None) -> None:
        """Update the speedhack config; applies live if a run is in progress.

        ``package`` updates the workflow-level package (not nested under speedhack).
        ``native`` picks the compiled-C clock hook (faster, detected by some
        protected titles) and only takes effect on the next injection.
        """
        cfg = dict(self.speedhack_cfg or {})
        if enabled is not None:
            cfg["enabled"] = bool(enabled)
        if native is not None:
            cfg["native"] = bool(native)
        if speed is not None:
            try:
                cfg["speed"] = float(speed)
            except (TypeError, ValueError):
                pass
        if package is not None:
            self.package = str(package).strip()
            if isinstance(self.flow, dict):
                self.flow["package"] = self.package
        # Keep speedhack_cfg free of package (top-level owns it).
        cfg.pop("package", None)
        self.speedhack_cfg = cfg
        if not self.running:
            return
        # Live: reflect the change into the running injection.
        if self._truthy(cfg.get("enabled", False)):
            if self._speedhack is None:
                self._start_speedhack()
            else:
                # Also covers re-enabling after a park, where only the toggle
                # changed and ``speed`` came in as None.
                self.set_speed_scale(cfg.get("speed", self._speed_scale))
        elif self._speedhack is not None:
            # Park rather than tear down: unloading a hook that every thread
            # calls millions of times a second is itself a crash risk, and the
            # run may well re-enable it. _stop_speedhack() at the end of the run
            # does the real teardown.
            try:
                self._speedhack.reset()
            except Exception as e:
                log_warning(f"[speedhack] error while parking: {e}")
            self._speed_scale = 1.0

    def set_speed_scale(self, scale: float) -> bool:
        """Change the live time scale of a running speedhack injection."""
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            return False
        self._speed_scale = scale
        self.speedhack_cfg["speed"] = scale
        if self._speedhack is None:
            return False
        try:
            return self._speedhack.set_scale(scale)
        except Exception as e:
            log_error(f"[speedhack] set scale failed: {e}")
            return False

    def _start_speedhack(self) -> None:
        cfg = self.speedhack_cfg or {}
        if not self._truthy(cfg.get("enabled", False)):
            return
        # Win32 projects have no Frida/ADB and we no longer inject a cheat
        # DLL — speed hack is ADB-only. Silently no-op in Win32 mode.
        if getattr(self, "_controller", "adb") == "win32":
            return
        if self._speedhack is not None:
            return
        package = self._resolve_package()
        if not package:
            log_warning("[speedhack] enabled but no game package (set 'package' next "
                        "to the workflow name, or add a Launch app block)")
            return
        try:
            scale = float(cfg.get("speed", 2.0) or 2.0)
        except (TypeError, ValueError):
            scale = 2.0
        if scale == 1.0:
            return
        mgr = FridaSpeedhackManager(
            package=package,
            use_cmodule=self._truthy(cfg.get("native", False)),
            scale_boottime=self._truthy(cfg.get("boottime", True)),
        )
        mgr.adb_controller = self.auto.adb
        if not mgr.available:
            log_warning("[speedhack] frida-inject not found in vendor/frida/")
            return
        self._speedhack = mgr
        self._speed_scale = scale
        self._speedhack_stop = threading.Event()
        # The game may still be launching, so inject in the background and retry
        # until its process exists rather than failing once at start.
        threading.Thread(
            target=self._speedhack_loop, args=(scale,), daemon=True
        ).start()

    def _speedhack_loop(self, scale: float) -> None:
        """Arm the speedhack, then keep it armed for the whole run.

        The loop does not stop at the first success: a game restart gives the
        package a new PID and takes the hook with the old one, so we keep
        checking and re-inject when the agent is gone. Without that watchdog the
        run silently continues at normal speed while the UI still says "Live".
        """
        stop_ev = self._speedhack_stop
        mgr = self._speedhack
        log_info(f"[speedhack] will accelerate '{mgr.package}' x{scale} once the game runs…")
        armed = False
        while (mgr is not None and not self._stop.is_set()
               and stop_ev is not None and not stop_ev.is_set()):
            try:
                if not armed:
                    if mgr.set_scale(scale):
                        armed = True
                        log_success(f"[speedhack] enabled x{scale}")
                elif not mgr.ensure_alive():
                    armed = False       # game gone: fall back to waiting for it
            except Exception as e:
                log_warning(f"[speedhack] retrying: {e}")
            # Wait ~5s before the next check, but stay responsive to stop.
            for _ in range(50):
                if self._stop.is_set() or stop_ev.is_set():
                    return
                time.sleep(0.1)

    def _stop_speedhack(self) -> None:
        ev = self._speedhack_stop
        if ev is not None:
            ev.set()
        self._speedhack_stop = None
        mgr = self._speedhack
        self._speedhack = None
        self._speed_scale = 1.0
        if mgr is None:
            return
        try:
            mgr.detach()
        except Exception as e:
            log_warning(f"[speedhack] error while disabling: {e}")
