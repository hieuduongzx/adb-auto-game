"""
OCR (text recognition) helpers for region-based game checks.

This module provides a unified :class:`OCRReader` facade over multiple
backends. English-only - the project targets Latin in-game labels
(e.g. ``"0/5"``, ``"VIP 3"``, ``"Lv 35"``).

* **tesseract** - thin wrapper around the ``pytesseract`` binding. Fast
  and light; the default backend.
* **easyocr** - neural OCR via the ``easyocr`` package. Better with
  stylised fonts, but heavier (loads a Torch model).
* **paddleocr** - neural OCR via the ``paddleocr`` package. Strong
  accuracy; pulls its own ``paddlepaddle`` runtime.

If the requested backend isn't installed, :class:`OCRReader` keeps
working in a degraded mode where every read returns ``""`` so callers
can fall back to template matching without crashing.

Typical usage::

    ocr = OCRReader(backend="tesseract")
    text = ocr.read_text(screen, region=(1546, 942, 164, 53))
    if "0/5" in text:
        ...

Switch backends at runtime::

    ocr.set_backend("paddleocr")

Install:

* Tesseract:
  - ``pip install pytesseract``
  - plus the system Tesseract binary:
    - Windows: https://github.com/UB-Mannheim/tesseract/wiki
    - Linux:   ``apt-get install tesseract-ocr``
    - macOS:   ``brew install tesseract``
  - If the Windows installer puts Tesseract off PATH, set the
    ``TESSERACT_CMD`` environment variable to the binary path.

* EasyOCR:
  - ``pip install easyocr``
  - First run downloads the language models (~100MB).

* PaddleOCR:
  - ``pip install paddlepaddle paddleocr``
  - First run downloads the detection + recognition models (~50-100MB).
"""
from __future__ import annotations

import os
import re
import shutil
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import cv2
import numpy as np

from src.utils import log_debug, log_error, log_info, log_warning


# Type alias: (x, y, width, height) in image (device) pixel space.
Region = Tuple[int, int, int, int]


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


# --- Backend registry -----------------------------------------------------

# All known backend identifiers, in priority order for auto-detection.
KNOWN_BACKENDS = ("tesseract", "easyocr", "paddleocr")


def _list_available_backends() -> List[str]:
    """Return the subset of :data:`KNOWN_BACKENDS` that can be imported."""
    avail = []
    try:
        import pytesseract  # noqa: F401
        avail.append("tesseract")
    except ImportError:
        pass
    try:
        import easyocr  # noqa: F401
        avail.append("easyocr")
    except ImportError:
        pass
    try:
        import paddleocr  # noqa: F401
        avail.append("paddleocr")
    except ImportError:
        pass
    return avail


# English language-code map shared by the neural backends. EasyOCR and
# PaddleOCR both use ``"en"``; Tesseract uses ``"eng"``.
_EN_LANG = {"eng": "en", "en": "en"}


def _apply_whitelist(text: str, whitelist: Optional[str]) -> str:
    """Filter ``text`` to ``whitelist`` chars (plus whitespace), if given.

    The neural backends have no native whitelist, so we post-filter.
    """
    if not whitelist:
        return text
    allowed = set(whitelist)
    return "".join(ch for ch in text if ch in allowed or ch.isspace())


# --- Backends -------------------------------------------------------------


class OCRBackend(ABC):
    """One pluggable OCR engine.

    ``init`` probes/constructs the engine and returns whether it is usable.
    ``read`` runs OCR on an already-cropped, already-preprocessed image (the
    shared crop/preprocess lives on :class:`OCRReader`). ``teardown`` releases
    any heavy resources (e.g. a Torch model) before switching backends.
    """

    name = "base"

    def __init__(self, default_lang: str = "eng") -> None:
        self.default_lang = default_lang
        self.available = False

    @abstractmethod
    def init(self) -> bool:
        """Probe / construct the engine. Returns ``True`` when usable."""

    @abstractmethod
    def read(
        self, crop, *, lang=None, whitelist=None, config=None, psm=None,
    ) -> str:
        """Run OCR on a preprocessed ``crop`` and return recognised text."""

    def teardown(self) -> None:
        self.available = False


class TesseractBackend(OCRBackend):
    """``pytesseract`` wrapper. Fast and light; the default backend."""

    name = "tesseract"

    def __init__(
        self,
        default_lang: str = "eng",
        tesseract_cmd: Optional[str] = None,
        default_config: str = DEFAULT_TESSERACT_CONFIG,
    ) -> None:
        super().__init__(default_lang)
        self._tesseract_cmd = tesseract_cmd
        self._default_config = default_config
        self._pytesseract = None

    def init(self) -> bool:
        try:
            import pytesseract  # type: ignore
        except ImportError:
            return False

        cmd = self._tesseract_cmd or _try_locate_tesseract_binary()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            # Binding present but the binary is missing/unreachable -> stay
            # unavailable. Surface the reason for anyone debugging "OCR off".
            log_debug(f"tesseract version probe failed: {e}")
            return False

        self._pytesseract = pytesseract
        self.available = True
        return True

    def read(self, crop, *, lang=None, whitelist=None, config=None, psm=None) -> str:
        if config is None:
            mode = psm if psm is not None else 7
            cfg = f"--oem 3 --psm {mode}"
        else:
            cfg = config
        if whitelist:
            cfg = f"{cfg} -c tessedit_char_whitelist={whitelist}"
        return self._pytesseract.image_to_string(
            crop, lang=lang or self.default_lang, config=cfg,
        )

    def teardown(self) -> None:
        self._pytesseract = None
        self.available = False


