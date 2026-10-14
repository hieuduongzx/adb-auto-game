"""ADB device discovery, selection and the footer's connection state."""
from __future__ import annotations

import threading
import time

from src.core.adb import lifecycle
from src.utils import (
    log_error,
    log_warning,
)


class DeviceMixin:
    """ADB device discovery, selection and the footer's connection state."""

    # ── Devices ───────────────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        self._kick_device_scan()

    def select_device(self, serial: str) -> bool:
        if not self._adb_workflow():
            return False
        try:
            self._selected_serial = serial
            self.engine.auto.adb.device = None
            self.engine.auto.adb.device_id = serial
            self._connected_serial = None
            self.engine.set_selected_device(serial)
            threading.Thread(target=self._connect_device, args=(serial,), daemon=True).start()
            return True
        except Exception as e:
            log_error(f"Select device error: {e}")
            return False

    def _connect_device(self, serial: str) -> None:
        with self._device_lock:
            self._connect_device_locked(serial)

    def _connect_device_locked(self, serial: str) -> None:
        try:
            if serial != self._selected_serial:
                return
            self.engine.auto.adb.select_device(serial)
            self.engine.auto.adb.quick_refresh()
            if serial != self._selected_serial:
                return
            s = self.engine.auto.adb.get_status_summary()
            self._connected_serial = s.get("device_id") if s.get("connected") else None
            # The engine's "selected device" follows the live handle, not the
            # request: emulator nodes targeting `selected` must resolve to a
            # device that is actually connected.
            self.engine.set_selected_device(self._connected_serial or self._selected_serial)
            self._push("device_status", {
                "connected": bool(s.get("connected")),
                "serial": s.get("device_id"),
                "name": s.get("device_name") or serial,
            })
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _adb_workflow(self) -> bool:
        """True only when the loaded workflow drives a device over ADB.

        Everything below reaches the shared ADB server (``adb devices``, server
        start-up, emulator port scanning), so a Win32 project must not call any
        of it — that was the "why is my win32 game checking ADB" bug."""
        return self._controller() == "adb"

    def _ensure_adb_lease(self) -> None:
        """Claim this process as a live ADB client, once, on first need.

        Held so a sibling Macro2k app closing down doesn't ``kill-server`` out
        from under an in-flight ADB run. A Win32-only Runner never calls this,
        so it neither blocks nor triggers that teardown (see lifecycle)."""
        if self._adb_lease:
            return
        self._adb_lease = lifecycle.acquire_adb_lease("runner")

    def _kick_device_scan(self) -> None:
        """One device scan in the background, ADB workflows only."""
        if self._adb_workflow():
            self._ensure_adb_lease()
            threading.Thread(target=self._device_worker, args=(True,), daemon=True).start()
        else:
            # Clear any device state left over from an ADB project so the UI
            # doesn't keep a stale "Connecting…" around.
            self._selected_serial = None
            self._connected_serial = None
            self._push("devices_update", {"devices": [], "connected": False,
                                          "serial": None, "name": ""})

    def _device_worker(self, force_scan: bool = False) -> None:
        # The one place ADB is actually reached — hold the lease for as long as
        # that's true, however this got called.
        self._ensure_adb_lease()
        adb = self.engine.auto.adb
        with self._device_lock:
            try:
                if force_scan:
                    try:
                        adb.scan_all_devices()
                    except Exception as exc:
                        log_warning(f"ADB port scan failed: {exc}")
                devices = adb.list_devices(include_app=False) or []
                if devices and not self._selected_serial:
                    first = devices[0].get("serial")
                    if first:
                        self._selected_serial = first
                        adb.device_id = first
                        adb.select_device(first)
                elif devices and self._selected_serial:
                    if adb.device is None or adb.device_id != self._selected_serial:
                        adb.select_device(self._selected_serial)
                adb.quick_refresh()
                s = adb.get_status_summary(include_app=False)
                self._connected_serial = s.get("device_id") if s.get("connected") else None
                self.engine.set_selected_device(self._connected_serial or self._selected_serial)
                self._push("devices_update", {
                    "devices": devices,
                    "connected": bool(s.get("connected")),
                    "serial": s.get("device_id"),
                    "name": s.get("device_name") or s.get("device_id") or "",
                })
            except Exception as exc:
                log_warning(f"ADB device refresh failed: {exc}")
                adb.mark_disconnected("device refresh failed")
                self._connected_serial = None
                self.engine.set_selected_device(self._selected_serial)
                self._push("devices_update", {"devices": [], "connected": False,
                                              "serial": None, "name": ""})

    def _device_poll(self) -> None:
        while not self._closing:
            time.sleep(5)
            if not self._closing and self._adb_workflow():
                now = time.monotonic()
                deep = now - self._last_deep_scan >= self._deep_scan_interval
                if deep:
                    self._last_deep_scan = now
                self._device_worker(force_scan=deep)
