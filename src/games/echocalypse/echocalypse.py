from typing import List

from src.game_core.base_game import Activity, BaseGameAutomation
from src.game_core.speedhack import SpeedhackMixin
from src.utils import log_error, log_info, log_success, log_warning

# Package name of Echocalypse on the device (used by _ensure_app_foreground).
ECHOPOCALYPSE_PACKAGE = "com.yoozoo.jgame.us"


class Echocalypse(SpeedhackMixin, BaseGameAutomation):

    # App identity
    PACKAGE_NAME = ECHOPOCALYPSE_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/echocalypse"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 10
        self.package_name = self.PACKAGE_NAME

        self.setup_speedhack()

        self.tpl_common = {
            "bt_skip_dialog":        f"{self.assets_path}/bt_skip_dialog.png",
            "bt_accept_skip_dialog": f"{self.assets_path}/bt_accept_skip_dialog.png",
        }
        self.tpl_expedition = {
            "is_expedition": f"{self.assets_path}/expedition/is_expedition.png",
            "next_target": f"{self.assets_path}/expedition/next_target.png",
            "bt_attack": f"{self.assets_path}/expedition/bt_attack.png",
        }
        self.tpl_battle = {
            "check_end_battle": f"{self.assets_path}/battle/check_end_battle.png",
        }

    # ==================== Activity registry ====================

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
            self.speedhack_activity(),
            Activity(
                id="expedition",
                name="Expedition",
                description="Chạy expedition: chọn next target, tấn công, chờ kết thúc battle",
                enabled=True,
            ),
        ]

    # ==================== Main loop entry ====================

    def before_process_game_actions(self) -> bool:
        """Run the base activity loop only after Echocalypse is foregrounded."""
        if self._ensure_app_foreground():
            return True
        log_error("Aborting: Echocalypse app could not be started")
        return False

    # ==================== Background handlers ====================
    def handle_activity_auto_skip_dialog(self) -> bool:
        skip_tpl = self.tpl_common.get("bt_skip_dialog")
        accept_tpl = self.tpl_common.get("bt_accept_skip_dialog")
        if not skip_tpl or not accept_tpl:
            return False

        result = self.find_template(skip_tpl, last_screen=True)
        if not result:
            return False
        sx, sy, _conf = result
        log_success(f"[bg-skip_dialog] skip button at {sx},{sy}")
        if not self.tap(sx, sy):
            return False

        accept_result = self.wait_and_tap(accept_tpl, timeout=3)
        if accept_result:
            log_success("[bg-skip_dialog] accept tapped")
        else:
            log_info("[bg-skip_dialog] no confirm popup; skip succeeded")
        return True

    # ==================== Sequential handlers ====================
    def _expedition_loop(self) -> bool:
        next_target = self.tpl_expedition.get("next_target")
        bt_attack = self.tpl_expedition.get("bt_attack")
        check_end_battle = self.tpl_battle.get("check_end_battle")
        if not next_target or not bt_attack or not check_end_battle:
            log_error("[expedition] missing templates")
            return False

        result = self.find_template(next_target)
        if not result:
            log_warning("[expedition] next_target not found")
            return False
        tx, ty, _conf = result
        target_x, target_y = tx, ty + 150
        log_info(f"[expedition] next target at {tx},{ty}; tapping below at {target_x},{target_y}")
        if not self.tap(target_x, target_y):
            return False

        attack_result = self.wait_and_tap(bt_attack, timeout=5)
        if attack_result:
            log_success("[expedition] attack started")
        else:
            end_result = self.find_template(check_end_battle, last_screen=True)
            if end_result:
                log_info("[expedition] no attack button, battle already ended")
            else:
                log_warning("[expedition] bt_attack did not appear and battle not ended")
                return False

        if not self.wait_for_template(check_end_battle, timeout=60):
            log_warning("[expedition] check_end_battle did not appear")
            return False
        log_success("[expedition] battle ended")

        for i in range(2):
            if not self.tap(1080, 897):
                return False
            log_info(f"[expedition] post-battle tap #{i + 1} at 1080,897")
            if i == 0:
                self.safe_sleep(2.0)
        return True

    def handle_activity_expedition(self) -> bool:
        consecutive_empty = 0
        while self.running:
            if not self._expedition_loop():
                consecutive_empty += 1
                log_warning(f"[expedition] loop failed ({consecutive_empty}/3)")
                if consecutive_empty >= 3:
                    break
                self.safe_sleep(1.0)
                continue
            consecutive_empty = 0
        return True


if __name__ == "__main__":
    Echocalypse().start()