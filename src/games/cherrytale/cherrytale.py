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
        }

        # Welfare (phúc lợi) flow templates
        self.phuc_loi = {
            'bua_tiec': f"{self.templates_dir}/phuc_loi/bua_tiec.png",
            'invite_all': f"{self.templates_dir}/phuc_loi/invite_all.png",
            'nhan_vao_bat_ky_dau': f"{self.templates_dir}/phuc_loi/nhan_vao_bat_ky_dau.png",
        }
        self.combat = {
            'vtgk_icon': f"{self.templates_dir}/combat/vong_tron_gia_kim/icon.png",
            'vtgk_check': f"{self.templates_dir}/combat/vong_tron_gia_kim/check.png",
            'vtgk_point_tim': f"{self.templates_dir}/combat/vong_tron_gia_kim/point_tim.png",
            'vtgk_point_dau': f"{self.templates_dir}/combat/vong_tron_gia_kim/point_dau.png",
            'vtgk_end': f"{self.templates_dir}/combat/vong_tron_gia_kim/end.png",
            'vtgk_end_2': f"{self.templates_dir}/combat/vong_tron_gia_kim/end_2.png",
            'vtgk_exit': f"{self.templates_dir}/combat/vong_tron_gia_kim/exit.png",

            'area_icon': f"{self.templates_dir}/combat/area/icon.png",
            'area_check': f"{self.templates_dir}/combat/area/check.png",
            'area_thu_thach': f"{self.templates_dir}/combat/area/thu_thach.png",
            'area_is_full': f"{self.templates_dir}/combat/area/is_full.png",

            'tmdq_icon': f"{self.templates_dir}/combat/tmdq/icon.png",
            'tmdq_check': f"{self.templates_dir}/combat/tmdq/check.png",
            'tmdq_is_full': f"{self.templates_dir}/combat/tmdq/is_full.png",

            'dvq_icon': f"{self.templates_dir}/combat/dvq/icon.png",
            'dvq_check': f"{self.templates_dir}/combat/dvq/check.png",
            'dvq_thu_thach': f"{self.templates_dir}/combat/dvq/thu_thach.png",
            'dvq_tim_kiem_doi_thu': f"{self.templates_dir}/combat/dvq/tim_kiem_doi_thu.png",
            'dvq_tap_to_continue': f"{self.templates_dir}/combat/dvq/tap_to_continue.png",
            'dvq_is_full': f"{self.templates_dir}/combat/dvq/is_full.png",

        }

    def define_activities(self) -> List[Activity]:
        return [
      #      Activity(id="auto_phuc_loi",name="Phuc Loi",description="Claim daily welfare (bữa tiệc) and invite all",enabled=True,max_retries=1,),
            Activity(id="auto_combat_vtgk",name="Combat Vong Tron Gia Kim",description="Handle combat activities",enabled=True,max_retries=1,),
         #   Activity(id="auto_combat_area",name="Combat Area",description="Run Area thu thach combat 5 times",enabled=True,max_retries=1,),
          #  Activity(id="auto_combat_tmdq",name="Combat TMDQ",description="Run Thien Menh Doi Quyet combat",enabled=True,max_retries=1,),
            Activity(id="auto_combat_dvq",name="Combat DVQ",description="Run Dinh Vinh Quang combat",enabled=True,max_retries=1,),
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
        self.update_activity_progress(50.0)
        if not self.wait_and_tap(self.phuc_loi['invite_all'], timeout=10):
            log_warning("Could not find Invite All button")
            return False

        # Small pause for the invite popup/animation to settle
        time.sleep(0.5)

        # Step 4: start the banquet
        self.update_activity_progress(70.0)
        if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
            log_warning("Could not find Bat Dau button")
            return False
        
        # Wait for the banquet to start (detect via the "done" marker)
        if not self.wait_and_tap(self.phuc_loi['nhan_vao_bat_ky_dau'], timeout=30):
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
            self.combat['vtgk_check'], timeout=2, threshold=0.85
        ) is not None
        if already_in_vtgk:
            log_info("Already inside VTGK, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in VTGK, navigating from main menu...")

            # Try to return to in-game home first (best-effort, don't fail if missing)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=3):
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

            # 2a: tap heart to start a fight
            if not self.wait_and_tap(self.combat['vtgk_point_tim'], timeout=15) and not self.wait_and_tap(self.combat['vtgk_point_dau'], timeout=15):
                log_warning(f"Could not find VTGK heart or start button on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.25)

            # 2b: tap start
            if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.50)

            # 2c: wait for the stats/result screen
            if not self.wait_for_template(self.templates['exit'], timeout=300):
                log_warning(f"Stats screen did not appear on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.75)

            # 2d: tap exit, which brings us back to the heart screen
            if not self.wait_and_tap(self.templates['exit'], timeout=10):
                log_warning(f"Could not find Exit on run {run_no}")
                return False

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

    def handle_activity_auto_combat_area(self) -> bool:
        """
        Run "Area" thu thach combat up to 5 times.

        Flow:
            1. Check if we are already inside Area (via area_check marker)
               - If yes: jump straight to the fight loop
               - If no:  press Home (best-effort) -> Combat -> tap Area icon
            2. Loop 5 times:
               a. Tap "Thu Thach" to enter the fight
               b. Tap "Bắt Đầu" to start
               c. Wait until "stats" screen appears
               d. Tap "Exit" to go back to the Area screen
            3. Return to in-game home screen (best-effort)
        """
        log_info("Starting Combat - Area activity...")
        # Step 1: detect whether we are already on the Area screen
        self.update_activity_progress(2.0)
        already_in_area = self.wait_for_template(
            self.combat['area_check'], timeout=2, threshold=0.85
        ) is not None

        if already_in_area:
            log_info("Already inside Area, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in Area, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=3):
                log_info("Home button not visible, continuing without it")

            # Open combat from main menu
            self.update_activity_progress(8.0)
            if not self.wait_and_tap(self.main_menu['combat'], timeout=10):
                log_warning("Could not find Combat button on main menu")
                return False

            # Enter Area
            self.update_activity_progress(12.0)
            if not self.wait_and_tap(self.combat['area_icon'], timeout=10):
                log_warning("Could not find Area icon")
                return False

            # Confirm we actually landed on the Area screen
            if not self.wait_for_template(self.combat['area_check'], timeout=10):
                log_warning("Area screen did not appear after navigation")
                return False
            self.update_activity_progress(15.0)

        # Step 2: run the thu thach combat loop up to 5 times
        total_runs = 5
        progress_start = 20.0
        progress_end = 95.0
        progress_step = (progress_end - progress_start) / total_runs

        for i in range(total_runs):
            run_no = i + 1
            log_info(f"Area run {run_no}/{total_runs}")

            base_progress = progress_start + progress_step * i

            # 2a: tap thu thach to start a fight
            if not self.wait_and_tap(self.combat['area_thu_thach'], timeout=15):
                log_warning(f"Could not find Thu Thach on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.25)


            # 2b: tap start
            if not self.wait_and_tap(self.templates['bat_dau'], timeout=10):
                log_warning(f"Could not find Bat Dau on run {run_no}")
                return False
            self.update_activity_progress(base_progress + progress_step * 0.50)

            # 2b.1: if Area is already full, stop the activity early (success)
            is_full = self.wait_for_template(self.combat['area_is_full'], timeout=10) is not None
            if is_full:
                log_info("Area is full, ending Area activity early")
                self.wait_and_tap(self.templates['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.templates['home'], timeout=10)  # Try to return home
                self.update_activity_progress(100.0)
                log_success(f"Combat Area finished (full at run {run_no})")
                return True
            
            # 2c: wait for the stats/result screen
            self._find_end_tap_exit(timeout=300)  # Wait up to 5 minutes for the fight to finish
            self.update_activity_progress(base_progress + progress_step * 0.75)

            # Small pause for the transition back
            time.sleep(1.0)
            log_success(f"Area run {run_no}/{total_runs} done")

        # Step 3: return home (best-effort)
        self.update_activity_progress(97.0)
        if not self.wait_and_tap(self.templates['home'], timeout=10):
            log_warning("Could not find Home button after Area (continuing)")

        self.update_activity_progress(100.0)
        log_success("Combat Area completed (5 runs)")
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
            self.combat['tmdq_check'], timeout=2, threshold=0.85
        ) is not None

        if already_in_tmdq:
            log_info("Already inside TMDQ, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in TMDQ, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=3):
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
            is_full = self.wait_for_template(self.combat['tmdq_is_full'], timeout=10) is not None
            if is_full:
                log_info("TMDQ is full, ending TMDQ activity early")
                self.wait_and_tap(self.templates['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.templates['home'], timeout=10)  # Try to return home
                self.update_activity_progress(100.0)
                log_success(f"Combat TMDQ finished (full at run {run_no})")
                return True

            # 3c: tap "Skip" (best-effort)
            if not self.wait_and_tap(self.templates['skip'], timeout=10):
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
            self.combat['dvq_check'], timeout=2, threshold=0.85
        ) is not None

        if already_in_dvq:
            log_info("Already inside DVQ, skipping navigation")
            self.update_activity_progress(15.0)
        else:
            log_info("Not in DVQ, navigating from main menu...")

            # Try to return to in-game home first (best-effort)
            self.update_activity_progress(5.0)
            if not self.wait_and_tap(self.templates['home'], timeout=3):
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
            is_full = self.wait_for_template(self.combat['dvq_is_full'], timeout=10) is not None
            if is_full:
                log_info("DVQ is full, ending DVQ activity early")
                self.wait_and_tap(self.templates['huy_bo'], timeout=10)  # Tap cancel to exit out of the full screen
                self.wait_and_tap(self.templates['home'], timeout=10)  # Try to return home
                self.update_activity_progress(100.0)
                log_success(f"Combat DVQ finished (full at run {run_no})")
                return True

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

    # ==================== Helpers ====================

    def _is_vtgk_finished(self, timeout: float = 1.0,
                         threshold: float = 0.85) -> bool:
        """Return True if either VTGK end marker is currently on screen."""
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
