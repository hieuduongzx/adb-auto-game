"""
GirlWars Game Automation
"""
from typing import List

from src.games.base_game import BaseGameAutomation, Activity
from src.utils import log_info, log_success, log_warning


# Package name of GirlWars on the device
GIRLWARS_PACKAGE = "com.girlwars.game"


class GirlWars(BaseGameAutomation):

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/girlwars"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 3

        # Template paths
        self.templates = {
            'skip_dialog': f"{self.assets_path}/skip_dialog.png",
        }

    def define_activities(self) -> List[Activity]:
        return [
            Activity(
                id="auto_skip_dialog",
                name="Tự Động Bỏ Qua Hội Thoại",
                description="Liên tục đóng các popup hội thoại trong game (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
        ]

    # ==================== Background Handlers ====================

    def handle_activity_auto_skip_dialog(self) -> bool:
        template = self.templates.get('skip_dialog')
        if not template:
            return False
        result = self.find_template(template, last_screen=True)
        if not result:
            return False
        x, y, _conf = result
        return self.tap(x, y)


if __name__ == "__main__":
    game = GirlWars()
    game.start()