class EasyOCRBackend(OCRBackend):
    """Neural OCR via ``easyocr``. Better with stylised fonts; heavier (Torch)."""

    name = "easyocr"

    def __init__(self, default_lang: str = "eng") -> None:
        super().__init__(default_lang)
        self._reader = None

    def init(self) -> bool:
        try:
            import easyocr  # type: ignore
        except ImportError:
            return False
        langs = [_EN_LANG.get(self.default_lang or "eng", "en")]
        try:
            self._reader = easyocr.Reader(langs, gpu=False, verbose=False)
            self.available = True
            return True
        except Exception as e:
            log_error(f"OCR (easyocr) init failed: {e}")
            self._reader = None
            self.available = False
            return False

    def read(self, crop, *, lang=None, whitelist=None, config=None, psm=None) -> str:
        if self._reader is None:
            return ""
        if lang:
            easy_lang = _EN_LANG.get(lang, "en")
            if easy_lang not in self._reader.lang_list:
                self._reader.setLanguage([easy_lang])
        # EasyOCR expects RGB.
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB) if len(crop.shape) == 3 else crop
        results = self._reader.readtext(rgb, detail=0, paragraph=True)
        return _apply_whitelist(" ".join(str(r) for r in results), whitelist)

    def teardown(self) -> None:
        self._reader = None
        self.available = False


