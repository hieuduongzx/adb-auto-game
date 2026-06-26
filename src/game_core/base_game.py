"""
Base game automation class for easy tool development with GUI support.
This class provides a structured framework for creating game automation tools.
"""
import time
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Callable, Optional, Any, Tuple

from src.core import ADBGameAutomation
from src.core.adb.auto.config import Config
from src.game_core.activity import Activity, ActivityStatus
from src.game_core.ocr_helpers import OCRHelperMixin
from src.game_core.vision_helpers import VisionHelperMixin
from src.game_core.settings_store import SettingsStore
from src.game_core.background_workers import BackgroundWorkerManager
from src.game_core.activity_manager import ActivityManager
from src.game_core.gui_base import GUIBase
from src.utils import log_error, log_warning, log_success, log_info


class BaseGameAutomation(OCRHelperMixin, VisionHelperMixin, ADBGameAutomation, ABC):
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

    # Default OCR backend for every game that inherits from this class.
    # Override per-game by setting the class attribute in the subclass:
    #
    #     class GirlWars(BaseGameAutomation):
    #         DEFAULT_OCR_BACKEND = "easyocr"
    #
    # Available backends (see src/core/adb/auto/ocr.py KNOWN_BACKENDS):
    #   - "tesseract" : fast, light, Latin labels ("0/5", "VIP 3", "Lv 35")  ← default
    #   - "easyocr"   : neural, better with stylised fonts, pulls torch (~520MB)
    #   - "paddleocr" : neural, strong accuracy, pulls paddlepaddle (~400MB)
    #
    # Callers can still pass `ocr_backend=...` at construction time to
    # A/B test without changing the class attribute.
    DEFAULT_OCR_BACKEND: str = "tesseract"
    
    def __init__(
        self,
        config_file: Optional[str] = None,
        device_id: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 5037,
        config: Optional[Config] = None,
        ocr_backend: Optional[str] = None,
    ):
        # Resolve backend: explicit arg wins > subclass class attribute > "tesseract"
        backend = ocr_backend or self.DEFAULT_OCR_BACKEND
        super().__init__(config_file, device_id, host, port, config, ocr_backend=backend)
        
        # Game-specific paths (override in subclass)
        self.assets_path: str = ""
        self.templates_dir: str = ""
        self.logs_dir: str = "logs"
        
        # Activity management. State lives in the manager; the ``_activity_*``
        # properties below forward to it so existing internal accesses (and
        # SpeedhackMixin) keep working unchanged.
        self._activities_mgr = ActivityManager()

        # Optional thread pool subclasses can use for parallel sub-tasks.
        # Lazily created via :meth:`get_executor` so we don't spin up threads
        # for games that don't need them.
        self.max_workers: int = 3
        self._executor: Optional[ThreadPoolExecutor] = None
        
        # GUI callbacks
        self._callbacks: Dict[str, List[Callable]] = {
            'on_start': [],
            'on_stop': [],
            'on_activity_start': [],
            'on_activity_complete': [],
            'on_activity_failed': [],
            'on_error': [],
            'on_status_change': [],
        }
        
        # State flags
        self._paused: bool = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        
        # Background activity management. The manager owns the worker threads
        # and collaborates only through these injected callables.
        self._bg = BackgroundWorkerManager(
            handler_resolver=self._get_activity_handler,
            is_paused=lambda: self._paused,
            ensure_ready=self._ensure_runtime_ready,
        )

        # Persisted per-activity settings. Each concrete game keeps its own
        # file keyed by class name, so settings never collide between games.
        self._settings = SettingsStore(self.__class__.__name__)
        self._ui_settings: Dict[str, Any] = {}

        # Initialize activities
        self._initialize_activities()

    # ==================== Activity state (delegates to manager) ============
    #
    # These forward to ``self._activities_mgr`` so all existing internal
    # accesses — and SpeedhackMixin's ``self._activity_map`` read — work
    # unchanged after the state moved into ActivityManager.

    @property
    def _activities(self) -> List[Activity]:
        return self._activities_mgr.activities

    @_activities.setter
    def _activities(self, value: List[Activity]) -> None:
        self._activities_mgr.activities = value

    @property
    def _activity_map(self) -> Dict[str, Activity]:
        return self._activities_mgr.activity_map

    @_activity_map.setter
    def _activity_map(self, value: Dict[str, Activity]) -> None:
        self._activities_mgr.activity_map = value

    @property
    def _activity_order(self) -> List[str]:
        return self._activities_mgr.activity_order

    @_activity_order.setter
    def _activity_order(self, value: List[str]) -> None:
        self._activities_mgr.activity_order = value

    @property
    def _current_activity(self) -> Optional[Activity]:
        return self._activities_mgr.current_activity

    @_current_activity.setter
    def _current_activity(self, value: Optional[Activity]) -> None:
        self._activities_mgr.current_activity = value

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
        """Initialize activities from define_activities() and apply saved settings."""
        activities = self.define_activities()
        saved = self._load_activity_settings()

        if saved:
            # Merge saved settings with the hard-coded defaults.
            by_id = {a.id: a for a in activities}
            merged: List[Activity] = []
            for data in saved:
                aid = data.get("id")
                default = by_id.pop(aid, None)
                act = Activity.from_settings_dict(data, defaults=default)
                if act is not None:
                    merged.append(act)
            # Append any new activities that weren't saved yet.
            activities = merged + list(by_id.values())

        # Install into the manager: seeds custom defaults, builds the id map,
        # and computes the sequential (enabled, non-background) run order.
        self._activities_mgr.set_activities(activities)

        log_info(
            f"Initialized {len(activities)} activities "
            f"(sequential: {self._activity_order}, "
            f"background: {[a.id for a in activities if a.background]})"
        )
    
    def get_executor(self) -> ThreadPoolExecutor:
        """Lazily create and return the thread pool for parallel sub-tasks."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self._executor
    
    # ==================== Activity Management ====================
    
    def get_activities(self) -> List[Activity]:
        """Get all activities"""
        return self._activities.copy()
    
    def get_activity(self, activity_id: str) -> Optional[Activity]:
        """Get activity by ID"""
        return self._activity_map.get(activity_id)
    
    def set_activity_enabled(self, activity_id: str, enabled: bool):
        """Enable or disable an activity.

        For background activities this also starts/stops the worker thread
        immediately, so the user can toggle them on and off while the main
        automation loop is running.
        """
        activity = self._activity_map.get(activity_id)
        if not activity:
            return
        activity.enabled = enabled
        if activity.background:
            # Background activities are not part of the sequential order; we
            # only need to manage their worker thread.
            if enabled:
                self._start_background_activity(activity)
            else:
                self._stop_background_activity(activity)
        else:
            self._activities_mgr.enable_in_order(activity_id, enabled)
        log_info(f"Activity '{activity_id}' {'enabled' if enabled else 'disabled'}")
        self._save_activity_settings()

    def set_activity_poll_interval(self, activity_id: str, interval: float) -> bool:
        """Change the poll interval of a background activity at runtime.

        The worker loop picks up the new value on its next sleep, so there is
        no need to restart the thread. Returns ``True`` if the activity exists
        and is a background activity.
        """
        activity = self._activity_map.get(activity_id)
        if not activity or not activity.background:
            return False
        activity.poll_interval = max(0.05, float(interval))
        log_info(f"[bg] '{activity_id}' poll interval set to {activity.poll_interval:.2f}s")
        self._save_activity_settings()
        return True

    def set_custom_setting(self, activity_id: str, key: str, value: Any) -> bool:
        """Update a custom per-activity setting declared via ``custom_settings``.

        Stores the value in ``activity.custom_values`` and persists it. The
        game subclass is expected to override :meth:`apply_custom_setting` (or
        react in its handler) to actually apply the new value at runtime.
        Returns ``True`` if the activity + key exist.
        """
        activity = self._activity_map.get(activity_id)
        if not activity:
            return False
        declared = [s.get("key") for s in activity.custom_settings]
        if key not in declared:
            return False
        activity.custom_values[key] = value
        self._save_activity_settings()
        try:
            self.apply_custom_setting(activity_id, key, value)
        except Exception as e:
            log_warning(f"[settings] apply_custom_setting('{key}') failed: {e}")
        return True

    def apply_custom_setting(self, activity_id: str, key: str, value: Any) -> None:
        """Hook for subclasses to react to a custom setting change.

        Default implementation is a no-op. Override to apply the new value
        immediately (e.g. re-inject the speedhack with the new multiplier).
        """

    def set_activity_order(self, order: List[str]):
        """Set the execution order of activities"""
        if not self._activities_mgr.set_order(order):
            invalid = [aid for aid in order if aid not in self._activity_map]
            log_warning(f"Invalid activity IDs in order: {invalid}")
            return
        log_info(f"Activity order updated: {order}")

    def reset_activities(self):
        """Reset all activities to pending state"""
        self._activities_mgr.reset_all()
        log_info("All activities reset")
    
    def get_current_activity(self) -> Optional[Activity]:
        """Get currently running activity"""
        return self._current_activity
    
    def set_ocr_backend(self, backend: str) -> bool:
        """Switch the OCR backend at runtime and persist the choice.

        Supported backends: ``"tesseract"``, ``"easyocr"``. Returns
        ``True`` if the new backend became available. The choice is
        saved to the game's settings file so it survives restarts.
        """
        ok = super().set_ocr_backend(backend)
        self._save_activity_settings()
        return ok

    def get_ui_setting(self, key: str, default: Any = None) -> Any:
        """Return a persisted UI-level setting for this game."""
        return self._ui_settings.get(key, default)

    def set_ui_setting(self, key: str, value: Any) -> None:
        """Persist a UI-level setting for this game."""
        self._ui_settings[key] = value
        self._save_activity_settings()

    def _load_activity_settings(self) -> List[Dict[str, Any]]:
        """Load persisted activity settings for this game, if any.

        Also restores the OCR backend when present in the settings file.
        Returns the activity list (possibly empty).
        """
        activities, ui_settings, backend = self._settings.load()
        self._ui_settings = ui_settings
        if backend and backend != self.ocr.backend_name:
            # Only auto-restore when the caller didn't already pin a backend at
            # construction time (construction-time choice has already been
            # applied and wins). This OCR side effect stays here, not in the
            # store, to keep persistence free of OCR coupling.
            super().set_ocr_backend(backend)
        return activities

    def _save_activity_settings(self) -> None:
        """Persist current enabled/poll_interval state + OCR backend."""
        self._settings.save(
            activities=[act.to_settings_dict() for act in self._activities],
            ui_settings=self._ui_settings,
            ocr_backend=self.ocr.backend_name if self.ocr.available else None,
        )

    # ==================== Background Activity Management ====================
    #
    # Worker threads live in ``self._bg`` (BackgroundWorkerManager). These thin
    # wrappers keep the historical method names that the GUI and
    # ``set_activity_enabled`` call.

    def _start_background_activity(self, activity: Activity) -> bool:
        """Start a worker thread for a background activity (idempotent)."""
        # Starting work clears any prior stop request so the worker's wait_*
        # calls don't immediately abort.
        self._stop_event.clear()
        return self._bg.start(activity)

    def _stop_background_activity(self, activity: Activity, join_timeout: float = 0.5) -> None:
        """Signal a single background worker to stop and wait briefly for it."""
        self._bg.stop(activity, join_timeout=join_timeout)

    def _start_all_background_activities(self) -> None:
        """Start workers for every enabled background activity."""
        self._bg.start_all(self._activities)

    def _stop_all_background_activities(self) -> None:
        """Signal every background worker to stop, then join once."""
        self._bg.stop_all()

    def is_background_running(self, activity_id: str) -> bool:
        """Whether a given background activity currently has a live worker."""
        return self._bg.is_running(activity_id)

    def set_background_enabled(self, enabled: bool) -> None:
        """Start or stop all enabled background activities as a group.

        Public entry point for the GUI's background toggle. When enabling,
        ensures ADB + continuous capture are alive first (a no-op when the main
        automation loop is already running).
        """
        if enabled:
            self._stop_event.clear()
            self._ensure_runtime_ready()
            self._start_all_background_activities()
        else:
            self._stop_all_background_activities()
    
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
        
        try:
            log_info(f"Starting activity: {activity.name} ({activity.id})")
            
            # Wait if paused
            self._pause_event.wait()
            
            # Execute handler
            result = handler()
            
            if result:
                activity.status = ActivityStatus.COMPLETED
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
            - 'on_error': Called on error (error)
            - 'on_status_change': Called on status change (status_dict)
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)
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
    
    # ==================== Control Methods ====================

    def _ensure_runtime_ready(self) -> bool:
        """Make sure ADB is connected and continuous capture is running.

        Used by both the main ``start()`` flow and ad-hoc operations like
        background-activity toggles or single-activity runs that need a
        live screencap stream but haven't been routed through ``start()``.

        Returns ``True`` on success, ``False`` if ADB couldn't be reached.
        """
        try:
            if not self.adb.device:
                self.adb.check_adb_connection()
            if not self.adb.device:
                log_error("Failed to connect to ADB device")
                return False
            # Refresh screen size in case it changed (rotation, new device).
            self._update_screen_size()
            # Start the continuous capture thread if it's not already up.
            if not getattr(self, "capture_running", False):
                self.start_continuous_capture()
            return True
        except Exception as e:
            log_error(f"Runtime not ready: {e}")
            return False

    def _ensure_app_foreground(self, timeout: float = 60.0) -> bool:
        """Make sure the game app is in the foreground before running.

        Launches the app via ``am start`` (falling back to ``monkey``)
        when a different one (or the home screen) is focused, then polls
        until it reports as the current app. Returns ``True`` when the
        app is foregrounded, ``False`` on timeout or when automation was
        stopped while waiting.

        Requires ``self.package_name`` to be set by the subclass.
        """
        package = getattr(self, "package_name", None)
        if not package:
            log_error("[app] package_name not set; cannot launch app")
            return False
        if not getattr(self.adb, "device", None):
            log_error("[app] no device connected; cannot launch app")
            return False

        self.adb.clear_info_cache()
        current = self.adb.get_current_app()
        if current == package:
            return True

        log_warning(f"[app] foreground is '{current}', launching {package}...")
        if not self.adb.launch_app(package):
            return False

        start = time.time()
        while self.running and time.time() - start < timeout:
            self.adb.clear_info_cache()
            current = self.adb.get_current_app()
            if current == package:
                log_success(f"[app] {package} is in foreground")
                return True
            self.sleep(2.0)
        log_error(f"[app] {package} did not come to foreground")
        return False

    def run_single_activity(self, activity_id: str) -> bool:
        """Execute one specific activity once, outside the main loop.

        Useful when the user wants to run a single task on demand (e.g. via
        a per-row "Run" button in the GUI) without having to start the
        whole sequential queue.

        - Ensures ADB + capture are alive
        - Skips when another single-activity run, the main loop, or this
          activity itself is already running
        - Honours pause state
        - Emits the same callbacks (``on_activity_start`` / ``_complete`` /
          ``_failed``) the main loop uses, so the UI updates the same way

        Returns ``True`` if the activity returned success.
        """
        activity = self._activity_map.get(activity_id)
        if not activity:
            log_error(f"Unknown activity: {activity_id}")
            return False
        if activity.background:
            log_warning(
                f"'{activity_id}' is a background activity; toggle it on "
                "instead of running it once."
            )
            return False
        if self.running:
            log_warning("Cannot run a single activity while the main loop is running.")
            return False
        if self._current_activity is not None:
            log_warning(
                f"Another activity is already running: "
                f"{self._current_activity.id}"
            )
            return False

        if not self._ensure_runtime_ready():
            return False

        # Reset the activity's state so the UI reflects a fresh run.
        activity.reset()

        log_info(f"Running single activity: {activity.name}")
        self._stop_event.clear()
        previous_running = self.running
        self.running = True
        try:
            return self._execute_activity(activity)
        finally:
            self.running = previous_running
            log_info(f"Single activity finished: {activity.name}")

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
        """Stop everything: sequential queue + background workers + cleanup."""
        log_info("Stopping automation...")
        self._stop_event.set()
        self.running = False
        self._paused = False
        self._pause_event.set()
        
        # Stop continuous capture
        self.stop_continuous_capture()
        
        # Stop all background activity workers (idempotent if already stopped)
        self._stop_all_background_activities()
        
        # Shutdown executor if it was ever created
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        
        # Close visualizer
        self.visualizer.close()
        
        self._trigger_callback('on_stop')
        log_success("Automation stopped")

    def stop_sequential(self):
        """Stop only the sequential automation loop, leaving background workers running.

        Unlike :meth:`stop`, this does **not** tear down background
        activities, continuous capture, or the executor. It simply signals
        the main loop (``self.running = False``) so ``process_game_actions``
        exits after the current activity finishes.
        """
        log_info("Stopping sequential automation...")
        self._stop_event.set()
        self.running = False
        self._paused = False
        self._pause_event.set()
        self._trigger_callback('on_stop')
        log_success("Sequential automation stopped")
    
    # ==================== Main Process Hooks ====================

    def before_process_game_actions(self) -> bool:
        """Hook for game-specific startup checks before the activity loop."""
        return True

    def after_process_game_actions(self):
        """Hook for game-specific cleanup after the activity loop."""
        pass

    # ==================== Main Process ====================
    
    def process_game_actions(self):
        """
        Main automation loop - processes activities in order.
        Override this method only if you need custom flow control.
        """
        self._stop_event.clear()
        if not self.before_process_game_actions():
            self.running = False
            return

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
                
                # Execute activity, retrying up to ``max_retries`` times in
                # total (the first run counts as attempt 1).
                success = False
                for attempt in range(1, max(1, activity.max_retries) + 1):
                    if not self.running:
                        break
                    if attempt > 1:
                        log_info(
                            f"Retrying activity {activity.id} "
                            f"(attempt {attempt}/{activity.max_retries})"
                        )
                        activity.reset()
                    success = self._execute_activity(activity)
                    if success:
                        break
                
                # Small delay between activities
                if self.running:
                    time.sleep(0.5)
            
            log_success("All activities completed")
            self.running = False
            
        except KeyboardInterrupt:
            log_info("Automation interrupted by user")
        except Exception as e:
            log_error(f"Error in automation loop: {e}")
            self._trigger_callback('on_error', e)
        finally:
            self.after_process_game_actions()
    
    # ==================== Utility Methods ====================
    
    def wait_and_check_pause(self, timeout: float = 0.1):
        self._pause_event.wait()
        time.sleep(timeout)
    
    def sleep(self, seconds: float):
        log_info(f"Sleeping for {seconds}s")
        end_time = time.time() + seconds
        while time.time() < end_time and not self._stop_event.is_set():
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
                    'enabled': act.enabled,
                    'background': act.background,
                    'background_running': self.is_background_running(act.id) if act.background else False,
                }
                for act in self._activities
            ],
            'performance': self.get_performance_metrics(),
        }



