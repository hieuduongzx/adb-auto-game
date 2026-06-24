"""
ADB Controller - Main class for ADB device management
"""
import os
import shlex
import time
from typing import Dict, Optional, List, Tuple
from ppadb.client import Client as AdbClient

from .constants import (
    KEYCODE_HOME, KEYCODE_BACK,
    DEFAULT_HOST, DEFAULT_PORT, COMMON_APPS, get_adb_path
)
from .cache import get_cache
from .scanner import DeviceScanner
from src.utils import log_error, log_success, log_warning, log_normal, log_debug


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
        port: int = DEFAULT_PORT,
        auto_connect: bool = False,
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
        # Attempt connection only when explicitly requested. The GUI passes
        # ``auto_connect=False`` (the default) so the window can open
        # immediately and a port scan can't block startup. The CLI flow
        # calls :meth:`check_adb_connection` from ``start()`` once the user
        # actually wants to run automation.
        if auto_connect:
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
        except Exception as e:
            log_debug(f"getprop ro.product.model failed for {device.serial}: {e}")
        return device.serial or "Unknown Device"
    
    def list_devices(self) -> List[Dict[str, str]]:
        """Return available ADB devices without prompting or connecting.

        Each entry contains ``serial``, ``name``, and optionally ``current_app``.
        Safe to call from the GUI thread. Quiet: no server-startup logging.
        """
        devices: List[Dict[str, str]] = []
        try:
            for device in self.client.devices():
                try:
                    device_name = self._get_device_name_for_device(device)
                except Exception as e:
                    log_debug(f"device name lookup failed for {device.serial}: {e}")
                    device_name = device.serial or "Unknown Device"
                current_app = ""
                try:
                    current_app = self._get_current_app_for_device(device) or ""
                except Exception as e:
                    log_debug(f"current-app lookup failed for {device.serial}: {e}")
                entry = {
                    "serial": device.serial,
                    "name": device_name,
                }
                if current_app:
                    entry["current_app"] = current_app
                    entry["app_name"] = self._get_app_name_for_package(current_app)
                devices.append(entry)
        except Exception as e:
            log_warning(f"Could not list devices: {e}")
        return devices

    def select_device(self, serial: str) -> bool:
        """Connect to a specific device by serial without prompting.

        Idempotent and quiet: returns ``True`` immediately when we are already
        connected to ``serial`` without re-logging the connection.
        """
        if self.device is not None and self.device_id == serial:
            return True
        try:
            for device in self.client.devices():
                if device.serial == serial:
                    self.device = device
                    self.device_id = device.serial
                    device_name = self._get_device_name_for_device(self.device)
                    log_success(f"Connected to device: {self.device_id} ({device_name})")
                    return True
            log_warning(f"Device '{serial}' not found")
        except Exception as e:
            log_error(f"Error selecting device: {e}")
        return False

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
        log_normal("\nMultiple devices found:")
        for i, device in enumerate(devices):
            device_name = self._get_device_name_for_device(device)
            log_normal(f"  {i + 1}. {device.serial} ({device_name})")
        log_normal("  0. Scan for more devices")

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
                    log_warning(f"Invalid choice. Please enter 0-{len(devices)}")

            except ValueError:
                log_warning("Invalid input. Please enter a number.")
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
        """Get screen dimensions, or ``(0, 0)`` if unavailable.

        Callers must treat ``(0, 0)`` as "unknown" (it flows into
        center/random-point math), so we guard the no-device case explicitly
        rather than letting ``self.device`` be ``None`` raise inside the parse.
        """
        if self.device is None:
            return (0, 0)
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

    def clear_info_cache(self) -> None:
        """Drop cached device info (current_app, device_name) for this device.

        Call after launching / switching apps so the next :meth:`get_current_app`
        reflects the new foreground app instead of the stale cached value.
        """
        self._cache.clear(self.device_id or "default")

    def launch_app(self, package: str) -> bool:
        """Bring ``package`` to the foreground.

        Tries ``am start`` with the package's launcher activity (resolved
        via ``cmd package resolve-activity``), falling back to ``monkey``
        if ``am`` isn't available. Clears the cached ``current_app``
        afterwards so a follow-up :meth:`get_current_app` returns the
        freshly-launched app.

        Returns ``True`` when the launch command was issued successfully;
        this does not guarantee the app is already fully foregrounded -
        poll :meth:`get_current_app` if you need to confirm.
        """
        if not self.device:
            log_error("Cannot launch app: no device connected")
            return False

        # 1. Preferred: resolve the launcher activity and use ``am start``.
        #    ``monkey`` is missing on some stripped emulator builds
        #    (e.g. older LDPlayer), so ``am start`` is the reliable path.
        if self._am_start(package):
            self.clear_info_cache()
            return True

        # 2. Fallback: ``monkey`` (some stock Android images ship it but
        #    not ``am``; very rare, but kept for completeness).
        try:
            self.device.shell(
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
            )
        except Exception as e:
            log_error(f"Could not launch {package}: {e}")
            return False
        self.clear_info_cache()
        return True

    def _am_start(self, package: str) -> bool:
        """Launch ``package`` via ``am start`` using its main activity.

        Returns ``False`` if the activity can't be resolved or the shell
        command fails (caller can then try the ``monkey`` fallback).
        """
        try:
            # Resolve the main launcher activity for this package.
            out = self.device.shell(
                f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {package}"
            )
            # ``--brief`` prints a single line like:
            #   PING Intent { act=android.intent.action.MAIN ... cmp=pkg/.Activity }
            # or on older Android: just the component name.
            component = self._parse_resolve_activity(out, package)
            if not component:
                return False
            self.device.shell(f"am start -n {component}")
            return True
        except Exception as e:
            log_debug(f"am start failed for {package}: {e}")
            return False

    @staticmethod
    def _parse_resolve_activity(output: str, package: str) -> str:
        """Extract the ``package/Activity`` component from resolve output.

        ``cmd package resolve-activity --brief`` can emit two formats:

        * Old Android (``am``-style intent dump): a line containing
          ``cmp=pkg/.Activity``.
        * Newer Android (``resolve-activity --brief``): a two-line dump
          whose second line is the bare ``pkg/.Activity`` component.

        We accept either.
        """
        if not output:
            return ""
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Format 1: ``cmp=pkg/.Activity`` inside an intent line.
            if "cmp=" in line:
                after = line.split("cmp=", 1)[1]
                comp = after.split()[0].rstrip("}")
                if "/" in comp:
                    return comp
            # Format 2: a bare ``pkg/.Activity`` line (no spaces, has "/").
            if "/" in line and " " not in line and line.startswith(package):
                return line
        return ""
    
    def get_device_name(self) -> str:
        """Get device name (cached)."""
        def _fetch_name():
            if self.device is None:
                return self.device_id or "Unknown Device"
            return self._get_device_name_for_device(self.device)

        return self._cache.get(self.device_id or "default", "device_name", _fetch_name)
    
    def get_app_name(self, package_name: str) -> str:
        """Get display name for app package"""
        return self._get_app_name_for_package(package_name)

    # ==================== Status helpers ====================

    def is_connected(self) -> bool:
        """Lightweight check whether we currently have a usable device."""
        if self.device is None:
            return False
        try:
            # ``shell`` raises if the device went away; this is much cheaper
            # than re-running the full check_adb_connection flow.
            self.device.shell("echo ok")
            return True
        except Exception as e:
            log_debug(f"is_connected probe failed; dropping device: {e}")
            self.device = None
            return False

    def quick_refresh(self) -> bool:
        """Re-scan **already-connected** ADB devices without port scanning.

        Cheap (~tens of ms) so it's safe to call from a UI poll. Returns
        ``True`` if we now have a device. Use :meth:`check_adb_connection`
        for the heavy version that also scans emulator ports.
        """
        try:
            devices = self.client.devices()
            if not devices:
                self.device = None
                return False
            # Prefer the previously-selected device id; otherwise pick the
            # first available one.
            target = None
            if self.device_id:
                for d in devices:
                    if d.serial == self.device_id:
                        target = d
                        break
            if target is None:
                target = devices[0]
                self.device_id = target.serial
            self.device = target
            return True
        except Exception as e:
            log_debug(f"quick_refresh failed: {e}")
            self.device = None
            return False

    def get_status_summary(self) -> dict:
        """Return a snapshot suitable for display in a status bar.

        Keys:
            connected (bool):    whether ``self.device`` is usable
            device_id (str|None)
            device_name (str|None)
            app_package (str|None)
            app_name (str|None)
        """
        if self.device is None:
            return {
                "connected": False,
                "device_id": self.device_id,
                "device_name": None,
                "app_package": None,
                "app_name": None,
            }
        try:
            device_name = self._get_device_name_for_device(self.device)
        except Exception as e:
            log_debug(f"status_summary device-name lookup failed: {e}")
            device_name = self.device_id
        try:
            app_pkg = _detect_current_app(self.device)
        except Exception as e:
            log_debug(f"status_summary current-app lookup failed: {e}")
            app_pkg = None
        app_name = self._get_app_name_for_package(app_pkg) if app_pkg else None
        return {
            "connected": True,
            "device_id": self.device_id or self.device.serial,
            "device_name": device_name,
            "app_package": app_pkg,
            "app_name": app_name,
        }
