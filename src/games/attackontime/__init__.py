import os
from typing import List

from src.game_core.base_game import Activity, BaseGameAutomation
from src.game_core.speedhack import SpeedhackMixin


ATTACKONTIME_PACKAGE = "com.onemt.and.shen"


class Attackontime(SpeedhackMixin, BaseGameAutomation):
    """Attack on Time automation — hiện tại chỉ hỗ trợ hack speed."""

    PACKAGE_NAME = ATTACKONTIME_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.templates_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.package_name = self.PACKAGE_NAME

        self.setup_speedhack()

    def define_activities(self) -> List[Activity]:
        return [
            self.speedhack_activity(enabled=False, default_speed=2.0),
        ]

    def before_process_game_actions(self) -> bool:
        return True


if __name__ == "__main__":
    Attackontime().start()
