"""
Base game automation class for easy tool development with GUI support.
This class provides a structured framework for creating game automation tools.
"""
import os
import time
import threading
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Callable, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from src.core import ADBGameAutomation
from src.core.adb.auto.config import Config
from src.utils import log_error, log_warning, log_success, log_info


class ActivityStatus(Enum):
    """Status of an activity"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Activity:
    """Represents an automation activity/task"""
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    status: ActivityStatus = ActivityStatus.PENDING
    progress: float = 0.0  # 0.0 to 100.0
    error_message: Optional[str] = None
    execution_count: int = 0
    max_retries: int = 3
    
    def reset(self):
        """Reset activity state"""
        self.status = ActivityStatus.PENDING
        self.progress = 0.0
        self.error_message = None


class BaseGameAutomation(ADBGameAutomation):
    """
    Base class for game automation with GUI support and activity management.
    
    To create a new game automation:
    1. Inherit from this class
    2. Define your activities in define_activities()
    3. Implement activity handlers
    4. Set templates_dir and assets_path
    
    Example:
        class MyGame(BaseGameAutomation):
            def __init__(self):
                super().__init__()
                self.assets_path = "assets/mygame"
                self.templates_dir = f"{self.assets_path}/templates"
            
            def define_activities(self) -> List[Activity]:
                return [
                    Activity(id="daily", name="Daily Quests", description="Complete daily quests"),
                    Activity(id="farm", name="Auto Farm", description="Farm resources"),
                ]
            
            def handle_activity_daily(self):
                # Implement daily quest logic
                pass
            
            def handle_activity_farm(self):
                # Implement farming logic
                pass
    """
    
    def __init__(
        self,
        config_file: Optional[str] = None,
        device_id: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 5037,
        config: Optional[Config] = None,
    ):
        super().__init__(config_file, device_id, host, port, config)
        
        # Game-specific paths (override in subclass)
        self.assets_path: str = ""
        self.templates_dir: str = ""
        self.logs_dir: str = "logs"
        
        # Activity management
        self._activities: List[Activity] = []
        self._activity_map: Dict[str, Activity] = {}
        self._current_activity: Optional[Activity] = None
        self._activity_order: List[str] = []
        
        # Thread pool for concurrent operations
        self.max_workers: int = 3
        self._executor: Optional[ThreadPoolExecutor] = None
        
        # GUI callbacks
        self._callbacks: Dict[str, List[Callable]] = {
            'on_start': [],
            'on_stop': [],
            'on_activity_start': [],
            'on_activity_complete': [],
            'on_activity_failed': [],
            'on_progress': [],
            'on_error': [],
            'on_status_change': [],
        }
        
        # State flags
        self._paused: bool = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        
        # Initialize activities
        self._initialize_activities()
    
    # ==================== Abstract Methods ====================
    
    @abstractmethod
    def define_activities(self) -> List[Activity]:
        """
        Define the activities for this game automation.
        Override this method to specify what activities your game supports.
        
        Returns:
            List of Activity objects
        """
        raise NotImplementedError("Subclasses must implement define_activities()")
    
    # ==================== Initialization ====================
    
    def _initialize_activities(self):
        """Initialize activities from define_activities()"""
        activities = self.define_activities()
        self._activities = activities
        self._activity_map = {act.id: act for act in activities}
        self._activity_order = [act.id for act in activities if act.enabled]
        
        # Initialize thread pool
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        log_info(f"Initialized {len(activities)} activities: {self._activity_order}")
    
    # ==================== Template Helpers ====================
    
    def get_template_path(self, template_name: str) -> str:
        """Get full path to a template image"""
        return os.path.join(self.templates_dir, template_name)
    
    def template_exists(self, template_name: str) -> bool:
        """Check if a template file exists"""
        return os.path.exists(self.get_template_path(template_name))
    
    def ensure_templates_exist(self, template_names: List[str]) -> bool:
        """Ensure all required templates exist"""
        missing = []
        for name in template_names:
            if not self.template_exists(name):
                missing.append(name)
        
        if missing:
            log_error(f"Missing templates: {missing}")
            return False
        return True
    
    # ==================== Activity Management ====================
    
    def get_activities(self) -> List[Activity]:
        """Get all activities"""
        return self._activities.copy()
    
    def get_activity(self, activity_id: str) -> Optional[Activity]:
        """Get activity by ID"""
        return self._activity_map.get(activity_id)
    
    def set_activity_enabled(self, activity_id: str, enabled: bool):
        """Enable or disable an activity"""
        activity = self._activity_map.get(activity_id)
        if activity:
            activity.enabled = enabled
            if enabled and activity_id not in self._activity_order:
                self._activity_order.append(activity_id)
            elif not enabled and activity_id in self._activity_order:
                self._activity_order.remove(activity_id)
            log_info(f"Activity '{activity_id}' {'enabled' if enabled else 'disabled'}")
    
    def set_activity_order(self, order: List[str]):
        """Set the execution order of activities"""
        # Validate all IDs exist
        invalid = [aid for aid in order if aid not in self._activity_map]
        if invalid:
            log_warning(f"Invalid activity IDs in order: {invalid}")
            return
        
        self._activity_order = order
        log_info(f"Activity order updated: {order}")
    
    def reset_activities(self):
        """Reset all activities to pending state"""
        for activity in self._activities:
            activity.reset()
        log_info("All activities reset")
    
    def get_current_activity(self) -> Optional[Activity]:
        """Get currently running activity"""
        return self._current_activity
    
    # ==================== Activity Handlers ====================
    
    def _get_activity_handler(self, activity_id: str) -> Optional[Callable]:
        """Get the handler method for an activity"""
        handler_name = f"handle_activity_{activity_id}"
        handler = getattr(self, handler_name, None)
        if handler and callable(handler):
            return handler
        return None
    
    def _execute_activity(self, activity: Activity) -> bool:
        """Execute a single activity"""
        handler = self._get_activity_handler(activity.id)
        if not handler:
            log_error(f"No handler found for activity: {activity.id}")
            return False
        
        activity.status = ActivityStatus.RUNNING
        activity.execution_count += 1
        self._current_activity = activity
        
        # Trigger callbacks
        self._trigger_callback('on_activity_start', activity)
        self._update_progress(activity.id, 0.0)
        
        try:
            log_info(f"Starting activity: {activity.name} ({activity.id})")
            
            # Wait if paused
            self._pause_event.wait()
            
            # Execute handler
            result = handler()
            
            if result:
                activity.status = ActivityStatus.COMPLETED
                activity.progress = 100.0
                log_success(f"Completed activity: {activity.name}")
                self._trigger_callback('on_activity_complete', activity, True)
                return True
            else:
                activity.status = ActivityStatus.FAILED
                log_warning(f"Activity returned False: {activity.name}")
                self._trigger_callback('on_activity_complete', activity, False)
                return False
                
        except Exception as e:
            activity.status = ActivityStatus.FAILED
            activity.error_message = str(e)
            log_error(f"Error in activity {activity.id}: {e}")
            self._trigger_callback('on_activity_failed', activity, e)
            self._trigger_callback('on_error', e)
            return False
        finally:
            self._current_activity = None
    
    # ==================== GUI Callback System ====================
    
    def register_callback(self, event: str, callback: Callable):
        """
        Register a callback for an event.
        
        Events:
            - 'on_start': Called when automation starts
            - 'on_stop': Called when automation stops
            - 'on_activity_start': Called when an activity starts (activity)
            - 'on_activity_complete': Called when activity completes (activity, success)
            - 'on_activity_failed': Called when activity fails (activity, error)
            - 'on_progress': Called when progress updates (activity_id, progress)
            - 'on_error': Called on error (error)
            - 'on_status_change': Called on status change (status_dict)
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)
            log_info(f"Registered callback for '{event}'")
        else:
            log_warning(f"Unknown event type: {event}")
    
    def unregister_callback(self, event: str, callback: Callable):
        """Unregister a callback"""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
    
    def _trigger_callback(self, event: str, *args, **kwargs):
        """Trigger all callbacks for an event"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                log_error(f"Error in callback for {event}: {e}")
    
    def _update_progress(self, activity_id: str, progress: float):
        """Update progress for an activity"""
        activity = self._activity_map.get(activity_id)
        if activity:
            activity.progress = progress
        self._trigger_callback('on_progress', activity_id, progress)
    
    def update_activity_progress(self, progress: float):
        """Update progress for current activity (call from handlers)"""
        if self._current_activity:
            self._current_activity.progress = progress
            self._trigger_callback('on_progress', self._current_activity.id, progress)
    
    # ==================== Control Methods ====================
    
    def pause(self):
        """Pause automation (will pause after current operation)"""
        self._paused = True
        self._pause_event.clear()
        log_info("Automation paused")
        self._trigger_callback('on_status_change', {'paused': True})
    
    def resume(self):
        """Resume automation"""
        self._paused = False
        self._pause_event.set()
        log_info("Automation resumed")
        self._trigger_callback('on_status_change', {'paused': False})
    
    def is_paused(self) -> bool:
        """Check if automation is paused"""
        return self._paused
    
    def stop(self):
        """Stop automation gracefully"""
        log_info("Stopping automation...")
        self.running = False
        self._paused = False
        self._pause_event.set()
        
        # Stop continuous capture
        self.stop_continuous_capture()
        
        # Shutdown executor
        if self._executor:
            self._executor.shutdown(wait=False)
        
        # Close visualizer
        self.visualizer.close()
        
        self._trigger_callback('on_stop')
        log_success("Automation stopped")
    
    # ==================== Main Process ====================
    
    def process_game_actions(self):
        """
        Main automation loop - processes activities in order.
        Override this method only if you need custom flow control.
        """
        log_info(f"Starting automation with activities: {self._activity_order}")
        self._trigger_callback('on_start')
        
        try:
            for activity_id in self._activity_order:
                # Check if stopped
                if not self.running:
                    log_info("Automation stopped by user")
                    break
                
                activity = self._activity_map.get(activity_id)
                if not activity or not activity.enabled:
                    continue
                
                # Execute activity
                success = self._execute_activity(activity)
                
                # Handle failure with retry
                if not success and activity.execution_count < activity.max_retries:
                    log_info(f"Retrying activity {activity.id} (attempt {activity.execution_count + 1})")
                    success = self._execute_activity(activity)
                
                # Small delay between activities
                if self.running:
                    time.sleep(0.5)
            
            log_success("All activities completed")
            # Mark as not running so the outer start() loop exits instead of
            # immediately re-running every activity again.
            self.running = False
            
        except KeyboardInterrupt:
            log_info("Automation interrupted by user")
        except Exception as e:
            log_error(f"Error in automation loop: {e}")
            self._trigger_callback('on_error', e)
    
    # ==================== Utility Methods ====================
    
    def wait_and_check_pause(self, timeout: float = 0.1):
        """Wait while checking for pause state"""
        self._pause_event.wait()
        time.sleep(timeout)
    
    def safe_sleep(self, seconds: float):
        """Sleep that can be interrupted by stop/pause"""
        end_time = time.time() + seconds
        while time.time() < end_time and self.running:
            self._pause_event.wait()
            time.sleep(0.1)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current automation status for GUI"""
        return {
            'running': self.running,
            'paused': self._paused,
            'current_activity': self._current_activity.id if self._current_activity else None,
            'activities': [
                {
                    'id': act.id,
                    'name': act.name,
                    'status': act.status.value,
                    'progress': act.progress,
                    'enabled': act.enabled,
                }
                for act in self._activities
            ],
            'performance': self.get_performance_metrics(),
        }


