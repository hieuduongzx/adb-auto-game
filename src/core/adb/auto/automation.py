"""
Main automation class for ADB game automation
"""
import os
import random
import cv2
import keyboard
import numpy as np
import time
import threading
import logging
from typing import Tuple, Optional, List, Dict, Any

from src.utils import log_error, log_info, log_warning, log_normal
from ..controller import ADBController
from .config import Config, PerformanceMetrics
from .template_matcher import TemplateMatcher
from .visualizer import DebugVisualizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class ADBGameAutomation:
    """Main automation class combining ADB control with template matching"""
    
    def __init__(
        self,
        config_file: Optional[str] = None,
        device_id: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 5037,
        config: Optional[Config] = None,
    ):
        # Initialize ADB controller
        self.adb = ADBController(device_id=device_id, host=host, port=port)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = False
        self.config_file = config_file
        
        # Configuration
        self.config = config or Config()
        
        # Screen capture
        self.capture_interval = self.config.capture_interval
        self.latest_screen: Optional[np.ndarray] = None
        self.screen_lock = threading.Lock()
        self.capture_thread: Optional[threading.Thread] = None
        self.capture_running = False
        
        # Debug settings
        self.is_debug = self.config.debug_mode
        self.is_debug_fail = self.config.debug_fail_mode
        self.auto_orientation_detection = self.config.auto_orientation_detection
        
        # Components
        self.matcher = TemplateMatcher(cache_size=self.config.template_cache_size)
        self.visualizer = DebugVisualizer()
        if self.is_debug:
            self.visualizer.enable(self.is_debug_fail)
        
        # Performance tracking
        self.metrics = PerformanceMetrics() if self.config.performance_tracking else None
        
        # Screen dimensions
        self.monitor = {"top": 0, "left": 0, "width": 0, "height": 0}
        self._update_screen_size()
        
        # Template directory
        self.templates_dir = ""
    
    def _update_screen_size(self):
        """Update screen size from ADB"""
        width, height = self.adb.get_screen_size()
        if width > 0 and height > 0:
            self.monitor["width"] = width
            self.monitor["height"] = height
    
    def _continuous_capture_worker(self):
        """Background thread for continuous screen capture"""
        log_info("Starting continuous screen capture thread")
        while self.capture_running:
            try:
                result = self.adb.capture_screen_raw()
                if result:
                    nparr = np.frombuffer(result, np.uint8)
                    screen = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if screen is not None:
                        with self.screen_lock:
                            self.latest_screen = screen
                time.sleep(self.capture_interval)
            except Exception as e:
                log_error(f"Error in capture thread: {e}")
                time.sleep(self.capture_interval)
        log_info("Screen capture thread stopped")
    
    def start_continuous_capture(self):
        """Start continuous screen capture in background thread"""
        if not self.capture_running:
            self.capture_running = True
            self.capture_thread = threading.Thread(
                target=self._continuous_capture_worker, daemon=True
            )
            self.capture_thread.start()
            log_info("Continuous screen capture started")
    
    def stop_continuous_capture(self):
        """Stop continuous screen capture"""
        if self.capture_running:
            self.capture_running = False
            if self.capture_thread and self.capture_thread.is_alive():
                self.capture_thread.join(timeout=2.0)
            log_info("Continuous screen capture stopped")
    
    def get_latest_screen(self) -> Optional[np.ndarray]:
        """Get latest captured screen (thread-safe)"""
        with self.screen_lock:
            return self.latest_screen.copy() if self.latest_screen is not None else None
    
    def get_screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions"""
        return self.adb.get_screen_size()
    
    def capture_screen(self) -> Optional[np.ndarray]:
        """Capture screen immediately"""
        try:
            result = self.adb.capture_screen_raw()
            if not result:
                log_warning("Empty screencap result")
                return None
            nparr = np.frombuffer(result, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if image is None:
                log_error("Failed to decode screenshot")
                return None
            return image
        except Exception as e:
            log_error(f"Error capturing screen: {e}")
            return None
    
    
    def tap(self, x: int, y: int, duration: float = 0.1, tap_count: int = 1) -> bool:
        """Tap at coordinates with debug visualization"""
        if self.is_debug:
            screen = self.get_latest_screen()
            if screen is not None:
                self.visualizer.show_tap(screen, x, y, tap_count)
        
        return self.adb.tap(x, y, duration, tap_count)
    
    def find_and_tap(
        self,
        template_name: str,
        log_msg: str = "",
        threshold: Optional[float] = None,
        tap_count: int = 1,
        retry_attempts: Optional[int] = None,
    ) -> bool:
        """Find template and tap on it with retry"""
        threshold = threshold or self.config.default_threshold
        retry_attempts = retry_attempts or self.config.max_retry_attempts
        
        start_time = time.time()
        
        for attempt in range(retry_attempts):
            try:
                result = self.find_template(template_name, threshold=threshold)
                if result:
                    x, y, confidence = result
                    if self.tap(x, y, tap_count=tap_count):
                        total_time = time.time() - start_time
                        log_normal(
                            f"[FIND TAP] [{x}, {y}] [{os.path.basename(template_name)}] "
                            f"[conf: {confidence:.2f}, time: {total_time:.2f}s] {log_msg}"
                        )
                        return True
                
                if attempt < retry_attempts - 1:
                    time.sleep(self.config.retry_delay)
                    
            except Exception as e:
                log_warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < retry_attempts - 1:
                    time.sleep(self.config.retry_delay)
        
        return False
  
    def wait_and_tap(
        self,
        template_name: str,
        timeout: float = 10.0,
        threshold: float = 0.9,
        offset: Tuple[int, int] = (0, 0),
    ) -> bool:
        """Wait for template and tap on it"""
        result = self.wait_for_template(template_name, timeout=timeout, threshold=threshold)
        if result:
            x, y, confidence = result
            if self.tap(x + offset[0], y + offset[1]):
                log_normal(
                    f"[WAIT TAP] [{x}, {y}] [{os.path.basename(template_name)}] [conf: {confidence:.2f}]"
                )
                return True
        return False

    def find_template(
        self,
        template_path: str,
        threshold: Optional[float] = None,
        use_grayscale: bool = False,
        multi_scale: Optional[bool] = None,
        last_screen: bool = True,
    ) -> Optional[Tuple[int, int, float]]:
        """Find template in screen with performance tracking"""
        start_time = time.time()
        
        threshold = threshold or self.config.default_threshold
        
        # Get screen
        screen = self.get_latest_screen() if last_screen else self.capture_screen()
        if screen is None:
            if self.metrics:
                self.metrics.update_failure()
            return None
        
        # Determine scales based on orientation
        if multi_scale is None and self.auto_orientation_detection:
            h, w = screen.shape[:2]
            is_portrait = w <= h
            multi_scale = True
            scales = list(self.config.portrait_scales if is_portrait else self.config.landscape_scales)
            # Adjust threshold for portrait
            if is_portrait:
                threshold = max(threshold - self.config.portrait_threshold_adjustment, self.config.min_threshold)
        else:
            scales = [1.0]
        
        # Load template
        template = self.matcher.load(template_path, grayscale=use_grayscale)
        if template is None:
            if self.metrics:
                self.metrics.update_failure()
            return None
        
        # Perform matching
        result = self.matcher.match(
            screen, template, threshold=threshold,
            use_grayscale=use_grayscale, multi_scale=multi_scale, scales=scales
        )
        
        # Update metrics and visualize
        match_time = time.time() - start_time
        if result:
            if self.metrics:
                self.metrics.update_match_time(match_time)
            
            center_x, center_y, confidence, scale = result
            
            # Visualize if debug enabled
            if self.is_debug:
                self.visualizer.show_template_match(
                    screen, (center_x - int(template.shape[1] * scale) // 2,
                             center_y - int(template.shape[0] * scale) // 2),
                    template.shape[:2], scale, confidence,
                    os.path.basename(template_path), is_match=True
                )
            
            return (center_x, center_y, confidence)
        else:
            if self.metrics:
                self.metrics.update_failure()
            
            if self.is_debug and self.is_debug_fail:
                # Re-run with threshold=0 to find best (sub-threshold) match
                # for visualization, so users can see where matching is going wrong.
                best = self.matcher.match(
                    screen, template, threshold=0.0,
                    use_grayscale=use_grayscale, multi_scale=multi_scale, scales=scales,
                )
                if best:
                    cx, cy, conf, sc = best
                    self.visualizer.show_template_match(
                        screen,
                        (cx - int(template.shape[1] * sc) // 2,
                         cy - int(template.shape[0] * sc) // 2),
                        template.shape[:2], sc, conf,
                        os.path.basename(template_path), is_match=False,
                    )
            
            return None
    
    def find_all_templates(
        self,
        template_path: str,
        threshold: float = 0.8,
        use_grayscale: bool = False,
    ) -> List[Tuple[int, int, float]]:
        """Find all instances of template in screen"""
        screen = self.get_latest_screen()
        if screen is None:
            return []
        
        template = self.matcher.load(template_path, grayscale=use_grayscale)
        if template is None:
            return []
        
        return self.matcher.match_all(screen, template, threshold=threshold, use_grayscale=use_grayscale)

    def wait_for_template(
        self,
        template_name: str,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: Optional[float] = None,
    ) -> Optional[Tuple[int, int, float]]:
        """Wait for template to appear on screen"""
        threshold = threshold or self.config.default_threshold
        start_time = time.time()
        attempts = 0
        
        while time.time() - start_time < timeout:
            attempts += 1
            result = self.find_template(template_name, threshold=threshold)
            
            if result:
                elapsed = time.time() - start_time
                log_normal(
                    f"[WAIT TEMPLATE] {template_name} found after {elapsed:.2f}s ({attempts} attempts)"
                )
                return result
            
            # Log progress every 5 seconds
            elapsed = time.time() - start_time
            if int(elapsed) % 5 == 0 and elapsed - int(elapsed) < interval:
                log_info(f"[WAIT TEMPLATE] Still waiting for {template_name}... ({elapsed:.1f}s)")
            
            time.sleep(interval)
        
        log_warning(f"[WAIT TEMPLATE] Timeout waiting for {template_name}")
        return None
    
    def wait_for_any_template(
        self,
        template_names: List[str],
        timeout: float = 30.0,
        interval: float = 0.5,
        threshold: Optional[float] = None,
    ) -> Optional[Tuple[str, int, int, float]]:
        """Wait for any of the given templates to appear"""
        threshold = threshold or self.config.default_threshold
        start_time = time.time()
        
        log_info(f"Waiting for any of {len(template_names)} templates (timeout: {timeout}s)")
        
        while time.time() - start_time < timeout:
            for template_name in template_names:
                result = self.find_template(template_name, threshold=threshold)
                if result:
                    elapsed = time.time() - start_time
                    x, y, confidence = result
                    log_info(
                        f"Template found: {template_name} at ({x}, {y}) conf={confidence:.3f} "
                        f"after {elapsed:.2f}s"
                    )
                    return (template_name, x, y, confidence)
            
            time.sleep(interval)
        
        log_warning("Timeout waiting for any template")
        return None
        
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        """Swipe gesture with debug visualization"""
        if self.is_debug:
            screen = self.get_latest_screen()
            if screen is not None:
                self.visualizer.show_swipe(screen, x1, y1, x2, y2, duration)
        
        return self.adb.swipe(x1, y1, x2, y2, duration)
    
    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        """Drag gesture with debug visualization"""
        if self.is_debug:
            screen = self.get_latest_screen()
            if screen is not None:
                self.visualizer.show_drag(screen, x1, y1, x2, y2, duration)
        
        return self.adb.drag(x1, y1, x2, y2, duration)
    
    def send_text(self, text: str) -> bool:
        """Send text input"""
        return self.adb.send_text(text)
    
    def press_key(self, keycode: int) -> bool:
        """Press key by keycode"""
        return self.adb.press_key(keycode)
    
    def go_back(self) -> bool:
        """Press back button"""
        return self.adb.go_back()
    
    def go_home(self) -> bool:
        """Press home button"""
        return self.adb.go_home()
    
    def get_center_point(self) -> Tuple[int, int]:
        """Get center of screen"""
        width, height = self.get_screen_size()
        return width // 2, height // 2
    
    def get_random_point(self) -> Tuple[int, int]:
        """Get random point on screen"""
        width, height = self.get_screen_size()
        return random.randint(0, width), random.randint(0, height)
    
    def get_performance_metrics(self) -> Optional[Dict[str, Any]]:
        """Get performance metrics"""
        if not self.metrics:
            return None
        return self.metrics.to_dict()
    
    def set_debug_mode(self, enabled: bool, fail_mode: bool = False):
        """Enable/disable debug mode"""
        self.is_debug = enabled
        self.is_debug_fail = fail_mode
        if enabled:
            self.visualizer.enable(fail_mode)
        else:
            self.visualizer.disable()
        log_info(f"Debug mode: {'enabled' if enabled else 'disabled'}")
    
    def set_config(self, config: Config):
        """Update configuration"""
        self.config = config
        self.capture_interval = config.capture_interval
        self.is_debug = config.debug_mode
        self.is_debug_fail = config.debug_fail_mode
        self.auto_orientation_detection = config.auto_orientation_detection
        if self.is_debug:
            self.visualizer.enable(self.is_debug_fail)
        log_info("Configuration updated")
    
    def start(self):
        """Start automation loop (to be overridden by subclasses)"""
        if not self.adb.device:
            self.adb.check_adb_connection()
        
        if not self.adb.device:
            log_error("Failed to connect to ADB device")
            return
        
        self._update_screen_size()
        log_info("Starting ADB automation... Press 'q' to quit")
        self.running = True
        self.start_continuous_capture()
        
        try:
            while self.running:
                try:
                    if keyboard.is_pressed("q"):
                        log_info("Stopping automation...")
                        self.running = False
                        break
                    
                    # Subclasses should override process_game_actions
                    self.process_game_actions()
                    
                    time.sleep(0.1)
                    
                except Exception as e:
                    log_error(f"Error in automation loop: {e}")
                    time.sleep(0.5)
        finally:
            self.stop_continuous_capture()
            self.visualizer.close()
    
    def process_game_actions(self):
        """Process game actions - override in subclass"""
        raise NotImplementedError("Subclasses must implement process_game_actions()")
