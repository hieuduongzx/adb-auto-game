import time
from typing import List

from src.game_core.base_game import Activity, BaseGameAutomation
from src.game_core.speedhack import SpeedhackMixin
from src.utils import log_error, log_info, log_success, log_warning


# Package name of GirlWars on the device (used by _ensure_app_foreground).
GIRLWARS_PACKAGE = "com.y2sgames.girlwarsbignewen"


class GirlWars(SpeedhackMixin, BaseGameAutomation):

    # App identity
    PACKAGE_NAME = GIRLWARS_PACKAGE
    DEFAULT_OCR_BACKEND = "tesseract"
    # Navigation taps (device pixel coords)
    TAP_MAIN_STORY_ENTRY = (1551, 556)      # Home -> main story map
    TAP_MAIN_STORY_FIRST_STAGE = (96, 199)  # first stage on the map
    TAP_PREPARATION_CONTINUE = (957, 450)   # "Tap to continue" inside Preparation
    TAP_DUNGEON_START = (1528, 950)         # "Start" button inside a dungeon

    # OCR regions (x, y, w, h) for screen-state checks
    REGION_PREPARATION = (162, 17, 329, 58)
    REGION_ELITE_CHECK = (787, 814, 350, 32)
    REGION_TAP_TO_CONTINUE = (801, 1015, 308, 58)

    # Thresholds / timings
    DEFAULT_BACK_MAX_ATTEMPTS = 30
    BATTLE_ENTRY_TIMEOUT = 300.0   # seconds to wait for a battle to appear

    # ==================== Instance setup ====================

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/girlwars"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 10
        self.package_name = self.PACKAGE_NAME

        self.setup_speedhack()

        self.tpl_common = {
            "is_home":      f"{self.assets_path}/is_home.png",
            "back_button":  f"{self.assets_path}/back_button.png",
            "skip_dialog":  f"{self.assets_path}/skip_dialog.png",
            "skip_battle":  f"{self.assets_path}/skip_battle.png",
        }
        self.tpl_main_story = {
            "is_main_story":   f"{self.assets_path}/main_story/is_main_story.png",
            "challenge_button": f"{self.assets_path}/main_story/challenge_button.png",
            "icon_elite_mode": f"{self.assets_path}/main_story/icon_elite_mode.png",
            "battle_button":   f"{self.assets_path}/main_story/battle_button.png",
        }
        self.tpl_adventure = {
            "icon_adventure":  f"{self.assets_path}/adventure/icon_adventure.png",
            "is_adventure":    f"{self.assets_path}/adventure/is_adventure.png",
            "icon_dungeon":    f"{self.assets_path}/adventure/dungeon/icon_dungeon.png",
            "is_dungeon":      f"{self.assets_path}/adventure/dungeon/is_dungeon.png",
            "continue_battle": f"{self.assets_path}/adventure/dungeon/continue_battle.png",
            "next_floor":      f"{self.assets_path}/adventure/dungeon/next_floor.png",
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
            Activity(
                id="auto_skip_battle",
                name="Tự Động Bỏ Qua Trận Đấu",
                description="Liên tục bỏ qua các trận đấu trong game (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            Activity(
                id="auto_tap_to_continue",
                name="Tự Động Tap To Continue",
                description="Kiểm tra vùng Tap to continue và tap nếu có (chạy nền)",
                enabled=True,
                background=True,
                poll_interval=1.0,
            ),
            self.speedhack_activity(),
            # ---- Sequential (run once, in order) ----
            Activity(
                id="main_story",
                name="Main Story",
                description="Tự động chạy main story",
                enabled=True,
            ),
            Activity(
                id="dungeon",
                name="Auto Dungeon",
                description="Tự động vào Adventure -> Dungeon",
                enabled=True,
            ),
            Activity(
                id="main_story_elite_battle",
                name="Main Story Elite Battle",
                description="Chạy main story tới stage 1.4, bật elite mode và lặp battle",
                enabled=True,
            ),
        ]

    # ==================== Main loop entry ====================

    def before_process_game_actions(self) -> bool:
      #  if self._ensure_app_foreground():
        return True
        log_error("Aborting: GirlWars app could not be started")
        return False

    # ==================== Background handlers ====================

    def handle_activity_auto_skip_dialog(self) -> bool:
        """Tap the 'skip dialog' popup if present."""
        tpl = self.tpl_common.get("skip_dialog")
        if not tpl:
            return False
        result = self.find_template(tpl, last_screen=True)
        if not result:
            return False
        x, y, _conf = result
        log_success(f"[bg-skip_dialog] tap {x},{y}")
        return self.tap(x, y)

    def handle_activity_auto_skip_battle(self) -> bool:
        """Tap the 'skip battle' popup if present."""
        tpl = self.tpl_common.get("skip_battle")
        if not tpl:
            return False
        result = self.find_template(tpl, last_screen=True)
        if not result:
            return False
        x, y, _conf = result
        log_success(f"[bg-skip_battle] tap {x},{y}")
        return self.tap(x, y)

    def handle_activity_auto_tap_to_continue(self) -> bool:
        """Tap the 'Tap to continue' region if the text is detected."""
        if self.region_has_text(
            "Tap to continue",
            region=self.REGION_TAP_TO_CONTINUE,
            last_screen=True,
        ):
            cx, cy = self.region_center(self.REGION_TAP_TO_CONTINUE)
            log_success(f"[bg-tap_continue] tap {cx},{cy}")
            return self.tap(cx, cy)
        return False

    # ==================== Sequential handlers ====================

    # ----- Main Story -----
    def handle_activity_main_story(self) -> bool:
        """Clear the main story map: enter the first stage and loop battles."""
        is_home_tpl = self.tpl_common["is_home"]
        is_main_story_tpl = self.tpl_main_story["is_main_story"]
        back_button_tpl = self.tpl_common["back_button"]
        challenge_tpl = self.tpl_main_story["challenge_button"]

        # 1. Reach the main story map.
        if not self._enter_main_story_map(is_main_story_tpl, back_button_tpl):
            return False
        # 2. Tap the first stage on the map.
        if not self.tap(*self.TAP_MAIN_STORY_FIRST_STAGE):
            return False

        # 3. Loop: wait for a battle entry, then push through Preparation.
        while self.running:
            entry = self._await_battle_entry(challenge_tpl)
            if not entry:
                # No battle appeared within the timeout -> story finished;
                # walk back to home.
                return self._back_to_home_from_story(is_home_tpl, back_button_tpl)

            if entry == "challenge":
                if not self.wait_and_tap(challenge_tpl, timeout=5):
                    continue
                if not self.wait_region_has_text(
                    "Preparation", region=self.REGION_PREPARATION, timeout=15,
                ):
                    return False

            # At Preparation -> tap "Tap to continue".
            if not self.tap(*self.TAP_PREPARATION_CONTINUE):
                return False

        # Loop exited because the user stopped the automation.
        return False

    # ----- Adventure -> Dungeon -----
    def handle_activity_dungeon(self) -> bool:
        """Enter Adventure -> Dungeon and loop battles until cleared."""
        is_home_tpl = self.tpl_common["is_home"]
        back_button_tpl = self.tpl_common["back_button"]
        is_adventure_tpl = self.tpl_adventure["is_adventure"]
        icon_adventure_tpl = self.tpl_adventure["icon_adventure"]
        icon_dungeon_tpl = self.tpl_adventure["icon_dungeon"]
        is_dungeon_tpl = self.tpl_adventure["is_dungeon"]
        next_floor_tpl = self.tpl_adventure["next_floor"]
        continue_battle_tpl = self.tpl_adventure["continue_battle"]

        # 1. Reach the Adventure screen.
        if not self._enter_adventure(
            is_adventure_tpl, icon_adventure_tpl, back_button_tpl,
        ):
            return False

        # 2. Open the Dungeon.
        if not self.wait_and_tap(icon_dungeon_tpl, timeout=5):
            log_warning("[dungeon] icon_dungeon not found")
            return False
        if not self.wait_for_template(is_dungeon_tpl, timeout=15):
            log_warning("[dungeon] is_dungeon not reached")
            return False
        # 2.1. Optional next-floor popup.
        if self.wait_and_tap(next_floor_tpl, timeout=10):
            log_info("[dungeon] next_floor found, tapping to enter next floor")
            self.safe_sleep(2.0)

        # 3. Start the first battle and reach Preparation.
        if not self._start_dungeon_battle():
            return False

        # 4. Loop: continue_battle -> Preparation, or wait + restart.
        while self.running:
            if self.wait_and_tap(continue_battle_tpl, timeout=self.BATTLE_ENTRY_TIMEOUT):
                if not self._wait_preparation_and_continue():
                    return False
                continue
            # No continue button -> battle ended; wait for the dungeon
            # screen to settle, then start the next battle.
            self.wait_for_template(is_dungeon_tpl, timeout=self.BATTLE_ENTRY_TIMEOUT)
            self.safe_sleep(3.5)
            if not self._start_dungeon_battle():
                return False

        return False

    # ----- Main Story Elite Battle -----
    def handle_activity_main_story_elite_battle(self) -> bool:
        """Enter main story 1-4, enable elite mode, and loop battles."""
        is_main_story_tpl = self.tpl_main_story["is_main_story"]
        back_button_tpl = self.tpl_common["back_button"]
        icon_elite_tpl = self.tpl_main_story["icon_elite_mode"]
        battle_button_tpl = self.tpl_main_story["battle_button"]

        # 1. Reach the main story map.
        if not self._enter_main_story_map(is_main_story_tpl, back_button_tpl):
            return False

        # 2. Enable elite mode and start the first battle.
        if not self.wait_and_tap(icon_elite_tpl, timeout=10):
            log_warning("[elite] icon_elite_mode not found")
            return False
        self.safe_sleep(1.0)
        if not self._start_elite_battle(battle_button_tpl):
            return False

        # 3. Loop: wait for the battle button to reappear, then push through.
        while self.running:
            if not self.wait_and_tap(battle_button_tpl, timeout=self.BATTLE_ENTRY_TIMEOUT):
                return False
            if not self._start_elite_battle(battle_button_tpl):
                return False

        return False

    # ==================== Private helpers ====================

    # ----- Navigation helpers -----

    def _enter_main_story_map(
        self, is_main_story_tpl: str, back_button_tpl: str,
    ) -> bool:
        """Make sure we are on the main story map.

        Taps Back -> Home -> main story entry if we aren't already there.
        Returns ``True`` when ``is_main_story`` is visible.
        """
        if self.wait_for_template(
            is_main_story_tpl, timeout=5,
        ):
            return True
        if not self._back_to_home():
            log_warning("[main_story] could not reach home screen")
            return False
        if not self.tap(*self.TAP_MAIN_STORY_ENTRY):
            return False
        return self.wait_for_template(
            is_main_story_tpl, timeout=5,
        )

    def _enter_adventure(
        self, is_adventure_tpl: str, icon_adventure_tpl: str, back_button_tpl: str,
    ) -> bool:
        """Make sure we are on the Adventure screen.

        Taps Back -> Home -> Adventure icon if we aren't already there.
        """
        if self.wait_for_template(is_adventure_tpl, timeout=5):
            return True
        log_warning("[adventure] is_adventure not found, recovering")
        if not self._back_to_home():
            log_warning("[adventure] could not reach home screen")
            return False
        if not self.wait_and_tap(icon_adventure_tpl, timeout=5):
            log_warning("[adventure] icon_adventure not found")
            return False
        if not self.wait_for_template(is_adventure_tpl, timeout=15):
            log_warning("[adventure] is_adventure not reached")
            return False
        return True

    def _back_to_home(self, max_attempts: int = None) -> bool:
        """Tap Back repeatedly until the home screen is reached.

        Returns ``True`` when ``is_home`` is visible, ``False`` if the
        back button cannot be found (or the automation was stopped).
        """
        if max_attempts is None:
            max_attempts = self.DEFAULT_BACK_MAX_ATTEMPTS
        is_home_tpl = self.tpl_common["is_home"]
        back_button_tpl = self.tpl_common["back_button"]

        if self.find_template(is_home_tpl, last_screen=True):
            return True

        for _ in range(max_attempts):
            if not self.running:
                return False
            if not self.find_and_tap(back_button_tpl):
                return False
            self.safe_sleep(3.0)
            if self.find_template(is_home_tpl, last_screen=True):
                return True
        return False

    def _back_to_home_from_story(
        self, is_home_tpl: str, back_button_tpl: str,
    ) -> bool:
        """Walk back from a finished story stage to the home screen."""
        while not self.find_template(is_home_tpl, last_screen=True):
            if not self.running:
                return False
            if not self.find_and_tap(back_button_tpl):
                return False
        return True

    # ----- Battle-flow helpers -----

    def _await_battle_entry(
        self, challenge_tpl: str, timeout: float = None,
    ) -> str:
        """Wait for either the challenge button or the Preparation screen.

        After entering a stage the game usually shows a challenge button,
        but sometimes skips it and shows Preparation directly. Poll for
        both.

        Returns:
            ``"preparation"`` - Preparation screen appeared (caller taps
            "Tap to continue" directly).
            ``"challenge"`` - challenge button appeared (caller taps it,
            then waits for Preparation).
            ``""`` - timeout / stop (treated as end of story).
        """
        if timeout is None:
            timeout = self.BATTLE_ENTRY_TIMEOUT
        start = time.time()
        while self.running and time.time() - start < timeout:
            # Preparation already shown -> no challenge button needed.
            if self.region_has_text(
                "Preparation", region=self.REGION_PREPARATION, last_screen=True,
            ):
                return "preparation"
            if self.find_template(challenge_tpl, last_screen=True):
                return "challenge"
            self.safe_sleep(0.5)
        return ""

    def _start_dungeon_battle(self) -> bool:
        """Tap the dungeon Start button and push through Preparation."""
        if not self.tap(*self.TAP_DUNGEON_START):
            return False
        return self._wait_preparation_and_continue()

    def _start_elite_battle(self, battle_button_tpl: str) -> bool:
        """Tap the battle button, wait for the elite check, and continue."""
        if not self.wait_and_tap(battle_button_tpl, timeout=10):
            log_warning("[elite] battle_button not found")
            return False
        if not self.wait_region_has_text(
            "Restraining Enemy Hero",
            region=self.REGION_ELITE_CHECK, timeout=15,
        ):
            return False
        return self.tap(*self.TAP_PREPARATION_CONTINUE)

    def _wait_preparation_and_continue(self) -> bool:
        """Wait for the Preparation screen, then tap 'Tap to continue'."""
        if not self.wait_region_has_text(
            "Preparation", region=self.REGION_PREPARATION, timeout=15,
        ):
            return False
        return self.tap(*self.TAP_PREPARATION_CONTINUE)


if __name__ == "__main__":
    GirlWars().start()