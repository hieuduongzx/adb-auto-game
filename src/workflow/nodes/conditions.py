"""Condition nodes: every block with a true/false exit."""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

from src.workflow.logs import log_info, log_warning


class ConditionNodes:
    """``_eval_condition`` dispatch plus the comparison and app/screen probes."""

    def _eval_condition(self, ntype: str, params: Dict) -> bool:
        if ntype in ("if_color", "wait_color", "tap_color"):
            return self._eval_color_condition(ntype, params)
        if ntype == "tap_all_images":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            screen = self.auto.capture_screen()
            hits = self.auto.find_all_templates(tpl, threshold=threshold, screen=screen) or []
            region = self._search_region(params)
            if region:
                rx, ry, rw, rh = region
                hits = [h for h in hits if rx <= h[0] <= rx + rw and ry <= h[1] <= ry + rh]
            max_taps = self._resolve_count(params.get("maxTaps", 0), default=0)
            if max_taps > 0:
                hits = hits[:max_taps]
            # Overlay every hit before tapping so Preview shows the full set.
            name = os.path.basename(tpl) if tpl else "?"
            tw, th = self._tpl_wh(tpl)
            self._report_match_rects(
                [self._rect_from_center(int(hx), int(hy), float(sc), tw, th, 1.0, True, name)
                 for hx, hy, sc in hits],
                ok=bool(hits), threshold=threshold, label=name, region=region,
                conf=float(hits[0][2]) if hits else 0.0,
            )
            if hits and not self._wait_after_find(params):
                return False
            delay = max(0.0, float(params.get("delayBetween", 0.15) or 0))
            tapped = 0
            for hx, hy, _score in hits:
                if self._stop.is_set():
                    break
                self._pause.wait()
                if self._stop.is_set():
                    break
                if self._tap_at(int(hx), int(hy), params, label="image"):
                    tapped += 1
                if delay:
                    self._sleep(delay)
            if tapped:
                self._last_pos = (int(hits[0][0]), int(hits[0][1]))
                log_info(f"👆 tapped {tapped} matches for {os.path.basename(tpl)}")
            return tapped > 0
        if ntype == "if_emulator":
            return self._c_if_emulator(params)
        if ntype == "wait_emulator":
            return self._c_wait_emulator(params)
        if ntype in ("win_if_window", "win_wait_window"):
            return self._c_win_window(ntype, params)
        if ntype == "if_screen_on":
            return self._c_if_screen_on(params)
        if ntype == "if_device_size":
            return self._c_if_device_size(params)
        if ntype == "find_image_pos":
            return self._c_find_image_pos(params)
        if ntype == "wait_stable":
            return self._c_wait_stable(params)
        if ntype == "if_app":
            return self._app_match(params) != bool(params.get("negate", False))
        if ntype == "wait_app":
            return self._c_wait_app(params)
        if ntype == "if_image":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            negate = bool(params.get("negate", False))
            res = self._find_template(tpl, threshold=threshold, region=self._search_region(params))
            if res:
                self._last_pos = (res[0], res[1])
            return (res is not None) != negate
        if ntype == "if_image_any":
            templates = self._templates_list(params)
            negate = bool(params.get("negate", False))
            parallel = params.get("mode", "sequential") == "parallel"
            finder = self._find_any_parallel if parallel else self._find_any
            hit = finder(templates, float(params.get("threshold", 0.85)), region=self._search_region(params))
            if hit:
                self._last_pos = hit
            return (hit is not None) != negate
        if ntype == "wait_image_any":
            templates = self._templates_list(params)
            parallel = params.get("mode", "sequential") == "parallel"
            hit = self._wait_any(templates, float(params.get("timeout", 10.0)),
                                 float(params.get("threshold", 0.85)),
                                 parallel=parallel, region=self._search_region(params))
            if hit:
                self._last_pos = hit
                log_info(f"🔍 found image at ({hit[0]}, {hit[1]})")
            return hit is not None
        if ntype == "tap_image_any":
            templates = self._templates_list(params)
            parallel = params.get("mode", "sequential") == "parallel"
            hit = self._wait_any(templates, float(params.get("timeout", 10.0)),
                                 float(params.get("threshold", 0.85)),
                                 parallel=parallel, region=self._search_region(params))
            if not hit:
                return False  # no match — false branch fires; no log (tap-miss is expected)
            self._last_pos = hit
            if not self._wait_after_find(params):
                return False
            return self._tap_at(hit[0], hit[1], params, label="image")
        if ntype == "tap_image":
            # Find (with timeout), remember position, optionally wait, then tap.
            tpl = self._resolve_template(params.get("template", ""))
            res = self._wait_for_template(
                tpl, timeout=float(params.get("timeout", 10.0)),
                threshold=float(params.get("threshold", 0.85)),
                region=self._search_region(params),
            )
            if not res:
                return False  # not found — false branch fires; no log (tap-miss is expected)
            self._last_pos = (res[0], res[1])
            if not self._wait_after_find(params):
                return False
            return self._tap_at(res[0], res[1], params, label=os.path.basename(tpl))
        if ntype == "wait_image":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            timeout = float(params.get("timeout", 10.0))
            region = self._search_region(params)
            if bool(params.get("negate", False)):
                # Đảo: chờ đến khi ảnh BIẾN MẤT (màn hình loading, hộp thoại…)
                # — true ngay khi không còn thấy template; hết timeout → false.
                end = time.time() + max(0.0, timeout)
                while not self._stop.is_set():
                    self._pause.wait()
                    if self._find_template(tpl, threshold=threshold, region=region,
                                           report=False) is None:
                        log_info(f"🔍 image {os.path.basename(tpl)} disappeared")
                        self._report_template_match(tpl, None, threshold, region)
                        return True
                    if time.time() >= end:
                        # still visible — report the hit as fail for negate path
                        res = self._find_template(tpl, threshold=threshold, region=region)
                        return False
                    time.sleep(0.25)
                return False
            res = self._wait_for_template(
                tpl, timeout=timeout, threshold=threshold, region=region,
            )
            if res:
                self._last_pos = (res[0], res[1])
                log_info(f"🔍 found image {os.path.basename(tpl)} at ({res[0]}, {res[1]})")
            return res is not None
        if ntype == "tap_text":
            needle, regex = self._ocr_needle(params)
            needle = needle.strip()
            region = self._region(params)
            timeout = float(params.get("timeout", 10.0))
            if not needle:
                log_warning("Tap text: no text to look for")
                self._report_ocr_region(region, False, needle)
                return False
            end = time.time() + max(0.0, timeout)
            last_read = ""
            while not self._stop.is_set():
                self._pause.wait()
                if self._stop.is_set():
                    return False
                found, read = self.auto.region_find_text(
                    needle, region=region, whitelist=self._ocr_whitelist(params),
                    regex=regex)
                if read:
                    last_read = read
                if found:
                    x, y, w, h = region
                    center = (int(x) + max(0, int(w)) // 2,
                              int(y) + max(0, int(h)) // 2)
                    self._last_pos = center
                    self._report_ocr_region(region, True, needle)
                    if not self._wait_after_find(params):
                        return False
                    return self._tap_at(center[0], center[1], params, label=f"text '{needle}'")
                if time.time() >= end:
                    log_info(
                        f"🔤 timeout ({timeout:g}s) waiting to tap '{needle}' "
                        f"in {region} — last read: {last_read!r}"
                    )
                    self._report_ocr_region(region, False, needle)
                    return False
                time.sleep(min(0.5, max(0.0, end - time.time())))
            return False
        if ntype == "wait_text":
            needle, regex = self._ocr_needle(params)
            needle = needle.strip()
            region = self._region(params)
            wl = self._ocr_whitelist(params)
            timeout = float(params.get("timeout", 10.0))
            # Same rules as the other bool params: the string "false" is off.
            # bool("false") is True, which inverted Negate and returned immediately.
            negate = self._truthy(params.get("negate", False))
            if not needle:
                log_warning("Wait text: no text to look for")
                self._report_ocr_region(region, False, needle)
                return False
            # Poll here, not in wait_for_text_in_region: that helper cannot see
            # the workflow pause, so a paused run kept recognising text and
            # could take the true branch before the user resumed.
            end = time.time() + max(0.0, timeout)
            last_read = ""
            while not self._stop.is_set():
                self._pause.wait()
                if self._stop.is_set():
                    return False
                found, read = self.auto.region_find_text(needle, region=region, whitelist=wl,
                                                          regex=regex)
                if read:
                    last_read = read
                if negate:
                    # A blank read means the phrase is not on screen. OCR being
                    # unavailable is not the same thing — that stays false.
                    if not getattr(self.auto.ocr, "available", False):
                        log_warning("Wait text: OCR is unavailable")
                        self._report_ocr_region(region, False, needle)
                        return False
                    if not found:
                        log_info(f"🔤 text '{needle}' disappeared — read: {read!r}")
                        self._report_ocr_region(region, True, needle)
                        return True
                elif found:
                    x, y, w, h = region
                    self._last_pos = (int(x) + max(0, int(w)) // 2,
                                      int(y) + max(0, int(h)) // 2)
                    log_info(f"🔤 found text '{needle}' — read: {read!r}")
                    self._report_ocr_region(region, True, needle)
                    return True
                if time.time() >= end:
                    log_info(
                        f"🔤 timeout ({timeout:g}s) waiting for '{needle}' "
                        f"in {region} — last read: {last_read!r}"
                    )
                    self._report_ocr_region(region, False, needle)
                    return False
                time.sleep(min(0.5, max(0.0, end - time.time())))
            return False
        if ntype == "if_text":
            negate = bool(params.get("negate", False))
            # needle nhận biến — đồng bộ với if_app.package.
            needle, regex = self._ocr_needle(params)
            region = self._region(params)
            found, read = self.auto.region_find_text(
                needle, region=region, whitelist=self._ocr_whitelist(params),
                regex=regex)
            log_info(
                f"🔤 if_text region {region}: read {read!r} → "
                f"{'found' if found else 'not found'} '{needle}'"
            )
            ok = bool(found) != negate
            self._report_ocr_region(region, ok, needle)
            return ok
        if ntype == "if_var":
            cur = self._vars.get(str(params.get("name", "")))
            rhs = self._resolve_value(params.get("value", ""))
            return self._compare(cur, str(params.get("op", "==")), rhs)
        if ntype == "scroll_find":
            template  = self._resolve_template(params.get("template", ""))
            direction = str(params.get("direction", "up")).lower()
            max_sw    = max(1, int(params.get("max_swipes", 10)))
            distance  = int(params.get("swipe_distance", 400))
            duration  = int(params.get("swipe_duration", 300))
            threshold = float(params.get("threshold", 0.85))
            try:
                w, h = self.auto.adb.get_screen_size()
            except Exception:
                w, h = 0, 0
            cx, cy = (w // 2, h // 2) if (w and h) else (540, 960)
            delta  = {"up": (0, -distance), "down": (0, distance),
                      "left": (-distance, 0), "right": (distance, 0)}.get(direction, (0, -distance))
            region = self._search_region(params)
            for i in range(max_sw):
                if self._stop.is_set():
                    return False
                self._pause.wait()
                res = self.auto.find_template(template, threshold=threshold, region=region)
                if res:
                    self._report_template_match(template, res, threshold, region)
                    self._last_pos = (res[0], res[1])
                    log_info(f"🔍 found image after {i} swipes at ({res[0]}, {res[1]})")
                    return True
                if i == max_sw - 1:
                    self._report_template_match(template, None, threshold, region)
                self.auto.swipe(cx, cy, cx + delta[0], cy + delta[1], duration)
                self._sleep(0.4)
            return False
        if ntype == "if_time":
            negate = bool(params.get("negate", False))
            now = time.localtime()
            cur = now.tm_hour * 60 + now.tm_min
            a = self._parse_hhmm(params.get("from"), 0)
            b = self._parse_hhmm(params.get("to"), 24 * 60 - 1)
            # a <= b: a normal window in one day. a > b: the window wraps past
            # midnight (e.g. 22:00–06:00), so "inside" means before b OR after a.
            inside = (a <= cur <= b) if a <= b else (cur >= a or cur <= b)
            return inside != negate
        return False

    @staticmethod
    def _parse_hhmm(raw: Any, default: int) -> int:
        """Parse a ``HH:MM`` string to minutes-since-midnight; ``default`` if bad."""
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(raw or ""))
        if not m:
            return default
        return int(m.group(1)) * 60 + int(m.group(2))

    def _compare(self, cur: Any, op: str, rhs: Any) -> bool:
        type_ops = {
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "text": lambda value: isinstance(value, str),
            "empty": lambda value: value is None or (isinstance(value, str) and not value.strip()),
        }
        if op.startswith("is_"):
            base = op[6:] if op.startswith("is_not_") else op[3:].lstrip("_")
            if base == "integer" and isinstance(cur, str):
                try:
                    int(cur.strip())
                    result = bool(cur.strip())
                except ValueError:
                    result = False
            elif base == "number" and isinstance(cur, str):
                try:
                    float(cur.strip())
                    result = bool(cur.strip())
                except ValueError:
                    result = False
            elif base in type_ops:
                result = type_ops[base](cur)
            else:
                result = False
            return (not result) if op.startswith("is_not_") else result
        if isinstance(cur, list) and op in ("contains", "!contains"):
            found = rhs in cur
            return found if op == "contains" else not found
        # String-shaped operators first — OCR results almost always need soft
        # matching ("Stage 3/5" contains "3/5") rather than numeric equality.
        if op in ("contains", "!contains", "starts", "ends", "regex"):
            hay = str("" if cur is None else cur)
            needle = str("" if rhs is None else rhs)
            if op == "regex":
                try:
                    return re.search(needle, hay) is not None
                except re.error as exc:
                    log_warning(f"invalid regex /{needle}/: {exc}")
                    return False
            h, n = hay.lower(), needle.lower()
            if op == "contains":
                return n in h
            if op == "!contains":
                return n not in h
            if op == "starts":
                return h.startswith(n)
            return h.endswith(n)
        # Boolean comparison when the right-hand side is true/false.
        if op in ("==", "!=") and str(rhs).strip().lower() in ("true", "false"):
            res = self._truthy(cur) == (str(rhs).strip().lower() == "true")
            return res if op == "==" else not res
        a, b = self._coerce(cur), self._coerce(rhs)
        # Fall back to string compare when types differ for ordering ops.
        try:
            if op == "==":
                return a == b or str(cur) == str(rhs)
            if op == "!=":
                return not (a == b or str(cur) == str(rhs))
            if op == ">":
                return a > b
            if op == "<":
                return a < b
            if op == ">=":
                return a >= b
            if op == "<=":
                return a <= b
        except TypeError:
            return False
        return False

    # ── Win32 / ADB conditions added alongside the action handlers ─────────────

    def _app_match(self, params: Dict, log: bool = True) -> bool:
        """Is the target app (ADB package) / window (Win32 title) running now?

        Shared by ``if_app`` and ``wait_app``; ``negate`` is the caller's job.
        ``log=False`` keeps a polling caller from writing a line per probe.
        """
        # Win32: hỏi CỬA SỔ MỤC TIÊU, không phải cửa sổ đang foreground —
        # ở input mode background (mặc định) cửa sổ game hầu như không bao
        # giờ được focus, nên get_current_app() sẽ luôn trả về sai.
        if getattr(self, "_controller", "adb") == "win32":
            # pkgSrc=project ở dự án Win32 = "cửa sổ trong Project settings",
            # tức chỉ cần hỏi nó còn sống; custom = so khớp chuỗi tiêu đề.
            needle = ""
            if str(params.get("pkgSrc") or "").strip().lower() != "project":
                needle = str(self._resolve_value(params.get("package", "")) or "").strip().lower()
            ctrl = getattr(self.auto, "adb", None)
            title = ""
            alive = False
            if ctrl is not None and hasattr(ctrl, "target_title"):
                title = ctrl.target_title() or ""
                alive = bool(title) or bool(getattr(ctrl, "device", None))
            elif ctrl is not None:
                alive = bool(getattr(ctrl, "device", None))
            ok = alive if not needle else (needle in title.lower())
            if log:
                log_info(f"🪟 target window: {title or '(not found)'} → "
                         f"{'matched' if ok else 'not matched'}"
                         + (f" '{needle}'" if needle else ""))
            return ok
        needle = self._node_package(params).lower()
        try:
            if hasattr(self.auto.adb, "clear_info_cache"):
                self.auto.adb.clear_info_cache()
            cur_app = (self.auto.adb.get_current_app() or "").lower()
        except Exception:
            cur_app = ""
        ok = bool(needle) and needle in cur_app
        if log:
            log_info(f"📱 current app: {cur_app or '(?)'} → "
                     f"{'matched' if ok else 'not matched'} '{needle}'")
        return ok

    def _c_wait_app(self, params: Dict) -> bool:
        """Poll ``if_app`` until it holds (or, with ``negate``, stops holding).

        True as soon as the wanted state is reached, False after ``timeout``
        seconds — the crash-detection / "wait for the game to close" loop that
        previously needed loop ∞ + if_app + break.
        """
        negate = bool(params.get("negate", False))
        try:
            timeout = max(0.0, float(params.get("timeout", 30.0)))
        except (TypeError, ValueError):
            timeout = 30.0
        end = time.time() + timeout
        want = "closed" if negate else "running"
        while not self._stop.is_set():
            self._pause.wait()
            if self._app_match(params, log=False) != negate:
                log_info(f"📱 app is {want}")
                return True
            if time.time() >= end:
                log_warning(f"📱 app is not {want} after {timeout:g}s")
                return False
            time.sleep(0.5)
        return False

    def _c_if_screen_on(self, params: Dict) -> bool:
        """ADB: is the device display awake? (the read side of screen_power)."""
        if self._adb_only_blocked("🖥 If screen is on"):
            return False
        negate = self._truthy(params.get("negate", False))
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False != negate
        on = False
        try:
            out = dev.shell("dumpsys power") or ""
            m = re.search(r"mWakefulness=(\w+)", out)
            if m:
                on = m.group(1).strip().lower() == "awake"
            else:
                # Older/AOSP builds: fall back to the display-power state line.
                on = "mScreenOn=true" in out or "Display Power: state=ON" in out
        except Exception as exc:
            log_warning(f"if_screen_on error: {exc}")
            return False != negate
        log_info(f"🖥 screen is {'on' if on else 'off'}")
        return on != negate

    def _c_if_device_size(self, params: Dict) -> bool:
        """ADB: compare the Android screen resolution reported by ``wm size``."""
        if self._adb_only_blocked("📱 If device size", "If window … (size)"):
            return False
        want_w = self._resolve_count(params.get("width", 1920), default=1920)
        want_h = self._resolve_count(params.get("height", 1080), default=1080)
        tolerance = max(0, self._resolve_count(params.get("tolerance", 0), default=0))
        negate = self._truthy(params.get("negate", False))
        try:
            width, height = self.auto.adb.get_screen_size()
        except Exception as exc:
            log_warning(f"📱 failed to read device size: {exc}")
            return False
        width, height = int(width or 0), int(height or 0)
        if width <= 0 or height <= 0:
            log_warning("📱 could not read device size")
            return False
        matches = abs(width - want_w) <= tolerance and abs(height - want_h) <= tolerance
        expected = f"{want_w}×{want_h}" + (f"±{tolerance}" if tolerance else "")
        log_info(f"📱 size {width}×{height}, expected {expected} → "
                 f"{'matched' if matches else 'not matched'}")
        return matches != negate

    def _c_find_image_pos(self, params: Dict) -> bool:
        """Find a template and store its centre in two variables (x / y).

        True when found (and the variables are written); false on a miss, leaving
        the variables untouched so a previous value isn't silently clobbered.
        """
        tpl = self._resolve_template(params.get("template", ""))
        res = self._find_template(
            tpl, threshold=float(params.get("threshold", 0.85)),
            region=self._search_region(params),
        )
        if not res:
            log_info(f"🔍 {os.path.basename(tpl) if tpl else '?'} not found — variables unchanged")
            return False
        x, y = int(res[0]), int(res[1])
        self._last_pos = (x, y)
        nx = str(params.get("nameX", "") or "").strip()
        ny = str(params.get("nameY", "") or "").strip()
        if nx:
            self._set_var(nx, x)
        if ny:
            self._set_var(ny, y)
        log_info(f"🔍 {os.path.basename(tpl) if tpl else '?'} at ({x}, {y})"
                 + (f" → {nx}/{ny}" if (nx or ny) else ""))
        return True

    def _c_wait_stable(self, params: Dict) -> bool:
        """Wait until the screen stops changing (loading/animation settled).

        Compares consecutive frames (optionally only inside the search region);
        the screen counts as stable once the mean absolute pixel difference stays
        under ``tolerance`` for ``settle`` seconds. True when stable, false on
        timeout — so a flow can branch instead of pushing on into an animation.
        """
        import numpy as np
        settle = max(0.1, float(params.get("settle", 1.0) or 1.0))
        timeout = max(settle, float(params.get("timeout", 15.0) or 15.0))
        tol = max(0.0, float(params.get("tolerance", 2.0) or 0))
        region = self._search_region(params)

        def frame():
            img = self.auto.capture_screen()
            if img is None:
                return None
            if region:
                rx, ry, rw, rh = region
                h, w = img.shape[:2]
                img = img[max(0, ry):min(h, ry + rh), max(0, rx):min(w, rx + rw)]
                if img.size == 0:
                    return None
            return img.astype(np.float32)

        end = time.time() + timeout
        prev = frame()
        stable_since: Optional[float] = None
        while not self._stop.is_set():
            self._pause.wait()
            time.sleep(0.2)
            cur = frame()
            if cur is None or prev is None or cur.shape != prev.shape:
                # No frame yet, or the window resized — restart the settle timer.
                prev = cur
                stable_since = None
            else:
                diff = float(np.mean(np.abs(cur - prev)))
                prev = cur
                if diff <= tol:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= settle:
                        log_info(f"🧊 screen stable (Δ={diff:.2f} ≤ {tol:g})")
                        return True
                else:
                    stable_since = None
            if time.time() >= end:
                log_warning(f"🧊 screen not stable after {timeout:g}s")
                return False
        return False
