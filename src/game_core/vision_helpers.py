"""Template-path and colored-state vision helpers, mixed into BaseGameAutomation."""
import os
from typing import List, Optional, Tuple

import cv2

from src.utils import log_error, log_info, log_warning

Region = Tuple[int, int, int, int]


class VisionHelperMixin:
    """Template-path helpers + a post-match "is this button colored?" check.

    matchTemplate compares shape only, so a grayed-out (disabled) button still
    matches its colored template. :meth:`is_button_active` disambiguates by
    comparing the count of strongly-saturated pixels in the ROI vs. the
    template — that ratio collapses to ~0 when the button is desaturated.
    """

    # Pixels with HSV saturation >= this value are treated as "colored".
    # 80 keeps us comfortably above noisy near-gray pixels (typically <40)
    # while still catching pastel UI elements.
    _COLORED_PIXEL_SAT_THRESHOLD = 80

    # Below this many colored pixels a template carries too little color for the
    # active/disabled ratio to mean anything (e.g. a white-on-dark icon), so the
    # check fails open instead.
    _MIN_TEMPLATE_COLORED_PIXELS = 50

    # Re-exported so existing ``BaseGameAutomation.Region`` annotations resolve.
    Region = Region

    # ==================== Template / Region Helpers ====================

    def get_template_path(self, template_name: str) -> str:
        """Get full path to a template image."""
        return os.path.join(self.templates_dir, template_name)

    def template_exists(self, template_name: str) -> bool:
        """Check if a template file exists."""
        return os.path.exists(self.get_template_path(template_name))

    @staticmethod
    def region_center(region: Region) -> Tuple[int, int]:
        """Return the ``(cx, cy)`` center of a ``(x, y, w, h)`` region."""
        x, y, w, h = region
        return (x + w // 2, y + h // 2)

    def ensure_templates_exist(self, template_names: List[str]) -> bool:
        """Ensure all required templates exist."""
        missing = [name for name in template_names if not self.template_exists(name)]
        if missing:
            log_error(f"Missing templates: {missing}")
            return False
        return True

    # ==================== Color / Active-State Helpers ====================

    @staticmethod
    def _colored_pixel_count(img_bgr, sat_threshold: int) -> int:
        """Count pixels in a BGR image whose HSV saturation is >= threshold."""
        if img_bgr is None or len(img_bgr.shape) < 3:
            return 0
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        return int((hsv[:, :, 1] >= sat_threshold).sum())

    def is_button_active(
        self,
        template_path: str,
        center: Tuple[int, int],
        min_color_ratio: float = 0.4,
        sat_threshold: Optional[int] = None,
    ) -> bool:
        """Whether the matched button looks colored (active) vs. grayed-out.

        Compares ``colored(roi) / colored(template)`` against ``min_color_ratio``.
        Returns ``False`` when it looks gray or the check can't run (treat as
        "don't tap").
        """
        screen = self.get_latest_screen()
        if screen is None or len(screen.shape) < 3:
            return False

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return False

        th, tw = template.shape[:2]
        cx, cy = center
        x1 = max(cx - tw // 2, 0)
        y1 = max(cy - th // 2, 0)
        x2 = min(x1 + tw, screen.shape[1])
        y2 = min(y1 + th, screen.shape[0])
        if x2 <= x1 or y2 <= y1:
            return False

        sat_thr = sat_threshold if sat_threshold is not None else self._COLORED_PIXEL_SAT_THRESHOLD

        roi = screen[y1:y2, x1:x2]
        roi_colored = self._colored_pixel_count(roi, sat_thr)
        tpl_colored = self._colored_pixel_count(template, sat_thr)

        # If the template itself has almost no colored pixels (e.g. a pure
        # white-on-dark icon), the metric is meaningless. Fail open so the
        # caller can fall back to a different strategy.
        if tpl_colored < self._MIN_TEMPLATE_COLORED_PIXELS:
            log_warning(
                f"[ACTIVE CHECK] {os.path.basename(template_path)} has too "
                f"few colored pixels ({tpl_colored}); skipping active check"
            )
            return True

        ratio = roi_colored / tpl_colored
        passed = ratio >= min_color_ratio

        log_info(
            f"[ACTIVE CHECK] {os.path.basename(template_path)} "
            f"roi_colored={roi_colored} tpl_colored={tpl_colored} "
            f"ratio={ratio:.2f} (min_ratio={min_color_ratio}, "
            f"sat_thr={sat_thr}) -> {'ACTIVE' if passed else 'DISABLED'}"
        )
        return passed

    def find_active_template(
        self,
        template_path: str,
        timeout: float = 5.0,
        threshold: float = 0.85,
        min_color_ratio: float = 0.4,
        sat_threshold: Optional[int] = None,
    ) -> Optional[Tuple[int, int, float]]:
        """Find a template only if the matched region is in its colored state.

        Wraps ``wait_for_template`` + :meth:`is_button_active`. Returns the same
        ``(x, y, conf)`` tuple as ``find_template`` when the button is active,
        ``None`` otherwise (template missing, not visible, or grayed out).
        """
        result = self.wait_for_template(
            template_path, timeout=timeout, threshold=threshold
        )
        if not result:
            return None
        x, y, _ = result
        if not self.is_button_active(
            template_path, (x, y),
            min_color_ratio=min_color_ratio,
            sat_threshold=sat_threshold,
        ):
            return None
        return result

    def wait_and_tap_active(
        self,
        template_path: str,
        timeout: float = 5.0,
        threshold: float = 0.85,
        min_color_ratio: float = 0.4,
        sat_threshold: Optional[int] = None,
        offset: Tuple[int, int] = (0, 0),
    ) -> bool:
        """Like ``wait_and_tap`` but only taps when the button is colored.

        Returns ``True`` only when an active match was found and the tap
        succeeded.
        """
        result = self.find_active_template(
            template_path, timeout=timeout, threshold=threshold,
            min_color_ratio=min_color_ratio,
            sat_threshold=sat_threshold,
        )
        if not result:
            return False
        x, y, _ = result
        return self.tap(x + offset[0], y + offset[1])
