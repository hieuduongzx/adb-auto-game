"""
Device scanning functionality
"""
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Set
from ppadb.client import Client as AdbClient

from .constants import ALL_EMULATOR_PORTS, EMULATOR_PORT_RANGES, get_adb_path
from src.utils import log_error, log_info, log_success, log_warning, log_normal, log_debug


class DeviceScanner:
    """Scanner for finding ADB devices on emulator ports"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5037):
        self.host = host
        self.port = port
        self.adb_path = get_adb_path()
        # Remember the last reported status so periodic polling (every few
        # seconds) only logs when something actually changes — no spam.
        self._last_server_ok: Optional[bool] = None
        self._last_device_count: int = -1
    
    @staticmethod
    def _local_ipv4s() -> List[str]:
        """This host's own non-loopback IPv4 addresses.

        Needed because LDPlayer binds ``0.0.0.0:5555`` while MuMu binds the more
        specific ``127.0.0.1:5555``; Windows routes loopback connects to the
        specific bind (MuMu), so LDPlayer is only reachable via a LAN IP.
        """
        ips = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if ip and not ip.startswith("127."):
                    ips.add(ip)
        except Exception:
            pass
        return sorted(ips)

    def _scan_targets(self) -> List[str]:
        """Loopback emulator ports, plus LDPlayer ports on each LAN IP."""
        targets = list(ALL_EMULATOR_PORTS)
        lan_ips = self._local_ipv4s()
        if lan_ips:
            ld_ports = [h.split(":", 1)[1]
                        for h in EMULATOR_PORT_RANGES.get("ldplayer", [])]
            for ip in lan_ips:
                for port in ld_ports:
                    targets.append(f"{ip}:{port}")
        seen, out = set(), []
        for t in targets:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def unique_devices(self, devices) -> List[dict]:
        """One entry per *physical* device, as ``[{"serial","name"}]``.

        A single emulator can appear under several ADB serials at once
        (e.g. MuMu as ``127.0.0.1:16384`` + ``:5555`` + ``:7555`` +
        ``emulator-5554``). We group by a stable hardware fingerprint
        (``android_id``, falling back to ``ro.serialno``) so duplicates collapse
        to one, while genuinely different emulators stay separate — even when
        they share a port number on different hosts. The representative serial
        prefers a loopback (``127.0.0.1``) address, then a LAN IP, then the
        ``emulator-*`` console form.
        """
        info = []  # (serial, model, fingerprint)
        for d in devices:
            model = fp = ""
            # A just-`adb connect`-ed device is briefly offline; retry so its
            # fingerprint is stable instead of splitting one emulator into
            # several rows right after a scan. Warm devices hit this once.
            for attempt in range(3):
                try:
                    out = d.shell("getprop ro.product.model; settings get secure android_id") or ""
                    parts = [ln.strip() for ln in out.splitlines() if ln.strip()]
                    if parts:
                        model = parts[0]
                    if len(parts) > 1 and parts[1].lower() != "null":
                        fp = parts[1]
                except Exception:
                    pass
                if fp:
                    break
                if attempt < 2:
                    time.sleep(0.3)
            if not fp:
                try:
                    fp = (d.shell("getprop ro.serialno") or "").strip()
                except Exception:
                    fp = ""
            if not fp:
                fp = "@" + d.serial  # can't fingerprint → treat as its own device
            info.append((d.serial, model, fp))

        def rank(serial: str):
            if serial.startswith("127.0.0.1:"):
                return (0, serial)
            if serial.startswith("emulator-"):
                return (2, serial)
            return (1, serial)  # LAN-IP form: between loopback and console

        groups: Dict[str, list] = {}
        for serial, model, fp in info:
            groups.setdefault(fp, []).append((serial, model))
        result = []
        for fp, lst in groups.items():
            lst.sort(key=lambda sm: rank(sm[0]))
            serial, model = lst[0]
            result.append({"serial": serial, "name": model or serial})
        return result

    def _is_port_open(self, host: str, port: int, timeout: float = 1.0) -> bool:
        """Quickly check if a port is open"""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, socket.error):
            return False
    
    def _try_connect_to_host(self, host: str) -> Optional[str]:
        """Try to connect to a single host and return device serial if successful"""
        try:
            # First, quickly check if port is open
            host_ip, port_str = host.split(":")
            port = int(port_str)
            if not self._is_port_open(host_ip, port, timeout=1.0):
                return None
            
            # Try ADB connect with shorter timeout
            result = subprocess.run(
                [self.adb_path, "connect", host],
                capture_output=True,
                text=True,
                timeout=2,
            )
            
            # Check if connection was successful
            stdout = result.stdout.lower()
            if "connected" not in stdout and "already connected" not in stdout:
                return None
            
            # adb connect succeeded — the serial IS the host string.
            # Do not fall back to devices[0]: under parallel scanning multiple
            # threads may query ADB simultaneously, and the first-registered
            # device would mask every other port's result.
            return host
                
        except subprocess.TimeoutExpired:
            return None
        except Exception as e:
            # Most port probes during a scan miss; keep this at debug level so a
            # full scan doesn't spam the console, but the reason is recoverable.
            log_debug(f"connect probe to {host} failed: {e}")
            return None

        return None
    
    def scan_ports(
        self,
        ports: List[str],
        max_workers: int = 100,
        stop_on_first: bool = False
    ) -> List[Tuple[str, str]]:
        """
        Scan a list of ports for devices
        
        Args:
            ports: List of host:port strings to scan
            max_workers: Number of parallel threads
            stop_on_first: If True, stop after finding first device
            
        Returns:
            List of (device_serial, host) tuples
        """
        found_devices: List[Tuple[str, str]] = []
        found_serials: Set[str] = set()
        
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_host = {
                    executor.submit(self._try_connect_to_host, host): host
                    for host in ports
                }
                
                for future in as_completed(future_to_host):
                    host = future_to_host[future]
                    try:
                        device_serial = future.result()
                        if device_serial and device_serial not in found_serials:
                            log_success(f"Found device {device_serial} on {host}")
                            found_devices.append((device_serial, host))
                            found_serials.add(device_serial)
                            
                            if stop_on_first:
                                # Cancel remaining futures
                                for remaining in future_to_host:
                                    if not remaining.done():
                                        remaining.cancel()
                                break
                        elif device_serial:
                            log_normal(f"Device {device_serial} already found, skipping")
                            
                    except Exception as e:
                        log_error(f"Error processing result for {host}: {e}")
            
            return found_devices
            
        except Exception as e:
            log_error(f"Error during port scan: {e}")
            return []
    
    def scan_all(self, stop_on_first: bool = False) -> List[Tuple[str, str]]:
        """Scan all emulator ports (loopback + LAN IPs for 0.0.0.0-bound ones)."""
        targets = self._scan_targets()
        log_info(f"Scanning {len(targets)} ports for all emulators...")
        log_info("Supported: MuMu, LDPlayer, BlueStacks, Nox, MEmu")

        return self.scan_ports(targets, stop_on_first=stop_on_first)
    
    def scan_emulator(self, emulator_type: str) -> List[Tuple[str, str]]:
        """Scan specific emulator type"""
        if emulator_type not in EMULATOR_PORT_RANGES:
            log_error(f"Unsupported emulator type: {emulator_type}")
            log_info(f"Supported types: {', '.join(EMULATOR_PORT_RANGES.keys())}")
            return []
        
        ports = EMULATOR_PORT_RANGES[emulator_type]
        log_info(f"Scanning {len(ports)} ports for {emulator_type}...")
        
        return self.scan_ports(ports)
    
    def ensure_adb_server_running(self) -> bool:
        """Ensure ADB server is running"""
        try:
            result = subprocess.run(
                [self.adb_path, "devices"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[1:]  # Skip header
                devices = [
                    line for line in lines
                    if line.strip() and "List of devices" not in line
                ]
                # Only surface to the log when the picture actually changes;
                # routine re-checks during polling go to debug instead of spamming.
                changed = (self._last_server_ok is not True
                           or len(devices) != self._last_device_count)
                if changed:
                    log_success("ADB server is running")
                    if devices:
                        log_info(f"Connected devices: {len(devices)}")
                        for device in devices:
                            log_info(f"  - {device}")
                    else:
                        log_info("No devices connected yet")
                else:
                    log_debug("ADB server still running "
                              f"({len(devices)} device(s))")
                self._last_server_ok = True
                self._last_device_count = len(devices)
                return True
            else:
                if self._last_server_ok is not False:
                    log_error(f"ADB server error: {result.stderr}")
                self._last_server_ok = False
                self._last_device_count = -1
                return False
                
        except subprocess.TimeoutExpired:
            log_error("Timeout checking ADB server")
            return False
        except Exception as e:
            log_error(f"Error checking ADB server: {e}")
            return False
    
    def restart_adb_server(self) -> bool:
        """Restart ADB server"""
        try:
            log_info("Restarting ADB server...")
            try:
                subprocess.run([self.adb_path, "kill-server"], capture_output=True, timeout=5)
            except subprocess.TimeoutExpired:
                log_warning("kill-server timed out, continuing anyway")
            time.sleep(1)
            return self.ensure_adb_server_running()
        except Exception as e:
            log_error(f"Failed to restart ADB server: {e}")
            return False
