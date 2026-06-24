"""Per-game settings persistence (activities + UI prefs + OCR backend).

Owns the on-disk JSON format so :class:`~src.game_core.base_game.BaseGameAutomation`
doesn't have to. The OCR-backend *restore* side effect deliberately stays in
``BaseGameAutomation`` — this store only reads/writes the backend string.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.utils import log_warning


class SettingsStore:
    """Load/save a game's settings file under ``data/settings/<Game>.json``.

    The file format is a dict::

        {"ocr_backend": "...", "ui_settings": {...}, "activities": [...]}

    A legacy bare-list format (just the activities list) is still read.
    """

    def __init__(self, game_class_name: str,
                 settings_dir: Optional[Path] = None) -> None:
        self.settings_dir = settings_dir or (Path("data") / "settings")
        self.settings_file = self.settings_dir / f"{game_class_name}.json"

    def load(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
        """Return ``(activities, ui_settings, ocr_backend)`` from disk.

        Missing file / parse error yields ``([], {}, None)``. A legacy list
        file yields its contents as ``activities`` with empty ui/backend.
        """
        if not self.settings_file.exists():
            return [], {}, None
        try:
            with self.settings_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log_warning(f"Could not load activity settings: {e}")
            return [], {}, None

        if isinstance(data, dict):
            ui_settings = data.get("ui_settings", {}) or {}
            return data.get("activities", []), ui_settings, data.get("ocr_backend")
        if isinstance(data, list):
            return data, {}, None
        return [], {}, None

    def save(
        self,
        activities: List[Dict[str, Any]],
        ui_settings: Dict[str, Any],
        ocr_backend: Optional[str],
    ) -> None:
        """Persist the activity settings + UI prefs + OCR backend."""
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "ocr_backend": ocr_backend,
                "ui_settings": ui_settings,
                "activities": activities,
            }
            with self.settings_file.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log_warning(f"Could not save activity settings: {e}")
