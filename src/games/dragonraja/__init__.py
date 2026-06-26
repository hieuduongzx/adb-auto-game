import os
import time
from typing import List, Optional, Tuple
from src.utils import log_error, log_info, log_success, log_warning

from src.game_core.base_game import Activity, BaseGameAutomation
from src.game_core.speedhack import SpeedhackMixin


DRAGONRAJA_PACKAGE = "com.vnlz.gp"


class Dragonraja(SpeedhackMixin, BaseGameAutomation):
    """Dragon Raja automation."""

    PACKAGE_NAME = DRAGONRAJA_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.templates_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.package_name = self.PACKAGE_NAME

        self.setup_speedhack()

        self.tpl_common = {
            "skip_dialog":        f"{self.templates_dir}/bt_skip_dialog.png",
            "accept_skip_dialog": f"{self.templates_dir}/bt_accept_skip_dialog.png",
            "is_in_battle":       f"{self.templates_dir}/is_in_battle.png",
            "skip_battle":        f"{self.templates_dir}/bt_skip_battle.png",
            "is_end_battle":      f"{self.templates_dir}/is_end_battle.png",
            "is_main_story":      f"{self.templates_dir}/is_main_story.png",
            "bt_battle":          f"{self.templates_dir}/bt_battle.png",
            "bt_home":            f"{self.templates_dir}/bt_home.png",
        }
        self.tpl_home = {
            "is_home": f"{self.templates_dir}/home/is_home.png",
            "icon_nibelungen": f"{self.templates_dir}/home/icon_nibelungen.png",
        }
        self.tpl_nibelungen ={
            "is_nibelungen": f"{self.templates_dir}/nibelungen/is_nibelungen.png",
            "bt_hien_da_luan_hoi": f"{self.templates_dir}/nibelungen/bt_hien_da_luan_hoi.png",
            "is_hien_da_luan_hoi": f"{self.templates_dir}/nibelungen/is_hien_da_luan_hoi.png",
            "bt_khieu_chien": f"{self.templates_dir}/nibelungen/bt_khieu_chien.png",
            "bt_khieu_chien_2": f"{self.templates_dir}/nibelungen/bt_khieu_chien_2.png",
            "chuc_mung_chan": f"{self.templates_dir}/nibelungen/chuc_mung_chan.png",
            "ai_sau": f"{self.templates_dir}/nibelungen/ai_sau.png",
            "tro_ve": f"{self.templates_dir}/nibelungen/tro_ve.png",
        }

    def define_activities(self) -> List[Activity]:
        return [
            Activity(
                id="auto_skip_dialog",
                name="Bỏ Qua Hội Thoại",
                description="Liên tục đóng các popup hội thoại trong game (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            Activity(
                id="auto_skip_battle",
                name="Bỏ Qua Chiến Đấu",
                description="Liên tục bỏ qua các trận chiến trong game (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            Activity(
                id="end_combat",
                name="Kết Thúc Chiến Đấu",
                description="Tự động xử lý khi trận chiến kết thúc",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            Activity(
                id="main_story",
                name="Cốt Truyện Chính",
                description="Tự động bấm chiến đấu khi ở màn hình cốt truyện chính",
                enabled=True,
            ),
            Activity(
                id="hien_da_luan_hoi",
                name="Hiên Đá Luân Hồi",
                description="Tự động xử lý trận chiến trong chế độ Hiện Đã Luân Hồi",
                enabled=True,
            ),
            self.speedhack_activity(enabled=False, default_speed=2.0),
        ]

    def before_process_game_actions(self) -> bool:
        return True

    def handle_activity_auto_skip_dialog(self) -> bool:
        skip_tpl = self.tpl_common.get("skip_dialog")
        accept_tpl = self.tpl_common.get("accept_skip_dialog")
        is_in_battle_tpl = self.tpl_common.get("is_in_battle")
        # Nếu như đang trong trận chiến thì không bỏ qua hội thoại
        if self.find_template(is_in_battle_tpl):
            return False
        result = self.find_template(skip_tpl)
        if not result:
            return False
        x, y, _conf = result
        log_success(f"[bg-skip_dialog] tìm thấy nút bỏ qua tại ({x},{y})")
        if not self.tap(x, y):
            return False

        if self.wait_and_tap(accept_tpl, timeout=3):
            log_success("[bg-skip_dialog] đã xác nhận bỏ qua")
        else:
            log_info("[bg-skip_dialog] không có popup xác nhận, bỏ qua thành công")
        return True

    def handle_activity_auto_skip_battle(self) -> bool:
        is_in_battle_tpl = self.tpl_common.get("is_in_battle")
        result = self.find_template(is_in_battle_tpl)
        if not result:
            return False
        log_success("[bg-skip_battle] đang trong chiến đấu, tiến hành bỏ qua")
        skip_battle_tpl = self.tpl_common.get("skip_battle")
        if not skip_battle_tpl:
            return False
        btn = self.find_template(skip_battle_tpl)
        if not btn:
            return False
        x, y, _conf = btn
        if self.tap(x, y):
            log_success(f"[bg-skip_battle] đã bấm nút bỏ qua tại ({x},{y})")
            return True
        return False
    
    def handle_activity_end_combat(self) -> bool:
        return self._handle_end_combat()

#===SEQUENCE===
    def handle_activity_main_story(self) -> bool:
        is_main_story_tpl = self.tpl_common.get("is_main_story")
        bt_battle_tpl = self.tpl_common.get("bt_battle")
        while self.running:
            if not self.wait_for_template(is_main_story_tpl, timeout=10):
                continue
            log_success("[main_story] đang ở màn hình cốt truyện, tiến hành chiến đấu")
            if not self.wait_and_tap(bt_battle_tpl, timeout=5):
                continue
            log_success("[main_story] đã bấm nút chiến đấu, chờ kết thúc trận")
            self._handle_end_combat(timeout=120)
            log_success("[main_story] trận kết thúc, chờ quay lại cốt truyện")
        return True

    def handle_activity_hien_da_luan_hoi(self) -> bool:
        if not self._back_to_menu():
            log_warning("[hien_da_luan_hoi] không thể quay về menu chính")
            return False

        icon_nibelungen_tpl = self.tpl_home.get("icon_nibelungen")
        if not self.wait_and_tap(icon_nibelungen_tpl, timeout=10):
            log_warning("[hien_da_luan_hoi] không tìm thấy icon Nibelungen")
            return False

        is_nibelungen_tpl = self.tpl_nibelungen.get("is_nibelungen")
        if not self.wait_for_template(is_nibelungen_tpl, timeout=15):
            log_warning("[hien_da_luan_hoi] không vào được màn hình Nibelungen")
            return False

        bt_hien_da_luan_hoi_tpl = self.tpl_nibelungen.get("bt_hien_da_luan_hoi")
        if not self.wait_and_tap(bt_hien_da_luan_hoi_tpl, timeout=10):
            log_warning("[hien_da_luan_hoi] không tìm thấy nút Hiện Đã Luân Hồi")
            return False

        is_hien_da_luan_hoi_tpl = self.tpl_nibelungen.get("is_hien_da_luan_hoi")
        if not self.wait_for_template(is_hien_da_luan_hoi_tpl, timeout=15):
            log_warning("[hien_da_luan_hoi] không vào được màn hình Hiện Đã Luân Hồi")
            return False

        bt_khieu_chien_tpl = self.tpl_nibelungen.get("bt_khieu_chien")
        bt_khieu_chien_2_tpl = self.tpl_nibelungen.get("bt_khieu_chien_2")
        ai_sau_tpl = self.tpl_nibelungen.get("ai_sau")
        tro_ve_tpl = self.tpl_nibelungen.get("tro_ve")

        if not self.wait_and_tap(bt_khieu_chien_tpl, timeout=10):
            log_warning("[hien_da_luan_hoi] không tìm thấy nút Khiêu Chiến")
            return False

        self.safe_sleep(1.0)
        while self.running:
            if not self.wait_and_tap(bt_khieu_chien_2_tpl, timeout=10):
                log_warning("[hien_da_luan_hoi] không tìm thấy nút Khiêu Chiến 2")
                break
            self.safe_sleep(1.0)
            result = self.wait_for_any_template(
                [ai_sau_tpl, tro_ve_tpl], timeout=120
            )
            if result is None:
                log_warning("[hien_da_luan_hoi] không tìm thấy nút Ai Sau hoặc Trở Về")
                break
            tpl_found, x, y, _ = result
            self.tap(x, y)
            if tpl_found == ai_sau_tpl:
                log_success("[hien_da_luan_hoi] đã khiêu chiến, chờ vòng tiếp theo")
                self.safe_sleep(1.0)
            else:
                log_success("[hien_da_luan_hoi] trở về, kiểm tra màn hình chúc mừng")
                self.safe_sleep(1.0)
                chuc_mung_chan_tpl = self.tpl_nibelungen.get("chuc_mung_chan")
                if self.wait_for_template(chuc_mung_chan_tpl, timeout=5):
                    log_success("[hien_da_luan_hoi] thấy bảng chúc mừng, ấn để tiếp tục")
                    self.tap(957, 804)
                    self.safe_sleep(1.0)
                if not self.wait_and_tap(bt_khieu_chien_tpl, timeout=10):
                    log_warning("[hien_da_luan_hoi] không tìm thấy nút Khiêu Chiến sau trở về")
                    break
                self.safe_sleep(1.0)
        return True

#===HELPER===
    def _handle_end_combat(self, timeout: float = 30.0) -> bool:
        is_end_battle_tpl = self.tpl_common.get("is_end_battle")
        if not self.wait_for_template(is_end_battle_tpl, timeout=timeout):
            return False
        log_success("[end_combat] trận chiến đã kết thúc, tiến hành bỏ qua")
        self.tap(952, 835)
        return True

    def _back_to_menu(self, timeout: float = 30.0, threshold: float = 0.85) -> bool:
        start_time = time.time()
        home_template = self.tpl_common.get('bt_home')
        is_home_template = self.tpl_home.get('is_home')

        if not is_home_template:
            log_error("[back_to_menu] is_home template missing")
            return False

        while time.time() - start_time < timeout:
            if self.find_template(is_home_template, threshold=threshold):
                log_success("Main menu detected")
                return True

            tapped = False
            for template in [home_template]:
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
    Dragonraja().start()
