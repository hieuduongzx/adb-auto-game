"""
OCR (text recognition) helpers for region-based game checks.

Wraps Tesseract via :mod:`pytesseract` behind a small ``OCRReader`` class so
the rest of the codebase doesn't import the engine directly. Designed for
short in-game labels like ``"0/5"``, ``"VIP3"``, ``"Lv 35"`` rather than
full document OCR.

Tesseract binary needs to be installed separately on the system:

* Windows: https://github.com/UB-Mannheim/tesseract/wiki
* Linux:   ``apt-get install tesseract-ocr``
* macOS:   ``brew install tesseract``

If the Python wrapper or the binary is missing, :class:`OCRReader` will
log a warning and return ``""`` from :meth:`read_text` so callers can
continue with other strategies (template matching, etc.) instead of
crashing.

Typical usage::

    ocr = OCRReader()
    text = ocr.read_text(screen, region=(1546, 942, 164, 53))
    if "0/5" in text:
        ...

The reader is intentionally cheap to construct so games can keep one
instance per automation class.
"""
from __future__ import annotations

import os
import re
import shutil
from typing import Optional, Tuple

import cv2
import numpy as np

from src.utils import log_error, log_info, log_warning


# Type alias: (x, y, width, height) in image (device) pixel space.
Region = Tuple[int, int, int, int]


# Default Tesseract config:
#   --oem 3  : default LSTM engine
#   --psm 7  : "Treat the image as a single text line" (good for in-game
#              labels like "0/5" / "VIP 3" / "Lv 35")
DEFAULT_TESSERACT_CONFIG = "--oem 3 --psm 7"

# Common Tesseract install locations on Windows that aren't on PATH.
_WINDOWS_TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _try_locate_tesseract_binary() -> Optional[str]:
    """Return the absolute path to ``tesseract`` if findable, else ``None``.

    Honours the ``TESSERACT_CMD`` env var first, then PATH, then the
    Windows installer's default location. This is best-effort; if it
    returns ``None`` we let pytesseract fall back to its own discovery.
    """
    env = os.environ.get("TESSERACT_CMD")
    if env and os.path.exists(env):
        return env

    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    if os.name == "nt":
        for cand in _WINDOWS_TESSERACT_CANDIDATES:
            if os.path.exists(cand):
                return cand
    return None


