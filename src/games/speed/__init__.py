import os
from typing import List

from src.game_core.base_game import Activity, BaseGameAutomation
from src.game_core.speedhack import SpeedhackMixin
from src.utils import log_info, log_warning

_PLACEHOLDER = "auto.detect.foreground"


class Speed(SpeedhackMixin, BaseGameAutomation):
    """Speedhack tự động phát hiện app đang chạy — không cần biết package name."""

    PACKAGE_NAME = _PLACEHOLDER
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.templates_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.package_name = self.PACKAGE_NAME
        self.setup_speedhack(_PLACEHOLDER)

    def define_activities(self) -> List[Activity]:
        return [
            self.speedhack_activity(enabled=True, default_speed=2.0),
        ]

    def before_process_game_actions(self) -> bool:
        return True

    def handle_activity_speedhack(self) -> bool:
        pkg = None
        try:
            self.adb.clear_info_cache()
            pkg = self.adb.get_current_app()
        except Exception:
            pass

        if pkg:
            self.speedhack.package = pkg
            self.package_name = pkg
            log_info(f"[speed] foreground app: {pkg}")
        else:
            log_warning("[speed] không detect được foreground app")

        return super().handle_activity_speedhack()


if __name__ == "__main__":
    Speed().start()
