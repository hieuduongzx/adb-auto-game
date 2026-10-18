"""
Template matching functionality
"""
import cv2
import numpy as np
import threading
from typing import Tuple, Optional, List, Dict
from src.utils import log_error, log_info, log_warning
from src.utils.asset_crypto import maybe_decrypt


class TemplateMatcher:
    """Handles template loading and matching operations"""

    # A scaled template smaller than this on either side is skipped — too few
    # pixels to match reliably.
    _MIN_TEMPLATE_SIDE = 10

    # Coarse-to-fine search: templates at least this big on their short side
    # are first looked for on a half-size frame (they keep >= 12 px there),
    # and only frames at least this big bother — below it a full search is
    # already cheap.
    _PYRAMID_MIN_TEMPLATE_SIDE = 24
    _PYRAMID_MIN_SCREEN_AREA = 640 * 360
    # Coarse candidates refined at full size, and the slack (px) around each.
    _TOP_K = 3
    _REFINE_PAD = 6
    # A coarse score this far under the threshold is a confident miss.
    _COARSE_MARGIN = 0.2
    # A hit at least this good ends a multi-scale sweep early.
    _EARLY_EXIT_CONF = 0.95

    # Flat (single-colour) templates: per-channel std below this, scored by
    # RMS colour distance where a difference of _FLAT_RMS_SPAN levels is 0.0.
    _FLAT_STD = 3.0
    _FLAT_RMS_SPAN = 50.0

    # Hue check: max allowed difference in mean chromaticity (a channel's
    # share of the brightness), skipped for windows darker than the floor.
    _HUE_TOLERANCE = 0.12
    _HUE_MIN_BRIGHTNESS = 40.0

    def __init__(self, cache_size: int = 100):
        self._cache: Dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()
        self._max_cache_size = cache_size
        self._flat_warned: set = set()

    def load(self, template_path: str, grayscale: bool = False) -> Optional[np.ndarray]:
        """Load template image with caching"""
        cache_key = f"{template_path}_{grayscale}"

        # Check cache first
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key].copy()

        # Load from disk. Read raw bytes (not cv2.imread's own file path) so a
        # packaged Runner's encrypted templates (see src/utils/asset_crypto.py)
        # decrypt transparently; a plain file (source/Designer) round-trips
        # through maybe_decrypt as a no-op.
        try:
            with open(template_path, "rb") as fh:
                raw = fh.read()
            buf = np.frombuffer(maybe_decrypt(raw), dtype=np.uint8)
            flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
            template = cv2.imdecode(buf, flag)

            if template is None:
                log_error(f"Could not load template: {template_path}")
                return None

            # Cache it
            with self._cache_lock:
                if len(self._cache) >= self._max_cache_size:
                    # Remove oldest entry (FIFO)
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]

                self._cache[cache_key] = template.copy()

            return template

        except Exception as e:
            log_error(f"Error loading template {template_path}: {e}")
            return None

    def match(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        threshold: float = 0.8,
        use_grayscale: bool = False,
        multi_scale: bool = False,
        scales: Optional[List[float]] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        verify_color: bool = True,
    ) -> Optional[Tuple[int, int, float, float]]:
        """
        Match template in screen

        Returns:
            Tuple of (center_x, center_y, confidence, scale) or None

        ``region``: optional (x, y, w, h) crop of the screen (device coords) to
        search within. Tames false positives when the same icon appears in many
        places. Coordinates in the returned match are mapped back to full-screen.

        ``verify_color``: reject a hit whose overall hue differs from the
        template's (see ``_same_hue``). Callers after the raw best location at
        any confidence (miss overlays) turn it off.
        """
        try:
            color_screen, reg_x, reg_y = self._crop(screen, region)
            screen_processed, template = self._prepare(color_screen, template, use_grayscale)
            check_hue = verify_color and screen_processed.ndim == 3

            best: Optional[Tuple[float, int, int, float]] = None   # conf, x, y, scale
            coarse_screen = None
            scale_list = scales if (multi_scale and scales) else [1.0]

            for scale in scale_list:
                if scale != 1.0:
                    h, w = template.shape[:2]
                    new_w, new_h = int(w * scale), int(h * scale)
                    if new_w < self._MIN_TEMPLATE_SIDE or new_h < self._MIN_TEMPLATE_SIDE:
                        continue
                    template_scaled = cv2.resize(
                        template, (new_w, new_h), interpolation=cv2.INTER_AREA
                    )
                else:
                    template_scaled = template
                th, tw = template_scaled.shape[:2]
                if tw > screen_processed.shape[1] or th > screen_processed.shape[0]:
                    continue

                if self._use_pyramid(screen_processed, template_scaled):
                    if coarse_screen is None:
                        coarse_screen = self._half(screen_processed)
                    candidates = self._coarse_to_fine(
                        screen_processed, coarse_screen, template_scaled, threshold)
                else:
                    candidates = self._peaks(
                        self._score_map(screen_processed, template_scaled), tw, th)

                # Best candidate first; one that clears the threshold but has
                # the wrong hue gives way to the runner-up.
                for conf, x, y in candidates:
                    if best is not None and conf <= best[0]:
                        break
                    if (check_hue and conf >= threshold
                            and not self._same_hue(color_screen[y:y + th, x:x + tw],
                                                   template_scaled)):
                        continue
                    best = (conf, x, y, scale)
                    break

                # Nothing at another scale can beat a near-perfect hit by
                # enough to matter — skip the rest of the sweep.
                if best is not None and best[0] >= max(threshold, self._EARLY_EXIT_CONF):
                    break

            if best is not None and best[0] >= threshold:
                conf, x, y, scale = best
                # Calculate center point (mapped back to full-screen coords).
                h, w = template.shape[:2]
                center_x = int(x + (w * scale) // 2) + reg_x
                center_y = int(y + (h * scale) // 2) + reg_y
                return (center_x, center_y, float(conf), scale)

            return None

        except Exception as e:
            log_error(f"Error in template matching: {e}")
            return None

    def match_all(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        threshold: float = 0.8,
        use_grayscale: bool = False,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[Tuple[int, int, float]]:
        """
        Find all template matches in screen

        Returns:
            List of (center_x, center_y, confidence) tuples

        ``region`` restricts the search like :meth:`match`; returned centres
        are in full-screen coordinates.
        """
        try:
            color_screen, reg_x, reg_y = self._crop(screen, region)
            screen_processed, template = self._prepare(color_screen, template, use_grayscale)
            template_h, template_w = template.shape[:2]
            if (template_w > screen_processed.shape[1]
                    or template_h > screen_processed.shape[0]):
                return []

            result = self._score_map(screen_processed, template)
            ys, xs = np.where(result >= threshold)
            if not len(xs):
                return []

            # Cap raw hits before building tuples — a permissive threshold can
            # match a large share of the screen, and sorting millions of points
            # just to have NMS drop them is wasted work.
            vals = result[ys, xs]
            if len(vals) > 5000:
                idx = np.argpartition(vals, -5000)[-5000:]
                ys, xs, vals = ys[idx], xs[idx], vals[idx]
            candidates = [
                (int(x) + template_w // 2, int(y) + template_h // 2, float(v))
                for x, y, v in zip(xs, ys, vals)
            ]
            candidates.sort(key=lambda c: c[2], reverse=True)

            # Greedy non-maximum suppression on a spatial grid: keep the
            # highest-confidence hit, drop any later hit within ~one template
            # of it. Cells sized at the suppression radius make the "already
            # covered?" check look at 9 cells instead of every kept match.
            min_distance = max(template_w, template_h) * 0.8
            cell = max(1, int(min_distance))
            occupied: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
            matches = []
            check_hue = screen_processed.ndim == 3
            for x, y, confidence in candidates:
                gx, gy = x // cell, y // cell
                if any((x - ex) ** 2 + (y - ey) ** 2 < min_distance ** 2
                       for ix in (gx - 1, gx, gx + 1)
                       for iy in (gy - 1, gy, gy + 1)
                       for ex, ey in occupied.get((ix, iy), ())):
                    continue
                if check_hue:
                    left, top = x - template_w // 2, y - template_h // 2
                    patch = color_screen[top:top + template_h, left:left + template_w]
                    if not self._same_hue(patch, template):
                        continue
                occupied.setdefault((gx, gy), []).append((x, y))
                matches.append((x + reg_x, y + reg_y, confidence))

            if len(matches) > 10:
                log_warning(f"Found {len(matches)} matches - possible false positives")
            else:
                log_info(f"Found {len(matches)} instances")

            return matches

        except Exception as e:
            log_error(f"Error finding all templates: {e}")
            return []

    # ── Matching internals ────────────────────────────────────────────────────

    @staticmethod
    def _crop(screen: np.ndarray, region) -> Tuple[np.ndarray, int, int]:
        """``screen`` cropped to ``region`` (x, y, w, h), plus the crop's
        offset. Coords are clamped to the screen; an empty or whole-screen
        region leaves the screen as is."""
        # asarray avoids copying when the inputs are already uint8 (they
        # always are from screencap) — matchTemplate only reads them.
        screen = np.asarray(screen, dtype=np.uint8)
        if region is None:
            return screen, 0, 0
        rx, ry, rw, rh = region
        sh, sw = screen.shape[:2]
        rx = max(0, int(rx)); ry = max(0, int(ry))
        rw = max(0, int(rw)); rh = max(0, int(rh))
        rx2 = min(sw, rx + rw); ry2 = min(sh, ry + rh)
        if rx2 > rx and ry2 > ry and (rx2 - rx, ry2 - ry) != (sw, sh):
            return screen[ry:ry2, rx:rx2], rx, ry
        return screen, 0, 0

    @staticmethod
    def _prepare(screen: np.ndarray, template: np.ndarray,
                 use_grayscale: bool) -> Tuple[np.ndarray, np.ndarray]:
        """Screen and template in the same colour space (grey when asked)."""
        template = np.asarray(template, dtype=np.uint8)
        if use_grayscale and screen.ndim == 3:
            screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        if template.ndim == 3 and screen.ndim == 2:
            template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        return screen, template

    @staticmethod
    def _half(image: np.ndarray) -> np.ndarray:
        return cv2.resize(image, (image.shape[1] // 2, image.shape[0] // 2),
                          interpolation=cv2.INTER_AREA)

    @staticmethod
    def _channel_stats(image: np.ndarray, fn) -> np.ndarray:
        channels = image.shape[2] if image.ndim == 3 else 1
        return fn(image.reshape(-1, channels), axis=0)

    def _is_flat(self, template: np.ndarray) -> bool:
        """True for a (near) single-colour template. Normalised correlation
        divides by the template's variance, so a flat crop scores 1.0 against
        *every* window of the screen — it would match anywhere."""
        return bool(np.all(self._channel_stats(template, np.std) < self._FLAT_STD))

    def _use_pyramid(self, screen: np.ndarray, template: np.ndarray) -> bool:
        th, tw = template.shape[:2]
        sh, sw = screen.shape[:2]
        return (min(th, tw) >= self._PYRAMID_MIN_TEMPLATE_SIDE
                and sw * sh >= self._PYRAMID_MIN_SCREEN_AREA
                and not self._is_flat(template))

    def _score_map(self, screen: np.ndarray, template: np.ndarray) -> np.ndarray:
        """Confidence at every position, higher is better.

        Normal templates use ``TM_CCOEFF_NORMED``. Flat ones would score 1.0
        everywhere under it, so they are scored by RMS colour distance
        instead: identical is 1.0, ``_FLAT_RMS_SPAN`` levels off is 0.0.
        """
        if not self._is_flat(template):
            return cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        key = (template.shape,
               tuple(int(v) for v in self._channel_stats(template, np.mean)))
        if key not in self._flat_warned:
            self._flat_warned.add(key)
            log_warning("Template is a single flat colour; matching it by colour "
                        "distance. Crop some edges or detail into it for a reliable match")
        sq = cv2.matchTemplate(screen.astype(np.float32),
                               template.astype(np.float32), cv2.TM_SQDIFF)
        rms = np.sqrt(np.maximum(sq, 0) / float(template.size))
        return 1.0 - rms / self._FLAT_RMS_SPAN

    def _peaks(self, result: np.ndarray, tw: int, th: int) -> List[Tuple[float, int, int]]:
        """Top-``_TOP_K`` peaks of a score map, best first, each at least half
        a template from the others — so a runner-up is a different place, not
        the flank of the winner."""
        result = result.copy()
        rx, ry = max(1, tw // 2), max(1, th // 2)
        out: List[Tuple[float, int, int]] = []
        for _ in range(self._TOP_K):
            _, max_val, _, (x, y) = cv2.minMaxLoc(result)
            if not np.isfinite(max_val) or max_val <= -2.0:
                break
            out.append((float(max_val), int(x), int(y)))
            result[max(0, y - ry):y + ry + 1, max(0, x - rx):x + rx + 1] = -np.inf
        return out

    def _coarse_to_fine(self, screen: np.ndarray, coarse_screen: np.ndarray,
                        template: np.ndarray, threshold: float) -> List[Tuple[float, int, int]]:
        """Find candidates on the half-size frame, then re-score each at full
        size in a small window around it — about a quarter of the work of a
        full-size search, and it lands on the same pixel.

        When even the best coarse score is far under ``threshold`` it is a
        confident miss: only that spot is refined, so miss overlays still show
        where the nearest look-alike was.
        """
        th, tw = template.shape[:2]
        sh, sw = screen.shape[:2]
        coarse_tpl = self._half(template)
        if coarse_tpl.shape[1] > coarse_screen.shape[1] or coarse_tpl.shape[0] > coarse_screen.shape[0]:
            return self._peaks(self._score_map(screen, template), tw, th)
        coarse = cv2.matchTemplate(coarse_screen, coarse_tpl, cv2.TM_CCOEFF_NORMED)
        peaks = self._peaks(coarse, coarse_tpl.shape[1], coarse_tpl.shape[0])
        if peaks and peaks[0][0] < threshold - self._COARSE_MARGIN:
            peaks = peaks[:1]
        pad = self._REFINE_PAD
        refined: List[Tuple[float, int, int]] = []
        for _, cx, cy in peaks:
            x0 = max(0, cx * 2 - pad); y0 = max(0, cy * 2 - pad)
            x1 = min(sw, cx * 2 + tw + pad); y1 = min(sh, cy * 2 + th + pad)
            if x1 - x0 < tw or y1 - y0 < th:
                continue
            fine = cv2.matchTemplate(screen[y0:y1, x0:x1], template, cv2.TM_CCOEFF_NORMED)
            _, val, _, (fx, fy) = cv2.minMaxLoc(fine)
            refined.append((float(val), x0 + fx, y0 + fy))
        refined.sort(key=lambda c: c[0], reverse=True)
        return refined

    def _same_hue(self, patch: np.ndarray, template: np.ndarray) -> bool:
        """Do the matched window and the template share the same overall hue?

        Correlation ignores brightness and contrast by design, which also makes
        it half colour-blind: a greyed-out (disabled) button scores ~0.7
        against its red template. Comparing mean chromaticity — each channel's
        share of the brightness — catches that, while a dimmed or brightened
        copy of the same colour (a popup's backdrop, a glow) keeps its
        chromaticity and still passes. Dark windows carry no reliable colour,
        so they always pass.
        """
        if patch.shape != template.shape or patch.ndim != 3:
            return True
        mp = self._channel_stats(patch, np.mean)
        mt = self._channel_stats(template, np.mean)
        sp, st = float(mp.sum()), float(mt.sum())
        if min(sp, st) / 3 < self._HUE_MIN_BRIGHTNESS:
            return True
        return float(np.abs(mp / sp - mt / st).max()) <= self._HUE_TOLERANCE
