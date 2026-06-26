import time
from typing import List, Optional, Tuple
from src.utils import log_error, log_info, log_success, log_warning

from src.game_core.base_game import Activity, BaseGameAutomation
from src.game_core.speedhack import SpeedhackMixin

# Package name of Echocalypse on the device (used by _ensure_app_foreground).
ECHOPOCALYPSE_PACKAGE = "com.yoozoo.jgame.us"


class Echocalypse(SpeedhackMixin, BaseGameAutomation):
    """Echocalypse automation: dialog skip, expedition, and case-fight runs.

    Mixes in :class:`SpeedhackMixin` for the optional Frida time-scale speedup.
    """

    # App identity
    PACKAGE_NAME = ECHOPOCALYPSE_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.templates_dir = "assets/echocalypse"
        self.templates_dir = f"{self.templates_dir}/templates"
        self.max_workers = 10
        self.package_name = self.PACKAGE_NAME

        self.setup_speedhack()

        self.tpl_common = {
            "bt_skip_dialog":        f"{self.templates_dir}/bt_skip_dialog.png",
            "bt_accept_skip_dialog": f"{self.templates_dir}/bt_accept_skip_dialog.png",
            "bt_home": f"{self.templates_dir}/bt_home.png",
            "bt_back": f"{self.templates_dir}/bt_back.png",
        }
        self.tpl_home = {
            'is_home': f"{self.templates_dir}/home/is_home.png",
            'bt_patrol': f"{self.templates_dir}/home/bt_patrol.png",
            'bt_expedition': f"{self.templates_dir}/home/bt_expedition.png",
        }
        self.tpl_expedition = {
            "is_expedition": f"{self.templates_dir}/expedition/is_expedition.png",
            "next_target": f"{self.templates_dir}/expedition/next_target.png",
            "bt_attack": f"{self.templates_dir}/expedition/bt_attack.png",
        }
        self.tpl_battle = {
            "check_end_battle": f"{self.templates_dir}/battle/check_end_battle.png",
            "check_challenge_rewards": f"{self.templates_dir}/battle/check_challenge_rewards.png",
        }
        self.tpl_patrol = {
            "is_patrol": f"{self.templates_dir}/patrol/is_patrol.png",
            "icon_case_fight": f"{self.templates_dir}/patrol/icon_case_fight.png",
            "is_case_fight": f"{self.templates_dir}/patrol/is_case_fight.png",
            'bt_start_fight': f"{self.templates_dir}/patrol/bt_start_fight.png",
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
            Activity(
                id="case_fight",
                name="Case Fight",
                description="Vào patrol -> case fight, chọn case và bắt đầu chiến đấu",
                enabled=True,
                custom_settings=[
                    {
                        "key": "fight_count",
                        "label": "Số lượt đánh",
                        "type": "int",
                        "min": 1,
                        "max": 50,
                        "default": 5,
                    },
                ],
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

        result = self.find_template(skip_tpl, last_screen=False)
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
            if self._find_end_battle_screen():
                log_info("[expedition] no attack button, battle already ended")
            else:
                log_warning("[expedition] bt_attack did not appear and battle not ended")
                return False

        if not self._wait_end_battle_and_tap():
            log_warning("[expedition] end battle screen did not appear")
            return False

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

    def handle_activity_case_fight(self) -> bool:
        log_info("[case_fight] handler started v3")
        activity = self.get_activity("case_fight")
        target_count = int(activity.custom_values.get("fight_count", 5) if activity else 5)

        is_case_fight = self.tpl_patrol.get("is_case_fight")
        bt_patrol = self.tpl_home.get("bt_patrol")
        icon_case_fight = self.tpl_patrol.get("icon_case_fight")
        bt_start_fight = self.tpl_patrol.get("bt_start_fight")

        if not all([is_case_fight, bt_patrol, icon_case_fight, bt_start_fight]):
            log_error("[case_fight] missing templates")
            return False

        if not self._ensure_case_fight_screen(is_case_fight, bt_patrol, icon_case_fight):
            return False

        remaining = self._read_case_fight_remaining()
        log_info(f"[case_fight] user target={target_count}, remaining={remaining}")
        runs = min(target_count, remaining) if remaining is not None else target_count
        if runs <= 0:
            log_warning("[case_fight] no remaining attempts, returning to menu")
            self._back_to_menu()
            return True

        for i in range(runs):
            if not self.running:
                log_info("[case_fight] stopped by user")
                return False

            log_info(f"[case_fight] run {i + 1}/{runs}")

            # Mỗi lượt trước khi đánh đều kiểm tra/đảm bảo ở màn case fight.
            if not self._ensure_case_fight_screen(is_case_fight, bt_patrol, icon_case_fight):
                return False

            # Đọc lại remaining trước mỗi lượt để dừng sớm nếu đã hết lượt.
            current_remaining = self._read_case_fight_remaining()
            log_info(f"[case_fight] current remaining before run: {current_remaining}")
            if current_remaining is not None and current_remaining <= 0:
                log_warning("[case_fight] no remaining attempts left")
                break

            self.safe_sleep(1.5)
            log_info("[case_fight] tapping case position 1573,366")
            if not self.tap(1573, 366):
                return False

            if not self.wait_and_tap(bt_start_fight, timeout=5):
                log_warning("[case_fight] bt_start_fight did not appear")
                return False
            log_success("[case_fight] started fight")

            if not self._wait_end_battle_and_tap():
                log_warning("[case_fight] end battle screen did not appear")
                return False

        return True

    def _ensure_case_fight_screen(
        self,
        is_case_fight: str,
        bt_patrol: str,
        icon_case_fight: str,
    ) -> bool:
        """Đảm bảo đang ở màn case fight; nếu không thì về menu -> patrol -> case fight."""
        if self.find_template(is_case_fight):
            log_info("[case_fight] already in case fight screen")
            return True

        log_info("[case_fight] not in case fight screen, returning to menu")
        if not self._back_to_menu():
            return False

        if not self.wait_and_tap(bt_patrol, timeout=5):
            log_warning("[case_fight] bt_patrol not found")
            return False
        log_success("[case_fight] tapped bt_patrol")

        if not self.wait_and_tap(icon_case_fight, timeout=5):
            log_warning("[case_fight] icon_case_fight not found")
            return False
        log_success("[case_fight] tapped icon_case_fight")

        if not self.wait_for_template(is_case_fight, timeout=5):
            log_warning("[case_fight] case fight screen did not appear")
            return False

        return True

    def _read_case_fight_remaining(self) -> Optional[int]:
        """Đọc số lượt case fight còn lại từ vùng UI (1740, 838, 57, 56)."""
        region = (1716, 835, 81, 60)
        ocr_available = getattr(self.ocr, "available", False)
        log_info(f"[case_fight] OCR available={ocr_available}")
        if not ocr_available:
            log_warning("[case_fight] OCR unavailable; skipping remaining read")
            return None

        try:
            text = self.read_text(region=region, last_screen=False)
        except Exception as e:
            log_error(f"[case_fight] OCR read failed: {e}")
            return None

        log_info(f"[case_fight] OCR remaining text: '{text}'")
        if not text:
            return None

        digits = "".join(c for c in text if c.isdigit())
        try:
            return int(digits)
        except ValueError:
            log_warning(f"[case_fight] OCR digits parse failed: '{text}'")
            return None

    # ==== HELPERS ====
    def _find_end_battle_screen(self, threshold: float = 0.85) -> Optional[Tuple[int, int, float]]:
        """Tìm màn hình kết thúc battle, trả về tọa độ và confidence."""
        check_end_battle = self.tpl_battle.get("check_end_battle")
        if not check_end_battle:
            return None
        return self.find_template(check_end_battle, threshold=threshold, last_screen=False)

    def _tap_end_battle(self) -> bool:
        """Tap 2 lần tại vị trí post-battle cố định để đóng màn hình kết thúc."""
        for i in range(2):
            if not self.tap(1080, 897):
                return False
            log_info(f"[end_battle] post-battle tap #{i + 1} at 1080,897")
            if i == 0:
                self.safe_sleep(2.0)

        # Một số màn hình kết thúc battle hiện thêm "challenge rewards" cần click để đóng.
        challenge_rewards = self.tpl_battle.get("check_challenge_rewards")
        result = self.wait_and_tap(challenge_rewards, timeout=5)
        if result:
            log_success("[end_battle] challenge rewards tapped")
        else:
            log_info("[end_battle] no challenge rewards popup")
        return True

    def _wait_end_battle_and_tap(self, timeout: float = 300.0) -> bool:
        """Chờ màn hình kết thúc battle xuất hiện rồi tap để đóng."""
        start = time.time()
        while time.time() - start < timeout:
            if self._find_end_battle_screen():
                log_success("[end_battle] battle ended")
                return self._tap_end_battle()
            self.safe_sleep(0.5)
        log_warning("[end_battle] check_end_battle did not appear")
        return False

    def _back_to_menu(self, timeout: float = 30.0, threshold: float = 0.85) -> bool:
        log_info("Returning to main menu...")
        start_time = time.time()
        home_template = self.tpl_common.get('bt_home')
        back_template = self.tpl_common.get('bt_back')
        is_home_template = self.tpl_home.get('is_home')

        if not is_home_template:
            log_error("[back_to_menu] is_home template missing")
            return False

        while time.time() - start_time < timeout:
            if self.find_template(is_home_template, threshold=threshold):
                log_success("Main menu detected")
                return True

            tapped = False
            for template in [home_template, back_template]:
                if not template:
                    continue
                result = self.find_template(template, threshold=threshold)
                if not result:
                    continue
                x, y, _ = result
                if self.tap(x, y):
                    tapped = True
                    self.safe_sleep(1.0)
                    break

            if not tapped:
                self.safe_sleep(0.5)

        log_warning("Could not return to main menu")
        return False


if __name__ == "__main__":
    Echocalypse().start()