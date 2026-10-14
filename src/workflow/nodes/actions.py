"""Action nodes: taps, swipes, keys, variables, apps, device and time."""
from __future__ import annotations

import os
import random
import re
import threading
import time
from typing import Any, Dict

from src.core.keynames import (
    android_key_is_known,
    android_key_name,
)
from src.utils import (
    LOG_KIND_USER,
)
from src import notify
from src.workflow.logs import log_info, log_success, log_warning


class ActionNodes:
    """Handlers of the form ``_a_<type>(node, params) -> bool``."""

    # ── Action handlers ──────────────────────────────────────────────────────

    def _pos(self, p) -> tuple:
        """(x, y) for a tap-like node: the found image, or fixed coords."""
        if str(p.get("target", "pos")) == "found" and self._last_pos:
            return self._last_pos
        return (int(p.get("x", 0)), int(p.get("y", 0)))

    def _tap_at(self, x: int, y: int, params: Dict, label: str = "image") -> bool:
        """Tap a found image's center, applying the node's optional offsetX/offsetY
        (handy when the thing to tap sits beside the matched icon). Honours the
        ``taps`` field (1 / 2-double) and logs the actual tapped point."""
        ox = int(params.get("offsetX", 0) or 0)
        oy = int(params.get("offsetY", 0) or 0)
        tx, ty = int(x) + ox, int(y) + oy
        tc = 2 if str(params.get("taps", "1")) in ("2", "double") else 1
        ok = bool(self.auto.tap(tx, ty, tap_count=tc))
        if ok:
            suffix = f" (+{ox},{oy})" if (ox or oy) else ""
            log_info(f"👆 tapped {label} at ({tx}, {ty}){suffix}")
        return ok

    def _a_tap(self, node, p) -> bool:
        x, y = self._pos(p)
        # taps=2 → chạm đúp: gộp công dụng của node double_tap (đã ẩn khỏi palette).
        taps = 2 if str(p.get("taps", "1")) == "2" else 1
        ok = self.auto.tap(x, y, tap_count=taps)
        if ok:
            log_info(f"👆 tapped ({x}, {y})" + (" ×2" if taps == 2 else ""))
        return ok

    def _a_multi_tap(self, node, p) -> bool:
        """Start two or more fixed touch points in one concurrent batch."""
        points = []
        for raw in p.get("points", []) if isinstance(p.get("points"), list) else []:
            try:
                if isinstance(raw, dict):
                    x, y = int(raw.get("x", 0)), int(raw.get("y", 0))
                elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                    x, y = int(raw[0]), int(raw[1])
                else:
                    continue
                points.append((x, y))
            except (TypeError, ValueError):
                continue
        if len(points) < 2:
            log_warning("multi-point tap requires at least 2 points")
            return False
        # Most Android devices expose at most ten touch slots. Limiting here also
        # prevents malformed workflow JSON from spawning an unbounded batch.
        points = points[:10]
        try:
            duration_ms = int(p.get("duration", 80) or 80)
        except (TypeError, ValueError):
            duration_ms = 80
        duration_ms = max(20, min(10_000, duration_ms))
        ok = bool(self.auto.multi_tap(points, duration_ms=duration_ms))
        if ok:
            coords = ", ".join(f"({x}, {y})" for x, y in points)
            log_info(f"👆 tapped {len(points)} points simultaneously: {coords} · {duration_ms}ms")
        return ok

    def _a_sequence_tap(self, node, p) -> bool:
        """Tap fixed points one by one, waiting after each tap."""
        points = p.get("points", []) if isinstance(p.get("points"), list) else []
        if not points:
            log_warning("sequence tap requires at least 1 point")
            return False
        sequence_id = str(p.get("sequenceId", "main") or "main")
        stop_event = self._sequence_stop_event(sequence_id, reset=True)
        for raw in points[:50]:
            if stop_event.is_set():
                log_info(f"■ stopped sequence '{sequence_id}'")
                return True
            try:
                if isinstance(raw, dict):
                    x, y = int(raw.get("x", 0)), int(raw.get("y", 0))
                    delay = max(0.0, float(raw.get("delay", 0) or 0))
                elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                    x, y = int(raw[0]), int(raw[1])
                    delay = max(0.0, float(raw[2] if len(raw) > 2 else 0) or 0)
                else:
                    continue
            except (TypeError, ValueError):
                continue
            if not self.auto.tap(x, y, tap_count=1):
                return False
            log_info(f"👆 sequential tap at ({x}, {y})")
            if delay and self._sequence_delay(stop_event, delay):
                return True
        return True

    def _a_sequence_tap_image(self, node, p) -> bool:
        """Find and tap each template in order, waiting after each tap."""
        images = p.get("images", []) if isinstance(p.get("images"), list) else []
        if not images:
            log_warning("sequence tap image requires at least 1 image")
            return False
        sequence_id = str(p.get("sequenceId", "main") or "main")
        stop_event = self._sequence_stop_event(sequence_id, reset=True)
        for raw in images[:50]:
            if stop_event.is_set():
                log_info(f"■ stopped sequence '{sequence_id}'")
                return True
            if not isinstance(raw, dict):
                continue
            tpl = self._resolve_template(raw.get("template", ""))
            if not tpl:
                return False
            try:
                threshold = float(raw.get("threshold", 0.85))
                timeout = max(0.0, float(raw.get("timeout", 10) or 0))
                delay = max(0.0, float(raw.get("delay", 0) or 0))
            except (TypeError, ValueError):
                return False
            res = self._wait_for_template(
                tpl, timeout=timeout, threshold=threshold,
                region=self._search_region(raw),
            )
            if not res:
                return False
            self._last_pos = (res[0], res[1])
            after_find = self._after_find_seconds(raw)
            if after_find and self._sequence_delay(stop_event, after_find):
                return True
            # A sequence can be cancelled while finding, waiting, or paused.
            while not self._pause.wait(timeout=0.05):
                if self._stop.is_set() or stop_event.is_set():
                    break
            if self._stop.is_set():
                return False
            if stop_event.is_set():
                return True
            if not self._tap_at(res[0], res[1], raw, label=os.path.basename(tpl)):
                return False
            if delay and self._sequence_delay(stop_event, delay):
                return True
        return True

    def _sequence_stop_event(self, sequence_id: str, reset: bool = False) -> threading.Event:
        with self._sequence_stops_lock:
            event = self._sequence_stops.setdefault(sequence_id, threading.Event())
            if reset:
                event.clear()
            return event

    def _sequence_delay(self, stop_event: threading.Event, seconds: float) -> bool:
        """Wait between items, returning early when the paired stop node fires."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop.is_set():
            if stop_event.wait(timeout=min(0.05, max(0.0, end - time.time()))):
                return True
            while not self._pause.wait(timeout=0.05):
                if self._stop.is_set() or stop_event.is_set():
                    return stop_event.is_set()
        return stop_event.is_set()

    def _a_stop_sequence(self, node, p) -> bool:
        sequence_id = str(p.get("sequenceId", "main") or "main")
        self._sequence_stop_event(sequence_id).set()
        log_info(f"■ requested stop for sequence '{sequence_id}'")
        return True

    def _a_double_tap(self, node, p) -> bool:
        x, y = self._pos(p)
        ok = self.auto.tap(x, y, tap_count=2)
        if ok:
            log_info(f"👆 double-tapped ({x}, {y})")
        return ok

    def _a_swipe_dir(self, node, p) -> bool:
        direction = str(p.get("direction", "up")).lower()
        dist = int(p.get("distance", 400))
        dur = int(p.get("duration", 300))
        try:
            w, h = self.auto.adb.get_screen_size()
        except Exception:
            w, h = 0, 0
        cx, cy = (w // 2, h // 2) if (w and h) else (540, 960)
        dx = dy = 0
        if direction == "up":
            dy = -dist
        elif direction == "down":
            dy = dist
        elif direction == "left":
            dx = -dist
        elif direction == "right":
            dx = dist
        return self.auto.swipe(cx, cy, cx + dx, cy + dy, dur)

    def _a_tap_random(self, node, p) -> bool:
        # New shape uses two explicit corners, which is easier to reason about
        # than x/y + width/height. Keep legacy params runnable for old JSON files.
        if any(k in p for k in ("x1", "y1", "x2", "y2")):
            x1, y1 = int(p.get("x1", 0)), int(p.get("y1", 0))
            x2, y2 = int(p.get("x2", 100)), int(p.get("y2", 100))
        else:
            x1, y1 = int(p.get("x", 0)), int(p.get("y", 0))
            x2 = x1 + max(0, int(p.get("w", 100)))
            y2 = y1 + max(0, int(p.get("h", 100)))
        lo_x, hi_x = sorted((x1, x2))
        lo_y, hi_y = sorted((y1, y2))
        rx = random.randint(lo_x, hi_x)
        ry = random.randint(lo_y, hi_y)
        ok = self.auto.tap(rx, ry)
        if ok:
            log_info(f"👆 random tap at ({rx}, {ry})")
        return ok

    def _a_wait_random(self, node, p) -> bool:
        lo = float(p.get("min", 0.5))
        hi = float(p.get("max", 2.0))
        if hi < lo:
            lo, hi = hi, lo
        dur = random.uniform(lo, hi)
        log_info(f"⏳ Waiting {dur:.1f}s (random {lo:g}–{hi:g}s)")
        self._sleep(dur)
        return True

    def _resolve_operand(self, raw: Any) -> float:
        """A calc operand: a number literal, or the value of a variable name."""
        s = str(raw).strip()
        if s in self._vars:
            v = self._coerce(self._vars[s])
            return float(v) if isinstance(v, (int, float)) else 0.0
        v = self._coerce(s)
        return float(v) if isinstance(v, (int, float)) else 0.0

    def _resolve_value(self, raw: Any) -> Any:
        """Resolve a param that may reference variables.

        Precedence: a bare variable name (the whole value equals a known var) →
        that variable's live value; a string containing ``{name}`` placeholders →
        filled from the current vars (like the Log field); otherwise the literal,
        best-effort number-coerced. Lets value fields (Set variable, If variable,
        loop count…) point at another variable instead of a fixed literal.
        """
        if isinstance(raw, list):
            return list(raw)
        if isinstance(raw, (int, float, bool)):
            return raw
        s = str(raw)
        stripped = s.strip()
        if not stripped:
            return ""
        if stripped in self._vars:
            return self._vars[stripped]
        if "{" in s and "}" in s:
            return self._coerce(self._format_msg(s))
        return self._coerce(s)

    def _resolve_count(self, raw: Any, default: int = 0) -> int:
        """A loop/branch count that may be a number literal or a variable name."""
        val = self._resolve_value(raw)
        try:
            return max(0, int(float(val)))
        except (TypeError, ValueError):
            return default

    def _a_set_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        if name:
            self._set_var(name, self._resolve_value(p.get("value", "")))
            log_info(f"set {name} = {self._vars[name]!r}")
        return True

    def _a_calc_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        if not name:
            return True
        op = str(p.get("op", "+"))
        cur = self._resolve_operand(self._vars.get(name, 0))
        rhs = self._resolve_operand(p.get("value", 0))
        if op == "+":
            res = cur + rhs
        elif op == "-":
            res = cur - rhs
        elif op == "*":
            res = cur * rhs
        elif op == "/":
            res = cur / rhs if rhs else 0.0
        elif op == "%":
            # Modulo — cần cho counter vòng lặp ("mỗi 5 vòng thì …").
            res = (cur % rhs) if rhs else 0.0
        elif op == "min":
            res = min(cur, rhs)
        elif op == "max":
            res = max(cur, rhs)
        elif op == "round":
            # rhs = số chữ số thập phân.
            res = round(cur, int(rhs))
        elif op == "abs":
            res = abs(cur)
        else:  # "=" assign
            res = rhs
        # Keep ints clean (3.0 -> 3) for nicer comparisons/logs.
        if isinstance(res, float) and res.is_integer():
            res = int(res)
        self._set_var(name, res)
        log_info(f"{name} {op}= {rhs} -> {res}")
        return True

    def _a_read_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        region = self._region(p)
        text = self.auto.read_text(region=region, whitelist=self._ocr_whitelist(p)) or ""
        if name:
            value = self._apply_pattern(
                text, self._resolve_value(p.get("pattern", "")), p.get("group", 1))
            if value is None:
                value = ""
            self._set_var(name, self._coerce(value))
            log_info(
                f"🔤 read {name} = {self._vars[name]!r} "
                f"(OCR region {region}: {text!r})"
            )
        return True

    def _a_parse_var(self, node, p) -> bool:
        """Tách một đoạn text theo regex và lưu nhóm capture vào biến.

        Nguồn text: vùng OCR (mặc định, dùng x/y/w/h), hoặc giá trị của một
        biến có sẵn khi ``source`` = "var" (đọc từ ``fromVar``). Regex ``pattern``
        được áp dụng (re.search); nhóm capture thứ ``group`` (mặc định 1) được
        gán vào biến ``name``. Nếu không khớp, biến được đặt về "" và node vẫn
        trả về True (không phải lỗi—chỉ là không thấy).

        Ví dụ: text "5/5", pattern "(\\d+)/(\\d+)", group 1 -> name = "5".
        """
        name = str(p.get("name", "")).strip()
        src = str(p.get("source", "region")).strip().lower()
        if src == "var":
            text = str(self._vars.get(str(p.get("fromVar", "")).strip(), ""))
        else:
            region = self._region(p)
            try:
                text = self.auto.read_text(region=region, whitelist=self._ocr_whitelist(p)) or ""
                log_info(f"🔤 parse_var OCR region {region}: {text!r}")
            except Exception as exc:
                log_warning(f"parse_var OCR error: {exc}")
                text = ""
        pattern = str(p.get("pattern", "")).strip()
        if not pattern:
            if name:
                self._set_var(name, self._coerce(text.strip()))
                log_info(f"parse {name} = {self._vars[name]!r} (no pattern)")
            return True
        value = self._apply_pattern(text, pattern, p.get("group", 1))
        if value is None:
            if name:
                self._set_var(name, "")
            return False
        if name:
            self._set_var(name, self._coerce(value))
            log_info(f"parse {name} = {self._vars[name]!r} (from {text!r})")
        return True

    def _a_break(self, node, p) -> bool:
        self._break_loop = True
        log_info("break — will exit the next loop")
        return True

    def _a_long_press(self, node, p) -> bool:
        x, y = self._pos(p)
        return self.auto.adb.hold_and_release(x, y, int(p.get("duration", 800)))

    def _a_swipe(self, node, p) -> bool:
        if p.get("mode") == "direction":
            return self._a_swipe_dir(node, p)
        return self.auto.swipe(
            int(p.get("x1", 0)), int(p.get("y1", 0)),
            int(p.get("x2", 0)), int(p.get("y2", 0)),
            int(p.get("duration", 300)),
        )

    def _a_wait(self, node, p) -> bool:
        if p.get("mode") == "random":
            return self._a_wait_random(node, p)
        secs = float(p.get("seconds", 1.0))
        log_info(f"⏱ Waiting {secs:g}s")
        self._sleep(secs)
        return True

    def _a_send_text(self, node, p) -> bool:
        # Điền {var} vào text (giống Log) — gõ giá trị biến ra ô nhập của game.
        return self.auto.send_text(self._format_msg(str(p.get("text", ""))))

    def _a_key(self, node, p) -> bool:
        """Gửi một phím Android — nhận cả keycode số (4) lẫn tên ("BACK").

        Trước đây block này chạy im lặng: một keycode sai chỉ trả về False mà
        không nói gì, nên log không phân biệt được "đã gửi phím" với "block chết".
        """
        code = p.get("keycode", "")
        name = android_key_name(code)
        if not android_key_is_known(code):
            # `input keyevent` nhận mọi chuỗi, nên lỗi typo chỉ lộ ra ở thiết bị
            # dưới dạng lỗi mờ nghĩa — gọi tên giá trị đáng ngờ ngay tại đây.
            log_warning(f"⌨ '{code}' is not a known Android keycode — sending anyway")
        try:
            ok = self.auto.press_key(int(code))
        except (TypeError, ValueError):
            try:
                self.auto.adb.device.shell(f"input keyevent {code}")
                ok = True
            except Exception as exc:
                log_warning(f"⌨ failed to send key '{name}': {exc}")
                return False
        if ok:
            log_info(f"⌨ {name}")
        return ok

    def _a_back(self, node, p) -> bool:
        return self.auto.go_back()

    def _a_home(self, node, p) -> bool:
        return self.auto.go_home()

    def _adb_only_blocked(self, what: str, alternative: str = "") -> bool:
        """True — after a warning — when an ADB-only block runs in a Win32 project.

        Such a block used to report success and skip, so a flow carried on as if
        the phone step had happened. It now fails like the Win32-only blocks do
        in an ADB project (the Designer already flags both as errors).
        """
        if getattr(self, "_controller", "adb") != "win32":
            return False
        hint = f" — use {alternative} instead" if alternative else ""
        log_warning(f"{what} is ADB-only but this is a Win32 project{hint}")
        return True

    def _a_app_stop(self, node, p) -> bool:
        """Force-stop một app (tuỳ chọn xóa dữ liệu) — cặp với launch_app cho
        flow 'game treo → dừng hẳn → mở lại'. Chỉ áp dụng cho dự án ADB."""
        if self._adb_only_blocked("⛔ Stop app", "Kill process / Close window"):
            return False
        pkg = self._node_package(p)
        if not pkg:
            log_warning("⛔ app_stop: no package specified (Project settings or Custom)")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        try:
            dev.shell(f"am force-stop {pkg}")
            if self._truthy(p.get("clearData", False)):
                dev.shell(f"pm clear {pkg}")
                log_info(f"⛔ stopped '{pkg}' and cleared its data")
            else:
                log_info(f"⛔ stopped '{pkg}'")
            return True
        except Exception as exc:
            log_warning(f"app_stop error: {exc}")
            return False

    def _a_app_uninstall(self, node, p) -> bool:
        """pm uninstall một app (tuỳ chọn -k giữ dữ liệu/cache). ADB-only."""
        if self._adb_only_blocked("🗑 Uninstall app"):
            return False
        pkg = self._node_package(p)
        if not pkg:
            log_warning("🗑 app_uninstall: no package specified (Project settings or Custom)")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        try:
            keep = "-k " if self._truthy(p.get("keepData", False)) else ""
            out = (dev.shell(f"pm uninstall {keep}{pkg}") or "").strip()
            ok = "success" in out.lower()
            if ok:
                log_info(f"🗑 uninstalled '{pkg}'{' (kept data)' if keep else ''}")
            else:
                log_warning(f"🗑 failed to uninstall '{pkg}': {out or '(no response)'}")
            return ok
        except Exception as exc:
            log_warning(f"app_uninstall error: {exc}")
            return False

    def _a_app_install(self, node, p) -> bool:
        """Cài một file .apk trên PC vào thiết bị (``adb -s <serial> install``).

        Dùng CLI adb (không phải shell) vì APK nằm trên PC và cần được push.
        ``reinstall`` (-r) giữ dữ liệu, ``grantPerms`` (-g) cấp sẵn quyền.
        """
        if self._adb_only_blocked("📦 Install app"):
            return False
        apk = str(self._resolve_value(p.get("apk", ""))).strip().strip('"')
        if not apk:
            log_warning("📦 app_install: no APK file selected")
            return False
        if not os.path.isfile(apk):
            log_warning(f"📦 app_install: file '{apk}' not found")
            return False
        serial = str(getattr(self.auto.adb, "device_id", "") or "").strip()
        if not serial:
            log_warning("📦 app_install: no device connected")
            return False
        import subprocess

        from src.core.adb.constants import get_adb_path
        adb = get_adb_path()
        if not adb:
            log_warning("📦 app_install: adb.exe not found")
            return False
        cmd = [adb, "-s", serial, "install"]
        if self._truthy(p.get("reinstall", True)):
            cmd.append("-r")
        if self._truthy(p.get("grantPerms", False)):
            cmd.append("-g")
        cmd.append(apk)
        try:
            timeout = max(10.0, float(p.get("timeout", 180) or 180))
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            out = ((res.stdout or "") + (res.stderr or "")).strip()
            ok = "success" in out.lower()
            if ok:
                log_success(f"📦 installed '{os.path.basename(apk)}'")
            else:
                log_warning(f"📦 failed to install '{os.path.basename(apk)}': "
                            f"{out or '(no response)'}")
            return ok
        except Exception as exc:
            log_warning(f"app_install error: {exc}")
            return False

    def _a_adb_shell(self, node, p) -> bool:
        """Chạy một câu ``adb shell`` tuỳ ý; lưu stdout vào biến (nếu có tên).

        Cửa thoát cho những gì chưa có node riêng. ``failIfEmpty`` cho phép coi
        "không có output" là thất bại để rẽ nhánh trong Try in order.
        """
        if self._adb_only_blocked("💻 ADB shell"):
            return False
        cmd = str(self._resolve_value(p.get("command", ""))).strip()
        if not cmd:
            log_warning("💻 adb_shell: no command specified")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            log_warning("💻 adb_shell: no device connected")
            return False
        try:
            out = (dev.shell(cmd) or "").strip()
        except Exception as exc:
            log_warning(f"💻 adb_shell '{cmd}' error: {exc}")
            return False
        name = str(p.get("name", "") or "").strip()
        if name:
            pat = str(self._resolve_value(p.get("pattern", "")) or "").strip()
            value = self._apply_pattern(out, pat, p.get("group", 1)) if pat else out
            if value is None:
                value = ""
            self._set_var(name, self._coerce(value))
        log_info(f"💻 {cmd} → {out[:160]!r}"
                 + (f" (→ {name})" if name else ""))
        return not (self._truthy(p.get("failIfEmpty", False)) and not out)

    def _a_app_exit(self, node, p) -> bool:
        """Thoát app ĐANG mở: ADB force-stop app foreground (không cần biết
        package); Win32 đóng cửa sổ mục tiêu."""
        if getattr(self, "_controller", "adb") == "win32":
            ctrl = getattr(self.auto, "adb", None)
            if ctrl is None or not hasattr(ctrl, "close_window"):
                return False
            log_info("🚪 closing target window")
            return bool(ctrl.close_window())
        try:
            if hasattr(self.auto.adb, "clear_info_cache"):
                self.auto.adb.clear_info_cache()
            cur = (self.auto.adb.get_current_app() or "").strip()
        except Exception:
            cur = ""
        if not cur:
            log_warning("🚪 could not identify the current app")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        try:
            dev.shell(f"am force-stop {cur}")
            log_info(f"🚪 exited '{cur}'")
            return True
        except Exception as exc:
            log_warning(f"app_exit error: {exc}")
            return False

    def _a_launch_app(self, node, p) -> bool:
        # package: Project settings (pkgSrc=project) hoặc custom/var (pkgSrc=custom).
        pkg = self._node_package(p)
        if not pkg:
            log_warning("🚀 launch_app: no package specified (Project settings or Custom)")
            return False
        if not self.auto.adb.launch_app(pkg):
            return False
        # Optional: block until the app is actually in the foreground (0 = don't
        # wait). Lets "open game → tap image" work without a manual fixed delay.
        wait = float(p.get("wait", 0) or 0)
        if wait > 0:
            end = time.time() + wait
            while time.time() < end and not self._stop.is_set():
                self._pause.wait()
                try:
                    self.auto.adb.clear_info_cache()
                    cur = self.auto.adb.get_current_app() or ""
                except Exception:
                    cur = ""
                if cur and pkg in cur:
                    log_success(f"'{pkg}' is now in the foreground")
                    return True
                time.sleep(0.5)
            log_warning(f"'{pkg}' did not reach the foreground after {wait:.0f}s")
        return True

    def _a_screenshot(self, node, p) -> bool:
        """Chụp màn hình và LƯU thành PNG (trước đây chỉ refresh frame trong RAM).

        ``save`` = false → chỉ làm mới frame (hành vi cũ, dùng khi chỉ cần ép
        capture lại trước một node ảnh). ``name`` nhận cả {var}; thư mục mặc
        định là ``out/screenshots`` cạnh workflow (hoặc cwd nếu chưa lưu file).
        """
        img = self.auto.capture_screen()
        if img is None:
            log_warning("📷 could not capture a frame")
            return False
        if not self._truthy(p.get("save", True)):
            return True
        raw = self._format_msg(str(p.get("name", "") or "")).strip()
        stem = re.sub(r"[^\w.\-]+", "_", raw).strip("._") or "shot"
        folder = str(self._resolve_value(p.get("folder", ""))).strip()
        if not folder:
            anchor = (os.path.dirname(self.flow_path) if self.flow_path
                      else (self.templates_base or os.getcwd()))
            folder = os.path.join(anchor, "out", "screenshots")
        try:
            import cv2
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.png")
            # Unicode-safe write (cv2.imwrite chokes on non-ASCII Windows paths).
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                log_warning("📷 PNG encoding failed")
                return False
            buf.tofile(path)
            log_info(f"📷 saved {path}")
            name = str(p.get("pathVar", "") or "").strip()
            if name:
                self._set_var(name, path)
            return True
        except Exception as exc:
            log_warning(f"📷 failed to save image: {exc}")
            return False

    def _a_log(self, node, p) -> bool:
        log_info(self._format_msg(p.get('message', '')), kind=LOG_KIND_USER)
        return True

    def _a_format_var(self, node, p) -> bool:
        name     = str(p.get("name", "")).strip()
        template = str(p.get("template", ""))
        result   = template
        for k, v in list(self._vars.items()):
            result = result.replace(f"{{{k}}}", str(v))
        pat = str(self._resolve_value(p.get("pattern", "")) or "").strip()
        if pat:
            extracted = self._apply_pattern(result, pat, p.get("group", 1))
            result = "" if extracted is None else extracted
        if name:
            self._set_var(name, result)
            log_info(f"📝 {name} = \"{result}\"")
        return True

    def _a_notify(self, node, p) -> bool:
        # The title fills {var} like the message (the Designer marks both insertVar).
        title   = self._format_msg(str(p.get("title", "Workflow"))).strip() or "Workflow"
        message = self._format_msg(str(p.get("message", "Completed!")))
        log_info(f"🔔 {title}: {message}", kind=LOG_KIND_USER)
        if self._truthy(p.get("sound", True)):
            notify.beep()
        notify.desktop(title, message)
        return True

    # ── Device / time handlers ────────────────────────────────────────────────

    def _a_get_time(self, node, p) -> bool:
        """Read the current local time into a variable, in the chosen shape."""
        name = str(p.get("name", "")).strip()
        part = str(p.get("part", "hm")).strip().lower()
        now = time.localtime()
        if part == "timestamp":
            val: Any = int(time.time())
        elif part == "hour":
            val = now.tm_hour
        elif part == "minute":
            val = now.tm_min
        elif part == "second":
            val = now.tm_sec
        elif part == "hms":
            val = time.strftime("%H:%M:%S", now)
        elif part == "date":
            val = time.strftime("%Y-%m-%d", now)
        elif part == "datetime":
            val = time.strftime("%Y-%m-%d %H:%M:%S", now)
        elif part == "weekday":
            val = now.tm_wday + 1  # 1 = Monday … 7 = Sunday
        elif part == "custom":
            val = time.strftime(str(p.get("format", "%H:%M")), now)
        else:  # "hm"
            val = time.strftime("%H:%M", now)
        if name:
            self._set_var(name, val)
            log_info(f"🕒 {name} = {self._vars[name]!r}")
        return True

    def _wait_until_clock(self, target: str, next_day: bool = True) -> bool:
        """Block until a wall-clock ``HH:MM`` (or ``HH:MM:SS``). If the time is
        already past today, wait until the same time tomorrow (unless disabled).
        Returns False only on a malformed time string. Shared by the ``wait_until``
        node and ``launch_emulator``'s optional ``at`` schedule."""
        m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", target)
        if not m:
            log_warning(f"⏰ Schedule: invalid time '{target}' (expected HH:MM)")
            return False
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        now = time.localtime()
        now_secs = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        delay = (hh * 3600 + mm * 60 + ss) - now_secs
        if delay <= 0:
            if next_day:
                delay += 86400
            else:
                log_info(f"⏰ {hh:02d}:{mm:02d} has passed — skipping wait")
                return True
        log_info(f"⏰ Scheduled for {hh:02d}:{mm:02d}:{ss:02d} — waiting {delay}s")
        self._sleep(delay)
        return True

    def _a_wait_until(self, node, p) -> bool:
        return self._wait_until_clock(str(p.get("time", "")).strip(), self._truthy(p.get("nextDay", True)))

    def _a_device_info(self, node, p) -> bool:
        """Read a live device property into a variable (battery, app, size…)."""
        name = str(p.get("name", "")).strip()
        prop = str(p.get("prop", "battery")).strip().lower()
        val = self._read_device_prop(prop)
        if name:
            self._set_var(name, val)
            log_info(f"📱 {name} = {self._vars[name]!r} ({prop})")
        return True

    def _read_device_prop(self, prop: str) -> Any:
        dev = getattr(self.auto.adb, "device", None)

        def _sh(cmd: str) -> str:
            return (dev.shell(cmd) if dev else "") or ""

        try:
            if prop == "battery":
                m = re.search(r"level:\s*(\d+)", _sh("dumpsys battery"))
                return int(m.group(1)) if m else 0
            if prop == "current_app":
                return self.auto.adb.get_current_app() or ""
            if prop in ("width", "height"):
                w, h = self.auto.adb.get_screen_size()
                return int(w if prop == "width" else h)
            if prop == "model":
                return _sh("getprop ro.product.model").strip()
            if prop == "brand":
                return _sh("getprop ro.product.brand").strip()
            if prop == "android":
                return _sh("getprop ro.build.version.release").strip()
            if prop == "sdk":
                v = _sh("getprop ro.build.version.sdk").strip()
                return int(v) if v.isdigit() else v
            if prop == "serial":
                return str(getattr(self.auto.adb, "device_id", "") or "")
            if prop == "ip":
                m = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", _sh("ip route"))
                return m.group(1) if m else ""
        except Exception as exc:
            log_warning(f"device_info '{prop}' error: {exc}")
        return ""

    def _a_screen_power(self, node, p) -> bool:
        """Wake, sleep, or toggle the device screen via key events."""
        if self._adb_only_blocked("🖥 Screen power"):
            return False
        action = str(p.get("action", "on")).strip().lower()
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        # KEYCODE_POWER 26 · KEYCODE_SLEEP 223 · KEYCODE_WAKEUP 224
        try:
            if action == "toggle":
                dev.shell("input keyevent 26")
            else:
                out = dev.shell("dumpsys power") or ""
                is_on = ("mWakefulness=Awake" in out) or ("Display Power: state=ON" in out)
                if action == "on" and not is_on:
                    dev.shell("input keyevent 224")
                elif action == "off" and is_on:
                    dev.shell("input keyevent 223")
            log_info(f"🖥 screen: {action}")
            return True
        except Exception as exc:
            log_warning(f"screen_power '{action}' error: {exc}")
            return False