# ==================== GUI Base Classes ====================

class GUIBase:
    """
    Base class for creating GUI interfaces.
    Extend this class to create custom GUIs (Tkinter, PyQt, etc.)
    """
    
    def __init__(self, automation: BaseGameAutomation):
        self.automation = automation
        self._setup_callbacks()
    
    def _setup_callbacks(self):
        """Setup default callbacks to update GUI"""
        self.automation.register_callback('on_start', self.on_automation_start)
        self.automation.register_callback('on_stop', self.on_automation_stop)
        self.automation.register_callback('on_activity_start', self.on_activity_start)
        self.automation.register_callback('on_activity_complete', self.on_activity_complete)
        self.automation.register_callback('on_activity_failed', self.on_activity_failed)
        self.automation.register_callback('on_progress', self.on_progress_update)
        self.automation.register_callback('on_error', self.on_error)
        self.automation.register_callback('on_status_change', self.on_status_change)
    
    # Callback handlers - override these in your GUI class
    def on_automation_start(self):
        """Called when automation starts"""
        pass
    
    def on_automation_stop(self):
        """Called when automation stops"""
        pass
    
    def on_activity_start(self, activity: Activity):
        """Called when an activity starts"""
        pass
    
    def on_activity_complete(self, activity: Activity, success: bool):
        """Called when an activity completes"""
        pass
    
    def on_activity_failed(self, activity: Activity, error: Exception):
        """Called when an activity fails"""
        pass
    
    def on_progress_update(self, activity_id: str, progress: float):
        """Called when progress updates"""
        pass
    
    def on_error(self, error: Exception):
        """Called on error"""
        pass
    
    def on_status_change(self, status: Dict[str, Any]):
        """Called on status change"""
        pass
    
    def start(self):
        """Start the GUI - implement in subclass"""
        raise NotImplementedError("Subclasses must implement start()")
    
    def stop(self):
        """Stop the GUI - implement in subclass"""
        self.automation.stop()


