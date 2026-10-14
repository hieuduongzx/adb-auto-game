"""Device list, connection, device info and the Unity Bridge."""
from __future__ import annotations

import threading
import time
from typing import Optional

import webview

from src.core.adb import device_info
from src.core.adb.auto.scrcpy_capture import (
    warm_scrcpy_source,
)
from src.utils import (
    log_error,
    log_info,
    log_success,
    log_warning,
)
from designer.common import (
    _ts,
)


class DeviceMixin:
    """Device list, connection, device info and the Unity Bridge."""

    # ── Unity Bridge (in-game plugin for the unity_bridge input mode) ──────────

    @staticmethod
    def _unity_bridge_port(cfg: Optional[dict]) -> int:
        from src.core.win32 import unity_bridge
        try:
            return int((cfg or {}).get("bridgePort") or unity_bridge.DEFAULT_PORT)
        except (TypeError, ValueError):
            return unity_bridge.DEFAULT_PORT

    @staticmethod
    def _unity_bridge_exe(cfg: Optional[dict]) -> str:
        """Executable of the project's target window, or "" when it isn't open."""
        cfg = cfg or {}
        if not str(cfg.get("window", "")).strip():
            return ""
        try:
            import win32process
            from src.core.win32 import Win32Controller
            from src.core.win32.automation import process_exe_path
            ctrl = Win32Controller(cfg)
            if not ctrl.attach():
                return ""
            pid = win32process.GetWindowThreadProcessId(ctrl.hwnd)[1]
            return process_exe_path(pid)
        except Exception:
            return ""

    def unity_bridge_status(self, cfg: Optional[dict] = None, exe: str = "") -> dict:
        """Inspect the target game (from ``exe`` or the project's window) and
        ping the bridge — drives the deploy prompt in the designer."""
        try:
            from src.core.win32 import unity_bridge
            # Running game first; else the project game path (Project settings).
            exe = (exe or self._unity_bridge_exe(cfg)
                   or str((cfg or {}).get("path") or "").strip())
            return unity_bridge.status(exe, self._unity_bridge_port(cfg))
        except Exception as exc:
            log_warning(f"Unity Bridge status error: {exc}")
            return {"exe": exe, "problems": [str(exc)], "bridgeRunning": False}

    def unity_bridge_deploy(self, exe: str) -> dict:
        """Inject the bridge plugin into the running game (see unity_bridge.deploy)."""
        try:
            from src.core.win32 import unity_bridge
            result = unity_bridge.deploy(exe)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        if not result.get("ok"):
            log_warning(f"Unity Bridge deploy failed: {result.get('error')}")
        return result

    # ── Device info (mirrors DevScope) ────────────────────────────────────────

    def refresh_info(self) -> None:
        threading.Thread(target=self._info_worker, daemon=True).start()

    def _info_worker(self) -> None:
        with self._info_lock:
            if self._info_in_flight:
                return
            self._info_in_flight = True
        try:
            ui = device_info.collect_device_info(
                self.controller.device,
                app_name_resolver=self.controller.get_app_name,
            )
            self._push("device_info", ui)
        except Exception as exc:
            log_warning(f"Device info error: {exc}")
        finally:
            with self._info_lock:
                self._info_in_flight = False

    def copy_info(self) -> bool:
        self._push("copy_device_info", {})
        return True

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        log_info("Log cleared")
        return True

    def save_log(self) -> str:
        """Save the full backend log buffer to a .txt file (native save dialog).

        Returns the written path, or "" when the buffer is empty / the dialog
        was cancelled / the write failed.
        """
        if not self._log_buffer:
            return ""
        lines = [f"{e.get('ts', '')} [{e.get('level', 'info').upper():7s}] {e.get('msg', '')}"
                 for e in self._log_buffer]
        default = f"workflow_log_{_ts()}.txt"
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=self._scope_out(), save_filename=default,
                    file_types=("Text (*.txt)", "All files (*.*)"))
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception:
            path = None
        if not path:
            return ""
        if not path.lower().endswith(".txt"):
            path += ".txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            return ""
        return path

    # ── Device ops ───────────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        threading.Thread(target=self._device_worker, daemon=True).start()

    def select_device(self, serial: str) -> bool:
        try:
            self._selected_serial = serial or None
            self.controller.device = None
            self.controller.device_id = serial or None
            self._connected_serial = None
            self._sync_engine_device()
            threading.Thread(target=self._connect_device, args=(serial,), daemon=True).start()
            return True
        except Exception as e:
            log_error(f"Select device error: {e}")
            return False

    def _sync_engine_device(self) -> None:
        """Tell the engine which device the picker has selected.

        Emulator nodes targeting ``selected`` resolve against it, so a test run
        resizes/kills the instance the user is looking at rather than whichever
        one the flow launched last. ``_connected_serial`` wins over
        ``_selected_serial``: the worker clears the former when a device drops
        off ``adb devices`` but never the latter, so the raw field can point at
        an emulator that is already gone.
        """
        if self._engine is not None:
            self._engine.set_selected_device(self._connected_serial or self._selected_serial)

    def scan_ports(self) -> None:
        threading.Thread(target=self._scan_ports_worker, daemon=True).start()

    def restart_adb(self) -> None:
        threading.Thread(target=self._restart_adb_worker, daemon=True).start()

    def _connect_device(self, serial: str) -> None:
        with self._device_lock:
            self._connect_device_locked(serial)

    def _connect_device_locked(self, serial: str) -> None:
        try:
            if serial != self._selected_serial:
                return
            if not serial:
                self._connected_serial = None
                self._push("device_status", {"connected": False})
                return
            self.controller.select_device(serial)
            self.controller.quick_refresh()
            if serial != self._selected_serial:
                return
            s = self.controller.get_status_summary()
            self._connected_serial = s.get("device_id") if s.get("connected") else None
            if s.get("connected"):
                self._device_lost_announced = False
            self._push("device_status", {
                "connected": bool(s.get("connected")),
                "serial": s.get("device_id"),
                "name": s.get("device_name") or serial,
            })
            self._sync_engine_device()
            self._warm_capture_async()
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _warm_capture_async(self) -> None:
        """Pre-start the scrcpy frame source for the connected device.

        Runs right after a device connects (not on Play), so by the time the
        user starts a test run the client already has frames and the first
        block executes immediately instead of waiting out the scrcpy warm-up.
        """
        serial = self._connected_serial or self._selected_serial
        if not serial:
            return
        threading.Thread(target=warm_scrcpy_source, args=(serial,), daemon=True).start()

    def _device_worker(self, deep: bool = False) -> None:
        """Refresh the device list. ``deep`` also probes known emulator ports
        (slower) — used on a 30s cadence when nothing is connected so a new
        emulator instance is found without a manual Scan ports click."""
        with self._device_lock:
            try:
                self.scanner.ensure_adb_server_running()
                devices = self.controller.online_devices()
                items = self.scanner.unique_devices(devices)
                if deep:
                    try:
                        found = self.scanner.scan_all(stop_on_first=False) or []
                        if found:
                            log_info(f"Auto-scan found {len(found)} device(s)")
                    except Exception as exc:
                        log_warning(f"Auto port scan failed: {exc}")
                    devices = self.controller.online_devices()
                    items = self.scanner.unique_devices(devices)
                if items and not self._selected_serial:
                    first = items[0].get("serial")
                    if first:
                        self._selected_serial = first
                        self.controller.select_device(first)
                elif items and self._selected_serial:
                    if (self.controller.device is None
                            or self.controller.device_id != self._selected_serial):
                        self.controller.select_device(self._selected_serial)
                self._push("devices_update", {"devices": items})
                serials = {d.serial for d in devices}
                # Selected emulator closed → clear handle + stop live capture.
                wanted = self._selected_serial or self._connected_serial
                if wanted and wanted not in serials:
                    self.controller.mark_disconnected("no longer in adb devices")
                    self._connected_serial = None
                    if self._auto_refresh_enabled and self._capture_kind != "win32":
                        self._on_device_lost(f"{wanted} not found")
                    else:
                        self._push("device_status", {
                            "connected": False, "serial": None, "name": "",
                        })
                elif items:
                    s = self.controller.get_status_summary(include_app=False)
                    self._connected_serial = s.get("device_id") if s.get("connected") else None
                    if s.get("connected"):
                        self._device_lost_announced = False
                    self._push("device_status", {
                        "connected": bool(s.get("connected")),
                        "serial": s.get("device_id"),
                        "name": s.get("device_name") or "",
                    })
                    if self._connected_serial:
                        self._warm_capture_async()
                else:
                    # Empty device list — mirror disconnected state to the UI.
                    if self.controller.device is not None or self._connected_serial:
                        self.controller.mark_disconnected("no devices left")
                        self._connected_serial = None
                        if self._auto_refresh_enabled and self._capture_kind != "win32":
                            self._on_device_lost("no devices")
                        else:
                            self._push("device_status", {
                                "connected": False, "serial": None, "name": "",
                            })
                # After the branches, so a device that just dropped is reflected
                # rather than the serial it had a moment ago.
                self._sync_engine_device()
            except Exception as exc:
                log_warning(f"ADB device refresh failed: {exc}")
                self.controller.mark_disconnected("device refresh failed")
                self._connected_serial = None
                self._push("devices_update", {"devices": []})
                self._push("device_status", {
                    "connected": False, "serial": None, "name": "",
                })
                self._sync_engine_device()

    def _device_poll(self) -> None:
        """Light refresh every 5s; when no device is connected, also deep-scan
        emulator ports about every 30s so a newly started instance is found.

        Parked for the whole time a Win32 project is open: the preview captures
        a window, so polling the ADB server would just be noise (and would start
        it if it wasn't running)."""
        while not self._closing:
            time.sleep(5)
            if self._closing:
                break
            if self._capture_kind == "win32":
                continue
            deep = False
            now = time.monotonic()
            if now - self._last_deep_scan >= self._deep_scan_interval:
                deep = True
                self._last_deep_scan = now
            self._device_worker(deep=deep)

    def _scan_ports_worker(self) -> None:
        log_info("Port scanning all known emulator ranges...")
        try:
            found = self.scanner.scan_all(stop_on_first=False)
        except Exception as exc:
            log_error(f"Scan failed: {exc}")
            return
        log_success(f"Found {len(found)} device(s)") if found else log_warning("No devices found")
        self._device_worker()

    def _restart_adb_worker(self) -> None:
        log_info("Restarting ADB server...")
        if self.scanner.restart_adb_server():
            log_success("ADB server restarted")
        else:
            log_error("Failed to restart ADB server")
        self._device_worker()
