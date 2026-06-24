"""
CherryTale Game Automation
"""
import time
from typing import List

from src.game_core.base_game import BaseGameAutomation, Activity
from src.game_core.speedhack import SpeedhackMixin
from src.utils import log_error, log_warning, log_success, log_info


# Package name of CherryTale on the device
CHERRYTALE_PACKAGE = "com.neversoft.rpg.erolabs"


class CherryTale(SpeedhackMixin, BaseGameAutomation):
    """
    CherryTale Game Automation

    Activities:
        - enter_game:    Make sure CherryTale is in the foreground
        - auto_phuc_loi: Claim daily welfare (phúc lợi -> bữa tiệc)
        - auto_daily:    Run daily routine (after entering the game)
    """

    PACKAGE_NAME = CHERRYTALE_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/cherrytale"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 3
        self.package_name = self.PACKAGE_NAME
        self.setup_speedhack()

        # Template paths
        self.tpl_main_menu = {
            'phuc_loi': f"{self.templates_dir}/main_menu/phuc_loi.png",
            'combat': f"{self.templates_dir}/main_menu/combat.png",
        }
        self.tpl_common = {
            'icon': f"{self.templates_dir}/icon.png",
            'huy_bo': f"{self.templates_dir}/huy_bo.png",
            'home': f"{self.templates_dir}/home.png",
            'ra_tran': f"{self.templates_dir}/ra_tran.png",
            'skip': f"{self.templates_dir}/skip.png",
            'bat_dau': f"{self.templates_dir}/bat_dau.png",
            'thu_thach': f"{self.templates_dir}/thu_thach.png",
            'exit': f"{self.templates_dir}/exit.png",
            'exit_2': f"{self.templates_dir}/exit_2.png",
            'skip_dialog': f"{self.templates_dir}/skip_dialog.png",
            'nhan_vao_bat_ky_dau': f"{self.templates_dir}/nhan_vao_bat_ky_dau.png",
            'close' : f"{self.templates_dir}/close.png",
            'quet' : f"{self.templates_dir}/quet.png",
            'quet_5': f"{self.templates_dir}/quet_5.png",
            'quet_5_again': f"{self.templates_dir}/quet_5_again.png"
        }
        # Welfare (phúc lợi) flow templates
        self.tpl_welfare = {
            'bua_tiec': f"{self.templates_dir}/phuc_loi/bua_tiec.png",
            'invite_all': f"{self.templates_dir}/phuc_loi/invite_all.png",
            
        }
        self.tpl_friend = {
            'friend_icon': f"{self.templates_dir}/friend/icon.png",
            'friend_checking': f"{self.templates_dir}/friend/checking.png",
            'friend_take_all': f"{self.templates_dir}/friend/take_all.png",
            'friend_send_all': f"{self.templates_dir}/friend/send_all.png",
            'friend_check_done': f"{self.templates_dir}/friend/check_done.png",
        }
        self.tpl_mail = {
            'thu_icon': f"{self.templates_dir}/thu/icon.png",
            'thu_checking': f"{self.templates_dir}/thu/checking.png",
            'thu_take_all': f"{self.templates_dir}/thu/take_all.png",
        }
        self.tpl_combat = {
            'vtgk_icon': f"{self.templates_dir}/combat/vong_tron_gia_kim/icon.png",
            'vtgk_check': f"{self.templates_dir}/combat/vong_tron_gia_kim/check.png",
            'vtgk_point_tim': f"{self.templates_dir}/combat/vong_tron_gia_kim/point_tim.png",
            'vtgk_point_dau': f"{self.templates_dir}/combat/vong_tron_gia_kim/point_dau.png",
            'vtgk_end': f"{self.templates_dir}/combat/vong_tron_gia_kim/end.png",
            'vtgk_exit': f"{self.templates_dir}/combat/vong_tron_gia_kim/exit.png",
            'vtgk_reward_1': f"{self.templates_dir}/combat/vong_tron_gia_kim/reward_1.png",
            'vtgk_reward_2': f"{self.templates_dir}/combat/vong_tron_gia_kim/reward_2.png",
            'vtgk_reward_3': f"{self.templates_dir}/combat/vong_tron_gia_kim/reward_3.png",


            'arena_icon': f"{self.templates_dir}/combat/arena/icon.png",
            'arena_check': f"{self.templates_dir}/combat/arena/check.png",
            'arena_thu_thach': f"{self.templates_dir}/combat/arena/thu_thach.png",
            'arena_is_full': f"{self.templates_dir}/combat/arena/is_full.png",

            'tmdq_icon': f"{self.templates_dir}/combat/tmdq/icon.png",
            'tmdq_check': f"{self.templates_dir}/combat/tmdq/check.png",
            'tmdq_is_full': f"{self.templates_dir}/combat/tmdq/is_full.png",

            'dvq_icon': f"{self.templates_dir}/combat/dvq/icon.png",
            'dvq_check': f"{self.templates_dir}/combat/dvq/check.png",
            'dvq_thu_thach': f"{self.templates_dir}/combat/dvq/thu_thach.png",
            'dvq_doi_tiep_theo' : f"{self.templates_dir}/combat/dvq/doi_tiep_theo.png",
            'dvq_tim_kiem_doi_thu': f"{self.templates_dir}/combat/dvq/tim_kiem_doi_thu.png",
            'dvq_tap_to_continue': f"{self.templates_dir}/combat/dvq/tap_to_continue.png",
            'dvq_is_full': f"{self.templates_dir}/combat/dvq/is_full.png",

        }
        self.tpl_phieu_luu = {
            "icon": f"{self.templates_dir}/phieu_luu/icon.png",
            "check": f"{self.templates_dir}/phieu_luu/check.png",
        }
        self.tpl_phieu_luu_nguyen_lieu = {
            "icon": f"{self.templates_dir}/phieu_luu/nguyen_lieu/icon.png",
            "check": f"{self.templates_dir}/phieu_luu/nguyen_lieu/check.png",
        }

    def define_activities(self) -> List[Activity]:
        return [
            Activity(id="auto_phuc_loi",name="Phúc Lợi",description="Nhận phúc lợi hằng ngày (bữa tiệc) và mời tất cả",enabled=True,max_retries=1,),
            Activity(id="auto_friend",name="Bạn Bè",description="Tặng và nhận năng lượng từ bạn bè",enabled=True,max_retries=1,),
            Activity(id="auto_thu",name="Hòm Thư",description="Nhận tất cả thư trong hòm thư",enabled=True,max_retries=1,),
            Activity(id="auto_combat_vtgk",name="Vòng Tròn Giả Kim",description="Chạy combat Vòng Tròn Giả Kim 5 lần",enabled=True,max_retries=1,),
            Activity(id="auto_combat_arena",name="Đấu Trường",description="Chạy combat Thử Thách Đấu Trường 5 lần",enabled=True,max_retries=1,),
            Activity(id="auto_combat_tmdq",name="Thiên Mệnh Đối Quyết",description="Chạy combat Thiên Mệnh Đối Quyết",enabled=True,max_retries=1,),
            Activity(id="auto_combat_dvq",name="Đỉnh Vinh Quang",description="Chạy combat Đỉnh Vinh Quang",enabled=True,max_retries=1,),
            Activity(id="auto_phieu_luu_nguyen_lieu",name="Phiêu Lưu Nguyên Liệu",description="Farm nguyên liệu trong phiêu lưu",enabled=True,max_retries=1,),
            # Background activity: runs in its own thread alongside the
            # sequential ones above. Can be toggled on/off in the UI even
            # while automation is running.
            Activity(
                id="auto_skip_dialog",
                name="Tự Động Bỏ Qua Hội Thoại",
                description="Liên tục đóng các popup hội thoại trong game (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            self.speedhack_activity(),
        ]

    # ==================== Main loop entry ====================

    def before_process_game_actions(self) -> bool:
        """Run activities only after CherryTale is foregrounded."""
        if self._ensure_app_foreground():
            return True
        log_error("Aborting: CherryTale app could not be started")
        return False

    # ==================== Activity Handlers ====================

    def handle_activity_auto_phuc_loi(self) -> bool:
        log_info("Starting Phuc Loi activity...")
        # Step 1: open welfare panel
        if not self.wait_and_tap(self.tpl_main_menu['phuc_loi'], timeout=10):
            log_warning("Could not find Phuc Loi button")
            return False

        # Step 2: switch to banquet tab
        if not self.wait_and_tap(self.tpl_welfare['bua_tiec'], timeout=10):
            log_warning("Could not find Bua Tiec tab")
            return False

        # Step 3: invite all friends
        # If the Invite All button is missing, it means the banquet is not
        # ready to be claimed yet (cooldown). Treat that as success and exit.
        if not self.wait_and_tap(self.tpl_welfare['invite_all'], timeout=10):
            log_info("Invite All button not visible, banquet not ready yet")
            self.wait_and_tap(self.tpl_common['home'], timeout=5)  # best-effort return home
            log_success("Phuc Loi skipped (not ready)")
            return True

        # Small pause for the invite popup/animation to settle
        time.sleep(0.5)

        # Step 4: start the banquet
        if not self.wait_and_tap(self.tpl_common['bat_dau'], timeout=10):
            log_warning("Could not find Bat Dau button")
            return False
        
        # Wait for the banquet to start (detect via the "done" marker)
        if not self.wait_and_tap(self.tpl_common['nhan_vao_bat_ky_dau'], timeout=30):
            log_warning("Phuc Loi banquet did not start (Done marker not found)")
            return False
        
        time.sleep(1.0)  # Let the screen settle after starting the banquet
        # Step 5: return to home screen inside the game
        if not self.wait_and_tap(self.tpl_common['home'], timeout=10):
            log_warning("Could not find Home button after Phuc Loi")
            # Not fatal: the banquet was already started
            return True

        log_success("Phuc Loi completed")
        return True

    def handle_activity_auto_friend(self) -> bool:
        """
        Tặng và nhận năng lượng từ bạn bè.

        Flow:
            1. Check if we are already inside the Friends panel (via
               friend_checking marker)
               - If yes: skip navigation, jump straight to send/take
               - If no:  press Home (best-effort) then tap friend icon
            2. If "check_done" marker is already on screen, today's friend
               actions are already done -> return home and exit successfully
            3. Tap "Send All" to gift energy to all friends
            4. Tap "Take All" to claim energy from all friends
            5. Wait for the "nhan_vao_bat_ky_dau" prompt and tap it to dismiss
            6. Tap Home to return to the in-game home screen
        """
        log_info("Starting Friend activity...")

        # Step 1: detect whether we are already on the Friend panel
        already_in_friend = self.wait_for_template(
            self.tpl_friend['friend_checking'], timeout=5, threshold=0.85
        ) is not None
        if already_in_friend:
            log_info("Already inside Friend panel, skipping navigation")
        else:
            log_info("Not in Friend panel, returning to main menu...")

            # Return to the main menu first (best path to a known state)
            if not self.back_to_menu(timeout=30):
                return False

            # Open friends panel
            if not self.wait_and_tap(self.tpl_friend['friend_icon'], timeout=10):
                log_warning("Could not find Friend icon")
                return False

            # Confirm we actually landed on the Friend panel
            if not self.wait_for_template(self.tpl_friend['friend_checking'], timeout=10):
                log_warning("Friend panel did not appear after navigation")
                return False

        # Step 2: if already done for today, exit early. Short probe -
        # check_done is rendered as soon as the panel finishes opening.
        already_done = self.wait_for_template(
            self.tpl_friend['friend_check_done'], timeout=5, threshold=0.85
        ) is not None
        if already_done:
            log_info("Friend actions already completed for today")
            self.wait_and_tap(self.tpl_common['home'], timeout=5)  # best-effort
            log_success("Friend activity skipped (already done)")
            return True

        # Step 3: send energy to all friends (best-effort)
        if not self.wait_and_tap(self.tpl_friend['friend_send_all'], timeout=10):
            log_info("Send All button not visible, continuing")
        else:
            time.sleep(0.5)  # small pause for the send animation

        # Step 4: take energy from all friends
        if not self.wait_and_tap(self.tpl_friend['friend_take_all'], timeout=10):
            log_warning("Could not find Take All button")
            return False

        # Step 5: wait for the "tap anywhere" prompt and dismiss it
        if not self.wait_and_tap(self.tpl_common['nhan_vao_bat_ky_dau'], timeout=30):
            log_warning("Did not detect tap-anywhere prompt after Take All")
            # Not fatal: energy may already be claimed
        else:
            time.sleep(0.5)

        # Step 6: return to in-game home
        if not self.wait_and_tap(self.tpl_common['close'], timeout=10):
            log_warning("Could not find Close button after Friend activity")
            return True

        log_success("Friend activity completed")
        return True

    def handle_activity_auto_thu(self) -> bool:
        log_info("Starting Thu (Mail) activity...")
        # Step 1: detect whether we are already on the Mail panel
        already_in_thu = self.wait_for_template(
            self.tpl_mail['thu_checking'], timeout=5, threshold=0.85
        ) is not None
        if already_in_thu:
            log_info("Already inside Mail panel, skipping navigation")
        else:
            log_info("Not in Mail panel, returning to main menu...")
            if not self.back_to_menu(timeout=30):
                return False

            if not self.wait_and_tap(self.tpl_mail['thu_icon'], timeout=10):
                log_warning("Could not find Thu icon")
                return False

            # Confirm we actually landed on the Mail panel
            if not self.wait_for_template(self.tpl_mail['thu_checking'], timeout=10):
                log_warning("Mail panel did not appear after navigation")
                return False

        # Step 2: loop take_all -> nhan_vao_bat_ky_dau until no more mail
        # Use find_active_template so a grayed-out (already-claimed) Take All
        # button doesn't trigger another tap loop.
        max_iterations = 10  # safety cap to avoid infinite loops
        claimed = 0
        for i in range(max_iterations):
            # 2a: only tap Take All when it is in its active (colored) state
            active = self.find_active_template(
                self.tpl_mail['thu_take_all'], timeout=5, threshold=0.85,
            )
            if not active:
                if claimed == 0:
                    log_info("No active mail to claim (Take All grayed/missing)")
                else:
                    log_info(f"No more active mail after {claimed} iteration(s)")
                break

            x, y, _ = active
            if not self.tap(x, y):
                log_warning("Failed to tap Take All")
                break

            claimed += 1
            log_info(f"Mail take-all iteration {claimed}")

            # 2b: wait for the "tap anywhere" prompt and dismiss it
            if not self.wait_and_tap(self.tpl_common['nhan_vao_bat_ky_dau'], timeout=15):
                log_warning("Did not detect tap-anywhere prompt after Take All")
                # Not fatal: continue and let the next loop iteration check
            else:
                time.sleep(0.5)  # let the screen settle

            # Progress: scale within 20% -> 90%
            progress = 20.0 + min((i + 1) / max_iterations, 1.0) * 70.0
        else:
            log_warning(f"Reached max iterations ({max_iterations}) for mail take-all")

        # Step 3: return to in-game home
        if not self.wait_and_tap(self.tpl_common['close'], timeout=10):
            log_warning("Could not find Close button after Thu activity")
            return True

        log_success(f"Thu activity completed ({claimed} take-all iteration(s))")
        return True

    def handle_activity_auto_combat_vtgk(self) -> bool:
        log_info("Starting Combat - Vong Tron Gia Kim activity...")
        # Step 1: detect whether we are already on the VTGK screen
        already_in_vtgk = self.wait_for_template(
            self.tpl_combat['vtgk_check'], timeout=5, threshold=0.85
        ) is not None
        if already_in_vtgk:
            log_info("Already inside VTGK, skipping navigation")
        else:
            log_info("Not in VTGK, returning to main menu...")

            if not self.back_to_menu(timeout=30):
                return False

            # Open combat from main menu
            if not self.wait_and_tap(self.tpl_main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter VTGK
            if not self.wait_and_tap(self.tpl_combat['vtgk_icon'], timeout=10):
                log_warning("Could not find VTGK icon")
                return False

            # Confirm we actually landed on the VTGK screen
            if not self.wait_for_template(self.tpl_combat['vtgk_check'], timeout=10):
                log_warning("VTGK screen did not appear after navigation")
                return False

        # Step 1.5: if VTGK is already finished for the day, stop early
        if self._is_vtgk_finished():
            log_info("VTGK already completed for today, finishing activity")
            # Best-effort: claim the weekly reward slot 1 if available, then
            # exit VTGK screen and return to in-game home.
            self.wait_and_tap(self.tpl_combat['vtgk_reward_1'], timeout=5)
            self.wait_and_tap(self.tpl_combat['vtgk_exit'], timeout=5)
            self.wait_and_tap(self.tpl_common['home'], timeout=10)
            log_success("Combat VTGK already completed")
            return True

        # Step 2: run the heart-fight loop 5 times
        total_runs = 5
        progress_start = 20.0
        progress_end = 95.0
        progress_step = (progress_end - progress_start) / total_runs

        for i in range(total_runs):
            run_no = i + 1
            log_info(f"VTGK run {run_no}/{total_runs}")

            base_progress = progress_start + progress_step * i

            # 2a: tap heart to start a fight. Either point_tim or point_dau
            # appears (depending on the day's stage), so race them with a
            # single wait_for_any_template instead of chaining two 15s
            # waits - that way a missing template never costs us 30s.
            heart_templates = [
                self.tpl_combat['vtgk_point_tim'],
                self.tpl_combat['vtgk_point_dau'],
            ]
            heart_match = self.wait_for_any_template(
                heart_templates, timeout=15, threshold=0.85,
            )
            if not heart_match:
                log_warning(f"Could not find VTGK heart or start button on run {run_no}")
                return False
            _, hx, hy, _ = heart_match
            if not self.tap(hx, hy):
                log_warning(f"Failed to tap VTGK heart on run {run_no}")
                return False

            # 2b: tap start
            if not self.wait_and_tap(self.tpl_common['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False

            # 2c+2d: wait for the stats screen and tap Exit in one shot.
            # Previously we did wait_for_template(exit) + wait_and_tap(exit),
            # which polls the screen twice for the same template.
            if not self.wait_and_tap(self.tpl_common['exit'], timeout=300):
                log_warning(f"Stats screen did not appear / Exit not tapped on run {run_no}")
                return False

            # Small pause to let the screen transition back to the heart view
            time.sleep(1.0)
            log_success(f"VTGK run {run_no}/{total_runs} done")

            # 2e: after each run, check if VTGK is finished (no more attempts)
            if self._is_vtgk_finished():
                log_info(f"VTGK end marker detected after run {run_no}, finishing early")
                break

        # Step 3: return home (best-effort)
        if not self.wait_and_tap(self.tpl_common['home'], timeout=10):
            log_warning("Could not find Home button after VTGK (continuing)")

        log_success("Combat VTGK completed (5 runs)")
        return True

    def handle_activity_auto_combat_arena(self) -> bool:
        """
        Run "Arena" thu thach combat up to 5 times.

        Flow:
            1. Check if we are already inside Arena (via arena_check marker)
               - If yes: jump straight to the fight loop
               - If no:  press Home (best-effort) -> Combat -> tap Arena icon
            2. Loop 5 times:
               a. Tap "Thu Thach" to enter the fight
               b. Tap "Bắt Đầu" to start
               c. Wait until "stats" screen appears
               d. Tap "Exit" to go back to the Arena screen
            3. Return to in-game home screen (best-effort)
        """
        log_info("Starting Combat - Arena activity...")
        # Step 1: detect whether we are already on the Arena screen
        already_in_arena = self.wait_for_template(
            self.tpl_combat['arena_check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_arena:
            log_info("Already inside Arena, skipping navigation")
        else:
            log_info("Not in Arena, returning to main menu...")

            if not self.back_to_menu(timeout=30):
                return False

            # Open combat from main menu
            if not self.wait_and_tap(self.tpl_main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter Arena
            if not self.wait_and_tap(self.tpl_combat['arena_icon'], timeout=10):
                log_warning("Could not find Arena icon")
                return False

            # Confirm we actually landed on the Arena screen
            if not self.wait_for_template(self.tpl_combat['arena_check'], timeout=10):
                log_warning("Arena screen did not appear after navigation")
                return False

        # Step 2: run the thu thach combat loop up to 5 times
        total_runs = 5
        progress_start = 20.0
        progress_end = 95.0
        progress_step = (progress_end - progress_start) / total_runs

        for i in range(total_runs):
            run_no = i + 1
            log_info(f"Arena run {run_no}/{total_runs}")

            base_progress = progress_start + progress_step * i

            # 2a: tap thu thach to start a fight
            if not self.wait_and_tap(self.tpl_combat['arena_thu_thach'], timeout=15):
                log_warning(f"Could not find Thu Thach on run {run_no}")
                return False


            # 2b: tap start
            if not self.wait_and_tap(self.tpl_common['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False

            # 2b.1: if Arena is already full, stop the activity early (success)
            # Probe with a short timeout: the "full" banner appears within
            # ~1s after Bat Dau, so 10s wastes time on the common case.
            is_full = self.wait_for_template(self.tpl_combat['arena_is_full'], timeout=5) is not None
            if is_full:
                log_info("Arena is full, ending Arena activity early")
                self.wait_and_tap(self.tpl_common['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.tpl_common['home'], timeout=10)  # Try to return home
                log_success(f"Combat Arena finished (full at run {run_no})")
                return True
            
            # 2c: wait for the stats/result screen
            self._find_end_tap_exit(timeout=300)  # Wait up to 5 minutes for the fight to finish

            # Small pause for the transition back
            time.sleep(1.0)
            log_success(f"Arena run {run_no}/{total_runs} done")

        # Step 3: return home (best-effort)
        if not self.wait_and_tap(self.tpl_common['home'], timeout=10):
            log_warning("Could not find Home button after Arena (continuing)")

        log_success("Combat Arena completed (5 runs)")
        return True

    def handle_activity_auto_combat_tmdq(self) -> bool:
        """
        Run "Thien Menh Doi Quyet" (TMDQ) combat 5 times.

        Flow:
            1. Check if we are already inside TMDQ (via tmdq_check marker)
               - If yes: skip navigation
               - If no:  press Home (best-effort) -> Combat -> tap TMDQ icon
            2. Tap "Ra Tran" (once)
            3. Loop 5 times:
               a. Tap "Thu Thach"
               b. Tap "Bat Dau"
               c. Tap "Skip" (best-effort)
               d. Wait for end marker (exit/exit_2), then tap it
               After tapping exit we're back on the Thu Thach screen
            4. Return to in-game home (best-effort)
        """
        log_info("Starting Combat - TMDQ activity...")

        # Step 1: detect whether we are already on the TMDQ screen
        already_in_tmdq = self.wait_for_template(
            self.tpl_combat['tmdq_check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_tmdq:
            log_info("Already inside TMDQ, skipping navigation")
        else:
            log_info("Not in TMDQ, returning to main menu...")

            if not self.back_to_menu(timeout=30):
                return False

            # Open combat from main menu
            if not self.wait_and_tap(self.tpl_main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter TMDQ
            if not self.wait_and_tap(self.tpl_combat['tmdq_icon'], timeout=10):
                log_warning("Could not find TMDQ icon")
                return False

            # Confirm we actually landed on the TMDQ screen
            if not self.wait_for_template(self.tpl_combat['tmdq_check'], timeout=10):
                log_warning("TMDQ screen did not appear after navigation")
                return False

        # Step 2: tap "Ra Tran" once to enter the Thu Thach screen
        if not self.wait_and_tap(self.tpl_common['ra_tran'], timeout=10):
            log_warning("Could not find Ra Tran button")
            return False

        # Step 3: run the Thu Thach combat loop 5 times
        total_runs = 5
        progress_start = 25.0
        progress_end = 95.0
        progress_step = (progress_end - progress_start) / total_runs

        for i in range(total_runs):
            run_no = i + 1
            log_info(f"TMDQ run {run_no}/{total_runs}")

            base_progress = progress_start + progress_step * i

            # 3a: tap "Thu Thach"
            if not self.wait_and_tap(self.tpl_common['thu_thach'], timeout=15):
                log_warning(f"Could not find TMDQ Thu Thach on run {run_no}")
                return False

            # 3b: tap "Bat Dau"
            if not self.wait_and_tap(self.tpl_common['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False

            # 3b.1: if TMDQ is already full, stop the activity early (success)
            # Short probe - the full banner appears immediately after Bat Dau.
            is_full = self.wait_for_template(self.tpl_combat['tmdq_is_full'], timeout=5) is not None
            if is_full:
                log_info("TMDQ is full, ending TMDQ activity early")
                self.wait_and_tap(self.tpl_common['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.tpl_common['home'], timeout=10)  # Try to return home
                log_success(f"Combat TMDQ finished (full at run {run_no})")
                return True

            # 3c: tap "Skip" (best-effort). Short probe: when present the
            # button appears almost immediately after Bat Dau.
            if not self.wait_and_tap(self.tpl_common['skip'], timeout=5):
                log_info(f"Skip button not visible on run {run_no}, continuing")

            # 3d: wait for end marker and tap exit
            if not self._find_end_tap_exit(timeout=300):
                log_warning(f"Did not detect end marker on run {run_no}")
                return False

            # Small pause to let the screen transition back to Thu Thach
            time.sleep(1.0)
            log_success(f"TMDQ run {run_no}/{total_runs} done")

        # Step 4: return home (best-effort)
        if not self.wait_and_tap(self.tpl_common['home'], timeout=10):
            log_warning("Could not find Home button after TMDQ (continuing)")

        log_success("Combat TMDQ completed (5 runs)")
        return True

    def handle_activity_auto_combat_dvq(self) -> bool:
        """
        Run "Dinh Vinh Quang" (DVQ) combat 5 times.

        Flow:
            1. Check if we are already inside DVQ (via dvq_check marker)
               - If yes: skip navigation
               - If no:  press Home (best-effort) -> Combat -> tap DVQ icon
            2. Loop 5 times:
               a. Tap "Thu Thach"
               b. Tap "Tim Kiem Doi Thu"
               c. Wait for end marker (tap_to_continue), then tap it
               d. Wait for and tap "Exit" to return to the Thu Thach screen
            3. Return to in-game home (best-effort)
        """
        log_info("Starting Combat - DVQ activity...")

        # Step 1: detect whether we are already on the DVQ screen
        already_in_dvq = self.wait_for_template(
            self.tpl_combat['dvq_check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_dvq:
            log_info("Already inside DVQ, skipping navigation")
        else:
            log_info("Not in DVQ, returning to main menu...")

            if not self.back_to_menu(timeout=30):
                return False

            # Open combat from main menu
            if not self.wait_and_tap(self.tpl_main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter DVQ
            if not self.wait_and_tap(self.tpl_combat['dvq_icon'], timeout=10):
                log_warning("Could not find DVQ icon")
                return False

            # Confirm we actually landed on the DVQ screen
            if not self.wait_for_template(self.tpl_combat['dvq_check'], timeout=10):
                log_warning("DVQ screen did not appear after navigation")
                return False

        # Step 2: run the Thu Thach combat loop 5 times
        total_runs = 5
        progress_start = 20.0
        progress_end = 95.0
        progress_step = (progress_end - progress_start) / total_runs

        for i in range(total_runs):
            run_no = i + 1
            log_info(f"DVQ run {run_no}/{total_runs}")

            base_progress = progress_start + progress_step * i

            # 2a: tap "Thu Thach"
            if not self.wait_and_tap(self.tpl_combat['dvq_thu_thach'], timeout=15):
                log_warning(f"Could not find DVQ Thu Thach on run {run_no}")
                return False

            # 2a.1: if DVQ is already full, stop the activity early (success)
            # Short probe - full banner shows up immediately after Thu Thach.
            is_full = self.wait_for_template(self.tpl_combat['dvq_is_full'], timeout=5) is not None
            if is_full:
                log_info("DVQ is full, ending DVQ activity early")
                self.wait_and_tap(self.tpl_common['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.tpl_common['home'], timeout=10)  # Try to return home
                log_success(f"Combat DVQ finished (full at run {run_no})")
                return True

            # 2a.2: optionally cycle past "Đối Tiếp Theo" prompts. After
            # entering Thu Thach the game can show this button up to 3
            # times before letting us search for an opponent. Probe once
            # with a short timeout - if it isn't there now it never will
            # be - then loop only when the prompt actually appears so we
            # don't burn 3s on the common case.
            if self.wait_for_template(
                self.tpl_combat['dvq_doi_tiep_theo'], timeout=5, threshold=0.85
            ):
                for swap in range(3):
                    if not self.wait_and_tap(
                        self.tpl_combat['dvq_doi_tiep_theo'], timeout=5
                    ):
                        break
                    log_info(f"DVQ Doi Tiep Theo tapped ({swap + 1})")
                    time.sleep(0.5)

            # 2b: tap "Tim Kiem Doi Thu"
            if not self.wait_and_tap(self.tpl_combat['dvq_tim_kiem_doi_thu'], timeout=10):
                log_warning(f"Could not find Tim Kiem Doi Thu on run {run_no}")
                return False

            # 2c: wait for "Tap to Continue" and tap it
            if not self.wait_and_tap(self.tpl_combat['dvq_tap_to_continue'], timeout=300):
                log_warning(f"Could not find Tap to Continue on run {run_no}")
                return False

            # 2d: wait for end marker and tap exit
            if not self._find_end_tap_exit(timeout=30):
                log_warning(f"Did not detect end marker on run {run_no}")
                return False

            # Small pause to let the screen transition back to Thu Thach
            time.sleep(1.0)
            log_success(f"DVQ run {run_no}/{total_runs} done")

        # Step 3: return home (best-effort)
        if not self.wait_and_tap(self.tpl_common['home'], timeout=10):
            log_warning("Could not find Home button after DVQ (continuing)")

        log_success("Combat DVQ completed (5 runs)")
        return True

    def handle_activity_auto_phieu_luu_nguyen_lieu(self) -> bool:
        log_info("Starting Phieu Luu Nguyen Lieu activity...")

        # Step 1: check if already on phieu luu screen
        already_in_phieu_luu = self.wait_for_template(
            self.tpl_phieu_luu['check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_phieu_luu:
            log_info("Already inside Phieu Luu, skipping navigation")
        else:
            if not self.back_to_menu(timeout=30):
                return False

            if not self.wait_and_tap(self.tpl_phieu_luu['icon'], timeout=10):
                log_warning("Could not find Phieu Luu icon")
                return False

            if not self.wait_for_template(self.tpl_phieu_luu['check'], timeout=10):
                log_warning("Phieu Luu screen did not appear after navigation")
                return False

        # Step 2: tap Nguyen Lieu tab
        if not self.wait_and_tap(self.tpl_phieu_luu_nguyen_lieu['icon'], timeout=10):
            log_warning("Could not find Phieu Luu Nguyen Lieu icon")
            return False

        if not self.wait_for_template(self.tpl_phieu_luu_nguyen_lieu['check'], timeout=10):
            log_warning("Nguyen Lieu screen did not appear")
            return False

        # Step 3: tap the farm button at fixed coordinates
        if not self.tap(85, 736):
            log_warning("Failed to tap Nguyen Lieu farm button")
            return False

        # Step 4: wait 2s then tap the confirm/start button
        time.sleep(2.0)
        if not self.tap(1585, 694):
            log_warning("Failed to tap Nguyen Lieu confirm button")
            return False

        # Step 5: wait for quet_5 to appear and tap it
        if not self.wait_and_tap(self.tpl_common['quet_5'], timeout=30):
            log_warning("quet_5 did not appear after starting Nguyen Lieu")
            return False

        # Step 6: if quet_5_again appears, tap it too (best-effort)
        self.wait_and_tap(self.tpl_common['quet_5_again'], timeout=10)

        log_success("Phieu Luu Nguyen Lieu completed")
        return True

    # ==================== Background Handlers ====================

    def handle_activity_auto_skip_dialog(self) -> bool:
        template = self.tpl_common.get('skip_dialog')
        if not template:
            return False
        result = self.find_template(template, last_screen=True)
        if not result:
            return False
        x, y, _conf = result
        return self.tap(x, y)

    # ==================== Helpers ====================

    # Region (x, y, w, h) of the "0/5" attempts counter on the VTGK screen.
    # When the counter reads "0/5" all daily attempts have been used.
    _VTGK_COUNTER_REGION = (1530, 927, 273, 71)

    def back_to_menu(self, timeout: float = 30.0, threshold: float = 0.85) -> bool:
        log_info("Returning to main menu...")
        start_time = time.time()
        back_templates = [
            self.tpl_common['close'],
            self.tpl_common['exit'],
            self.tpl_common['home'],
        ]

        while time.time() - start_time < timeout:
            if self.find_template(self.tpl_main_menu['phuc_loi'], threshold=threshold):
                log_success("Main menu detected")
                return True

            tapped = False
            for template in back_templates:
                result = self.find_template(template, threshold=threshold)
                if not result:
                    continue
                x, y, _ = result
                if self.tap(x, y):
                    tapped = True
                    time.sleep(1.0)
                    break

            if not tapped:
                time.sleep(0.5)

        log_warning("Could not return to main menu")
        return False

    def _is_vtgk_finished(self, timeout: float = 1.0, threshold: float = 0.85) -> bool:
        return self.region_has_text(
            "0/5", region=self._VTGK_COUNTER_REGION, whitelist="0123456789/",
        )

    def _find_end_tap_exit(self, timeout: float = 10.0,
                           threshold: float = 0.85) -> bool:
        """Wait for either exit / exit_2 marker, then tap it.

        Both templates are polled in parallel via ``wait_for_any_template`` so
        whichever appears first will be tapped.
        """
        templates = [self.tpl_common[k] for k in ('exit', 'exit_2')
                     if self.tpl_common.get(k)]
        if not templates:
            return False

        result = self.wait_for_any_template(
            templates, timeout=timeout, threshold=threshold
        )
        if not result:
            return False

        _, x, y, _ = result
        if not self.tap(x, y):
            return False

        time.sleep(0.5)
        return True
    


if __name__ == "__main__":
    game = CherryTale()
    game.start()
