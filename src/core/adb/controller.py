"""
ADB Controller - Main class for ADB device management
"""
import os
import shlex
import time
from typing import Optional, List, Tuple
from ppadb.client import Client as AdbClient

from .constants import (
    KEYCODE_HOME, KEYCODE_BACK,
    DEFAULT_HOST, DEFAULT_PORT, COMMON_APPS, get_adb_path
)
from .cache import get_cache
from .scanner import DeviceScanner
from src.utils import log_error, log_success, log_warning, log_normal


def _extract_package_from_focus_line(line: str) -> Optional[str]:
    """Extract a package name from a dumpsys focus/activity line like
    '... u0 com.example.app/.MainActivity ...'."""
    if "/" not in line:
        return None
    # Token immediately before the '/' is the package
    left = line.split("/", 1)[0]
    token = left.split()[-1] if left.split() else ""
    if token and token != "null" and "." in token:
        return token
    return None


def _detect_current_app(device) -> Optional[str]:
    """Detect current foreground app package on a device.

    Tries multiple ADB shell commands and parses output in Python so it does
    not rely on `grep` / `awk` being present on the device.
    """
    queries = [
        "dumpsys window windows",
        "dumpsys window",
        "dumpsys activity activities",
        "dumpsys activity top",
    ]
    keys = ("mCurrentFocus", "mFocusedApp", "mResumedActivity",
            "mFocusedActivity", "topResumedActivity", "ACTIVITY ")
    for cmd in queries:
        try:
            result = device.shell(cmd) or ""
        except Exception:
            continue
        for line in result.splitlines():
            if any(k in line for k in keys):
                pkg = _extract_package_from_focus_line(line)
                if pkg:
                    return pkg
    return None