# ==================== Example Usage Template ====================

class ExampleGame(BaseGameAutomation):
    """
    Example game implementation showing how to use BaseGameAutomation.
    Copy and modify this template for your own games.
    """
    
    def __init__(self):
        super().__init__()
        self.assets_path = "assets/example"
        self.templates_dir = f"{self.assets_path}/templates"
        self.max_workers = 2
    
    def define_activities(self) -> List[Activity]:
        """Define what this game can do"""
        return [
            Activity(
                id="login",
                name="Auto Login",
                description="Login to the game",
                enabled=True,
            ),
            Activity(
                id="daily",
                name="Daily Quests",
                description="Complete daily quests",
                enabled=True,
            ),
            Activity(
                id="farm",
                name="Auto Farm",
                description="Farm resources automatically",
                enabled=False,  # Disabled by default
            ),
        ]
    
    # Activity handlers - must match pattern: handle_activity_<id>
    def handle_activity_login(self) -> bool:
        """Handle login activity"""
        # Example implementation
        if self.wait_and_tap(self.get_template_path("login_button.png"), timeout=10):
            self.update_activity_progress(50.0)
            if self.wait_for_template(self.get_template_path("main_screen.png"), timeout=15):
                self.update_activity_progress(100.0)
                return True
        return False
    
    def handle_activity_daily(self) -> bool:
        """Handle daily quests activity"""
        # Example implementation
        self.update_activity_progress(0.0)
        
        # Step 1: Open daily menu
        if not self.find_and_tap(self.get_template_path("daily_menu.png")):
            return False
        self.update_activity_progress(25.0)
        
        # Step 2: Claim rewards
        # ... more steps ...
        
        self.update_activity_progress(100.0)
        return True
    
    def handle_activity_farm(self) -> bool:
        """Handle farming activity"""
        # Example implementation
        # Implement your farming logic here
        return True


if __name__ == "__main__":
    # Example of running without GUI
    game = ExampleGame()
    game.start()
