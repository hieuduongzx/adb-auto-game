"""Region-based text recognition for Macro2k.

The app currently ships one recognition model: PP-OCRv5 Mobile. Callers
already crop the screen to the label they want to read, so this module sends
that crop directly to the bundled ONNX recognition graph and deliberately
does not run text detection.

The small registry remains in place so another recognition model can be added
later without changing the Designer, DevScope, or workflow engine APIs.
"""
from __future__ import annotations

import re
import sys
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple, Type

import numpy as np

from src.core.adb.auto.ppocr_onnx import PPOCRv5Recognizer
from src.utils import log_error, log_warning


Region = Tuple[int, int, int, int]
DEFAULT_OCR_MODEL = "ppocr_v5_mobile"
OCR_MODEL_LABELS = {DEFAULT_OCR_MODEL: "PP-OCRv5 Mobile"}
KNOWN_BACKENDS = tuple(OCR_MODEL_LABELS)

# Values written by older Designer versions.  They are accepted only while
# loading old workflows; every one resolves to the sole registered model.
_LEGACY_BACKENDS = {"", "auto", "tesseract", "easyocr", "paddleocr"}


def normalize_backend_name(name: Optional[str]) -> str:
    value = str(name or "").strip().lower()
    if value in KNOWN_BACKENDS or value in _LEGACY_BACKENDS:
        return value if value in KNOWN_BACKENDS else DEFAULT_OCR_MODEL
    return value


def _apply_whitelist(text: str, whitelist: Optional[str]) -> str:
    if not whitelist:
        return text
    allowed = set(whitelist)
    return "".join(ch for ch in text if ch in allowed or ch.isspace())


class OCRBackend(ABC):
    """Interface implemented by one selectable text-recognition model."""

    name = "base"

    def __init__(self) -> None:
        self.available = False

    @abstractmethod
    def init(self) -> bool:
        """Load the model and return whether it is ready."""

    @abstractmethod
    def read(self, crop: np.ndarray, *, whitelist: Optional[str] = None) -> str:
        """Recognize one already-cropped text line."""

    def teardown(self) -> None:
        self.available = False


class PPOCRv5MobileBackend(OCRBackend):
    """Recognition-only PP-OCRv5 Mobile model (no detector)."""

    name = DEFAULT_OCR_MODEL
    model_name = "PP-OCRv5_mobile_rec"

    def __init__(self) -> None:
        super().__init__()
        self._recognizer: Optional[PPOCRv5Recognizer] = None

    def init(self) -> bool:
        try:
            self._recognizer = PPOCRv5Recognizer()
            self.available = True
            return True
        except Exception as exc:
            log_error(
                f"OCR ({self.name}) init failed: {exc} "
                f"[python: {sys.executable}]"
            )
            self._recognizer = None
            self.available = False
            return False

    def read(self, crop: np.ndarray, *, whitelist: Optional[str] = None) -> str:
        if self._recognizer is None:
            return ""
        return _apply_whitelist(self._recognizer.read(crop), whitelist)

    def teardown(self) -> None:
        self._recognizer = None
        self.available = False


_MODEL_REGISTRY: Dict[str, Type[OCRBackend]] = {
    DEFAULT_OCR_MODEL: PPOCRv5MobileBackend,
}


def create_backend(name: str, **_compat) -> Optional[OCRBackend]:
    """Construct a registered recognition model without loading it."""
    backend_type = _MODEL_REGISTRY.get(normalize_backend_name(name))
    return backend_type() if backend_type else None


class OCRReader:
    """Crop-aware facade used by ADB, Win32, Designer, and Runner.

    Legacy backend names in saved workflows migrate to PP-OCRv5 Mobile;
    unknown future names remain unavailable rather than silently selecting the
    wrong model.
    """

    def __init__(
        self,
        backend: Optional[str] = None,
    ) -> None:
        self._backend_name = normalize_backend_name(backend)
        self._available = False
        self._backend: Optional[OCRBackend] = None
        self._init_backend()
        if not self._available:
            log_warning(
                "PP-OCRv5 Mobile is unavailable. Check ONNX Runtime and the "
                "bundled assets under assets/ocr/ppocr_v5_mobile."
            )

    def _init_backend(self) -> None:
        self._backend = create_backend(self._backend_name)
        if self._backend is None:
            log_warning(f"Unknown OCR model '{self._backend_name}'")
            self._available = False
            return
        self._backend_name = self._backend.name
        self._available = self._backend.init()

    def _teardown_backend(self) -> None:
        if self._backend is not None:
            self._backend.teardown()
        self._backend = None
        self._available = False

    def set_backend(self, backend: str) -> bool:
        requested = normalize_backend_name(backend)
        if requested not in KNOWN_BACKENDS:
            log_warning(f"Unknown OCR model '{backend}'. Known: {KNOWN_BACKENDS}")
            return False
        if requested == self._backend_name and self._available:
            return True
        self._teardown_backend()
        self._backend_name = requested
        self._init_backend()
        if self._available:
            log_info(f"OCR model switched to '{OCR_MODEL_LABELS[requested]}'")
            return True
        log_warning(
            f"OCR model '{OCR_MODEL_LABELS[requested]}' unavailable; "
            "OCR helpers will return empty results"
        )
        return False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def backend_name(self) -> str:
        return self._backend_name if self._available else "none"

    def read_text(
        self,
        screen: np.ndarray,
        region: Optional[Region] = None,
        lang: Optional[str] = None,
        whitelist: Optional[str] = None,
        preprocess: bool = False,
        config: Optional[str] = None,
        psm: Optional[int] = None,
    ) -> str:
        """Recognize one cropped text region with PP-OCRv5 Mobile.

        Detection is intentionally absent.  The region should contain one
        reasonably tight line or label.  Legacy OCR options remain accepted
        but are ignored by this recognition-only model.
        """
        del lang, preprocess, config, psm
        if not self._available or screen is None or screen.size == 0:
            return ""
        crop = self._crop(screen, region)
        if crop is None or crop.size == 0:
            return ""
        try:
            text = self._backend.read(crop, whitelist=whitelist)
        except Exception as exc:  # pragma: no cover - runtime model errors
            log_error(f"OCR ({self._backend_name}) error: {exc}")
            return ""
        return (text or "").strip()

    def find_text(
        self,
        screen: np.ndarray,
        needle: str,
        region: Optional[Region] = None,
        case_sensitive: bool = False,
        normalize_whitespace: bool = True,
        **kwargs,
    ) -> Tuple[bool, str]:
        text = self.read_text(screen, region=region, **kwargs)
        if not text:
            return False, ""
        haystack, target = text, needle
        if normalize_whitespace:
            haystack = re.sub(r"\s+", "", haystack)
            target = re.sub(r"\s+", "", target)
        if not case_sensitive:
            haystack = haystack.lower()
            target = target.lower()
        return target in haystack, text

    def contains_text(self, screen, needle, region=None, **kwargs) -> bool:
        return self.find_text(screen, needle, region=region, **kwargs)[0]

    @staticmethod
    def _crop(screen: np.ndarray, region: Optional[Region]) -> Optional[np.ndarray]:
        if region is None:
            return screen
        x, y, w, h = region
        if w <= 0 or h <= 0:
            return None
        height, width = screen.shape[:2]
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(width, int(x + w)), min(height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return None
        return screen[y0:y1, x0:x1].copy()


__all__ = [
    "OCRReader",
    "OCRBackend",
    "PPOCRv5MobileBackend",
    "Region",
    "DEFAULT_OCR_MODEL",
    "OCR_MODEL_LABELS",
    "KNOWN_BACKENDS",
    "normalize_backend_name",
]
