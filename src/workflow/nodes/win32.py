"""Win32 nodes: drive a native Windows program's window."""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from src.core.keynames import (
    vk_combo,
    vk_name,
)
from src.workflow.logs import log_info, log_success, log_warning


class Win32Nodes:
    """Window lifecycle, mouse/keyboard and window-state probes."""

    # ── Win32 handlers ─────────────────────────────────────────────────────────

    def _win32_ctrl(self):
        """Return the Win32 controller if this is a Win32 flow, else None."""
        if getattr(self, "_controller", "adb") != "win32":
            log_warning("Win32 nodes only run in Win32 projects (change Controller in Project settings)")
            return None
        return getattr(self.auto, "adb", None)

    def set_win32_path(self, path: str) -> None:
        """Point the project game path (``win32.path``) somewhere else — the
        Runner's Settings override. Read by Launch program nodes on ``project``."""
        value = str(path or "").strip()
        self._win32_cfg["path"] = value
        if isinstance(self.flow, dict):
            win = self.flow.get("win32")
            if not isinstance(win, dict):
                win = self.flow["win32"] = {}
            win["path"] = value

    def _win_launch_path(self, params: Dict[str, Any]) -> str:
        """Resolve the program for win_launch.

        ``pathSrc``:
          - ``project`` — the project game path (Project settings / Runner Settings)
          - ``custom``  — the node's own ``path`` field (text or variable)
          - missing     — legacy: explicit path wins; else fall back to project
        """
        p = params or {}
        src = str(p.get("pathSrc") or "").strip().lower()
        project = str((self._win32_cfg or {}).get("path") or "").strip()
        if src == "project":
            return project
        custom = str(self._resolve_value(p.get("path", "")) or "").strip()
        if src == "custom":
            return custom
        return custom or project

    def _a_win_launch(self, node, p) -> bool:
        """Start a program (exe path + optional args) or focus its window; then
        optionally wait until a matching window title appears and attach to it."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        path = self._win_launch_path(p)
        if not path:
            return self._fail_run(node, "Launch program: no game path specified — select it in "
                                        "Runner Settings → Game (Designer: Project settings / Custom)")
        if not os.path.isfile(path):
            return self._fail_run(node, f"Launch program: game not found at '{path}' — "
                                        "select the correct game path and run again")
        args = str(self._resolve_value(p.get("args", ""))).strip()
        cmd = f'"{path}" {args}'.strip() if args else path
        if self._truthy(p.get("unityBridge", False)):
            try:
                from src.core.win32 import unity_bridge
                port = int((self._win32_cfg or {}).get("bridgePort", unity_bridge.DEFAULT_PORT))
                launched = unity_bridge.launch_injected(path, args, port)
            except Exception as exc:
                launched = {"ok": False, "error": str(exc)}
            if not launched.get("ok"):
                return self._fail_run(node, str(launched.get("error") or "Launch with Unity Bridge failed"))
            ctrl.last_launch_pid = int(launched["pid"])
            log_success(f"▶ Launched with Unity Bridge (PID {ctrl.last_launch_pid})")
        elif not ctrl.launch_app(cmd):
            return False
        window = str(self._resolve_value(p.get("window", ""))).strip()
        wait = float(p.get("wait", 0) or 0)
        # Prefer the explicit title; when it is blank, attach the top-level
        # window created by the process we just launched. This makes an initial
        # Launch program node work without a pre-existing Project target.
        if wait > 0 and (window or getattr(ctrl, "last_launch_pid", None)):
            end = time.time() + wait
            while time.time() < end and not self._stop.is_set():
                self._pause.wait()
                hwnd = (ctrl._find_hwnd(window, "title") if window
                        else ctrl.find_window_by_pid(ctrl.last_launch_pid))
                if hwnd:
                    ctrl.hwnd = hwnd
                    title = ctrl._w[1].GetWindowText(hwnd) or window
                    log_success(f"🪟 Window '{title}' opened and attached")
                    try:
                        self.auto._update_screen_size()
                        if not getattr(self.auto, "capture_running", False):
                            self.auto.start_continuous_capture()
                    except Exception as exc:
                        log_warning(f"Win32 capture is not ready: {exc}")
                    return True
                time.sleep(0.5)
            label = window or f"PID {ctrl.last_launch_pid}"
            log_warning(f"🪟 Window '{label}' not found after {wait:.0f}s")
        return True

    def _a_win_activate(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not ctrl.device:
            ctrl.attach()
        return bool(ctrl.activate())

    def _a_win_close(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.close_window())

    def _a_win_kill(self, node, p) -> bool:
        """Force-terminate the process that owns the target window.

        ``win_close`` only posts WM_CLOSE, which a hung game or a "Save
        changes?" box ignores; this is the Win32 twin of ADB's Stop app.
        Nothing to kill (window already gone) counts as success.
        """
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        tree = self._truthy(p.get("tree", True))
        res = ctrl.kill_process(tree=tree)
        if res is None:
            log_info("☠ target window not found (already closed? — skipping)")
            return True
        if res:
            log_success("☠ target process terminated" + (" (with children)" if tree else ""))
        return bool(res)

    def _a_win_resize(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        w = int(p.get("width", 1280))
        h = int(p.get("height", 720))
        # Missing on nodes saved before these options existed → legacy behaviour
        # (outer window size, top-left kept). New nodes default both on.
        center = self._truthy(p.get("center", False))
        client = self._truthy(p.get("client", False))
        ok = bool(ctrl.resize_window(w, h, center=center, client=client))
        log_info(f"🪟 resize → {w}×{h}{' (client)' if client else ''}"
                 f"{' · centered' if center else ''}")
        return ok

    def _a_win_move(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        x = int(p.get("x", 0))
        y = int(p.get("y", 0))
        ok = bool(ctrl.move_window(x, y))
        log_info(f"🪟 move → ({x}, {y})")
        return ok

    def _a_win_minimize(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.minimize_window())

    def _a_win_maximize(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.maximize_window())

    def _a_win_restore(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.restore_window())

    def _a_win_always_on_top(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        on = self._truthy(p.get("enabled", True))
        ok = bool(ctrl.set_always_on_top(on))
        log_info(f"🪟 always on top → {on}")
        return ok

    def _a_win_set_title(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        title = str(p.get("title", "")).strip()
        if not title:
            return True
        ok = bool(ctrl.set_window_title(title))
        log_info(f"🪟 title → '{title}'")
        return ok

    def _a_win_style(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        style = str(p.get("style", "windowed")).strip()
        ok = bool(ctrl.set_window_style(style))
        log_info(f"🪟 style → {style}")
        return ok

    # ── Win32: extended mouse / keyboard ───────────────────────────────────────

    def _a_win_click(self, node, p) -> bool:
        """Left/right/middle click at coords (or the last found image position)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "click"):
            log_warning("🖱 Win32 backend does not support multiple mouse buttons")
            return False
        x, y = self._pos(p)
        x += int(p.get("offsetX", 0) or 0)
        y += int(p.get("offsetY", 0) or 0)
        button = str(p.get("button", "right")).strip().lower() or "right"
        clicks = 2 if str(p.get("clicks", "1")) == "2" else 1
        ok = bool(ctrl.click(x, y, button=button, click_count=clicks))
        if ok:
            log_info(f"🖱 click {button} ({x}, {y})" + (" ×2" if clicks == 2 else ""))
        return ok

    def _a_win_scroll(self, node, p) -> bool:
        """Mouse wheel at coords. ``direction`` up/down/left/right, ``notches`` count."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "scroll"):
            log_warning("🖱 Win32 backend does not support mouse wheel input")
            return False
        x, y = self._pos(p)
        direction = str(p.get("direction", "down")).strip().lower()
        try:
            notches = max(1, int(p.get("notches", 3) or 3))
        except (TypeError, ValueError):
            notches = 3
        horizontal = direction in ("left", "right")
        signed = notches if direction in ("up", "right") else -notches
        ok = bool(ctrl.scroll(x, y, notches=signed, horizontal=horizontal))
        if ok:
            log_info(f"🖱 scrolled {direction} ×{notches} at ({x}, {y})")
        return ok

    def _a_win_mouse_move(self, node, p) -> bool:
        """Move the pointer without clicking (hover-activated menus)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "move_mouse"):
            log_warning("🖱 Win32 backend does not support mouse movement")
            return False
        x, y = self._pos(p)
        ok = bool(ctrl.move_mouse(x, y))
        if ok:
            log_info(f"🖱 moved pointer → ({x}, {y})")
        return ok

    def _a_win_hotkey(self, node, p) -> bool:
        """Press a key with Ctrl/Shift/Alt/Win modifiers (Ctrl+C, Alt+Enter…)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "press_hotkey"):
            log_warning("⌨ Win32 backend does not support hotkeys")
            return False
        try:
            vk = int(p.get("keycode", 13))
        except (TypeError, ValueError):
            log_warning(f"⌨ win_hotkey: invalid key code '{p.get('keycode')}' — "
                        "select a key from the block's list")
            return False
        mods = {k: self._truthy(p.get(k, False)) for k in ("ctrl", "shift", "alt", "win")}
        ok = bool(ctrl.press_hotkey(vk, **mods))
        if ok:
            # Name the key, not its code: "Ctrl+Shift+A", never "Ctrl+Shift+VK65".
            log_info(f"⌨ {vk_combo(vk, **mods)}")
        return ok

    def _a_win_key(self, node, p) -> bool:
        """Press / hold down / release a Windows virtual key on the target.

        ``mode``: ``press`` (down → ``hold`` ms → up) · ``down`` (stays held
        across later blocks until a ``up`` — walking) · ``up``. Keys still held
        when the run stops are released by :meth:`stop`."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        try:
            vk = int(p.get("keycode", 13))
        except (TypeError, ValueError):
            log_warning(f"⌨ win_key: invalid key code '{p.get('keycode')}' — "
                        "select a key from the block's list")
            return False
        mode = str(p.get("mode", "press") or "press").strip().lower()
        hold = self._resolve_count(p.get("hold", 80), default=80)
        ok = bool(ctrl.press_key(vk, hold_ms=hold, action=mode))
        if ok:
            what = {"down": "held", "up": "released"}.get(mode, f"pressed for {hold}ms")
            # vk_name() falls back to "VK{n}" for codes the table doesn't cover —
            # still a code, but at least a recognisable one, and the user has no
            # other clue which key fired.
            log_info(f"⌨ {vk_name(vk)} {what}")
        return ok

    def _a_win_info(self, node, p) -> bool:
        """Read a target-window property into a variable (Win32's device_info)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        name = str(p.get("name", "")).strip()
        prop = str(p.get("prop", "width")).strip().lower()
        info = ctrl.window_info() if hasattr(ctrl, "window_info") else {}
        val: Any = info.get(prop, "")
        if isinstance(val, bool):
            val = "true" if val else "false"
        pat = str(self._resolve_value(p.get("pattern", "")) or "").strip()
        if pat:
            extracted = self._apply_pattern(val, pat, p.get("group", 1))
            val = "" if extracted is None else extracted
        if name:
            self._set_var(name, val)
            log_info(f"🪟 {name} = {self._vars[name]!r} ({prop})")
        return True

    def _c_win_window(self, ntype: str, params: Dict) -> bool:
        """win_if_window / win_wait_window: state of the TARGET window.

        ``state``: ``exists`` (still alive — crash detection) · ``foreground``
        (is the active window) · ``minimized`` · ``size`` (client area is
        ``width``×``height`` within ``tolerance`` px — the space captures and
        templates use). ``win_wait_window`` polls until the state holds or
        ``timeout`` runs out.
        """
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        state = str(params.get("state", "exists")).strip().lower()
        negate = self._truthy(params.get("negate", False))
        want_w = self._resolve_count(params.get("width", 0))
        want_h = self._resolve_count(params.get("height", 0))
        tol = self._resolve_count(params.get("tolerance", 0))
        seen = {"w": 0, "h": 0}

        def probe() -> bool:
            try:
                if state == "foreground":
                    return bool(ctrl.window_exists()) and bool(ctrl.is_foreground())
                if state == "minimized":
                    return bool(ctrl.window_exists()) and bool(ctrl.is_minimized())
                if state == "size":
                    if not ctrl.window_exists():
                        return False
                    seen["w"], seen["h"] = ctrl.get_screen_size()
                    return abs(seen["w"] - want_w) <= tol and abs(seen["h"] - want_h) <= tol
                return bool(ctrl.window_exists())
            except Exception as exc:
                log_warning(f"🪟 window check failed: {exc}")
                return False

        what = (f"client {want_w}×{want_h}" + (f"±{tol}" if tol else "")) if state == "size" else state
        now = lambda: f" (current {seen['w']}×{seen['h']})" if state == "size" else ""  # noqa: E731
        if ntype == "win_if_window":
            ok = probe()
            log_info(f"🪟 window {what} → {'yes' if ok else 'no'}{now()}")
            return ok != negate
        end = time.time() + max(0.0, float(params.get("timeout", 30) or 0))
        while not self._stop.is_set():
            self._pause.wait()
            if probe() != negate:
                log_info(f"🪟 window {what}{' (negated)' if negate else ''} — ready{now()}")
                return True
            if time.time() >= end:
                log_warning(f"🪟 timed out waiting for window {what}{now()}")
                return False
            time.sleep(0.25)
        return False
