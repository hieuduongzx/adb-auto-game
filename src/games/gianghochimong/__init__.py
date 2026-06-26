
import os
import time
from typing import List
from src.game_core.base_game import BaseGameAutomation, Activity
from src.game_core.speedhack import SpeedhackMixin
from src.utils import log_error, log_warning, log_success, log_info

DEMO_PACKAGE = "com.dianhun.jhrmsw.x7sy"

class gianghochimong(SpeedhackMixin, BaseGameAutomation):

    # --- Cấu hình cấp class -------------------------------------------------
    PACKAGE_NAME = DEMO_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.templates_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.max_workers = 3
        self.package_name = self.PACKAGE_NAME
        self.setup_speedhack()
        self.tpl_common = {
            'back':        f"{self.templates_dir}/back.png",
            "skip_dialog": f"{self.templates_dir}/skip_dialog.png",
            "accept_skip_dialog": f"{self.templates_dir}/accept_skip_dialog.png",       # nút Về trang chủ
        }
        self.tpl_home = {
            "is_home": f"{self.templates_dir}/home/is_home.png",
            "icon_main_story": f"{self.templates_dir}/home/icon_main_story.png",
        }
        self.tpl_main_story = {
            "is_main_story": f"{self.templates_dir}/main_story/is_main_story.png",
            "current_chapter": f"{self.templates_dir}/main_story/current_chapter.png",
            "is_current_chapter": f"{self.templates_dir}/main_story/is_current_chapter.png",
            "current_map": f"{self.templates_dir}/main_story/current_map.png",
            "next_map": f"{self.templates_dir}/main_story/next_map.png",
        }
        self.tpl_battle = {
            "is_before_battle": f"{self.templates_dir}/battle/is_before_battle.png",
            "start_battle": f"{self.templates_dir}/battle/start_battle.png",
            "is_end_battle": f"{self.templates_dir}/battle/is_end_battle.png",
        }

    # ====================================================================
    #  KHAI BÁO ACTIVITY
    # ====================================================================
    def define_activities(self) -> List[Activity]:
        return [
            # --- Activity tuần tự đơn giản --------------------------------
            Activity(
                id="main_story",
                name="Nhiệm vụ chính tuyến",
                description="Làm nhiệm vụ chính tuyến",
                enabled=True,
                max_retries=1,   # số lần thử lại nếu handler trả về False
            ),
            # --- Activity tuần tự có tuỳ chọn người dùng ------------------

            # --- Activity NỀN: lặp lại, bật/tắt khi đang chạy -------------
            Activity(
                id="auto_skip_dialog",
                name="Tự động bỏ qua hội thoại",
                description="Liên tục đóng popup hội thoại (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,   # gọi handler mỗi 1 giây
            ),
            # --- Activity Speedhack do SpeedhackMixin cung cấp sẵn --------
            self.speedhack_activity(),
        ]

    # ====================================================================
    #  HOOK VÒNG LẶP CHÍNH
    # ====================================================================
    def before_process_game_actions(self) -> bool:
        if self._ensure_app_foreground():
            return True
        log_error("Huỷ: không mở được app demo")
        return False

    # ====================================================================
    #  CÁC HANDLER ACTIVITY  (handle_activity_<id>)
    # ====================================================================
    def handle_activity_main_story(self) -> bool:
        log_info("Starting Main Story activity...")
        if not self.back_to_menu(timeout=30): return False
        self.wait_and_tap(self.tpl_home['icon_main_story'], timeout=10)
        if not self.wait_for_template(self.tpl_main_story['is_main_story'], timeout=10):
            log_error("Không vào được màn hình Nhiệm vụ chính tuyến")
            return False
        log_info("Đang làm nhiệm vụ chính tuyến...")
        self.wait_and_tap(self.tpl_main_story['current_chapter'], timeout=10)
        if not self.wait_for_template(self.tpl_main_story['is_current_chapter'], timeout=10):
            log_error("Không vào được chapter hiện tại")
            return False
        self.wait_and_tap(self.tpl_main_story['current_map'], timeout=10)

        while True:
            current_map =  self.wait_for_template(self.tpl_main_story['current_map'], timeout=10)
            if current_map:
                x, y, _ = current_map
                self.tap(x, y)

            if not self.wait_for_template(self.tpl_battle['is_before_battle'], timeout=30):
                log_error("Không vào được màn hình trước trận đấu")
                return False
            self.wait_and_tap(self.tpl_battle['start_battle'], timeout=10)
            self.wait_for_template(self.tpl_battle['is_end_battle'], timeout=180)
            next_map = self.wait_for_template(self.tpl_main_story['next_map'], timeout=5)
            if next_map:
                x, y, _ = next_map
                self.tap(x, y)
                time.sleep(1.0)
            else:
                self.tap(1369, 1015)
                time.sleep(1.0)
        return True


    # ==================== Handler NỀN ====================

    def handle_activity_auto_skip_dialog(self) -> bool:
        skip_tpl = self.tpl_common.get("skip_dialog")
        accept_tpl = self.tpl_common.get("accept_skip_dialog")
        if not skip_tpl or not accept_tpl:
            return False

        result = self.find_template(skip_tpl, last_screen=False)
        if not result:
            return False
        sx, sy, _conf = result
        log_success(f"[bg-skip_dialog] skip button at {sx},{sy}")
        if not self.tap(sx, sy):
            return False
        self.sleep(1)
        self.tap(1189, 818)
        return True


    # ====================================================================
    #  HÀM HELPER
    # ====================================================================
    def back_to_menu(self, timeout: float = 30.0, threshold: float = 0.85) -> bool:
        log_info("Đang quay về menu chính...")
        start_time = time.time()
        back_buttons = self.tpl_common['back']

        while time.time() - start_time < timeout:
            if self.find_template(self.tpl_home['is_home']):
                log_success("Đã ở menu chính")
                return True
            result = self.find_template(back_buttons)
            if not result:
                continue
            x, y, _ = result
            if result:
                self.tap(x, y)


        log_warning("Không quay về được menu chính")
        return False



# Cho phép chạy thử trực tiếp: ``python -m src.games._demo``
if __name__ == "__main__":
    game = gianghochimong()
    game.start()
