"""
CherryTale Game Automation
"""
import time
from typing import List

from src.games.base_game import BaseGameAutomation, Activity
from src.utils import log_warning, log_success, log_info


# Package name of CherryTale on the device
CHERRYTALE_PACKAGE = "com.neversoft.rpg.erolabs"


class CherryTale(BaseGameAutomation):
    """
    CherryTale Game Automation

    Activities:
        - enter_game:    Make sure CherryTale is in the foreground
        - auto_phuc_loi: Claim daily welfare (phúc lợi -> bữa tiệc)
        - auto_daily:    Run daily routine (after entering the game)
    """

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/cherrytale"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 3

        # Template paths
        self.main_menu = {
            'phuc_loi': f"{self.templates_dir}/main_menu/phuc_loi.png",
            'combat': f"{self.templates_dir}/main_menu/combat.png",
        }
        self.templates = {
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

        }

        # Welfare (phúc lợi) flow templates
        self.phuc_loi = {
            'bua_tiec': f"{self.templates_dir}/phuc_loi/bua_tiec.png",
            'invite_all': f"{self.templates_dir}/phuc_loi/invite_all.png",
            
        }
        self.friend = {
            'friend_icon': f"{self.templates_dir}/friend/icon.png",
            'friend_checking': f"{self.templates_dir}/friend/checking.png",
            'friend_take_all': f"{self.templates_dir}/friend/take_all.png",
            'friend_send_all': f"{self.templates_dir}/friend/send_all.png",
            'friend_check_done': f"{self.templates_dir}/friend/check_done.png",
        }
        self.thu = {
            'thu_icon': f"{self.templates_dir}/thu/icon.png",
            'thu_checking': f"{self.templates_dir}/thu/checking.png",
            'thu_take_all': f"{self.templates_dir}/thu/take_all.png",
        }
        self.combat = {
            'vtgk_icon': f"{self.templates_dir}/combat/vong_tron_gia_kim/icon.png",
            'vtgk_check': f"{self.templates_dir}/combat/vong_tron_gia_kim/check.png",
            'vtgk_point_tim': f"{self.templates_dir}/combat/vong_tron_gia_kim/point_tim.png",
            'vtgk_point_dau': f"{self.templates_dir}/combat/vong_tron_gia_kim/point_dau.png",
            'vtgk_end': f"{self.templates_dir}/combat/vong_tron_gia_kim/end.png",
            'vtgk_end_2': f"{self.templates_dir}/combat/vong_tron_gia_kim/end_2.png",
            'vtgk_exit': f"{self.templates_dir}/combat/vong_tron_gia_kim/exit.png",

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

    def define_activities(self) -> List[Activity]:
        return [
            Activity(id="auto_phuc_loi",name="Phúc Lợi",description="Nhận phúc lợi hằng ngày (bữa tiệc) và mời tất cả",enabled=True,max_retries=1,),
            Activity(id="auto_friend",name="Bạn Bè",description="Tặng và nhận năng lượng từ bạn bè",enabled=True,max_retries=1,),
            Activity(id="auto_thu",name="Hòm Thư",description="Nhận tất cả thư trong hòm thư",enabled=True,max_retries=1,),
            Activity(id="auto_combat_vtgk",name="Vòng Tròn Giả Kim",description="Chạy combat Vòng Tròn Giả Kim 5 lần",enabled=True,max_retries=1,),
            Activity(id="auto_combat_arena",name="Đấu Trường",description="Chạy combat Thử Thách Đấu Trường 5 lần",enabled=True,max_retries=1,),
            Activity(id="auto_combat_tmdq",name="Thiên Mệnh Đối Quyết",description="Chạy combat Thiên Mệnh Đối Quyết",enabled=True,max_retries=1,),
            Activity(id="auto_combat_dvq",name="Đỉnh Vinh Quang",description="Chạy combat Đỉnh Vinh Quang",enabled=True,max_retries=1,),
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
        ]

    # ==================== Activity Handlers ====================

    def handle_activity_auto_phuc_loi(self) -> bool:
        """
        Claim daily welfare (phúc lợi).

        Flow:
            1. Open Phúc Lợi panel
            2. Switch to Bữa Tiệc tab
            3. Tap "Invite All" to invite all friends
            4. Tap "Bắt Đầu" to start the banquet
            5. Return to home (in-game) screen
        """
        log_info("Starting Phuc Loi activity...")

        # Step 1: open welfare panel
        self.update_activity_progress(10.0)
        if not self.wait_and_tap(self.main_menu['phuc_loi'], timeout=10):
            log_warning("Could not find Phuc Loi button")
            return False

        # Step 2: switch to banquet tab
        self.update_activity_progress(30.0)
        if not self.wait_and_tap(self.phuc_loi['bua_tiec'], timeout=10):
            log_warning("Could not find Bua Tiec tab")
            return False

        # Step 3: invite all friends
        # If the Invite All button is missing, it means the banquet is not
        # ready to be claimed yet (cooldown). Treat that as success and exit.
        self.update_activity_progress(50.0)
        if not self.wait_and_tap(self.phuc_loi['invite_all'], timeout=10):
            log_info("Invite All button not visible, banquet not ready yet")
            self.wait_and_tap(self.templates['home'], timeout=5)  # best-effort return home
            self.update_activity_progress(100.0)
            log_success("Phuc Loi skipped (not ready)")
            return True

        # Small pause for the invite popup/animation to settle
        time.sleep(0.5)

        # Step 4: start the banquet
        self.update_activity_progress(70.0)
        if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
            log_warning("Could not find Bat Dau button")
            return False
        
        # Wait for the banquet to start (detect via the "done" marker)
        if not self.wait_and_tap(self.templates['nhan_vao_bat_ky_dau'], timeout=30):
            log_warning("Phuc Loi banquet did not start (Done marker not found)")
            return False
        
        time.sleep(1.0)  # Let the screen settle after starting the banquet
        # Step 5: return to home screen inside the game
        self.update_activity_progress(90.0)
        if not self.wait_and_tap(self.templates['home'], timeout=10):
            log_warning("Could not find Home button after Phuc Loi")
            # Not fatal: the banquet was already started
            return True

        self.update_activity_progress(100.0)
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
        self.update_activity_progress(2.0)
        already_in_friend = self.wait_for_template(
            self.friend['friend_checking'], timeout=5, threshold=0.85
        ) is not None
        if already_in_friend:
            log_info("Already inside Friend panel, skipping navigation")
            self.update_activity_progress(20.0)
        else:
            log_info("Not in Friend panel, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=5):
                log_info("Home button not visible, continuing without it")

            # Open friends panel
            self.update_activity_progress(10.0)
            if not self.wait_and_tap(self.friend['friend_icon'], timeout=10):
                log_warning("Could not find Friend icon")
                return False

            # Confirm we actually landed on the Friend panel
            if not self.wait_for_template(self.friend['friend_checking'], timeout=10):
                log_warning("Friend panel did not appear after navigation")
                return False
            self.update_activity_progress(20.0)

        # Step 2: if already done for today, exit early. Short probe -
        # check_done is rendered as soon as the panel finishes opening.
        self.update_activity_progress(25.0)
        already_done = self.wait_for_template(
            self.friend['friend_check_done'], timeout=5, threshold=0.85
        ) is not None
        if already_done:
            log_info("Friend actions already completed for today")
            self.wait_and_tap(self.templates['home'], timeout=5)  # best-effort
            self.update_activity_progress(100.0)
            log_success("Friend activity skipped (already done)")
            return True

        # Step 3: send energy to all friends (best-effort)
        self.update_activity_progress(40.0)
        if not self.wait_and_tap(self.friend['friend_send_all'], timeout=10):
            log_info("Send All button not visible, continuing")
        else:
            time.sleep(0.5)  # small pause for the send animation

        # Step 4: take energy from all friends
        self.update_activity_progress(60.0)
        if not self.wait_and_tap(self.friend['friend_take_all'], timeout=10):
            log_warning("Could not find Take All button")
            return False

        # Step 5: wait for the "tap anywhere" prompt and dismiss it
        self.update_activity_progress(80.0)
        if not self.wait_and_tap(self.templates['nhan_vao_bat_ky_dau'], timeout=30):
            log_warning("Did not detect tap-anywhere prompt after Take All")
            # Not fatal: energy may already be claimed
        else:
            time.sleep(0.5)

        # Step 6: return to in-game home
        self.update_activity_progress(95.0)
        if not self.wait_and_tap(self.templates['close'], timeout=10):
            log_warning("Could not find Close button after Friend activity")
            return True

        self.update_activity_progress(100.0)
        log_success("Friend activity completed")
        return True

    def handle_activity_auto_thu(self) -> bool:
        """
        Nhận tất cả thư trong hòm thư.

        Flow:
            1. Check if we are already inside the Mail panel (via
               thu_checking marker)
               - If yes: skip navigation, jump straight to take loop
               - If no:  press Home (best-effort) then tap thu icon
            2. Loop until no more mail:
               a. Tap "Take All" to claim mail rewards
               b. Wait for "nhan_vao_bat_ky_dau" prompt and tap it to dismiss
               c. Check if "Take All" is still visible -> repeat; otherwise stop
            3. Tap Home to return to the in-game home screen
        """
        log_info("Starting Thu (Mail) activity...")

        # Step 1: detect whether we are already on the Mail panel
        self.update_activity_progress(2.0)
        already_in_thu = self.wait_for_template(
            self.thu['thu_checking'], timeout=5, threshold=0.85
        ) is not None
        if already_in_thu:
            log_info("Already inside Mail panel, skipping navigation")
            self.update_activity_progress(20.0)
        else:
            log_info("Not in Mail panel, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['close'], timeout=5):
                log_info("Close button not visible, continuing without it")

            # Open mail panel
            self.update_activity_progress(10.0)
            if not self.wait_and_tap(self.thu['thu_icon'], timeout=10):
                log_warning("Could not find Thu icon")
                return False

            # Confirm we actually landed on the Mail panel
            if not self.wait_for_template(self.thu['thu_checking'], timeout=10):
                log_warning("Mail panel did not appear after navigation")
                return False
            self.update_activity_progress(20.0)

        # Step 2: loop take_all -> nhan_vao_bat_ky_dau until no more mail
        # Use find_active_template so a grayed-out (already-claimed) Take All
        # button doesn't trigger another tap loop.
        max_iterations = 10  # safety cap to avoid infinite loops
        claimed = 0
        for i in range(max_iterations):
            # 2a: only tap Take All when it is in its active (colored) state
            active = self.find_active_template(
                self.thu['thu_take_all'], timeout=5, threshold=0.85,
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
            if not self.wait_and_tap(self.templates['nhan_vao_bat_ky_dau'], timeout=15):
                log_warning("Did not detect tap-anywhere prompt after Take All")
                # Not fatal: continue and let the next loop iteration check
            else:
                time.sleep(0.5)  # let the screen settle

            # Progress: scale within 20% -> 90%
            progress = 20.0 + min((i + 1) / max_iterations, 1.0) * 70.0
            self.update_activity_progress(progress)
        else:
            log_warning(f"Reached max iterations ({max_iterations}) for mail take-all")

        # Step 3: return to in-game home
        self.update_activity_progress(95.0)
        if not self.wait_and_tap(self.templates['close'], timeout=10):
            log_warning("Could not find Close button after Thu activity")
            return True

        self.update_activity_progress(100.0)
        log_success(f"Thu activity completed ({claimed} take-all iteration(s))")
        return True

    def handle_activity_auto_combat_vtgk(self) -> bool:
        """
        Run "Vòng Tròn Giả Kim" combat 5 times.

        Flow:
            1. Check if we are already inside VTGK (via vtgk_check marker)
               - If yes: jump straight to the fight loop
               - If no:  press Home (best-effort) then tap Combat -> VTGK icon
            2. Loop 5 times:
               a. Tap "tim" (heart) to enter the fight
               b. Tap "Bắt Đầu" to start
               c. Wait until "stats" screen appears
               d. Tap "Exit" to go back to the heart screen
            3. Return to in-game home screen (best-effort)
        """
        log_info("Starting Combat - Vong Tron Gia Kim activity...")

        # Step 1: detect whether we are already on the VTGK screen
        self.update_activity_progress(2.0)
        already_in_vtgk = self.wait_for_template(
            self.combat['vtgk_check'], timeout=5, threshold=0.85
        ) is not None
        if already_in_vtgk:
            log_info("Already inside VTGK, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in VTGK, navigating from main menu...")

            # Try to return to in-game home first (best-effort, don't fail if missing)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=5):
                log_info("Home button not visible, continuing without it")

            # Open combat from main menu
            self.update_activity_progress(8.0)
            if not self.wait_and_tap(self.main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter VTGK
            self.update_activity_progress(12.0)
            if not self.wait_and_tap(self.combat['vtgk_icon'], timeout=10):
                log_warning("Could not find VTGK icon")
                return False

            # Confirm we actually landed on the VTGK screen
            if not self.wait_for_template(self.combat['vtgk_check'], timeout=10):
                log_warning("VTGK screen did not appear after navigation")
                return False
            self.update_activity_progress(15.0)

        # Step 1.5: if VTGK is already finished for the day, stop early
        if self._is_vtgk_finished():
            log_info("VTGK already completed for today, finishing activity")
            # Best-effort: exit VTGK screen and return to in-game home so
            # the next activity starts from a known state.
            self.wait_and_tap(self.combat['vtgk_exit'], timeout=5)
            self.wait_and_tap(self.templates['home'], timeout=10)
            self.update_activity_progress(100.0)
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
                self.combat['vtgk_point_tim'],
                self.combat['vtgk_point_dau'],
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
            self.update_activity_progress(base_progress + progress_step * 0.25)

            # 2b: tap start
            if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.50)

            # 2c+2d: wait for the stats screen and tap Exit in one shot.
            # Previously we did wait_for_template(exit) + wait_and_tap(exit),
            # which polls the screen twice for the same template.
            if not self.wait_and_tap(self.templates['exit'], timeout=300):
                log_warning(f"Stats screen did not appear / Exit not tapped on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.75)

            # Small pause to let the screen transition back to the heart view
            time.sleep(1.0)
            log_success(f"VTGK run {run_no}/{total_runs} done")

            # 2e: after each run, check if VTGK is finished (no more attempts)
            if self._is_vtgk_finished():
                log_info(f"VTGK end marker detected after run {run_no}, finishing early")
                break

        # Step 3: return home (best-effort)
        self.update_activity_progress(97.0)
        if not self.wait_and_tap(self.templates['home'], timeout=10):
            log_warning("Could not find Home button after VTGK (continuing)")

        self.update_activity_progress(100.0)
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
        self.update_activity_progress(2.0)
        already_in_arena = self.wait_for_template(
            self.combat['arena_check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_arena:
            log_info("Already inside Arena, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in Arena, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=5):
                log_info("Home button not visible, continuing without it")

            # Open combat from main menu
            self.update_activity_progress(8.0)
            if not self.wait_and_tap(self.main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter Arena
            self.update_activity_progress(12.0)
            if not self.wait_and_tap(self.combat['arena_icon'], timeout=10):
                log_warning("Could not find Arena icon")
                return False

            # Confirm we actually landed on the Arena screen
            if not self.wait_for_template(self.combat['arena_check'], timeout=10):
                log_warning("Arena screen did not appear after navigation")
                return False
            self.update_activity_progress(15.0)

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
            if not self.wait_and_tap(self.combat['arena_thu_thach'], timeout=15):
                log_warning(f"Could not find Thu Thach on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.25)


            # 2b: tap start
            if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.50)

            # 2b.1: if Arena is already full, stop the activity early (success)
            # Probe with a short timeout: the "full" banner appears within
            # ~1s after Bat Dau, so 10s wastes time on the common case.
            is_full = self.wait_for_template(self.combat['arena_is_full'], timeout=5) is not None
            if is_full:
                log_info("Arena is full, ending Arena activity early")
                self.wait_and_tap(self.templates['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.templates['home'], timeout=10)  # Try to return home
                self.update_activity_progress(100.0)
                log_success(f"Combat Arena finished (full at run {run_no})")
                return True
            
            # 2c: wait for the stats/result screen
            self._find_end_tap_exit(timeout=300)  # Wait up to 5 minutes for the fight to finish
            self.update_activity_progress(base_progress + progress_step * 0.75)

            # Small pause for the transition back
            time.sleep(1.0)
            log_success(f"Arena run {run_no}/{total_runs} done")

        # Step 3: return home (best-effort)
        self.update_activity_progress(97.0)
        if not self.wait_and_tap(self.templates['home'], timeout=10):
            log_warning("Could not find Home button after Arena (continuing)")

        self.update_activity_progress(100.0)
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
        self.update_activity_progress(2.0)
        already_in_tmdq = self.wait_for_template(
            self.combat['tmdq_check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_tmdq:
            log_info("Already inside TMDQ, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in TMDQ, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=5):
                log_info("Home button not visible, continuing without it")

            # Open combat from main menu
            self.update_activity_progress(8.0)
            if not self.wait_and_tap(self.main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter TMDQ
            self.update_activity_progress(12.0)
            if not self.wait_and_tap(self.combat['tmdq_icon'], timeout=10):
                log_warning("Could not find TMDQ icon")
                return False

            # Confirm we actually landed on the TMDQ screen
            if not self.wait_for_template(self.combat['tmdq_check'], timeout=10):
                log_warning("TMDQ screen did not appear after navigation")
                return False
            self.update_activity_progress(15.0)

        # Step 2: tap "Ra Tran" once to enter the Thu Thach screen
        if not self.wait_and_tap(self.templates['ra_tran'], timeout=10):
            log_warning("Could not find Ra Tran button")
            return False
        self.update_activity_progress(20.0)

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
            if not self.wait_and_tap(self.templates['thu_thach'], timeout=15):
                log_warning(f"Could not find TMDQ Thu Thach on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.20)

            # 3b: tap "Bat Dau"
            if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.40)

            # 3b.1: if TMDQ is already full, stop the activity early (success)
            # Short probe - the full banner appears immediately after Bat Dau.
            is_full = self.wait_for_template(self.combat['tmdq_is_full'], timeout=5) is not None
            if is_full:
                log_info("TMDQ is full, ending TMDQ activity early")
                self.wait_and_tap(self.templates['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.templates['home'], timeout=10)  # Try to return home
                self.update_activity_progress(100.0)
                log_success(f"Combat TMDQ finished (full at run {run_no})")
                return True

            # 3c: tap "Skip" (best-effort). Short probe: when present the
            # button appears almost immediately after Bat Dau.
            if not self.wait_and_tap(self.templates['skip'], timeout=5):
                log_info(f"Skip button not visible on run {run_no}, continuing")
            self.update_activity_progress(base_progress + progress_step * 0.60)

            # 3d: wait for end marker and tap exit
            if not self._find_end_tap_exit(timeout=300):
                log_warning(f"Did not detect end marker on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.90)

            # Small pause to let the screen transition back to Thu Thach
            time.sleep(1.0)
            log_success(f"TMDQ run {run_no}/{total_runs} done")

        # Step 4: return home (best-effort)
        self.update_activity_progress(97.0)
        if not self.wait_and_tap(self.templates['home'], timeout=10):
            log_warning("Could not find Home button after TMDQ (continuing)")

        self.update_activity_progress(100.0)
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
        self.update_activity_progress(2.0)
        already_in_dvq = self.wait_for_template(
            self.combat['dvq_check'], timeout=5, threshold=0.85
        ) is not None

        if already_in_dvq:
            log_info("Already inside DVQ, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in DVQ, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=5):
                log_info("Home button not visible, continuing without it")

            # Open combat from main menu
            self.update_activity_progress(8.0)
            if not self.wait_and_tap(self.main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter DVQ
            self.update_activity_progress(12.0)
            if not self.wait_and_tap(self.combat['dvq_icon'], timeout=10):
                log_warning("Could not find DVQ icon")
                return False

            # Confirm we actually landed on the DVQ screen
            if not self.wait_for_template(self.combat['dvq_check'], timeout=10):
                log_warning("DVQ screen did not appear after navigation")
                return False
            self.update_activity_progress(15.0)

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
            if not self.wait_and_tap(self.combat['dvq_thu_thach'], timeout=15):
                log_warning(f"Could not find DVQ Thu Thach on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.20)

            # 2a.1: if DVQ is already full, stop the activity early (success)
            # Short probe - full banner shows up immediately after Thu Thach.
            is_full = self.wait_for_template(self.combat['dvq_is_full'], timeout=5) is not None
            if is_full:
                log_info("DVQ is full, ending DVQ activity early")
                self.wait_and_tap(self.templates['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.templates['home'], timeout=10)  # Try to return home
                self.update_activity_progress(100.0)
                log_success(f"Combat DVQ finished (full at run {run_no})")
                return True

            # 2a.2: optionally cycle past "Đối Tiếp Theo" prompts. After
            # entering Thu Thach the game can show this button up to 3
            # times before letting us search for an opponent. Probe once
            # with a short timeout - if it isn't there now it never will
            # be - then loop only when the prompt actually appears so we
            # don't burn 3s on the common case.
            if self.wait_for_template(
                self.combat['dvq_doi_tiep_theo'], timeout=5, threshold=0.85
            ):
                for swap in range(3):
                    if not self.wait_and_tap(
                        self.combat['dvq_doi_tiep_theo'], timeout=5
                    ):
                        break
                    log_info(f"DVQ Doi Tiep Theo tapped ({swap + 1})")
                    time.sleep(0.5)

            # 2b: tap "Tim Kiem Doi Thu"
            if not self.wait_and_tap(self.combat['dvq_tim_kiem_doi_thu'], timeout=10):
                log_warning(f"Could not find Tim Kiem Doi Thu on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.40)

            # 2c: wait for "Tap to Continue" and tap it
            if not self.wait_and_tap(self.combat['dvq_tap_to_continue'], timeout=300):
                log_warning(f"Could not find Tap to Continue on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.70)

            # 2d: wait for end marker and tap exit
            if not self._find_end_tap_exit(timeout=30):
                log_warning(f"Did not detect end marker on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.90)

            # Small pause to let the screen transition back to Thu Thach
            time.sleep(1.0)
            log_success(f"DVQ run {run_no}/{total_runs} done")

        # Step 3: return home (best-effort)
        self.update_activity_progress(97.0)
        if not self.wait_and_tap(self.templates['home'], timeout=10):
            log_warning("Could not find Home button after DVQ (continuing)")

        self.update_activity_progress(100.0)
        log_success("Combat DVQ completed (5 runs)")
        return True

    # ==================== Background Handlers ====================

    def handle_activity_auto_skip_dialog(self) -> bool:
        """Background tick: dismiss any in-game dialog popup if visible.

        This runs in its own thread on a poll interval (default 1s) and is
        independent from the sequential activities. We use ``find_template``
        with ``last_screen=True`` so the worker reuses the latest screencap
        captured by the continuous-capture thread; that keeps polling cheap.

        Returns True if a dialog was found and tapped this tick. The return
        value is informational only; the background loop ignores it.
        """
        template = self.templates.get('skip_dialog')
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

    def _is_vtgk_finished(self, timeout: float = 1.0,
                         threshold: float = 0.85) -> bool:
        """Return True if VTGK is finished for the day.

        Uses two strategies in order:

        1. **OCR check (preferred)** - read the attempts counter at
           ``_VTGK_COUNTER_REGION`` and look for ``"0/5"``. Skipped when
           Tesseract is unavailable.
        2. **Template fallback** - look for ``vtgk_end`` / ``vtgk_end_2``
           markers anywhere on screen.
        """
        # Strategy 1: OCR with a digits + '/' whitelist so Tesseract can't
        # hallucinate letters in tiny labels.
        if self.region_has_text(
            "0/5", region=self._VTGK_COUNTER_REGION,
            whitelist="0123456789/",
        ):
            return True

        # Strategy 2: legacy template-based check.
        templates = [self.combat[k] for k in ('vtgk_end', 'vtgk_end_2')
                     if self.combat.get(k)]
        if not templates:
            return False
        return self.wait_for_any_template(
            templates, timeout=timeout, threshold=threshold
        ) is not None

    def _find_end_tap_exit(self, timeout: float = 10.0,
                           threshold: float = 0.85) -> bool:
        """Wait for either exit / exit_2 marker, then tap it.

        Both templates are polled in parallel via ``wait_for_any_template`` so
        whichever appears first will be tapped.
        """
        templates = [self.templates[k] for k in ('exit', 'exit_2')
                     if self.templates.get(k)]
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
