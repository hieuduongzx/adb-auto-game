"""
GirlWars Game Automation
"""
from typing import List

from src.games.base_game import BaseGameAutomation, Activity
import time

from src.utils import log_info, log_success, log_warning, log_error


# Package name of GirlWars on the device
GIRLWARS_PACKAGE = "com.y2sgames.girlwarsbignewen"

class GirlWars(BaseGameAutomation):

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/girlwars"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 10
        self.package_name = GIRLWARS_PACKAGE
        # Template paths
        self.templates = {
            'is_home' : f"{self.assets_path}/is_home.png",
            'back_button': f"{self.assets_path}/back_button.png",
            'skip_dialog': f"{self.assets_path}/skip_dialog.png",
            'skip_battle': f"{self.assets_path}/skip_battle.png",
        }
        self.main_story_templates = {
            'is_main_story': f"{self.assets_path}/main_story/is_main_story.png",
            'challenge_button': f"{self.assets_path}/main_story/challenge_button.png",
            'icon_elite_mode': f"{self.assets_path}/main_story/icon_elite_mode.png",
            'battle_button': f"{self.assets_path}/main_story/battle_button.png",
        }
        self.adventure_templates = {
            'icon_adventure': f"{self.assets_path}/adventure/icon_adventure.png",
            'is_adventure' : f"{self.assets_path}/adventure/is_adventure.png",

            'icon_dungeon': f"{self.assets_path}/adventure/dungeon/icon_dungeon.png",
            'is_dungeon' : f"{self.assets_path}/adventure/dungeon/is_dungeon.png",
            'continue_battle': f"{self.assets_path}/adventure/dungeon/continue_battle.png",
            'next_floor': f"{self.assets_path}/adventure/dungeon/next_floor.png",
        }

    def define_activities(self) -> List[Activity]:
        return [
            Activity(
                id="auto_skip_dialog",name="Tự Động Bỏ Qua Hội Thoại",
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

    def process_game_actions(self):
        """Run the base activity loop only after GirlWars is foregrounded."""
        if not self._ensure_app_foreground():
            log_error("Aborting: GirlWars app could not be started")
            return
        super().process_game_actions()

    # ==================== Background Handlers ====================

    def handle_activity_auto_skip_dialog(self) -> bool:
        template = self.templates.get('skip_dialog')
        if not template:
            return False
        result = self.find_template(template, last_screen=True)
        if not result:
            return False
        x, y, _conf = result
        log_success(f"[bg-skip_dialog] tap {x},{y}")
        return self.tap(x, y)

    def handle_activity_auto_skip_battle(self) -> bool:
        template = self.templates.get('skip_battle')
        if not template:
            return False
        result = self.find_template(template, last_screen=True)
        if not result:
            return False
        x, y, _conf = result
        log_success(f"[bg-skip_battle] tap {x},{y}")
        return self.tap(x, y)

    def handle_activity_auto_tap_to_continue(self) -> bool:
        region = (801, 1015, 308, 58)
        if self.region_has_text("Tap to continue", region=region, last_screen=True):
            log_success(f"[bg-tap_continue] tap")
            return self.tap(801 + 308 // 2, 1015 + 58 // 2)
        return False

    # ==================== Sequence Handlers ====================
    # Main Story
    def handle_activity_main_story(self) -> bool:
        is_home_tpl = self.templates.get('is_home')
        is_main_story_map_tpl = self.main_story_templates.get('is_main_story')
        back_button_tpl = self.templates.get('back_button')
    #1. Đảm bảo đang ở main story map.
        if not self.wait_for_template(is_main_story_map_tpl, timeout=5, threshold=0.6):
            #1.1 Nếu không ở main story map, tap Back để về Home và vào lại main story map.
            if not self._back_to_home():
                log_warning("[main_story] could not reach home screen")
                return False
            #1.2 Từ Home, tap vào vị trí của main story trên màn hình (1551, 556).
            if not self.tap(1551, 556):
                return False
        #1.3 Check lại xem đã vào main story map chưa.
        if not self.wait_for_template(is_main_story_map_tpl, timeout=5, threshold=0.6):
            return False
        #1.4 Tap vào vị trí của first stage trên main story map (96, 199).
        if not self.tap(96, 199):
            return False

        prep_region = (162, 17, 329, 58)
        challenge_tpl = self.main_story_templates.get('challenge_button')

    #2. Vào stage rồi lặp Preparation.
        while self.running:
            entry = self._await_battle_entry(challenge_tpl)
            if not entry:
                # Nothing appeared within the timeout -> story is finished.
                while not self.find_template(is_home_tpl, last_screen=True):
                    if not self.running:
                        return False
                    if not self.find_and_tap(back_button_tpl):
                        return False
                return True
            # Tap the challenge button to reach Preparation, unless we are
            # already there.
            if entry == "challenge":
                if not self.wait_and_tap(challenge_tpl, timeout=5):
                    continue
                if not self.wait_region_has_text("Preparation", region=prep_region, timeout=15):
                    return False

            # At Preparation -> tap "Tap to continue".
            if not self.tap(957, 450):
                return False

        # Loop exited because the user stopped the automation.
        return False
    # Adventure -> Dungeon
    def handle_activity_dungeon(self) -> bool:
        is_home_tpl = self.templates.get('is_home')
        icon_adventure_tpl = self.adventure_templates.get('icon_adventure')
        is_adventure_tpl = self.adventure_templates.get('is_adventure')
        icon_dungeon_tpl = self.adventure_templates.get('icon_dungeon')
        is_dungeon_tpl = self.adventure_templates.get('is_dungeon')
        back_button_tpl = self.templates.get('back_button')

        # Bước 1: đảm bảo đang ở Adventure.
        if not self.wait_for_template(is_adventure_tpl, timeout=5):
            log_warning("[dungeon] is_adventure not found")
            # 1.1 Nếu không ở Adventure, tap Back để về Home.
            if not self._back_to_home():
                log_warning("[dungeon] could not reach home screen")
                return False
            # 1.2 Từ Home, tap icon Adventure.
            if not self.wait_and_tap(icon_adventure_tpl, timeout=5):
                log_warning("[dungeon] icon_adventure not found")
                return False
            # 1.3 Check lại xem đã vào Adventure chưa.
            if not self.wait_for_template(is_adventure_tpl, timeout=15):
                log_warning("[dungeon] is_adventure not reached")
                return False
            
        #2: mở Dungeon.
        if not self.wait_and_tap(icon_dungeon_tpl, timeout=5):
            log_warning("[dungeon] icon_dungeon not found")
            return False
        if not self.wait_for_template(is_dungeon_tpl, timeout=15):
            log_warning("[dungeon] is_dungeon not reached")
            return False
        if self.wait_and_tap(self.adventure_templates.get('next_floor'), timeout=10):
            log_info("[dungeon] next_floor found, tapping to enter next floor")
            self.safe_sleep(2.0)  # wait for the next floor to load
            
        prep_region = (161, 22, 328, 55)

        #3: vào battle rồi lặp Preparation.
        if not self.tap(1528, 950):
            return False
        if not self.wait_region_has_text("Preparation", region=prep_region, timeout=15):
            return False
        if not self.tap(957, 450):
            return False

        # Tiếp tục cho đến khi hết dungeon hoặc user stop.
        while self.running:
            if self.wait_and_tap(self.adventure_templates.get('continue_battle'), timeout=300):
                if not self.wait_region_has_text("Preparation", region=prep_region, timeout=15):
                    return False
                if not self.tap(957, 450):
                    return False
                continue 
            self.wait_for_template(is_dungeon_tpl, timeout=300)
            self.safe_sleep(3.5)  # wait for the "Start" button to appear
            if not self.tap(1528, 950):
                return False
            if not self.wait_region_has_text("Preparation", region=prep_region, timeout=15):
                return False
            if not self.tap(957, 450):
                return False

        return False
    # Main Story Elite Battle
    def handle_activity_main_story_elite_battle(self) -> bool:
        is_home_tpl = self.templates.get('is_home')
        is_main_story_map_tpl = self.main_story_templates.get('is_main_story')
        back_button_tpl = self.templates.get('back_button')
        challenge_tpl = self.main_story_templates.get('challenge_button')
        icon_elite_tpl = self.main_story_templates.get('icon_elite_mode')
        battle_button_tpl = self.main_story_templates.get('battle_button')

        #1. Đảm bảo đang ở main story map.
        if not self.wait_for_template(is_main_story_map_tpl, timeout=5, threshold=0.6):
            if not self._back_to_home():
                log_warning("[elite] could not reach home screen")
                return False
            if not self.tap(1551, 556):
                return False
        if not self.wait_for_template(is_main_story_map_tpl, timeout=5, threshold=0.6):
            return False


    #2. Tìm icon elite mode trên main story map rồi bật.
        check_region = (787, 814, 350, 32)
        if not self.wait_and_tap(icon_elite_tpl, timeout=10):
            log_warning("[elite] icon_elite_mode not found")
            return False
        self.safe_sleep(1.0)

        if not self.wait_and_tap(battle_button_tpl, timeout=10):
            log_warning("[elite] battle_button not found")
            return False
        if not self.wait_region_has_text("Restraining Enemy Hero", region=check_region, timeout=15):
            return False
        if not self.tap(957, 450):
            return False

        #4. Loop: đợi battle_button hiện lên lại rồi tap.
        while self.running:
            if not self.wait_and_tap(battle_button_tpl, timeout=300):
                return False
            if not self.wait_region_has_text("Restraining Enemy Hero", region=check_region, timeout=15):
                return False
            if not self.tap(957, 450):
                return False

        return False

    # ==================== Helpers ====================
    # Helpers -> Await Battle Entry
    def _await_battle_entry(self, challenge_tpl: str, timeout: float = 300.0) -> str:
        """Wait for either the challenge button or the Preparation screen.

        After entering a stage the game usually shows a challenge button, but
        sometimes skips it and shows Preparation directly. Poll for both.

        Returns:
            ``"preparation"`` when the Preparation screen appears (caller taps
            "Tap to continue" directly), ``"challenge"`` when the challenge
            button appears (caller taps it, then waits for Preparation), or an
            empty string on timeout / stop (treated as end of story).
        """
        prep_region = (162, 17, 329, 58)
        start = time.time()
        while self.running and time.time() - start < timeout:
            # Preparation already shown -> no challenge button needed.
            if self.region_has_text("Preparation", region=prep_region, last_screen=True):
                return "preparation"
            if self.find_template(challenge_tpl, last_screen=True):
                return "challenge"
            self.safe_sleep(0.5)
        return ""
    # Helpers -> Back to Home
    def _back_to_home(self, max_attempts: int = 30) -> bool:
        """Tap Back repeatedly until the home screen is reached.

        Returns ``True`` when ``is_home`` is visible, ``False`` if the
        back button cannot be found (or the automation was stopped).
        """
        is_home_tpl = self.templates.get('is_home')
        back_button_tpl = self.templates.get('back_button')

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

if __name__ == "__main__":
    game = GirlWars()
    game.start()