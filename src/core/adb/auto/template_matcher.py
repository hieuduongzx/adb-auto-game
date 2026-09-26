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

    def __init__(self, cache_size: int = 100):
        self._cache: Dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()
        self._max_cache_size = cache_size
    
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
    ) -> Optional[Tuple[int, int, float, float]]:
        """
        Match template in screen

        Returns:
            Tuple of (center_x, center_y, confidence, scale) or None

        ``region``: optional (x, y, w, h) crop of the screen (device coords) to
        search within. Tames false positives when the same icon appears in many
        places. Coordinates in the returned match are mapped back to full-screen.
        """
        try:
            if use_grayscale and len(screen.shape) == 3:
                screen_processed = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            else:
                screen_processed = screen
            # asarray avoids copying when the inputs are already uint8 (they
            # always are from screencap) — matchTemplate only reads them.
            screen_processed = np.asarray(screen_processed, dtype=np.uint8)
            template = np.asarray(template, dtype=np.uint8)

            # Region crop: restrict the search to a sub-rectangle of the screen.
            # Coords are clamped to the screen bounds; empty/zero-area → full screen.
            reg_x = reg_y = 0
            if region is not None:
                rx, ry, rw, rh = region
                sh, sw = screen_processed.shape[:2]
                rx = max(0, int(rx)); ry = max(0, int(ry))
                rw = max(0, int(rw)); rh = max(0, int(rh))
                rx2 = min(sw, rx + rw); ry2 = min(sh, ry + rh)
                if rx2 > rx and ry2 > ry and (rx2 - rx) < sw and (ry2 - ry) < sh:
                    screen_processed = screen_processed[ry:ry2, rx:rx2]
                    reg_x, reg_y = rx, ry

            best_match = None
            best_confidence = 0.0
            best_scale = 1.0
            scale_list = scales if (multi_scale and scales) else [1.0]

            for scale in scale_list:
                if scale != 1.0:
                    h, w = template.shape[:2]
                    new_w, new_h = int(w * scale), int(h * scale)
                    if new_w > screen_processed.shape[1] or new_h > screen_processed.shape[0]:
                        continue
                    if new_w < self._MIN_TEMPLATE_SIDE or new_h < self._MIN_TEMPLATE_SIDE:
                        continue
                    template_scaled = cv2.resize(
                        template, (new_w, new_h), interpolation=cv2.INTER_AREA
                    )
                else:
                    template_scaled = template

                result = cv2.matchTemplate(
                    screen_processed, template_scaled, cv2.TM_CCOEFF_NORMED
                )
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val > best_confidence:
                    best_confidence = max_val
                    best_match = max_loc
                    best_scale = scale

            if best_confidence >= threshold:
                # Calculate center point (mapped back to full-screen coords).
                h, w = template.shape[:2]
                center_x = int(best_match[0] + (w * best_scale) // 2) + reg_x
                center_y = int(best_match[1] + (h * best_scale) // 2) + reg_y

                return (center_x, center_y, best_confidence, best_scale)

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
    ) -> List[Tuple[int, int, float]]:
        """
        Find all template matches in screen
        
        Returns:
            List of (center_x, center_y, confidence) tuples
        """
        try:
            if use_grayscale and len(screen.shape) == 3:
                screen_processed = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            else:
                screen_processed = screen
            screen_processed = np.asarray(screen_processed, dtype=np.uint8)
            template = np.asarray(template, dtype=np.uint8)

            result = cv2.matchTemplate(
                screen_processed, template, cv2.TM_CCOEFF_NORMED
            )
            ys, xs = np.where(result >= threshold)
            if not len(xs):
                return []

            template_h, template_w = template.shape[:2]
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
            for x, y, confidence in candidates:
                gx, gy = x // cell, y // cell
                if any((x - ex) ** 2 + (y - ey) ** 2 < min_distance ** 2
                       for ix in (gx - 1, gx, gx + 1)
                       for iy in (gy - 1, gy, gy + 1)
                       for ex, ey in occupied.get((ix, iy), ())):
                    continue
                occupied.setdefault((gx, gy), []).append((x, y))
                matches.append((x, y, confidence))

            if len(matches) > 10:
                log_warning(f"Found {len(matches)} matches - possible false positives")
            else:
                log_info(f"Found {len(matches)} instances")
            
            return matches
            
        except Exception as e:
            log_error(f"Error finding all templates: {e}")
            return []
