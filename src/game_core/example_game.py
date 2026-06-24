"""Example game implementation showing how to use BaseGameAutomation."""

from typing import List

from src.game_core.activity import Activity
from src.game_core.base_game import BaseGameAutomation


class ExampleGame(BaseGameAutomation):
    """Copy and modify this template for a new game automation."""

    def __init__(self):
        super().__init__()
        self.assets_path = "assets/example"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 2

    def define_activities(self) -> List[Activity]:
        """Define what this game can do."""
        return [
            Activity(id="login", name="Auto Login", description="Login to the game", enabled=True),
            Activity(id="daily", name="Daily Quests", description="Complete daily quests", enabled=True),
            Activity(id="farm", name="Auto Farm", description="Farm resources automatically", enabled=False),
        ]

    def handle_activity_login(self) -> bool:
        """Handle login activity."""
        if self.wait_and_tap(self.get_template_path("login_button.png"), timeout=10):
            if self.wait_for_template(self.get_template_path("main_screen.png"), timeout=15):
                return True
        return False

    def handle_activity_daily(self) -> bool:
        """Handle daily quests activity."""
        if not self.find_and_tap(self.get_template_path("daily_menu.png")):
            return False
        return True

    def handle_activity_farm(self) -> bool:
        """Handle farming activity."""
        return True


if __name__ == "__main__":
    game = ExampleGame()
    game.start()
