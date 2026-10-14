"""Live Preview, the DevScope tool panel, crops, matching and OCR."""
from __future__ import annotations

import base64
import os
import threading
import time
from typing import List, Optional

import cv2
import numpy as np

import webview

from src.core.adb import ADBController, device_info
from src.core.adb.auto.scrcpy_capture import (
    capture_screen as capture_screen_frame,
    stop_scrcpy_sources,
)
from src.core.adb.auto.ocr import KNOWN_BACKENDS, OCR_MODEL_LABELS, OCRReader
from src.utils import (
    log_success,
    log_warning,
)
from designer.common import (
    _PROJECT_ROOT,
    _sanitize_name,
    _ts,
)


class PreviewMixin:
    """Live Preview, the DevScope tool panel, crops, matching and OCR."""

    # ── Live Preview capture (mirrors DevScope) ─────────────────────────────
    # Only the Preview tab drives these; auto-refresh is OFF by default and the
    # JS side turns it on/off when the tab is shown/hidden, so captures only run
    # while the user is actually looking at the mirror.

    def _push_frame(self, bgr: np.ndarray) -> None:
        """Send a JPEG screenshot frame to JS as a data URL.

        Always report the frame's own width/height so the Preview box uses the
        real capture size (ADB screencap native resolution), not a stale value.
        """
        if self._window is None or self._closing:
            return
        try:
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                return
            h, w = bgr.shape[:2]
            self._screen_w = int(w)
            self._screen_h = int(h)
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            self._window.evaluate_js(
                f'window.__recvFrame("data:image/jpeg;base64,{b64}",{w},{h})')
        except Exception:
            pass

    def set_capture_source(self, kind: str = "adb", cfg: Optional[dict] = None) -> bool:
        """Point the Preview tab's capture at ADB or a Win32 window.

        Called from the designer whenever the project's controller / target
        window changes, so preview + crop + colour-inspect all grab from the
        same source the workflow will run against."""
        self._capture_kind = "win32" if str(kind) == "win32" else "adb"
        if self._capture_kind == "win32":
            try:
                from src.core.win32 import Win32Controller
                if self._win32 is None:
                    self._win32 = Win32Controller(cfg or {})
                else:
                    self._win32.configure(cfg or {})
            except Exception as exc:
                log_warning(f"Win32 capture source error: {exc}")
                return False
        return True

    def capture_now(self) -> dict:
        """Capture one frame synchronously and return it as a data URL.

        Context-menu node previews need a frame immediately before they build
        an overlay; the normal ``capture()`` API is deliberately fire-and-forget
        and arrives later through ``__recvFrame``. This bounded one-shot avoids
        timing guesses and doesn't alter the auto-refresh loop.
        """
        try:
            if self._capture_kind == "win32":
                if self._win32 is None:
                    return {"error": "No Win32 window set"}
                img = self._win32.capture_frame()
            else:
                if self.controller.device is None:
                    return {"error": "No device selected"}
                img = capture_screen_frame(self.controller)
            if img is None:
                return {"error": "Failed to capture screen"}
            h, w = img.shape[:2]
            self._screen = img
            self._screen_w = w
            self._screen_h = h
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                return {"error": "Failed to encode screen"}
            data = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
            return {"dataUrl": data, "w": w, "h": h}
        except Exception as exc:
            return {"error": str(exc)}

    def capture(self) -> bool:
        if self._capture_kind == "win32":
            if self._win32 is None:
                self._push("capture_failed", {"error": "No Win32 window set"})
                return False
        elif self.controller.device is None:
            # Device already gone — stop the live preview loop quietly. Do not
            # push capture_failed every tick (that was flooding the UI/log).
            if self._auto_refresh_enabled:
                self._on_device_lost("No device selected")
            return False
        with self._capture_lock:
            if self._capture_in_flight:
                return False
            self._capture_in_flight = True
        threading.Thread(target=self._capture_worker, daemon=True).start()
        return True

    def _on_device_lost(self, reason: str = "") -> None:
        """Stop live capture and tell the UI the device is gone — once."""
        if getattr(self, "_device_lost_announced", False) and not self._auto_refresh_enabled:
            # Already stopped + announced; stay quiet until a reconnect.
            return
        self._device_lost_announced = True
        was_refreshing = self._auto_refresh_enabled
        self._auto_refresh_enabled = False
        # Drop the stale ADB handle if capture hasn't already.
        try:
            self.controller.mark_disconnected(reason)
        except Exception:
            self.controller.device = None
        self._connected_serial = None
        try:
            stop_scrcpy_sources()
        except Exception:
            pass
        msg = reason or "Device not found"
        log_warning(f"Preview stopped — device lost: {msg}")
        self._push("device_status", {"connected": False, "serial": None, "name": ""})
        if was_refreshing:
            self._push("capture_failed", {"error": f"Device disconnected — capture stopped ({msg})"})

    def _capture_worker(self) -> None:
        try:
            if self._capture_kind == "win32":
                if not self._win32.device:
                    self._win32.attach()
                if not self._win32.device:
                    self._push("capture_failed", {"error": "Target Win32 window not found"})
                    return
                img = self._win32.capture_frame()
            else:
                img = capture_screen_frame(self.controller)
                # Capture path cleared the handle on "device not found" — stop
                # the preview loop so we don't keep spawning workers.
                if img is None and self.controller.device is None:
                    self._on_device_lost("device not found")
                    return
            if img is None:
                self._push("capture_failed", {"error": "Failed to capture screen"})
                return
            # Successful frame — allow a future disconnect to re-announce.
            self._device_lost_announced = False
            h, w = img.shape[:2]
            self._screen = img
            self._screen_w = w
            self._screen_h = h
            self._push_frame(img)
        except Exception as exc:
            if self._capture_kind != "win32" and (
                self.controller.device is None
                or ADBController.is_device_gone_error(exc)
            ):
                try:
                    self.controller.mark_disconnected(str(exc))
                except Exception:
                    self.controller.device = None
                self._on_device_lost(str(exc))
                return
            self._push("capture_failed", {"error": str(exc)})
        finally:
            with self._capture_lock:
                self._capture_in_flight = False

    def _auto_refresh_loop(self) -> None:
        while not self._closing:
            time.sleep(0.1)
            if not self._auto_refresh_enabled or self._closing:
                continue
            # Bail early when ADB already dropped the device (e.g. another
            # thread marked it disconnected mid-run).
            if self._capture_kind != "win32" and self.controller.device is None:
                self._on_device_lost("No device selected")
                continue
            now = time.monotonic()
            period = 1.0 / max(0.1, self._refresh_hz)
            if now - self._last_auto_capture >= period:
                self._last_auto_capture = now
                self.capture()

    def set_auto_refresh(self, enabled: bool) -> bool:
        self._auto_refresh_enabled = bool(enabled)
        self._last_auto_capture = time.monotonic()
        if enabled:
            # Fresh Preview session — allow disconnect messaging again.
            self._device_lost_announced = False
        return True

    def set_refresh_hz(self, hz: float) -> bool:
        self._refresh_hz = max(0.2, min(30.0, float(hz)))
        return True

    def _win32_ready(self):
        """The lazily-built Win32 controller, attached — or ``None``.

        Shared by every Preview-tab action tester (tap / swipe / long press /
        keys / text / click / wheel) so they all route to the same window the
        preview is capturing.
        """
        if self._win32 is None:
            return None
        if not self._win32.device:
            self._win32.attach()
        return self._win32 if self._win32.device else None

    def tap(self, x: int, y: int) -> bool:
        # Preview right-click tap goes to whatever the preview captures from:
        # the Win32 target window in a Win32 project, else the ADB device.
        if self._capture_kind == "win32":
            ctrl = self._win32_ready()
            if ctrl is None:
                return False
            return bool(ctrl.tap(int(x), int(y)))
        if self.controller.device is None:
            return False
        return bool(self.controller.tap(int(x), int(y)))

    # ── Scope toolset: selection / color / crop / OCR / match / actions ──────
    # Mirrors DevScope's DevHelperAPI so the Preview tab doubles as a region
    # picker + action tester. Crops land in the open workflow's ``templates/``
    # folder (resolved on demand) so they're picked up by image nodes directly.

    def _scope_out(self) -> str:
        """Resolve (and cache) the folder where preview crops/screenshots save.

        Falls back to the project ``out/`` dir when no workflow context exists.
        """
        if self._scope_out_dir and os.path.isdir(self._scope_out_dir):
            return self._scope_out_dir
        try:
            dest = self._workflow_templates_dir("")
        except Exception:
            dest = None
        if not dest:
            dest = os.path.join(_PROJECT_ROOT, "out")
        os.makedirs(dest, exist_ok=True)
        self._scope_out_dir = dest
        return dest

    def _scope_refresh_out(self) -> None:
        """Drop the cached output dir so the next crop re-resolves (e.g. after
        a save-as moved the workflow into a new folder)."""
        self._scope_out_dir = None

    def scope_out_dir(self) -> str:
        """Resolve (lazily) and announce the folder where preview crops save.

        Called by JS when entering the Preview tab so the Selection / Library
        labels reflect the current workflow's templates folder.
        """
        path = self._scope_out()
        self._push("out_dir", {"path": path})
        return path

    def set_point(self, x: int, y: int) -> dict:
        self._last_point = (int(x), int(y))
        self._region = None
        color = self._pixel_color(int(x), int(y))
        return {"x": int(x), "y": int(y), **color}

    def set_region(self, x: int, y: int, w: int, h: int) -> dict:
        self._region = (int(x), int(y), int(w), int(h))
        self._last_point = None
        cx = int(x) + int(w) // 2
        cy = int(y) + int(h) // 2
        color = self._pixel_color(cx, cy)
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                "centerX": cx, "centerY": cy, **color}

    def _pixel_color(self, x: int, y: int) -> dict:
        return device_info.pixel_color(self._screen, self._screen_w,
                                       self._screen_h, int(x), int(y))

    def clear_selection(self) -> bool:
        self._region = None
        self._last_point = None
        self._overlay = []
        self._push("selection_cleared", {})
        return True

    def check_color(self, x: int, y: int, hex_color: str, tolerance: int = 10) -> dict:
        return device_info.check_color_at(self._screen, self._screen_w,
                                          self._screen_h, x, y, hex_color,
                                          tolerance)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, dur: int) -> bool:
        # Like tap(): route to whatever the preview captures from (Win32 window
        # in a Win32 project, else the ADB device) so right-drag swipes work in
        # both project kinds.
        if self._capture_kind == "win32":
            ctrl = self._win32_ready()
            if ctrl is None:
                return False
            return bool(ctrl.swipe(int(x1), int(y1), int(x2), int(y2), int(dur)))
        if self.controller.device is None:
            return False
        return bool(self.controller.swipe(int(x1), int(y1), int(x2), int(y2), int(dur)))

    def long_press(self, x: int, y: int, duration: int = 800) -> bool:
        # Like tap()/swipe(): follow the preview's capture source so the Preview
        # tab's action testers work in Win32 projects too.
        if self._capture_kind == "win32":
            ctrl = self._win32_ready()
            if ctrl is None:
                return False
            return bool(ctrl.hold_and_release(int(x), int(y), int(duration)))
        if self.controller.device is None:
            return False
        try:
            self.controller.device.shell(
                f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration)}")
            return True
        except Exception:
            return False

    def send_key(self, keycode) -> bool:
        if self._capture_kind == "win32":
            ctrl = self._win32_ready()
            if ctrl is None:
                return False
            # Win32 keys are Windows virtual-key codes, not Android keycodes.
            try:
                return bool(ctrl.press_key(int(keycode)))
            except (TypeError, ValueError):
                log_warning(f"[Designer] Win32 requires a numeric virtual-key code; received '{keycode}'")
                return False
        if self.controller.device is None:
            return False
        try:
            self.controller.device.shell(f"input keyevent {keycode}")
            return True
        except Exception:
            return False

    def input_text(self, text: str) -> bool:
        if not text:
            return False
        if self._capture_kind == "win32":
            ctrl = self._win32_ready()
            if ctrl is None:
                return False
            return bool(ctrl.send_text(str(text)))
        if self.controller.device is None:
            return False
        try:
            safe = (text.replace("\\", "\\\\").replace('"', '\\"')
                    .replace("$", "\\$").replace("`", "\\`").replace(" ", "%s"))
            self.controller.device.shell(f'input text "{safe}"')
            return True
        except Exception:
            return False

    def preview_click(self, x: int, y: int, button: str = "right",
                      clicks: int = 1) -> bool:
        """Right/middle-click test from the Preview tab (Win32 projects only)."""
        if self._capture_kind != "win32":
            log_warning("[Designer] Right and middle click are available only for Win32 projects")
            return False
        ctrl = self._win32_ready()
        if ctrl is None:
            return False
        return bool(ctrl.click(int(x), int(y), button=str(button or "right"),
                               click_count=int(clicks or 1)))

    def preview_scroll(self, x: int, y: int, direction: str = "down",
                       notches: int = 3) -> bool:
        """Mouse-wheel test from the Preview tab (Win32 projects only)."""
        if self._capture_kind != "win32":
            log_warning("[Designer] Wheel scrolling is available only for Win32 projects")
            return False
        ctrl = self._win32_ready()
        if ctrl is None:
            return False
        d = str(direction or "down").lower()
        try:
            n = max(1, int(notches or 3))
        except (TypeError, ValueError):
            n = 3
        signed = n if d in ("up", "right") else -n
        return bool(ctrl.scroll(int(x), int(y), notches=signed,
                                horizontal=d in ("left", "right")))

    # ── Crop / save ───────────────────────────────────────────────────────────

    def save_full(self, name: str = "") -> bool:
        if self._screen is None:
            return False
        out_dir = self._scope_out()
        clean = _sanitize_name(name)
        fname = (f"{clean}_{_ts()}.png" if clean else f"screenshot_{_ts()}.png")
        path = os.path.join(out_dir, fname)
        return bool(cv2.imwrite(path, self._screen))

    def _ensure_region_in_filename(self, path: str, x, y, w, h) -> str:
        return device_info.ensure_region_in_filename(path, x, y, w, h)

    def save_crop_dialog(self, name: str = "") -> bool:
        region = self._region
        if self._screen is None or not region:
            return False
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        clean = _sanitize_name(name)
        default = (f"{clean}_{x}_{y}_{w}_{h}.png" if clean
                   else f"region_{_ts()}_{x}_{y}_{w}_{h}.png")
        out_dir = self._scope_out()
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=out_dir, save_filename=default,
                    file_types=("PNG (*.png)", "JPEG (*.jpg;*.jpeg)", "All files (*.*)"))
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception:
            path = None
        if not path:
            path = os.path.join(out_dir, default)
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        path = self._ensure_region_in_filename(path, x, y, w, h)
        return bool(cv2.imwrite(path, crop))

    def quick_crop(self, name: str = "") -> str:
        """Save the current region crop into the open workflow's templates folder.

        Always lands in the resolved workflow ``templates/`` dir (e.g.
        ``workflows/Cherry_Tale/templates/``) so the crop is immediately usable as
        a node template. Returns the saved path; "" on failure (no screen/region).
        """
        region = self._region
        if self._screen is None or not region:
            return ""
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        out_dir = self._scope_out()
        clean = _sanitize_name(name)
        if clean:
            fname = f"{clean}_{x}_{y}_{w}_{h}.png"
            if os.path.exists(os.path.join(out_dir, fname)):
                fname = f"{clean}_{_ts()}_{x}_{y}_{w}_{h}.png"
        else:
            fname = f"crop_{_ts()}_{x}_{y}_{w}_{h}.png"
        path = os.path.join(out_dir, fname)
        if cv2.imwrite(path, crop):
            log_success(f"Region captured: {path}")
            return path
        return ""

    def pick_out_dir(self) -> str:
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.FOLDER_DIALOG, directory=self._scope_out())
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
                    if path and os.path.isdir(str(path)):
                        self._scope_out_dir = str(path)
                        self._push("out_dir", {"path": self._scope_out_dir})
        except Exception:
            pass
        return self._scope_out()

    def pick_folder(self, start: str = "") -> str:
        """Open a folder-picker dialog and return the chosen directory (or "").

        Used by the ``launch_emulator`` node's path field to browse to an
        emulator install folder. Opens at ``start`` when it is a real directory.
        """
        win = self._win()
        if win is None:
            return ""
        start_dir = start if start and os.path.isdir(start) else ""
        try:
            paths = win.create_file_dialog(webview.FOLDER_DIALOG, directory=start_dir)
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return str(path)

    def pick_file(self, start: str = "") -> str:
        """Open a general file picker for executable/path fields and variables."""
        win = self._win()
        if win is None:
            return ""
        start_dir = ""
        if start:
            start_dir = start if os.path.isdir(start) else os.path.dirname(start)
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = _PROJECT_ROOT
        try:
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                file_types=("Programs (*.exe;*.bat;*.cmd;*.com)", "All files (*.*)"),
            )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return str(path)

    def list_windows(self) -> list:
        """List visible top-level windows as ``[{title, cls, pid, exe}]`` for
        the Win32 window picker. Returns [] if pywin32 is unavailable."""
        try:
            import win32gui
            import win32process
            from src.core.win32.automation import process_exe_name
        except Exception:
            return []
        out: List[dict] = []
        seen: set = set()

        def _cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = (win32gui.GetWindowText(hwnd) or "").strip()
                if not title:
                    return
                cls = win32gui.GetClassName(hwnd) or ""
                try:
                    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                except Exception:
                    pid = 0
                exe = process_exe_name(pid) if pid else ""
                key = (title, cls, pid)
                if key in seen:
                    return
                seen.add(key)
                out.append({"title": title, "cls": cls, "pid": int(pid), "exe": exe})
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            pass
        out.sort(key=lambda w: w["title"].lower())
        return out

    # ── Template matching ─────────────────────────────────────────────────────

    def pick_template(self) -> str:
        """Open a file dialog to pick a template image.

        Always opens in the current workflow's ``templates/`` folder first —
        that's where image-node templates belong, so it should be the default
        every time, not whatever folder the last dialog landed in. Falls back to
        the project ``out/`` dir if no workflow context exists.
        """
        win = self._win()
        if win is None:
            return ""
        # Resolve the workflow's templates dir (NOT via _start_dir — that would
        # honour a stale remembered dir and miss the templates folder).
        try:
            start_dir = self._scope_out()
        except Exception:
            start_dir = ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = os.path.join(_PROJECT_ROOT, "out")
            os.makedirs(start_dir, exist_ok=True)
        try:
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                file_types=("Images (*.png;*.jpg;*.jpeg;*.bmp)", "All files (*.*)"),
            )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return str(path)

    def match_template(self, template_path: str, threshold: float,
                       grayscale: bool, multiscale: bool, all_matches: bool) -> dict:
        if self._screen is None:
            return {"error": "Capture a screenshot first"}
        # Workflow nodes normally store paths relative to the JSON directory
        # (templates/foo.png). Inspector thumbnails already resolve them; match
        # preview must use the same resolver instead of depending on cwd.
        template_path = self._resolve_template(template_path)
        result = device_info.run_template_match(
            self._matcher, self._screen, template_path,
            threshold, grayscale, multiscale, all_matches,
        )
        if result.get("error"):
            return result
        rects = result["rects"]
        self._overlay = [(r[0], r[1], r[2], r[3], r[4]) for r in rects]
        self._push("overlay", {"rects": rects})
        return result

    def preview_match_template(self, template_path: str, threshold: float,
                               all_matches: bool = False,
                               region_x: int = 0, region_y: int = 0,
                               region_w: int = 0, region_h: int = 0) -> dict:
        """Read-only template match for a node's context-menu preview.

        Unlike ``match_template`` this never updates DevScope state and never
        emits an ``overlay`` event (which is gated by the runtime debug toggle
        in JS). An optional search region mirrors the node's runtime scope; the
        returned rectangles are translated back into full-screen coordinates.
        """
        if self._screen is None:
            return {"error": "Capture a screenshot first"}
        template_path = self._resolve_template(template_path)
        screen = self._screen
        ox = oy = 0
        try:
            x, y = max(0, int(region_x)), max(0, int(region_y))
            w, h = int(region_w), int(region_h)
            if w > 0 and h > 0:
                x2, y2 = min(self._screen_w, x + w), min(self._screen_h, y + h)
                if x2 <= x or y2 <= y:
                    return {"error": "Search region is outside the captured frame"}
                screen = screen[y:y2, x:x2]
                ox, oy = x, y
        except (TypeError, ValueError):
            pass
        result = device_info.run_template_match(
            self._matcher, screen, template_path,
            float(threshold), False, False, bool(all_matches),
        )
        if not result.get("error") and (ox or oy):
            for rect in result.get("rects", []):
                if len(rect) >= 2:
                    rect[0] += ox
                    rect[1] += oy
        return result

    def clear_overlay(self) -> bool:
        self._overlay = []
        self._push("overlay", {"rects": []})
        return True

    # ── OCR ───────────────────────────────────────────────────────────────────

    def set_ocr_backend(self, name: str) -> dict:
        try:
            if self._ocr_reader is None:
                self._ocr_reader = OCRReader(backend=name)
            else:
                self._ocr_reader.set_backend(name)
            engine = self._ocr_reader.backend_name
            available = bool(self._ocr_reader.available)
            label = OCR_MODEL_LABELS.get(name, OCR_MODEL_LABELS[KNOWN_BACKENDS[0]])
            return {"engine": engine if engine != "none" else "n/a", "label": label, "available": available}
        except Exception:
            return {"engine": "n/a", "available": False}

    def read_text(self, whitelist: str = "") -> str:
        if self._screen is None:
            return ""
        region = self._region
        if not region:
            return ""
        if self._ocr_reader is None:
            self._ocr_reader = OCRReader(backend=KNOWN_BACKENDS[0])
        if not self._ocr_reader.available:
            return ""
        wl = (whitelist or "").strip() or None
        return self._ocr_reader.read_text(self._screen, region=region, whitelist=wl) or ""

    # ── Image preview ──────────────────────────────────────────────────────────

    def _resolve_template(self, raw: str) -> str:
        """Resolve a (possibly relative) template path for previewing."""
        raw = (raw or "").strip().replace("\\", "/")
        if not raw:
            return ""
        if os.path.isabs(raw) and os.path.exists(raw):
            return raw
        cands = [raw, os.path.join(_PROJECT_ROOT, raw),
                 os.path.join(_PROJECT_ROOT, "out", raw)]
        if self._wf_path:
            cands.insert(0, os.path.join(os.path.dirname(self._wf_path), raw))
        for c in cands:
            if os.path.exists(c):
                return c
        return raw

    def image_thumbnail(self, path: str, max_w: int = 230) -> str:
        """Return a JPEG data-URL thumbnail for a template path (or "")."""
        p = self._resolve_template(path)
        if not p or not os.path.exists(p):
            return ""
        try:
            data = np.fromfile(p, dtype=np.uint8)   # unicode-path safe
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                return ""
            h, w = img.shape[:2]
            if w > max_w:
                img = cv2.resize(img, (max_w, max(1, int(h * max_w / w))),
                                 interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if not ok:
                return ""
            return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception:
            return ""
