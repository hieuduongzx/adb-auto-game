"""OCR convenience helpers (region text checks), mixed into BaseGameAutomation.

Thin wrappers over ``read_text`` / ``region_contains_text`` that short-circuit
when OCR is unavailable so callers can fall back to template matching.
"""
import time
from typing import Optional, Tuple

from src.utils import log_debug, log_success, log_warning

# Type alias: (x, y, width, height) in device-pixel space.
Region = Tuple[int, int, int, int]


class OCRHelperMixin:
    """Region text checks built on ``read_text`` / ``region_contains_text``."""

    def region_has_text(
        self,
        needle: str,
        region: Region,
        whitelist: Optional[str] = None,
        case_sensitive: bool = False,
        last_screen: bool = False,
    ) -> bool:
        """Return ``True`` if ``needle`` appears in OCR output of ``region``.

        Returns ``False`` immediately when the OCR engine isn't available, so
        callers can chain it before falling back to template checks.

        Args:
            needle: Substring to look for. Whitespace is ignored.
            region: ``(x, y, w, h)`` in device pixels.
            whitelist: Optional char whitelist (e.g. ``"0123456789/"``).
            case_sensitive: Default ``False``.
            last_screen: Use the most recent capture instead of forcing a
                fresh ``capture_screen()``. Default ``True``.
        """
        if not getattr(self.ocr, "available", False):
            return False

        text = self.read_text(
            region=region, whitelist=whitelist, last_screen=last_screen,
        )
        if not text:
            return False

        # Reuse the lower-level method so case/whitespace rules stay in one
        # place. We've already logged the raw read.
        return self.region_contains_text(
            needle, region=region,
            whitelist=whitelist, case_sensitive=case_sensitive,
            last_screen=last_screen,
        )

    def wait_region_has_text(
        self,
        needle: str,
        region: Region,
        timeout: float = 10.0,
        interval: float = 0.5,
        whitelist: Optional[str] = None,
        case_sensitive: bool = False,
    ) -> bool:
        """Poll ``region`` until ``needle`` is recognised or timeout.

        Pause-aware: while the automation is paused the poll skips reads and
        just sleeps, so a long ``wait_region_has_text`` won't burn ADB during
        a Pause.
        """
        if not getattr(self.ocr, "available", False):
            log_warning(f"[OCR] '{needle}' wait skipped - OCR unavailable")
            return False

        start = time.time()
        while time.time() - start < timeout:
            self._pause_event.wait()
            if self.region_has_text(
                needle, region=region,
                whitelist=whitelist, case_sensitive=case_sensitive,
            ):
                elapsed = time.time() - start
                log_success(
                    f"[OCR] Found '{needle}' in {region} after {elapsed:.2f}s"
                )
                return True
            time.sleep(interval)
        log_debug(f"[OCR] Timeout waiting for '{needle}' in {region}")
        return False
