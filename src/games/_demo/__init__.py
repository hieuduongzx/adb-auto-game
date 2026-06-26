
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
            'back':        f"{self.templates_dir}/back.png",       # nút Về trang chủ
        }
        self.tpl_home = {
            "is_home": f"{self.templates_dir}/home/is_home.png",
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
        if not self.back_to_menu(timeout=30):
            return False

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

        accept_result = self.wait_and_tap(accept_tpl, timeout=3)
        if accept_result:
            log_success("[bg-skip_dialog] accept tapped")
        else:
            log_info("[bg-skip_dialog] no confirm popup; skip succeeded")
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