class OCRReader:
    """Lightweight Tesseract wrapper with region cropping + preprocessing.

    Single-engine for now (pytesseract). The class is intentionally small
    so a different backend (RapidOCR / EasyOCR) could be plugged in later
    without changing call sites.

    Construction is non-fatal: if Tesseract is missing the reader logs
    once and goes into ``available=False`` mode where every read returns
    an empty string.
    """

    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        default_lang: str = "eng",
        default_config: str = DEFAULT_TESSERACT_CONFIG,
    ) -> None:
        self.default_lang = default_lang
        self.default_config = default_config
        self._available: bool = False
        self._pytesseract = None  # imported lazily so the dep stays optional
        self._init_engine(tesseract_cmd)

    # ----- setup -----------------------------------------------------------

    def _init_engine(self, tesseract_cmd: Optional[str]) -> None:
        try:
            import pytesseract  # type: ignore
        except ImportError:
            log_warning(
                "pytesseract is not installed; OCR features disabled. "
                "Install with: pip install pytesseract"
            )
            return

        # Resolve binary location: explicit > env/PATH > Windows defaults.
        cmd = tesseract_cmd or _try_locate_tesseract_binary()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        # Ping Tesseract once so we fail fast (and quietly) if the binary
        # is missing entirely.
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            log_warning(
                f"Tesseract binary not available ({e}). Install Tesseract "
                "or set the TESSERACT_CMD env var to enable OCR. "
                "Windows installer: "
                "https://github.com/UB-Mannheim/tesseract/wiki"
            )
            return

        self._pytesseract = pytesseract
        self._available = True
        log_info("OCR engine ready (Tesseract)")

    # ----- public API ------------------------------------------------------

    @property
    def available(self) -> bool:
        """``True`` when Tesseract is installed and reachable."""
        return self._available

    def read_text(
        self,
        screen: np.ndarray,
        region: Optional[Region] = None,
        lang: Optional[str] = None,
        config: Optional[str] = None,
        whitelist: Optional[str] = None,
        preprocess: bool = True,
    ) -> str:
        """Run OCR on ``screen`` (optionally cropped to ``region``).

        Args:
            screen: BGR ndarray captured by ADBGameAutomation.
            region: Optional ``(x, y, w, h)`` crop in device pixels. When
                ``None`` the whole screen is used.
            lang: Tesseract language code (default ``"eng"``).
            config: Override Tesseract CLI flags (defaults to PSM 7).
            whitelist: Optional ``tessedit_char_whitelist`` string. Useful
                for digit-only fields like ``"0123456789/"``.
            preprocess: When ``True`` (default) apply grayscale + Otsu
                threshold + 2x upscale to the crop. Turn off if your
                source is already a clean black-on-white render.

        Returns:
            Recognised text, stripped. Returns ``""`` when the engine is
            unavailable or recognition fails.
        """
        if not self._available or screen is None or screen.size == 0:
            return ""

        crop = self._crop(screen, region)
        if crop is None or crop.size == 0:
            return ""

        if preprocess:
            crop = self._preprocess(crop)

        cfg = config if config is not None else self.default_config
        if whitelist:
            cfg = f"{cfg} -c tessedit_char_whitelist={whitelist}"

        try:
            text = self._pytesseract.image_to_string(
                crop, lang=lang or self.default_lang, config=cfg
            )
        except Exception as e:  # pragma: no cover - tesseract runtime errors
            log_error(f"OCR error: {e}")
            return ""
        return (text or "").strip()

    def contains_text(
        self,
        screen: np.ndarray,
        needle: str,
        region: Optional[Region] = None,
        case_sensitive: bool = False,
        normalize_whitespace: bool = True,
        **kwargs,
    ) -> bool:
        """Check whether ``needle`` is present in the OCR output.

        ``kwargs`` are forwarded to :meth:`read_text` (lang, config,
        whitelist, preprocess).
        """
        text = self.read_text(screen, region=region, **kwargs)
        if not text:
            return False

        haystack = text
        target = needle
        if normalize_whitespace:
            haystack = re.sub(r"\s+", "", haystack)
            target = re.sub(r"\s+", "", target)
        if not case_sensitive:
            haystack = haystack.lower()
            target = target.lower()
        return target in haystack

    # ----- helpers ---------------------------------------------------------

    @staticmethod
    def _crop(screen: np.ndarray, region: Optional[Region]) -> Optional[np.ndarray]:
        """Slice ``screen`` to ``region`` with bounds checking."""
        if region is None:
            return screen
        x, y, w, h = region
        if w <= 0 or h <= 0:
            return None
        H, W = screen.shape[:2]
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(W, int(x + w))
        y1 = min(H, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return None
        return screen[y0:y1, x0:x1].copy()

    @staticmethod
    def _preprocess(crop: np.ndarray) -> np.ndarray:
        """Standard prep for short in-game labels.

        Steps:
            1. Convert to grayscale (no-op if already single channel).
            2. Upscale 2x with cubic interpolation - tiny labels OCR much
               better at slightly higher resolution.
            3. Apply Otsu binarisation. Tesseract's LSTM engine handles
               grayscale fine, but a clean black-on-white image is
               consistently more reliable for short strings.
        """
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop

        # Upscale only if the crop is small (avoid making 1080p crops huge).
        h, w = gray.shape[:2]
        if max(h, w) < 200:
            gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # Otsu binarisation. We try both polarities and keep the one with
        # the most "ink" near the borders == 0 (i.e. background). For game
        # UI labels the foreground text is typically darker than the
        # background once converted to grayscale, but enemy nameplates can
        # be inverted; keeping both options handled is cheap.
        _, otsu = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        # Heuristic: if the resulting image is mostly black, invert it so
        # text becomes black-on-white (Tesseract's preferred input).
        if cv2.countNonZero(otsu) < (otsu.size // 2):
            otsu = cv2.bitwise_not(otsu)
        return otsu


__all__ = ["OCRReader", "Region", "DEFAULT_TESSERACT_CONFIG"]
