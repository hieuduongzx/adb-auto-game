"""Template, colour and OCR probes shared by the image/colour/text nodes."""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

from src import utils as _utils
from src.workflow.logs import log_info, log_warning


class VisionHelpers:
    """Find templates/colours/text on the current frame and report overlays."""

    @staticmethod
    def _region(params: Dict) -> tuple:
        return (int(params.get("x", 0)), int(params.get("y", 0)),
                int(params.get("w", 200)), int(params.get("h", 80)))

    @staticmethod
    def _search_region(params: Dict) -> Optional[tuple]:
        """Optional (x, y, w, h) crop to restrict a template search to.

        Reads ``regionX/Y/W/H`` (set by the designer's optional "Vùng tìm" group
        on image nodes). Returns ``None`` when the crop is empty or covers the
        whole screen — i.e. when there's effectively no restriction.
        """
        x = int(params.get("regionX", 0) or 0)
        y = int(params.get("regionY", 0) or 0)
        w = int(params.get("regionW", 0) or 0)
        h = int(params.get("regionH", 0) or 0)
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    def _templates_list(self, params: Dict) -> List[str]:
        """Resolved template paths for an "…_any" node.

        Reads the ``templates`` list param (tolerating a single ``template``
        string for robustness), drops empties, and resolves each to an absolute
        path. Order is preserved so "first match wins" is predictable.
        """
        raw = params.get("templates")
        items: List[str] = []
        if isinstance(raw, (list, tuple)):
            items = [str(x) for x in raw if str(x).strip()]
        elif raw:
            items = [str(raw)]
        if not items and params.get("template"):
            items = [str(params.get("template"))]
        return [self._resolve_template(it) for it in items if it.strip()]

    # ── Match overlay helpers (designer Preview) ─────────────────────────────
    # When report_matches is on, every final template/color/OCR probe emits
    # on_match so the UI can draw the hit box + confidence. Misses still emit
    # the *best* below-threshold location (dashed red) so "why didn't it match?"
    # is visible without re-running in DevScope.

    def _tpl_wh(self, path: str) -> tuple:
        try:
            tpl = self.auto.matcher.load(path)
            if tpl is not None:
                return int(tpl.shape[1]), int(tpl.shape[0])
        except Exception:
            pass
        return 0, 0

    def _rect_from_center(
        self,
        cx: int,
        cy: int,
        conf: float,
        tw: int,
        th: int,
        scale: float = 1.0,
        ok: bool = True,
        label: str = "",
    ) -> Dict[str, Any]:
        sw = max(1, int(tw * scale)) if tw else 24
        sh = max(1, int(th * scale)) if th else 24
        return {
            "x": max(0, int(cx) - sw // 2),
            "y": max(0, int(cy) - sh // 2),
            "w": sw,
            "h": sh,
            "conf": float(conf),
            "ok": bool(ok),
            "label": label or "",
        }

    def _best_match_raw(self, tpl: str, region=None):
        """Best match at any confidence (for fail overlay). Returns matcher tuple
        ``(cx, cy, conf, scale)`` or ``None``."""
        try:
            screen = self.auto.get_latest_screen()
            if screen is None:
                screen = self.auto.capture_screen()
            if screen is None:
                return None
            template = self.auto.matcher.load(tpl)
            if template is None:
                return None
            # threshold just above 0 so a total miss (no valid scale) stays None
            # without requiring a real match.
            return self.auto.matcher.match(
                screen, template, threshold=0.01, multi_scale=False,
                scales=[1.0], region=region,
            )
        except Exception:
            return None

    def _report_template_match(
        self,
        tpl: str,
        res,
        threshold: float,
        region=None,
        label: str = "",
    ) -> None:
        """Emit on_match for one template probe. ``res`` is find_template's
        ``(cx, cy, conf)`` or ``None``."""
        if not self.report_matches:
            return
        name = os.path.basename(tpl or "") or "?"
        tw, th = self._tpl_wh(tpl)
        rects: List[Dict[str, Any]] = []
        ok = False
        conf = 0.0
        if res:
            cx, cy, conf = int(res[0]), int(res[1]), float(res[2])
            ok = conf >= float(threshold)
            rects.append(self._rect_from_center(
                cx, cy, conf, tw, th, 1.0, ok, label or name))
        else:
            best = self._best_match_raw(tpl, region)
            if best:
                cx, cy, conf, scale = best
                rects.append(self._rect_from_center(
                    int(cx), int(cy), float(conf), tw, th, float(scale),
                    False, label or name))
        self._emit("on_match", {
            "rects": rects,
            "ok": ok,
            "threshold": float(threshold),
            "template": name,
            "label": label or name,
            "region": list(region) if region else None,
            "conf": float(conf) if rects else 0.0,
        })

    def _report_match_rects(
        self,
        rects: List[Dict[str, Any]],
        *,
        ok: bool,
        threshold: float = 0.0,
        label: str = "",
        region=None,
        conf: float = 0.0,
    ) -> None:
        if not self.report_matches:
            return
        self._emit("on_match", {
            "rects": rects,
            "ok": ok,
            "threshold": float(threshold),
            "template": label,
            "label": label,
            "region": list(region) if region else None,
            "conf": float(conf),
        })

    def _report_ocr_region(self, region, ok: bool, needle: str = "") -> None:
        """Highlight the OCR search box after a text probe (no char boxes)."""
        if not self.report_matches:
            return
        rects: List[Dict[str, Any]] = []
        if region and len(region) >= 4:
            x, y, w, h = (int(region[0]), int(region[1]),
                          int(region[2]), int(region[3]))
            if w > 0 and h > 0:
                rects.append({
                    "x": x, "y": y, "w": w, "h": h,
                    "conf": 1.0 if ok else 0.0,
                    "ok": bool(ok),
                    "label": (needle or "OCR")[:24],
                })
        self._report_match_rects(
            rects, ok=bool(ok), label=needle or "OCR",
            region=region, conf=1.0 if ok else 0.0,
        )

    def _find_template(self, tpl: str, threshold: float = 0.85, region=None,
                       report: bool = True):
        """find_template + optional match overlay report."""
        res = self.auto.find_template(tpl, threshold=threshold, region=region)
        if report:
            self._report_template_match(tpl, res, threshold, region)
        return res

    def _wait_for_template(
        self,
        tpl: str,
        timeout: float = 10.0,
        threshold: float = 0.85,
        region=None,
        report: bool = True,
    ):
        """Poll for *tpl* until found or *timeout*; one overlay report at the end.

        Polled here rather than through ``auto.wait_for_template``: that helper
        cannot see the workflow's Pause, so a paused Tap image kept looking and
        tapped the moment its image appeared — mid-pause.
        """
        res = self._poll(lambda: self.auto.find_template(tpl, threshold=threshold, region=region),
                         timeout, interval=0.5)
        if report:
            self._report_template_match(tpl, res, threshold, region)
        return res

    def _find_any(self, templates: List[str], threshold: float, region=None):
        """(x, y) of the first listed template currently on screen, or ``None``.
        Sequential: stops at the first match (list order is the priority order).
        One frame per round: every probe judges the same pixels, and we pay one
        capture instead of one per template."""
        if not templates:
            return None
        screen = self.auto.capture_screen()
        if screen is None:
            self._report_template_match(templates[0], None, threshold, region)
            return None
        for tpl in templates:
            # report only the winner (or the first miss below)
            res = self.auto.find_template(tpl, threshold=threshold, region=region, screen=screen)
            if res:
                self._report_template_match(tpl, res, threshold, region)
                return (res[0], res[1])
        self._report_template_match(templates[0], None, threshold, region)
        return None

    def _find_any_parallel(self, templates: List[str], threshold: float, region=None):
        """Check all templates concurrently; return position of whichever matches first.
        Unlike the sequential variant, list order does NOT determine priority —
        the template actually visible on screen wins. All probes share one
        captured frame, so "on screen" is measured on the same snapshot."""
        if not templates:
            return None
        screen = self.auto.capture_screen()
        if screen is None:
            return None
        results: List = []
        lock = threading.Lock()

        def check(tpl: str) -> None:
            try:
                res = self.auto.find_template(tpl, threshold=threshold, region=region, screen=screen)
                if res:
                    with lock:
                        results.append((tpl, res[0], res[1], res[2]))
            except Exception as e:
                _utils.log_debug(f"[find_any_parallel] {tpl}: {e}")

        threads = [threading.Thread(target=check, args=(tpl,), daemon=True)
                   for tpl in templates]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if results:
            tpl, x, y, conf = results[0]
            self._report_template_match(tpl, (x, y, conf), threshold, region)
            return (x, y)
        self._report_template_match(templates[0], None, threshold, region)
        return None

    def _wait_any(self, templates: List[str], timeout: float, threshold: float,
                  parallel: bool = False, region=None):
        """Poll until ANY listed template appears, or ``timeout``. Pause/stop aware.

        ``wait_for_template`` waits on one specific image, so for an OR-over-images
        we poll ``find_template`` across the whole list each round instead.
        When ``parallel=True`` all templates are checked concurrently each round.
        """
        if not templates:
            return None
        finder = self._find_any_parallel if parallel else self._find_any
        return self._poll(lambda: finder(templates, threshold, region=region), timeout, interval=0.25)

    def _poll(self, probe, timeout: float, interval: float = 0.25):
        """Call *probe* until it returns something truthy, or *timeout* runs out.

        Stop ends the wait at once (``None``). Pause holds it — no probe runs
        while paused — and the time spent paused does not count against the
        timeout, so a resumed wait gets the rest of its budget back.
        """
        left = max(0.0, float(timeout))
        while not self._stop.is_set() and not self._background_cancelled():
            if not self._pause.is_set():
                if not self._wait_to_run():
                    return None
                continue
            started = time.monotonic()
            hit = probe()
            if hit:
                return hit
            if left <= 0:
                return None
            nap = min(interval, left)
            time.sleep(nap)
            left -= max(nap, time.monotonic() - started)
        return None

    # ── Color (pixel) helpers ────────────────────────────────────────────────

    @staticmethod
    def _parse_hex_color(raw: Any) -> Optional[tuple]:
        """``#RRGGBB`` (hash optional) → an ``(b, g, r)`` tuple, or ``None``."""
        s = str(raw or "").strip().lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
            return None
        return (int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16))

    @staticmethod
    def _bgr_to_hex(px) -> str:
        return "#{:02x}{:02x}{:02x}".format(int(px[2]), int(px[1]), int(px[0]))

    def _pixel_at(self, x: int, y: int) -> Optional[tuple]:
        """The screen's BGR pixel at (x, y), or ``None`` (no frame / off-screen)."""
        screen = self.auto.capture_screen()
        if screen is None:
            return None
        h, w = screen.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            log_warning(f"point ({x}, {y}) is outside the {w}×{h} screen")
            return None
        return tuple(int(c) for c in screen[y, x][:3])

    @staticmethod
    def _color_close(px: tuple, target: tuple, tol: int) -> bool:
        """True when every BGR channel differs by at most ``tol``."""
        return all(abs(int(a) - int(b)) <= tol for a, b in zip(px, target))

    def _find_color(self, target: tuple, tol: int, region=None) -> Optional[tuple]:
        """(x, y) of the first pixel matching ``target``±``tol``, or ``None``.

        Scans top-to-bottom / left-to-right (first match wins) over the whole
        frame or an optional ``(x, y, w, h)`` crop.
        """
        import numpy as np
        screen = self.auto.capture_screen()
        if screen is None:
            return None
        ox = oy = 0
        if region:
            rx, ry, rw, rh = region
            h, w = screen.shape[:2]
            rx, ry = max(0, rx), max(0, ry)
            screen = screen[ry:min(h, ry + rh), rx:min(w, rx + rw)]
            if screen.size == 0:
                return None
            ox, oy = rx, ry
        mask = np.all(np.abs(screen[:, :, :3].astype(np.int16) - np.int16(target)) <= tol, axis=2)
        hits = np.argwhere(mask)
        if not len(hits):
            return None
        y, x = hits[0]
        return (int(x) + ox, int(y) + oy)

    @staticmethod
    def _color_anywhere(params: Dict) -> bool:
        """``where`` = "anywhere" scans the search region; default checks one point."""
        return str(params.get("where", "point") or "point").strip().lower() == "anywhere"

    def _color_probe(self, target: tuple, tol: int, params: Dict):
        """One look at the screen for a colour node → ``(ok, x, y, region)``.

        ``where=point`` (default) tests the pixel at x/y; ``where=anywhere``
        scans the optional search region and reports where the first match sits.
        On a miss (x, y) is the point that was tested (0,0 when scanning).
        """
        if self._color_anywhere(params):
            region = self._search_region(params)
            hit = self._find_color(target, tol, region=region)
            return (hit is not None,
                    int(hit[0]) if hit else 0, int(hit[1]) if hit else 0, region)
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        px = self._pixel_at(x, y)
        return (px is not None and self._color_close(px, target, tol), x, y, None)

    def _color_rects(self, ok: bool, x: int, y: int, label: str, hit: bool = False) -> list:
        """Preview overlay rect for a colour probe (``hit`` = draw it as a success)."""
        return [self._rect_from_center(x, y, 1.0 if ok else 0.0, 18, 18, 1.0,
                                       ok or hit, label)]

    def _eval_color_condition(self, ntype: str, params: Dict) -> bool:
        target = self._parse_hex_color(params.get("color"))
        if target is None:
            log_warning(f"'{ntype}': invalid color ({params.get('color')!r}) — expected #RRGGBB")
            return False
        tol = max(0, int(params.get("tolerance", 10) or 0))
        if ntype == "if_color":
            negate = self._truthy(params.get("negate", False))
            ok, x, y, region = self._color_probe(target, tol, params)
            if ok:
                # Lưu vị trí "found" như các node ảnh — để "Tap → last found
                # image" sau một node màu chạm đúng điểm vừa kiểm tra.
                self._last_pos = (x, y)
            hex_lbl = self._bgr_to_hex(target)
            self._report_match_rects(
                self._color_rects(ok, x, y, hex_lbl),
                ok=ok != negate, label=hex_lbl, region=region, conf=1.0 if ok else 0.0,
            )
            return ok != negate
        if ntype == "wait_color":
            negate = self._truthy(params.get("negate", False))
            anywhere = self._color_anywhere(params)
            end = time.time() + max(0.0, float(params.get("timeout", 10.0)))
            hex_lbl = self._bgr_to_hex(target)
            while not self._stop.is_set():
                self._pause.wait()
                ok, x, y, region = self._color_probe(target, tol, params)
                where = "in the region" if anywhere else f"at ({x}, {y})"
                if ok and not negate:
                    self._last_pos = (x, y)
                    log_info(f"🎨 found color {hex_lbl} " + (f"at ({x}, {y})" if anywhere else where))
                    self._report_match_rects(
                        self._color_rects(True, x, y, hex_lbl),
                        ok=True, label=hex_lbl, region=region, conf=1.0,
                    )
                    return True
                if negate and not ok:
                    # Đảo: chờ đến khi màu BIẾN MẤT (nút sáng → tối, loading xong…).
                    log_info(f"🎨 color {hex_lbl} disappeared {where}")
                    self._report_match_rects(
                        self._color_rects(False, x, y, hex_lbl, hit=True),
                        ok=True, label=hex_lbl, region=region, conf=0.0,
                    )
                    return True
                if time.time() >= end:
                    self._report_match_rects(
                        self._color_rects(False, x, y, hex_lbl),
                        ok=False, label=hex_lbl, region=region, conf=0.0,
                    )
                    return False
                time.sleep(0.25)
            return False
        if ntype == "tap_color":
            region = self._search_region(params)
            end = time.time() + max(0.0, float(params.get("timeout", 10.0)))
            hex_lbl = self._bgr_to_hex(target)
            while not self._stop.is_set():
                self._pause.wait()
                hit = self._find_color(target, tol, region=region)
                if hit:
                    self._last_pos = hit
                    self._report_match_rects(
                        [self._rect_from_center(hit[0], hit[1], 1.0, 18, 18, 1.0, True, hex_lbl)],
                        ok=True, label=hex_lbl, region=region, conf=1.0,
                    )
                    if not self._wait_after_find(params):
                        return False
                    return self._tap_at(hit[0], hit[1], params, label=f"color {hex_lbl}")
                if time.time() >= end:
                    self._report_match_rects(
                        [], ok=False, label=hex_lbl, region=region, conf=0.0,
                    )
                    return False  # colour never appeared — false branch fires
                time.sleep(0.25)
            return False
        return False

    def _a_read_color(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        px = self._pixel_at(int(p.get("x", 0)), int(p.get("y", 0)))
        value = self._bgr_to_hex(px) if px is not None else ""
        if name:
            self._set_var(name, value)
            log_info(f"🎨 {name} = {value or '(unreadable)'}")
        return True

    @staticmethod
    def _ocr_whitelist(params: Dict) -> Optional[str]:
        """The node's optional OCR character whitelist ('' → None)."""
        wl = str(params.get("whitelist", "") or "").strip()
        return wl or None

    # ── loop_until family ──────────────────────────────────────────────────────
    # loop_until_image/color/text/var share the walk logic in _walk; only the
    # per-iteration probe differs. Each probe returns True when the loop should
    # exit through "found".

    def _loop_until_label(self, ntype: str, params: Dict) -> str:
        """Short human label of what the loop is waiting for (log lines)."""
        if ntype == "loop_until_color":
            return f"found color {params.get('color') or '?'}"
        if ntype == "loop_until_text":
            if str(params.get("match", "text")).strip().lower() == "pattern":
                return f"found text /{params.get('pattern') or ''}/"
            return f"found text \"{params.get('text') or ''}\""
        if ntype == "loop_until_var":
            return (f"variable {params.get('name') or '?'} "
                    f"{params.get('op') or '=='} {params.get('value')}")
        tpl = str(params.get("template") or "")
        return f"found image {os.path.basename(tpl) if tpl else '?'}"

    def _loop_until_hit(self, ntype: str, params: Dict) -> bool:
        """One probe of a loop_until node's exit condition."""
        if ntype == "loop_until_color":
            target = self._parse_hex_color(params.get("color"))
            if target is None:
                log_warning(f"loop_until_color: invalid color "
                            f"({params.get('color')!r}) — expected #RRGGBB")
                return False
            tol = max(0, int(params.get("tolerance", 10) or 0))
            hex_lbl = self._bgr_to_hex(target)
            # "anywhere" quét cả vùng tìm; mặc định kiểm 1 điểm x/y như if_color.
            ok, x, y, region = self._color_probe(target, tol, params)
            if ok:
                self._last_pos = (x, y)
            self._report_match_rects(
                self._color_rects(ok, x, y, hex_lbl),
                ok=ok, label=hex_lbl, region=region, conf=1.0 if ok else 0.0,
            )
            return ok
        if ntype == "loop_until_text":
            needle, regex = self._ocr_needle(params)
            region = self._region(params)
            found, _read = self.auto.region_find_text(
                needle, region=region, whitelist=self._ocr_whitelist(params),
                regex=regex)
            self._report_ocr_region(region, bool(found), needle)
            return bool(found)
        if ntype == "loop_until_var":
            cur = self._vars.get(str(params.get("name", "")))
            rhs = self._resolve_value(params.get("value", ""))
            return self._compare(cur, str(params.get("op", "==")), rhs)
        # loop_until_image (default)
        tpl = self._resolve_template(params.get("template", ""))
        res = self._find_template(
            tpl, threshold=float(params.get("threshold", 0.85)),
            region=self._search_region(params),
            report=True,  # live overlay each probe on designer
        )
        if res:
            self._last_pos = (res[0], res[1])
            return True
        return False
