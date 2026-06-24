"""PyWebView entry-point and JS API bridge for game automation."""
from __future__ import annotations

import datetime
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import webview

from src.game_core.base_game import BaseGameAutomation
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class AutomationAPI:
    """Methods on this class are exposed to JavaScript via pywebview.api.*"""

    def __init__(self, automation: BaseGameAutomation, title: str) -> None:
        self.automation = automation
        self.title = title
        self._window: Optional[webview.Window] = None
        self._log_buffer: List[Dict] = []
        self._is_running = False
        self._is_paused = False
        self._bg_running = False
        self._single_thread: Optional[threading.Thread] = None
        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None
        self._closing = False
        self._auto_thread: Optional[threading.Thread] = None

    # ── Setup (called after window is created) ───────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log)
        a = self.automation
        a.register_callback("on_start",  lambda: self._on_auto_start())
        a.register_callback("on_stop",   lambda: self._on_auto_stop())
        a.register_callback("on_activity_start",
            lambda act: self._push("activity_update", {
                "id": act.id, "status": "running",
            }))
        a.register_callback("on_activity_complete",
            lambda act, ok: self._push("activity_update", {
                "id": act.id,
                "status": "completed" if ok else "failed",
            }))
        a.register_callback("on_activity_failed",
            lambda act, _err: self._push("activity_update", {
                "id": act.id, "status": "failed",
            }))
        a.register_callback("on_status_change",
            lambda s: self._sync_pause(bool(s.get("paused", False))))
        # Kick device refresh
        threading.Thread(target=self._device_worker, daemon=True).start()
        threading.Thread(target=self._device_poll, daemon=True).start()

    def _on_auto_start(self) -> None:
        self._is_running = True
        self._is_paused = False
        self._push_running()

    def _on_auto_stop(self) -> None:
        # on_stop fires only on an explicit stop() (which tears down background
        # too), so clear the background flag here as well.
        self._is_running = False
        self._is_paused = False
        self._bg_running = False
        self._push_running()

    def _sync_pause(self, paused: bool) -> None:
        self._is_paused = paused
        self._push_running()

    def _push_running(self) -> None:
        self._push("running_state", {
            "running": self._is_running,
            "paused": self._is_paused,
            "bgRunning": self._bg_running,
        })

    # ── Log subscriber ───────────────────────────────────────────────────────

    def _on_log(self, level: str, message: str) -> None:
        bucket = {
            "info": "info", "success": "success", "warning": "warning",
            "error": "error",
        }.get(level, "info")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {"ts": ts, "level": bucket, "msg": message}
        self._log_buffer.append(entry)
        if len(self._log_buffer) > 2000:
            self._log_buffer = self._log_buffer[-2000:]
        self._push("log", entry)

    # ── JS push helper ───────────────────────────────────────────────────────

    def _push(self, event_type: str, data: dict) -> None:
        if self._window is None or self._closing:
            return
        try:
            payload = json.dumps({"type": event_type, "data": data},
                                  ensure_ascii=False)
            # escape backticks so the template literal is safe
            safe = payload.replace("\\", "\\\\").replace("`", "\\`")
            self._window.evaluate_js(f"window.__recv(`{safe}`)")
        except Exception:
            pass

    # ── Public API ───────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Initial state hydration called by JS on load."""
        acts = self.automation.get_activities()
        return {
            "title":       self.title,
            "activities":  [self._act_dict(a) for a in acts],
            "log":         self._log_buffer[-300:],
            "running":     self._is_running,
            "paused":      self._is_paused,
            "bgRunning":   self._bg_running,
            "debugMode":   bool(self.automation.get_ui_setting(
                               "debug_mode", self.automation.is_debug)),
            "debugFail":   bool(self.automation.get_ui_setting(
                               "debug_fail_mode", self.automation.is_debug_fail)),
            "connectedSerial": self._connected_serial,
            "selectedSerial":  self._selected_serial,
        }

    def _act_dict(self, act) -> dict:
        return {
            "id":             act.id,
            "name":           act.name,
            "enabled":        act.enabled,
            "status":         act.status.value,
            "background":     act.background,
            "pollInterval":   act.poll_interval,
            "customSettings": act.custom_settings or [],
            "customValues":   act.custom_values or {},
        }

    def start(self) -> bool:
        if self._is_running:
            return False
        try:
            self.automation.reset_activities()
            # Reset all seq activities to pending in UI
            for act in self.automation.get_activities():
                if not act.background:
                    self._push("activity_update",
                               {"id": act.id, "status": "pending"})
            self._auto_thread = threading.Thread(
                target=self.automation.start, daemon=True)
            self._auto_thread.start()
            self._is_running = True
            self._is_paused = False
            self._push_running()
            return True
        except Exception as e:
            log_error(f"Start error: {e}")
            return False

    def stop(self) -> bool:
        # Unified stop: ends the sequential queue AND background workers.
        # Available whenever a session is active (sequential or background).
        if not self._is_running and not self._bg_running:
            return False
        try:
            self.automation.stop()  # fires on_stop -> clears flags + pushes
            return True
        except Exception as e:
            log_error(f"Stop error: {e}")
            return False

    def pause(self) -> dict:
        try:
            if self._is_paused:
                self.automation.resume()
                self._is_paused = False
            else:
                self.automation.pause()
                self._is_paused = True
            self._push_running()
            return {"paused": self._is_paused}
        except Exception as e:
            log_error(f"Pause error: {e}")
            return {"paused": self._is_paused}

    def toggle_background(self, enabled: bool) -> bool:
        if bool(enabled) == self._bg_running:
            return True
        try:
            self.automation.set_background_enabled(bool(enabled))
            self._bg_running = bool(enabled)
            if enabled:
                log_success("Tác vụ nền đã bắt đầu")
            else:
                log_info("Tác vụ nền đã dừng")
            self._push_running()
            return True
        except Exception as e:
            log_error(f"Background toggle error: {e}")
            self._push_running()
            return False

    def toggle_activity(self, activity_id: str, enabled: bool) -> bool:
        try:
            self.automation.set_activity_enabled(activity_id, bool(enabled))
            for act in self.automation.get_activities():
                if act.id == activity_id:
                    act.enabled = bool(enabled)
            return True
        except Exception as e:
            log_error(f"Toggle error: {e}")
            return False

    def run_single(self, activity_id: str) -> bool:
        if self._is_running:
            log_error("Đang chạy tự động, không thể chạy đơn.")
            return False
        if self._single_thread and self._single_thread.is_alive():
            log_error("Đang có tác vụ đơn chạy.")
            return False

        def _runner():
            self._push("single_start", {"id": activity_id})
            try:
                self.automation.run_single_activity(activity_id)
            except Exception as e:
                log_error(f"Single run error: {e}")
            finally:
                self._push("single_done", {"id": activity_id})

        self._single_thread = threading.Thread(target=_runner, daemon=True)
        self._single_thread.start()
        return True

    def set_interval(self, activity_id: str, interval: float) -> bool:
        try:
            return bool(self.automation.set_activity_poll_interval(
                activity_id, float(interval)))
        except Exception as e:
            log_error(f"Interval error: {e}")
            return False

    def set_custom(self, activity_id: str, key: str, value: float) -> bool:
        try:
            return bool(self.automation.set_custom_setting(
                activity_id, key, float(value)))
        except Exception as e:
            log_error(f"Custom setting error: {e}")
            return False

    def set_debug(self, mode: bool, fail: bool) -> bool:
        try:
            self.automation.set_debug_mode(bool(mode), bool(fail))
            self.automation.set_ui_setting("debug_mode", bool(mode))
            self.automation.set_ui_setting("debug_fail_mode", bool(fail))
            return True
        except Exception as e:
            log_error(f"Debug error: {e}")
            return False

    def refresh_devices(self) -> None:
        threading.Thread(target=self._device_worker, daemon=True).start()

    def select_device(self, serial: str) -> bool:
        try:
            self._selected_serial = serial
            self.automation.adb.device_id = serial
            threading.Thread(
                target=self._connect_device, args=(serial,), daemon=True).start()
            return True
        except Exception as e:
            log_error(f"Select device error: {e}")
            return False

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        log_info("Đã xoá nhật ký")
        return True

    # ── Device helpers ───────────────────────────────────────────────────────

    def _connect_device(self, serial: str) -> None:
        try:
            self.automation.adb.select_device(serial)
            self.automation.adb.quick_refresh()
            s = self.automation.adb.get_status_summary()
            self._connected_serial = s.get("device_id") if s.get("connected") else None
            self._push("device_status", {
                "connected":   bool(s.get("connected")),
                "serial":      s.get("device_id"),
                "name":        s.get("device_name") or serial,
                "current_app": s.get("app_package"),
                "app_name":    s.get("app_name"),
            })
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _device_worker(self) -> None:
        with self._device_lock:
            try:
                devices = self.automation.adb.list_devices() or []
                if devices and not self._selected_serial:
                    first = devices[0].get("serial")
                    if first:
                        self._selected_serial = first
                        self.automation.adb.device_id = first
                        self.automation.adb.select_device(first)
                elif devices and self._selected_serial:
                    if (self.automation.adb.device is None
                            or self.automation.adb.device_id != self._selected_serial):
                        self.automation.adb.select_device(self._selected_serial)
                elif not devices:
                    try:
                        self.automation.adb.check_adb_connection()
                    except Exception:
                        pass
                self.automation.adb.quick_refresh()
                s = self.automation.adb.get_status_summary()
                self._connected_serial = s.get("device_id") if s.get("connected") else None
                self._push("devices_update", {
                    "devices":     devices,
                    "connected":   bool(s.get("connected")),
                    "serial":      s.get("device_id"),
                    "name":        s.get("device_name") or s.get("device_id") or "",
                    "current_app": s.get("app_package"),
                    "app_name":    s.get("app_name"),
                })
            except Exception:
                self._push("devices_update", {
                    "devices": [], "connected": False, "serial": None, "name": "",
                })

    def _device_poll(self) -> None:
        while not self._closing:
            time.sleep(5)
            if not self._closing:
                self._device_worker()

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        # ``_closing`` is set first so any callback fired during teardown (e.g.
        # ``on_stop``) finds ``_push`` a no-op and never touches the dying
        # window. ``stop()`` does the full, idempotent teardown — capture
        # thread, background workers, executor, visualizer (and speedhack
        # reset, for games that mix it in) — so we no longer poke internals.
        self._closing = True
        remove_log_subscriber(self._on_log)
        try:
            self.automation.stop()
        except Exception:
            pass


# ── Entry points ──────────────────────────────────────────────────────────────

def create_pywebview_window(game_class, title: str = "Game Automation") -> webview.Window:
    """Create the automation window without starting the event loop.

    Use this when already inside a running webview session (e.g. from a
    launcher window).  Call ``webview.start()`` separately, or let an
    existing ``webview.start()`` manage the new window.
    """
    game = game_class()
    api = AutomationAPI(game, title)

    html_path = os.path.join(_WEB_DIR, "index.html")
    url = f"file:///{html_path.replace(os.sep, '/')}"

    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=420,
        height=860,
        resizable=False,
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    window.events.closed += lambda: api._close()
    return window


def run_with_pywebview(game_class, title: str = "Game Automation") -> None:
    """Create a window and start the event loop (standalone entry point)."""
    create_pywebview_window(game_class, title)
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    print("Import and call run_with_pywebview(GameClass, title).")
