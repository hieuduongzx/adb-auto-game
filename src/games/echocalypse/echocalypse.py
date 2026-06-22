from typing import List
from src.games.base_game import Activity, BaseGameAutomation
from src.utils import log_error, log_info, log_success, log_warning

# Package name of Echocalypse on the device (used by _ensure_app_foreground).
ECHOPOCALYPSE_PACKAGE = "com.yoozoo.jgame.us"

class Echocalypse(BaseGameAutomation):

    # App identity
    PACKAGE_NAME = ECHOPOCALYPSE_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/echocalypse"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 10
        self.package_name = self.PACKAGE_NAME
        self.tpl_common = {
            "bt_skip_dialog":        f"{self.assets_path}/bt_skip_dialog.png",
            "bt_accept_skip_dialog": f"{self.assets_path}/bt_accept_skip_dialog.png",
        }

    # ==================== Activity registry ====================

    def define_activities(self) -> List[Activity]:
        return [
            # ---- Background (poll while the main loop is alive) ----
            Activity(
                id="auto_skip_dialog",
                name="Tự Động Bỏ Qua Hội Thoại",
                description="Liên tục đóng các popup hội thoại trong game (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            # ---- Sequential (run once, in order) ----

        ]

    # ==================== Main loop entry ====================

    def process_game_actions(self):
        """Run the base activity loop only after Echocalypse is foregrounded."""
        if not self._ensure_app_foreground():
            log_error("Aborting: Echocalypse app could not be started")
            return
        super().process_game_actions()

    # ==================== Background handlers ====================
    def handle_activity_auto_skip_dialog(self) -> bool:
        skip_tpl = self.tpl_common.get("bt_skip_dialog")
        accept_tpl = self.tpl_common.get("bt_accept_skip_dialog")
        if not skip_tpl or not accept_tpl:
            return False

        # 1. Look for the skip button on the current frame.
        result = self.find_template(skip_tpl, last_screen=True)
        if not result:
            return False
        sx, sy, _conf = result
        log_success(f"[bg-skip_dialog] skip button at {sx},{sy}")
        if not self.tap(sx, sy):
            return False

        # 2. Wait briefly for the confirm popup, then accept it.
        if not self.wait_and_tap(accept_tpl, timeout=3):
            log_warning("[bg-skip_dialog] accept button did not appear")
            return False
        log_success("[bg-skip_dialog] dialog skipped")
        return True

    # ==================== Sequential handlers ====================



if __name__ == "__main__":
    Echocalypse().start()