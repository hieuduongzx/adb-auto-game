"""
OCR (text recognition) helpers for region-based game checks.

This module wraps **Tesseract** (via ``pytesseract``) as the only OCR
backend. Tesseract is fast for short Latin labels (e.g. ``"0/5"``,
``"VIP 3"``, ``"Lv 35"``), which is what the in-game probes need.

If Tesseract isn't installed, :class:`OCRReader` keeps working in a
degraded mode where every read returns ``""`` so callers can fall back
to template matching without crashing.

Typical usage::

    ocr = OCRReader()
    text = ocr.read_text(screen, region=(1546, 942, 164, 53))
    if "0/5" in text:
        ...

Install:

* ``pip install pytesseract``
* Plus the system Tesseract binary:

  - Windows: https://github.com/UB-Mannheim/tesseract/wiki
  - Linux:   ``apt-get install tesseract-ocr``
  - macOS:   ``brew install tesseract``

If the Windows installer puts Tesseract somewhere off PATH, set the
``TESSERACT_CMD`` environment variable to the absolute path of
``tesseract.exe`` and the reader will pick it up automatically.
"""
from __future__ import annotations

import os
import re
import shutil
import unicodedata
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import cv2
import numpy as np

from src.utils import log_error, log_info, log_warning


# Type alias: (x, y, width, height) in image (device) pixel space.
Region = Tuple[int, int, int, int]


# Pre-compiled regex used to drop the ``đ`` -> ``d`` style mappings that
# ``unicodedata.normalize`` doesn't decompose.
_ASCII_FOLD_MAP = str.maketrans({
    "đ": "d", "Đ": "D",
    "ư": "u", "Ư": "U",
    "ơ": "o", "Ơ": "O",
    "ă": "a", "Ă": "A",
    "â": "a", "Â": "A",
    "ê": "e", "Ê": "E",
    "ô": "o", "Ô": "O",
})


def strip_diacritics(text: str) -> str:
    """Return ``text`` with Vietnamese / Latin diacritics removed.

    Handles both decomposable accents (à, é, ố, ...) via Unicode
    normalisation and the few characters Unicode keeps as a single
    codepoint (đ, ư, ơ, ă, â, ê, ô) via an explicit fold map.

    Empty / non-str inputs are returned untouched. Useful when an OCR
    backend can't get Vietnamese tone marks right but still recognises
    base letters - the caller can compare ``strip_diacritics(text)``
    against an ASCII needle like ``"Phuc Loi"``.
    """
    if not text:
        return text
    # NFKD splits ``ố`` -> ``o`` + combining acute + combining circumflex.
    decomposed = unicodedata.normalize("NFKD", text)
    # Drop all combining marks (category Mn).
    no_marks = "".join(ch for ch in decomposed
                       if not unicodedata.combining(ch))
    # Apply the explicit fold map for codepoints NFKD doesn't split.
    return no_marks.translate(_ASCII_FOLD_MAP)


# --- Tesseract config -----------------------------------------------------

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

# Project-relative folders to search for a portable Tesseract install.
# We resolve these against both the project root (computed from this
# file's location) and the current working directory, so the binary can
# live alongside the code OR next to wherever the user launches the app.
_PROJECT_TESSERACT_CANDIDATES = (
    "vendor/tesseract/tesseract.exe",
    "vendor/Tesseract-OCR/tesseract.exe",
    "ocr/Tesseract-OCR/tesseract.exe",
    "ocr/tesseract/tesseract.exe",
    "tools/tesseract/tesseract.exe",
    "tools/Tesseract-OCR/tesseract.exe",
    "tesseract/tesseract.exe",
    "Tesseract-OCR/tesseract.exe",
)


def _project_root() -> str:
    """Return the project root (the folder containing ``src/``).

    This file lives at ``<root>/src/core/adb/auto/ocr.py`` so the root
    is four ``dirname`` calls up.
    """
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(here)
    ))))


