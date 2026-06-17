"""
Base game automation class for easy tool development with GUI support.
This class provides a structured framework for creating game automation tools.
"""
import os
import time
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Callable, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

import cv2

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
    """Represents an automation activity/task.

    There are two execution modes:

    * **Sequential** (default): the activity runs once, in order, as part of
      the main automation loop in :meth:`BaseGameAutomation.process_game_actions`.
    * **Background** (``background=True``): the activity loops in its own
      thread, polling every ``poll_interval`` seconds, and can be toggled on
      and off at runtime via :meth:`BaseGameAutomation.set_activity_enabled`
      while the main loop is running.
    """
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    status: ActivityStatus = ActivityStatus.PENDING
    progress: float = 0.0  # 0.0 to 100.0
    error_message: Optional[str] = None
    execution_count: int = 0
    max_retries: int = 3
    # Background execution support
    background: bool = False
    poll_interval: float = 1.0
    
    def reset(self):
        """Reset activity state"""
        self.status = ActivityStatus.PENDING
        self.progress = 0.0
        self.error_message = None


class BaseGameAutomation(ADBGameAutomation, ABC):
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
            'on_progress': [],
            'on_error': [],
            'on_status_change': [],
        }
        
        # State flags
        self._paused: bool = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        
        # Background activity management
        self._background_threads: Dict[str, threading.Thread] = {}
        self._background_stop_events: Dict[str, threading.Event] = {}
        self._background_lock = threading.Lock()
        
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
        # Only sequential, enabled activities go into the run order. Background
        # activities are managed separately via worker threads.
        self._activity_order = [
            act.id for act in activities
            if act.enabled and not act.background
        ]
        
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

    # ==================== Color / Active-State Helpers ====================
    #
    # ``cv2.matchTemplate`` only compares shape/structure, so a button that's
    # been desaturated to indicate "already used / disabled" still matches
    # its colored template with very high confidence. These helpers add a
    # post-match color check.
    #
    # We use a *colored-pixel ratio* metric rather than mean saturation:
    # count how many strongly-saturated pixels exist in the template, then
    # how many exist in the matched ROI, and compare. A disabled (grayed
    # out) button loses almost every strongly-saturated pixel, so the
    # ratio collapses to near-zero, while an active button stays close to
    # 1.0. This separation is much sharper than mean saturation, which
    # gets diluted by neutral background pixels inside the button bbox.

    # Pixels with HSV saturation >= this value are treated as "colored".
    # 80 keeps us comfortably above noisy near-gray pixels (typically <40)
    # while still catching pastel UI elements.
    _COLORED_PIXEL_SAT_THRESHOLD = 80

    @staticmethod
    def _colored_pixel_count(img_bgr, sat_threshold: int) -> int:
        """Count pixels in a BGR image whose HSV saturation is >= threshold."""
        if img_bgr is None or len(img_bgr.shape) < 3:
            return 0
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        return int((hsv[:, :, 1] >= sat_threshold).sum())

    def is_button_active(
        self,
        template_path: str,
        center: Tuple[int, int],
        min_color_ratio: float = 0.4,
        sat_threshold: Optional[int] = None,
    ) -> bool:
        """Check whether the matched button is in its active (colored) state.

        Counts strongly-saturated pixels in both the template and the
        matched ROI, then compares::

            ratio = colored_pixels(roi) / colored_pixels(template)

        ``ratio`` near ``1.0`` means the ROI carries roughly as much color
        as the template (active). Disabled / grayed-out buttons collapse
        to ``~0`` because almost no pixel survives the saturation cutoff.

        Args:
            template_path: Template that was matched. Used to size the ROI
                *and* to read the reference colored-pixel count.
            center: ``(cx, cy)`` returned by ``find_template``.
            min_color_ratio: ROI must reach at least this fraction of the
                template's colored-pixel count to count as active. ``0.4``
                is a comfortable default; lower it for buttons whose
                disabled state still keeps a few colored accents.
            sat_threshold: Optional override for the saturation cutoff
                that defines a "colored" pixel. Defaults to
                ``_COLORED_PIXEL_SAT_THRESHOLD`` (80).

        Returns:
            ``True`` if the region looks colored, ``False`` if it looks gray
            or the check could not be performed (caller should treat that as
            "don't tap" to be safe).
        """
        screen = self.get_latest_screen()
        if screen is None or len(screen.shape) < 3:
            return False

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return False

        th, tw = template.shape[:2]
        cx, cy = center
        x1 = max(cx - tw // 2, 0)
        y1 = max(cy - th // 2, 0)
        x2 = min(x1 + tw, screen.shape[1])
        y2 = min(y1 + th, screen.shape[0])
        if x2 <= x1 or y2 <= y1:
            return False

        sat_thr = sat_threshold if sat_threshold is not None else self._COLORED_PIXEL_SAT_THRESHOLD

        roi = screen[y1:y2, x1:x2]
        roi_colored = self._colored_pixel_count(roi, sat_thr)
        tpl_colored = self._colored_pixel_count(template, sat_thr)

        # If the template itself has almost no colored pixels (e.g. a pure
        # white-on-dark icon), the metric is meaningless. Fail open so the
        # caller can fall back to a different strategy.
        if tpl_colored < 50:
            log_warning(
                f"[ACTIVE CHECK] {os.path.basename(template_path)} has too "
                f"few colored pixels ({tpl_colored}); skipping active check"
            )
            return True

        ratio = roi_colored / tpl_colored
        passed = ratio >= min_color_ratio

        log_info(
            f"[ACTIVE CHECK] {os.path.basename(template_path)} "
            f"roi_colored={roi_colored} tpl_colored={tpl_colored} "
            f"ratio={ratio:.2f} (min_ratio={min_color_ratio}, "
            f"sat_thr={sat_thr}) -> {'ACTIVE' if passed else 'DISABLED'}"
        )
        return passed

    def find_active_template(
        self,
        template_path: str,
        timeout: float = 5.0,
        threshold: float = 0.85,
        min_color_ratio: float = 0.4,
        sat_threshold: Optional[int] = None,
    ) -> Optional[Tuple[int, int, float]]:
        """Find a template only if the matched region is in its colored state.

        Wraps ``wait_for_template`` + :meth:`is_button_active` so callers
        can replace ``wait_and_tap`` with a two-step "find then tap" flow
        whenever a disabled-button false positive would be a problem::

            active = self.find_active_template(self.tpl['take_all'], timeout=5)
            if active:
                x, y, _ = active
                self.tap(x, y)

        Returns the same ``(x, y, conf)`` tuple as ``find_template`` when
        the button is active, ``None`` otherwise (template missing, not
        visible, or visible but grayed out).
        """
        result = self.wait_for_template(
            template_path, timeout=timeout, threshold=threshold
        )
        if not result:
            return None
        x, y, _ = result
        if not self.is_button_active(
            template_path, (x, y),
            min_color_ratio=min_color_ratio,
            sat_threshold=sat_threshold,
        ):
            return None
        return result

    def wait_and_tap_active(
        self,
        template_path: str,
        timeout: float = 5.0,
        threshold: float = 0.85,
        min_color_ratio: float = 0.4,
        sat_threshold: Optional[int] = None,
        offset: Tuple[int, int] = (0, 0),
    ) -> bool:
        """Like ``wait_and_tap`` but only taps when the button is colored.

        Convenience wrapper around :meth:`find_active_template` that performs
        the tap in a single call. Returns ``True`` only when an active match
        was found and the tap succeeded.
        """
        result = self.find_active_template(
            template_path, timeout=timeout, threshold=threshold,
            min_color_ratio=min_color_ratio,
            sat_threshold=sat_threshold,
        )
        if not result:
            return False
        x, y, _ = result
        return self.tap(x + offset[0], y + offset[1])

    # ==================== OCR Helpers ====================
    #
    # Thin wrappers over the OCR methods on ``ADBGameAutomation`` that add
    # consistent ``[OCR]`` logging and a fast-path "OCR not installed"
    # check. They're meant to be the primary OCR entry points for game
    # subclasses, mirroring the convenience tier of ``wait_and_tap`` /
    # ``find_and_tap`` over the lower-level ``find_template``.

    Region = Tuple[int, int, int, int]

    def region_has_text(
        self,
        needle: str,
        region: "BaseGameAutomation.Region",
        whitelist: Optional[str] = None,
        case_sensitive: bool = False,
        last_screen: bool = True,
        ascii_fold: bool = False,
    ) -> bool:
        """Return ``True`` if ``needle`` appears in OCR output of ``region``.

        Convenience wrapper around :meth:`ADBGameAutomation.region_contains_text`
        with logging tuned for game flows. Returns ``False`` immediately
        when the OCR engine isn't available (Tesseract not installed),
        so callers can chain it before falling back to template checks::

            if self.region_has_text("0/5", region=COUNTER_REGION,
                                    whitelist="0123456789/"):
                return True
            # template fallback...

        Args:
            needle: Substring to look for. Whitespace is ignored.
            region: ``(x, y, w, h)`` in device pixels.
            whitelist: Optional Tesseract char whitelist (e.g.
                ``"0123456789/"`` for digit-only labels).
            case_sensitive: Default ``False``.
            last_screen: Use the most recent capture instead of forcing
                a fresh ``capture_screen()``. Default ``True``.
            ascii_fold: When ``True``, strip diacritics from both the
                OCR result and ``needle`` before comparing. Lets you
                match Vietnamese labels via ASCII needles - useful when
                Tesseract reads "Phúc Lợi" as "Phue Loi" / "Phuc Loi"
                etc and you don't want to enumerate every variant.
        """
        if not getattr(self.ocr, "available", False):
            return False

        text = self.read_text(
            region=region, whitelist=whitelist, last_screen=last_screen,
            ascii_only=ascii_fold,
        )
        if not text:
            log_info(f"[OCR] region {region} empty")
            return False

        # Reuse the lower-level method so case/whitespace rules stay in
        # one place. We've already logged the raw read.
        log_info(f"[OCR] region {region} -> {text!r}")
        return self.region_contains_text(
            needle, region=region,
            whitelist=whitelist, case_sensitive=case_sensitive,
            last_screen=last_screen, ascii_fold=ascii_fold,
        )

    def wait_region_has_text(
        self,
        needle: str,
        region: "BaseGameAutomation.Region",
        timeout: float = 10.0,
        interval: float = 0.5,
        whitelist: Optional[str] = None,
        case_sensitive: bool = False,
        ascii_fold: bool = False,
    ) -> bool:
        """Poll ``region`` until ``needle`` is recognised or timeout.

        Pause-aware: while the automation is paused the poll skips reads
        and just sleeps, so a long ``wait_region_has_text`` won't burn
        ADB during a Pause. ``ascii_fold=True`` lets an ASCII needle
        match Vietnamese diacritic text.
        """
        if not getattr(self.ocr, "available", False):
            log_warning(
                f"[OCR] '{needle}' wait skipped - Tesseract unavailable"
            )
            return False

        start = time.time()
        while time.time() - start < timeout:
            self._pause_event.wait()
            if self.region_has_text(
                needle, region=region,
                whitelist=whitelist, case_sensitive=case_sensitive,
                ascii_fold=ascii_fold,
            ):
                elapsed = time.time() - start
                log_success(
                    f"[OCR] Found '{needle}' in {region} after {elapsed:.2f}s"
                )
                return True
            time.sleep(interval)
        log_warning(f"[OCR] Timeout waiting for '{needle}' in {region}")
        return False

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
    
    # ==================== Background Activity Management ====================
    
    def _background_worker(self, activity: Activity, stop_event: threading.Event):
        """Worker loop for a single background activity.

        Calls ``handle_activity_<id>`` repeatedly every ``poll_interval``
        seconds until ``stop_event`` is set.

        The handler return value is treated as a tick result rather than a
        completion: the loop keeps going regardless. Exceptions are caught
        and logged so a buggy handler cannot kill the worker thread.

        Background workers run independently of the sequential automation
        loop: a user can toggle them on/off even when ``self.running`` is
        ``False`` (e.g. before the main automation has been started).
        """
        handler = self._get_activity_handler(activity.id)
        if handler is None:
            log_error(
                f"Background activity '{activity.id}' has no handler "
                f"(expected method 'handle_activity_{activity.id}'); aborting"
            )
            return
        log_info(f"[bg] Background activity started: {activity.name}")
        activity.status = ActivityStatus.RUNNING
        try:
            while not stop_event.is_set():
                # Honour pause: skip ticks while the main loop is paused.
                if not self._paused:
                    try:
                        handler()
                        activity.execution_count += 1
                    except Exception as e:
                        # Swallow errors so a bug in one tick does not kill
                        # the whole background loop.
                        log_error(f"[bg] Error in background '{activity.id}': {e}")
                # Sleep on the stop event so we wake immediately on disable.
                if stop_event.wait(timeout=max(0.05, activity.poll_interval)):
                    break
        finally:
            activity.status = ActivityStatus.PENDING
            log_info(f"[bg] Background activity stopped: {activity.name}")
    
    def _start_background_activity(self, activity: Activity) -> bool:
        """Start a background activity worker thread.

        Idempotent: returns ``True`` if a worker is now running for the
        activity, ``False`` if the activity is not actually a background one.

        Ensures ADB connection and continuous screen capture are running
        first so the worker has frames to look at, even if the main
        automation loop hasn't been started yet.
        """
        if not activity.background:
            return False
        # Make sure ADB and capture are alive before kicking off the worker.
        # This is a no-op when the main automation loop is already running.
        self._ensure_runtime_ready()
        with self._background_lock:
            existing = self._background_threads.get(activity.id)
            if existing is not None and existing.is_alive():
                return True
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._background_worker,
                args=(activity, stop_event),
                name=f"bg-{activity.id}",
                daemon=True,
            )
            self._background_stop_events[activity.id] = stop_event
            self._background_threads[activity.id] = thread
            thread.start()
        return True
    
    def _stop_background_activity(self, activity: Activity, join_timeout: float = 2.0) -> None:
        """Signal a background worker to stop and wait briefly for it."""
        with self._background_lock:
            stop_event = self._background_stop_events.pop(activity.id, None)
            thread = self._background_threads.pop(activity.id, None)
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
    
    def _start_all_background_activities(self) -> None:
        """Start workers for every enabled background activity."""
        for activity in self._activities:
            if activity.background and activity.enabled:
                self._start_background_activity(activity)
    
    def _stop_all_background_activities(self) -> None:
        """Signal every background worker to stop."""
        for activity in list(self._activities):
            if activity.background:
                self._stop_background_activity(activity)
    
    def is_background_running(self, activity_id: str) -> bool:
        """Whether a given background activity currently has a live worker."""
        thread = self._background_threads.get(activity_id)
        return thread is not None and thread.is_alive()
    
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
        self._update_progress(activity_id, 0.0)

        log_info(f"Running single activity: {activity.name}")
        try:
            return self._execute_activity(activity)
        finally:
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
        """Stop automation gracefully"""
        log_info("Stopping automation...")
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
    
    # ==================== Main Process ====================
    
    def process_game_actions(self):
        """
        Main automation loop - processes activities in order.
        Override this method only if you need custom flow control.
        """
        log_info(f"Starting automation with activities: {self._activity_order}")
        self._trigger_callback('on_start')
        # Spin up any background activities that are enabled. They will run
        # alongside the sequential activities below.
        self._start_all_background_activities()
        
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
            # Mark as not running so the outer start() loop exits instead of
            # immediately re-running every activity again.
            self.running = False
            
        except KeyboardInterrupt:
            log_info("Automation interrupted by user")
        except Exception as e:
            log_error(f"Error in automation loop: {e}")
            self._trigger_callback('on_error', e)
        finally:
            # Always tear down background workers when the main loop exits,
            # even on error or KeyboardInterrupt.
            self._stop_all_background_activities()
    
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
                    'background': act.background,
                    'background_running': self.is_background_running(act.id) if act.background else False,
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