class ADBController:
    """Controller for ADB device operations"""
    
    def __init__(
        self,
        device_id: Optional[str] = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT
    ):
        # Set up ADB path in environment
        adb_path = get_adb_path()
        if os.path.exists(adb_path):
            os.environ["ADBUTILS_ADB_PATH"] = adb_path
        
        self.host = host
        self.port = port
        self.device_id = device_id
        self.client = AdbClient(host=host, port=port)
        self.device = None
        self.scanner = DeviceScanner(host=host, port=port)
        self._cache = get_cache()
        
        # Attempt connection
        self.check_adb_connection()
    
    def _get_current_app_for_device(self, device) -> Optional[str]:
        """Get current app for a specific device without changing self.device"""
        return _detect_current_app(device)
    
    def _get_device_name_for_device(self, device) -> str:
        """Get device name for a specific device without changing self.device"""
        try:
            result = device.shell("getprop ro.product.model")
            if result.strip():
                return result.strip()
        except Exception:
            pass
        return device.serial or "Unknown Device"
    
    def check_adb_connection(self) -> bool:
        """Check and establish ADB connection"""
        try:
            log_normal("Checking ADB connection...")
            
            # Ensure ADB server is running
            self.scanner.ensure_adb_server_running()
            
            devices = self.client.devices()
            if devices:
                log_normal("Available devices:")
                for device in devices:
                    current_app = self._get_current_app_for_device(device)
                    device_name = self._get_device_name_for_device(device)
                    if current_app:
                        app_name = self._get_app_name_for_package(current_app)
                        log_normal(f"Device: {device.serial} ({device_name}) - App: {app_name}")
                    else:
                        log_normal(f"Device: {device.serial} ({device_name})")
                
                if self.device_id is None:
                    # Auto-select first device
                    if len(devices) == 1:
                        self.device = devices[0]
                        self.device_id = self.device.serial
                        device_name = self._get_device_name_for_device(self.device)
                        log_success(f"Connected to device: {self.device_id} ({device_name})")
                        return True
                    else:
                        return self._prompt_device_selection(devices)
                else:
                    # Find specified device
                    for device in devices:
                        if device.serial == self.device_id:
                            self.device = device
                            device_name = self._get_device_name_for_device(self.device)
                            log_success(f"Connected to device: {self.device_id} ({device_name})")
                            return True
                    
                    # Device not found
                    log_warning(f"Specified device '{self.device_id}' not found")
                    return self._prompt_device_selection(devices)
            
            # No devices found, try scanning
            log_warning("No devices found, attempting port scan...")
            return self.scan_device()
            
        except Exception as e:
            log_error(f"Error checking ADB connection: {e}")
            
            # Try to restart ADB server on connection refused
            if "actively refused" in str(e) or "WinError 10061" in str(e):
                log_warning("ADB server connection refused, attempting to restart...")
                if self.scanner.restart_adb_server():
                    # Try again
                    self.client = AdbClient(host=self.host, port=self.port)
                    return self.check_adb_connection()
            
            # Try port scanning as fallback
            return self.scan_device()
    
    def _prompt_device_selection(self, devices: List) -> bool:
        """Prompt user to select a device from list"""
        print("\nMultiple devices found:")
        for i, device in enumerate(devices):
            device_name = self._get_device_name_for_device(device)
            print(f"  {i + 1}. {device.serial} ({device_name})")
        print(f"  0. Scan for more devices")
        
        while True:
            try:
                choice = input(f"\nSelect device (1-{len(devices)}) or 0 to scan: ").strip()
                
                if choice == "0":
                    if self.scan_device():
                        return True
                    continue
                
                device_index = int(choice) - 1
                if 0 <= device_index < len(devices):
                    self.device = devices[device_index]
                    self.device_id = self.device.serial
                    device_name = self._get_device_name_for_device(self.device)
                    log_success(f"Connected to device: {self.device_id} ({device_name})")
                    return True
                else:
                    print(f"Invalid choice. Please enter 0-{len(devices)}")
                    
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                log_error("User cancelled device selection")
                raise Exception("Device selection cancelled")
    
    def scan_device(self) -> bool:
        """Scan for devices on emulator ports and connect to first found"""
        found_devices = self.scanner.scan_all(stop_on_first=True)
        
        if found_devices:
            device_serial, host = found_devices[0]
            
            # Connect to the device
            client = AdbClient(host=self.host, port=self.port)
            devices = client.devices()
            
            for device in devices:
                if device.serial == device_serial:
                    self.client = client
                    self.device = device
                    self.device_id = device.serial
                    device_name = self.get_device_name()
                    log_success(f"Connected to device: {self.device_id} ({device_name})")
                    return True
        
        log_warning("No devices found on any port")
        return False
    
    def scan_specific_emulator(self, emulator_type: str = "all") -> bool:
        """Scan for specific emulator type"""
        found_devices = self.scanner.scan_emulator(emulator_type)
        
        if found_devices:
            device_serial, host = found_devices[0]
            
            # Connect to the device
            client = AdbClient(host=self.host, port=self.port)
            devices = client.devices()
            
            for device in devices:
                if device.serial == device_serial:
                    self.client = client
                    self.device = device
                    self.device_id = device.serial
                    log_success(f"Connected to device: {self.device_id}")
                    return True
        
        log_warning(f"No {emulator_type} devices found")
        return False
    
    def _get_app_name_for_package(self, package_name: str) -> str:
        """Get display name for package"""
        return COMMON_APPS.get(
            package_name,
            package_name.replace("com.", "").replace("org.", "").replace("net.", "").title()
        )
    
    def get_screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions"""
        try:
            result = self.device.shell("wm size")
            size = result.strip().split()[-1].split("x")
            return int(size[0]), int(size[1])
        except Exception as e:
            log_error(f"Error getting screen size: {e}")
            return (0, 0)
    
    def tap(self, x: int, y: int, duration: float = 0.1, tap_count: int = 1) -> bool:
        """Tap at coordinates.

        ``duration`` is the delay applied between taps (and after the last tap)
        when ``tap_count > 1``. For a single tap it is the post-tap delay.
        """
        try:
            cmd = f"input touchscreen tap {x} {y}"
            for i in range(tap_count):
                self.device.shell(cmd)
                if duration > 0 and (tap_count > 1 or i == tap_count - 1):
                    time.sleep(duration)
            return True
        except Exception as e:
            log_error(f"Error tapping at ({x}, {y}): {e}")
            return False
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        """Swipe from one point to another"""
        try:
            self.device.shell(f"input touchscreen swipe {x1} {y1} {x2} {y2} {duration}")
            return True
        except Exception as e:
            log_error(f"Error swiping: {e}")
            return False
    
    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        """Drag gesture"""
        try:
            self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")
            return True
        except Exception as e:
            log_error(f"Error dragging: {e}")
            return False
    
    def hold_and_release(self, x: int, y: int, duration: int = 1000) -> bool:
        """Hold and release at coordinates"""
        try:
            self.device.shell(f"input touchscreen swipe {x} {y} {x} {y} {duration}")
            return True
        except Exception as e:
            log_error(f"Error holding and releasing at ({x}, {y}): {e}")
            return False
    
    def send_text(self, text: str) -> bool:
        """Send text input.

        Android's ``input text`` command does not handle spaces or shell
        metacharacters well, so the text is quoted with ``shlex`` and spaces
        are replaced with ``%s`` (the convention recognised by ``input text``).
        """
        try:
            sanitized = text.replace(" ", "%s")
            self.device.shell(f"input text {shlex.quote(sanitized)}")
            return True
        except Exception as e:
            log_error(f"Error sending text: {e}")
            return False
    
    def press_key(self, keycode: int) -> bool:
        """Press a key by keycode"""
        try:
            self.device.shell(f"input keyevent {keycode}")
            return True
        except Exception as e:
            log_error(f"Error pressing key {keycode}: {e}")
            return False
    
    def go_back(self) -> bool:
        """Press back button"""
        return self.press_key(KEYCODE_BACK)
    
    def go_home(self) -> bool:
        """Press home button"""
        return self.press_key(KEYCODE_HOME)
    
    def capture_screen_raw(self) -> Optional[bytes]:
        """Capture raw screen data"""
        try:
            return self.device.screencap()
        except Exception as e:
            log_error(f"Error capturing screen: {e}")
            return None
    
    def get_current_app(self) -> Optional[str]:
        """Get current running app package name"""
        def _fetch_app():
            return _detect_current_app(self.device)
        
        return self._cache.get(self.device_id or "default", "current_app", _fetch_app)
    
    def get_device_name(self) -> str:
        """Get device name"""
        def _fetch_name():
            try:
                result = self.device.shell("getprop ro.product.model")
                if result.strip():
                    return result.strip()
            except Exception:
                pass
            return self.device_id or "Unknown Device"
        
        return self._cache.get(self.device_id or "default", "device_name", _fetch_name)
    
    def get_app_name(self, package_name: str) -> str:
        """Get display name for app package"""
        return self._get_app_name_for_package(package_name)
