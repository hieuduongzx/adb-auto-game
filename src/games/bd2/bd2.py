"""
BD2 (Đấu La Đại Lục 2) Game Automation
Refactored to use BaseGameAutomation for better structure and GUI support.
"""
from typing import List

from src.games.base_game import BaseGameAutomation, Activity
from src.utils import log_error, log_warning, log_success, log_info


class BD2(BaseGameAutomation):
    """
    BD2 Game Automation
    
    Activities:
        - auto_daily: Daily draw/free summon
        - auto_farm: Auto farming (placeholder)
    """
    
    def __init__(self):
        super().__init__()
        self.assets_path = "assets/bd2"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 3
        
        # Template paths (organized by category)
        self.templates = {
            'draw': f"{self.templates_dir}/draw.png",
            'is_draw_menu': f"{self.templates_dir}/is_draw_menu.png",
        }
    
    def define_activities(self) -> List[Activity]:
        """Define BD2 activities"""
        return [
            Activity(
                id="auto_daily",
                name="Daily Draw",
                description="Perform daily free draw/summon",
                enabled=True,
                max_retries=2,
            ),
            Activity(
                id="auto_farm",
                name="Auto Farm",
                description="Auto farming mode (not implemented)",
                enabled=False,
            ),
        ]
    
    # ==================== Activity Handlers ====================
    
    def handle_activity_auto_daily(self) -> bool:
        """
        Handle daily draw activity
        
        Flow:
            1. Tap on draw button
            2. Wait for draw menu
            3. Perform draw actions
        """
        log_info("Starting daily draw activity...")
        
        # Step 1: Find and tap draw button
        self.update_activity_progress(10.0)
        if not self.wait_and_tap(self.templates['draw'], timeout=5):
            log_warning("Could not find draw button")
            return False
        
        self.update_activity_progress(30.0)
        
        # Step 2: Wait for draw menu to appear
        if not self.wait_for_template(self.templates['is_draw_menu'], timeout=5):
            log_warning("Draw menu did not appear")
            return False
        
        log_info("In draw menu, performing daily draw actions...")
        self.update_activity_progress(50.0)
        
        # Step 3: Perform draw (add more logic here as needed)
        # Example: Find and tap free draw button
        # if self.find_and_tap(f"{self.templates_dir}/free_draw.png"):
        #     log_success("Daily draw completed")
        
        self.update_activity_progress(100.0)
        log_success("Daily draw activity completed")
        return True
    
    def handle_activity_auto_farm(self) -> bool:
        """
        Handle auto farming activity (placeholder)
        
        TODO: Implement farming logic
        """
        log_info("Auto farm not yet implemented")
        return True
    
    # ==================== Helper Methods ====================
    
    def is_in_draw_menu(self) -> bool:
        """Check if currently in draw menu"""
        return self.find_template(self.templates['is_draw_menu']) is not None
    
    def perform_draw(self, draw_type: str = "free") -> bool:
        """
        Perform a draw/summon
        
        Args:
            draw_type: Type of draw (free, single, ten)
            
        Returns:
            True if successful
        """
        template = f"{self.templates_dir}/draw_{draw_type}.png"
        return self.find_and_tap(template, retry_attempts=3)


if __name__ == "__main__":
    # Run BD2 automation directly
    game = BD2()
    game.start()