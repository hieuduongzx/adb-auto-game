"""The live preview: frames from the capture backend a run uses."""
from __future__ import annotations

import base64
import threading
import time
from typing import Optional


class PreviewMixin:
    """The live preview: frames from the capture backend a run uses."""

    # ── Live preview ─────────────────────────────────────────────────────────

    def _grab_frame(self):
        """One BGR frame from the active backend, or None when unavailable.

        ADB flows grab from the connected device; Win32 flows build/attach their
        window capture backend lazily (same path a run uses)."""
        try:
            auto = getattr(self.engine, "auto", None)
            if auto is None:
                return None
            if self._controller() == "win32":
                try:
                    from src.core.win32 import Win32GameAutomation
                    # Attach on the first frame, and keep retrying while no window
                    # is attached: the game is usually started *after* the app, so
                    # the window only becomes findable later. Throttled — a missing
                    # window must not re-enumerate (and re-log) at frame rate.
                    if (not isinstance(auto, Win32GameAutomation)
                            or not getattr(auto, "hwnd", None)):
                        now = time.time()
                        if now - self._win32_attach_at >= 2.0:
                            self._win32_attach_at = now
                            self.engine._ensure_ready_win32()
                        auto = self.engine.auto
                except Exception:
                    pass
                self._push_bridge_status()
            return auto.capture_screen()
        except Exception:
            return None

    def _push_bridge_status(self, force: bool = False) -> None:
        """Tell the page whether the in-game Unity Bridge answers.

        A ``unity_bridge`` workflow that can't reach its plugin silently falls
        back to ``anchored_touch``, which many Unity games ignore — the operator
        then sees "the window is there but nothing happens". Showing it in the
        footer (and logging it on attach) is what turns that into a one-glance
        diagnosis. Throttled; only for unity_bridge workflows."""
        if self._controller() != "win32":
            return
        cfg = (self.flow.get("win32") or {}) if self.flow else {}
        if str(cfg.get("inputMode") or "").strip().lower() != "unity_bridge":
            return
        now = time.time()
        if not force and now - self._bridge_status_at < 5.0:
            return
        self._bridge_status_at = now
        try:
            port = int(cfg.get("bridgePort") or 17820)
        except (TypeError, ValueError):
            port = 17820
        reply = ""
        try:
            from src.core.win32 import unity_bridge
            reply = unity_bridge.ping(port) or ""
        except Exception:
            reply = ""
        self._push("bridge_status", {"port": port, "ok": reply.startswith("ok"),
                                     "reply": reply})

    def _encode_frame(self, bgr) -> Optional[dict]:
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return None
            h, w = bgr.shape[:2]
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            return {"dataUrl": "data:image/jpeg;base64," + b64, "w": int(w), "h": int(h)}
        except Exception:
            return None

    def _push_frame(self, frame: Optional[dict]) -> None:
        if self._window is None or self._closing or not frame:
            return
        try:
            self._window.evaluate_js(
                'window.__recvFrame && window.__recvFrame("%s",%d,%d)'
                % (frame["dataUrl"], frame["w"], frame["h"]))
        except Exception:
            pass

    def capture_now(self) -> dict:
        """One synchronous frame for the Preview panel ({} when no frame)."""
        if self._window is None:
            return {}
        with self._capture_lock:
            img = self._grab_frame()
        return (self._encode_frame(img) if img is not None else None) or {}

    def capture(self) -> bool:
        """Fire-and-forget frame push, so the page never blocks on a capture."""
        if self._window is None or self._closing:
            return False
        # A slow capture must not queue a new thread for every repeated click.
        if not self._capture_request_lock.acquire(blocking=False):
            return False
        def capture_pending():
            try:
                self._capture_once()
            finally:
                self._capture_request_lock.release()
        try:
            threading.Thread(target=capture_pending, daemon=True).start()
        except Exception:
            self._capture_request_lock.release()
            raise
        return True

    def _capture_once(self) -> None:
        with self._capture_lock:
            img = self._grab_frame()
            frame = self._encode_frame(img) if img is not None else None
        self._push_frame(frame)

    def set_refresh_hz(self, hz: float) -> bool:
        try:
            self._refresh_hz = max(0.5, min(30.0, float(hz)))
        except (TypeError, ValueError):
            pass
        return True

    def set_auto_refresh(self, enabled: bool) -> bool:
        """Start/stop the preview frame loop. The page calls this when the
        Preview panel is shown or hidden, so nothing captures while it's shut."""
        self._auto_refresh_enabled = bool(enabled)
        if self._auto_refresh_enabled:
            if self._refresh_thread is None or not self._refresh_thread.is_alive():
                self._refresh_thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
                self._refresh_thread.start()
        return True

    def _auto_refresh_loop(self) -> None:
        while not self._closing and self._auto_refresh_enabled:
            start = time.time()
            self._capture_once()
            delay = (1.0 / max(0.5, self._refresh_hz)) - (time.time() - start)
            time.sleep(max(0.03, delay))