class PaddleOCRBackend(OCRBackend):
    """Neural OCR via ``paddleocr``. Strong accuracy; pulls ``paddlepaddle``."""

    name = "paddleocr"

    def __init__(self, default_lang: str = "eng") -> None:
        super().__init__(default_lang)
        self._reader = None

    def init(self) -> bool:
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError:
            return False
        try:
            # mkldnn oneDNN path crashes on Windows with paddle 3.3.x
            # (NotImplementedError: ConvertPirAttribute2RuntimeAttribute).
            # Disable it for portability across Windows installs.
            self._reader = PaddleOCR(
                lang=_EN_LANG.get(self.default_lang or "eng", "en"),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
            self.available = True
            return True
        except Exception as e:
            log_error(f"OCR (paddleocr) init failed: {e}")
            self._reader = None
            self.available = False
            return False

    def read(self, crop, *, lang=None, whitelist=None, config=None, psm=None) -> str:
        if self._reader is None:
            return ""
        # PaddleOCR expects 3-channel BGR; our shared preprocessor returns
        # grayscale, so convert back here.
        if len(crop.shape) == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        results = self._reader.predict(crop)
        if not results:
            return ""
        # ``predict`` returns one OCRResult dict per image; we pass a single crop.
        first = results[0]
        if hasattr(first, "get") or isinstance(first, dict):
            texts = first.get("rec_texts", []) or []
        else:
            texts = []
        return _apply_whitelist(" ".join(str(t) for t in texts), whitelist)

    def teardown(self) -> None:
        self._reader = None
        self.available = False


def create_backend(
    name: str,
    *,
    default_lang: str = "eng",
    tesseract_cmd: Optional[str] = None,
    default_config: str = DEFAULT_TESSERACT_CONFIG,
) -> Optional[OCRBackend]:
    """Construct (but do not ``init``) the backend named ``name``.

    Returns ``None`` for an unknown name so the caller can degrade gracefully.
    """
    if name == "tesseract":
        return TesseractBackend(default_lang, tesseract_cmd, default_config)
    if name == "easyocr":
        return EasyOCRBackend(default_lang)
    if name == "paddleocr":
        return PaddleOCRBackend(default_lang)
    return None


# --- Public facade --------------------------------------------------------


class OCRReader:
    """Region-aware OCR reader with pluggable backends (English-only).

    Three backends are supported:

    * ``"tesseract"`` - default; fast and light.
    * ``"easyocr"`` - neural OCR; better with stylised fonts, heavier
      (Torch).
    * ``"paddleocr"`` - neural OCR; strong accuracy, pulls its own
      ``paddlepaddle`` runtime.

    Construction probes the chosen backend. If it's missing the reader
    stays in ``available=False`` mode and every read returns ``""`` so
    callers can fall back to template matching. Use :meth:`set_backend`
    to switch backends at runtime; the previously active backend is
    released and the new one is (lazily) initialised.

    Args:
        backend: Backend name. ``None`` auto-picks the first available
            from :data:`KNOWN_BACKENDS` (tesseract first).
        tesseract_cmd: Optional explicit path to the Tesseract binary.
        default_lang: Language code passed to the backend. Defaults to
            ``"eng"``; backends translate to their own code (``"en"``).
        default_config: Tesseract CLI config override.
        preferred: Backward-compat alias for ``backend``. Ignored when
            ``backend`` is set.
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        tesseract_cmd: Optional[str] = None,
        default_lang: str = "eng",
        default_config: str = DEFAULT_TESSERACT_CONFIG,
        preferred: Optional[str] = None,  # backward-compat
    ) -> None:
        self.default_lang = default_lang
        self._default_config = default_config
        self._tesseract_cmd = tesseract_cmd

        # Resolve the requested backend. ``backend`` wins over the
        # legacy ``preferred`` argument; ``None`` auto-detects.
        requested = backend or preferred
        if requested is None:
            avail = _list_available_backends()
            requested = avail[0] if avail else "tesseract"

        self._backend_name: str = requested
        self._available: bool = False
        self._backend: Optional[OCRBackend] = None

        self._init_backend()

        if self._available:
            log_info(f"OCR engine ready ({self._backend_name})")
        else:
            log_warning(
                f"OCR backend '{self._backend_name}' not available. "
                "Install one of:\n"
                "  pip install pytesseract (+ system Tesseract binary)\n"
                "  pip install easyocr\n"
                "  pip install paddlepaddle paddleocr\n"
                "For Tesseract off PATH on Windows, set TESSERACT_CMD."
            )

    # ----- backend lifecycle ----------------------------------------------

    def _init_backend(self) -> None:
        """Construct + probe the active backend via the factory."""
        self._backend = create_backend(
            self._backend_name,
            default_lang=self.default_lang,
            tesseract_cmd=self._tesseract_cmd,
            default_config=self._default_config,
        )
        if self._backend is None:
            log_warning(f"Unknown OCR backend '{self._backend_name}'")
            self._available = False
            return
        self._available = self._backend.init()

    def _teardown_backend(self) -> None:
        """Release resources held by the active backend."""
        if self._backend is not None:
            self._backend.teardown()
        self._backend = None
        self._available = False

    def set_backend(self, backend: str) -> bool:
        """Switch to a different backend at runtime.

        Releases the previously active backend (so we don't keep two
        Torch models in memory, for example) and (lazily) initialises
        the new one. Returns ``True`` if the new backend became
        available, ``False`` otherwise (in which case the reader stays
        in degraded mode and callers should fall back to templates).
        """
        if backend not in KNOWN_BACKENDS:
            log_warning(
                f"Unknown OCR backend '{backend}'. "
                f"Known: {KNOWN_BACKENDS}"
            )
            return False
        if backend == self._backend_name and self._available:
            return True
        self._teardown_backend()
        self._backend_name = backend
        self._init_backend()
        if self._available:
            log_info(f"OCR backend switched to '{backend}'")
            return True
        log_warning(
            f"OCR backend '{backend}' unavailable; "
            "OCR helpers will return empty results"
        )
        return False

    # ----- public API ------------------------------------------------------

    @property
    def available(self) -> bool:
        """``True`` when the active backend is reachable."""
        return self._available

    @property
    def backend_name(self) -> str:
        """Name of the active backend, or ``"none"`` when unavailable."""
        return self._backend_name if self._available else "none"

    def read_text(
        self,
        screen: np.ndarray,
        region: Optional[Region] = None,
        lang: Optional[str] = None,
        whitelist: Optional[str] = None,
        preprocess: bool = True,
        config: Optional[str] = None,
        psm: Optional[int] = None,
    ) -> str:
        """Run OCR on ``screen`` (optionally cropped to ``region``).

        English-only. The project targets Latin in-game labels.

        Args:
            screen: BGR ndarray captured by ADBGameAutomation.
            region: Optional ``(x, y, w, h)`` crop in device pixels.
            lang: Language code override. Defaults to ``"eng"`` (or the
                backend's English equivalent). Backends translate
                between ``"eng"`` / ``"en"`` automatically.
            whitelist: Optional char whitelist. Tesseract maps this to
                ``tessedit_char_whitelist``; neural backends post-filter.
            preprocess: Apply grayscale + Otsu + smart upscale + padding
                to the crop. Small labels OCR much better with this on.
            config: Tesseract CLI override (ignored by neural backends).
            psm: Tesseract page segmentation mode (ignored by neural
                backends).

        Returns ``""`` when OCR is unavailable or recognition fails.
        """
        if not self._available or screen is None or screen.size == 0:
            return ""

        crop = self._crop(screen, region)
        if crop is None or crop.size == 0:
            return ""

        if preprocess:
            crop = self._preprocess(crop)

        try:
            text = self._backend.read(
                crop, lang=lang, whitelist=whitelist, config=config, psm=psm,
            )
        except Exception as e:  # pragma: no cover - runtime OCR errors
            log_error(f"OCR ({self._backend_name}) error: {e}")
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

        ``kwargs`` are forwarded to :meth:`read_text`.
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
    "OCRReader", "Region", "DEFAULT_TESSERACT_CONFIG", "KNOWN_BACKENDS",
]