def _try_locate_tesseract_binary() -> Optional[str]:
    """Return the absolute path to ``tesseract`` if findable, else ``None``.

    Search order (first hit wins):

    1. ``TESSERACT_CMD`` environment variable.
    2. Project-local portable folders (``vendor/tesseract/`` etc.) -
       lets the binary live next to the code with zero setup.
    3. System PATH.
    4. Windows installer's default locations.
    """
    env = os.environ.get("TESSERACT_CMD")
    if env and os.path.exists(env):
        return env

    if os.name == "nt":
        # Project-local portable install. Check both the project root
        # and the current working directory so it works whether the
        # user is launching from inside the repo or from a packaged
        # build that ships the binary alongside the executable.
        roots = [_project_root(), os.getcwd()]
        seen = set()
        for root in roots:
            if root in seen:
                continue
            seen.add(root)
            for rel in _PROJECT_TESSERACT_CANDIDATES:
                cand = os.path.join(root, rel)
                if os.path.exists(cand):
                    return cand

    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    if os.name == "nt":
        for cand in _WINDOWS_TESSERACT_CANDIDATES:
            if os.path.exists(cand):
                return cand
    return None


# --- Public facade --------------------------------------------------------


class OCRReader:
    """Region-aware OCR reader backed by Tesseract.

    Construction probes ``pytesseract`` and the system Tesseract binary.
    If either is missing, :attr:`available` stays ``False`` and every
    read returns ``""`` so callers can fall back to template matching.

    The reader performs cropping + light preprocessing (grayscale + Otsu
    + 2x upscale for tiny labels) before handing pixels to Tesseract.
    """

    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        default_lang: str = "eng",
        default_config: str = DEFAULT_TESSERACT_CONFIG,
        # ``backend`` / ``preferred`` are accepted for backward
        # compatibility with the old multi-backend API. They are
        # ignored: Tesseract is the only backend now.
        backend: Optional[str] = None,  # noqa: ARG002
        preferred: Optional[str] = None,  # noqa: ARG002
    ) -> None:
        self.default_lang = default_lang
        self._default_config = default_config
        self._pytesseract = None
        self._available = False
        self._init(tesseract_cmd)

        if self._available:
            log_info("OCR engine ready (tesseract)")
        else:
            log_warning(
                "Tesseract OCR not available. Install it with:\n"
                "  pip install pytesseract\n"
                "And the system binary:\n"
                "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "  Linux:   apt-get install tesseract-ocr\n"
                "  macOS:   brew install tesseract\n"
                "If installed off PATH, set TESSERACT_CMD to the binary path."
            )

    # ----- init ------------------------------------------------------------

    def _init(self, tesseract_cmd: Optional[str]) -> None:
        try:
            import pytesseract  # type: ignore
        except ImportError:
            return

        cmd = tesseract_cmd or _try_locate_tesseract_binary()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        try:
            pytesseract.get_tesseract_version()
        except Exception:
            return

        self._pytesseract = pytesseract
        self._available = True

    # ----- public API ------------------------------------------------------

    @property
    def available(self) -> bool:
        """``True`` when Tesseract is reachable."""
        return self._available

    @property
    def backend_name(self) -> str:
        """Name of the active backend, or ``"none"`` when unavailable."""
        return "tesseract" if self._available else "none"

    def read_text(
        self,
        screen: np.ndarray,
        region: Optional[Region] = None,
        lang: Optional[str] = None,
        whitelist: Optional[str] = None,
        preprocess: bool = True,
        config: Optional[str] = None,
        psm: Optional[int] = None,
        ascii_only: bool = False,
    ) -> str:
        """Run OCR on ``screen`` (optionally cropped to ``region``).

        Args:
            screen: BGR ndarray captured by ADBGameAutomation.
            region: Optional ``(x, y, w, h)`` crop in device pixels.
            lang: Tesseract language code (defaults to ``"eng"``). Pass
                ``"vie"`` if the ``vie.traineddata`` language pack is
                installed and you want diacritics preserved.
            whitelist: Optional char whitelist mapped to
                ``tessedit_char_whitelist``. Use e.g. ``"0123456789/"``
                for digit-only labels so Tesseract can't hallucinate
                letters.
            preprocess: Apply grayscale + Otsu + smart upscale + padding
                to the crop. Small labels OCR much better with this on.
            config: Optional Tesseract CLI override. When ``None``, uses
                ``DEFAULT_TESSERACT_CONFIG`` or builds one from ``psm``.
            psm: Optional Tesseract page segmentation mode override.
                Common values for game labels:

                * ``7`` (default) - single text line ("0/5", "Lv 35")
                * ``8`` - single word
                * ``6`` - uniform block of text
                * ``11`` - sparse text
                * ``13`` - raw line, no assumptions
            ascii_only: When ``True`` strip Vietnamese / Latin
                diacritics from the result before returning. Useful when
                Tesseract reads a Vietnamese label but mangles tone
                marks - the caller can compare against an ASCII needle
                like ``"Phuc Loi"`` and not care about ``"Phúc Lợi"``
                vs ``"Phuc Loi"`` vs ``"Phúe Loi"``.

        Returns ``""`` when OCR is unavailable or recognition fails.
        """
        if not self._available or screen is None or screen.size == 0:
            return ""

        crop = self._crop(screen, region)
        if crop is None or crop.size == 0:
            return ""

        if preprocess:
            crop = self._preprocess(crop)

        if config is None:
            mode = psm if psm is not None else 7
            cfg = f"--oem 3 --psm {mode}"
        else:
            cfg = config

        if whitelist:
            cfg = f"{cfg} -c tessedit_char_whitelist={whitelist}"

        try:
            text = self._pytesseract.image_to_string(
                crop, lang=lang or self.default_lang, config=cfg
            )
        except Exception as e:  # pragma: no cover - tesseract runtime errors
            log_error(f"OCR (tesseract) error: {e}")
            return ""
        result = (text or "").strip()
        if ascii_only:
            result = strip_diacritics(result)
        return result

    def contains_text(
        self,
        screen: np.ndarray,
        needle: str,
        region: Optional[Region] = None,
        case_sensitive: bool = False,
        normalize_whitespace: bool = True,
        ascii_fold: bool = False,
        **kwargs,
    ) -> bool:
        """Check whether ``needle`` is present in the OCR output.

        Args:
            ascii_fold: When ``True``, strip diacritics from both the
                OCR output and ``needle`` before comparing. Lets a
                caller match Vietnamese text via an ASCII needle even
                when the OCR engine garbles tone marks.

        ``kwargs`` are forwarded to :meth:`read_text`.
        """
        text = self.read_text(screen, region=region, **kwargs)
        if not text:
            return False

        haystack = text
        target = needle
        if ascii_fold:
            haystack = strip_diacritics(haystack)
            target = strip_diacritics(target)
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
            2. Smart upscale to target height ~48px. Tesseract is most
               accurate when text is ~30-50px tall; tiny labels get
               upscaled hard, larger ones are left alone.
            3. Apply Otsu binarisation + auto-invert. Tesseract prefers
               dark text on light background.
            4. Add a 12px white border around the result. Tesseract's
               LSTM engine struggles when text touches image edges.
        """
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop

        # Smart upscale: aim for ~48px text height. We use the smaller
        # dimension as a proxy for character height (works well for both
        # "0/5"-style labels and longer ones like "Stamina 120/120").
        h, w = gray.shape[:2]
        target_h = 48
        if h > 0 and h < target_h:
            scale = target_h / h
            # Cap upscaling at 4x so we don't blur tiny crops into mush.
            scale = min(scale, 4.0)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            gray = cv2.resize(
                gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC,
            )

        _, otsu = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        # Auto-invert: if foreground ended up black-dominant, flip so
        # text is dark on light (Tesseract's preferred polarity).
        if cv2.countNonZero(otsu) < (otsu.size // 2):
            otsu = cv2.bitwise_not(otsu)

        # Pad with white border. Tesseract's LSTM engine wants some
        # whitespace around the glyphs; without it, edge characters get
        # misread or dropped.
        padded = cv2.copyMakeBorder(
            otsu, 12, 12, 12, 12,
            borderType=cv2.BORDER_CONSTANT, value=255,
        )
        return padded


__all__ = [
    "OCRReader", "Region", "DEFAULT_TESSERACT_CONFIG", "strip_diacritics",
]
