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
from src.utils import log_error, log_info, log_success, log_warning, log_normal


class DeviceScanner:
    """Scanner for finding ADB devices on emulator ports"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5037):
        self.host = host
        self.port = port
        self.adb_path = get_adb_path()
    
    def _is_port_open(self, host: str, port: int, timeout: float = 0.3) -> bool:
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
            if not self._is_port_open(host_ip, port, timeout=0.3):
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
            
            # Small delay to ensure connection is established
            time.sleep(0.1)
            
            # Check if devices are available
            client = AdbClient(host=self.host, port=self.port)
            devices = client.devices()
            
            if devices:
                # Return first matching device
                for device in devices:
                    if device.serial == host:
                        return device.serial
                # If no specific match, return first device
                return devices[0].serial
                
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
        
        return None
    
    def scan_ports(
        self,
        ports: List[str],
        max_workers: int = 30,
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
        """Scan all emulator ports"""
        log_info(f"Scanning {len(ALL_EMULATOR_PORTS)} ports for all emulators...")
        log_info("Supported: MuMu, LDPlayer, BlueStacks, Nox, MEmu")
        
        return self.scan_ports(ALL_EMULATOR_PORTS, stop_on_first=stop_on_first)
    
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
                log_success("ADB server is running")
                lines = result.stdout.strip().split("\n")[1:]  # Skip header
                devices = [
                    line for line in lines
                    if line.strip() and "List of devices" not in line
                ]
                if devices:
                    log_info(f"Connected devices: {len(devices)}")
                    for device in devices:
                        log_info(f"  - {device}")
                else:
                    log_info("No devices connected yet")
                return True
            else:
                log_error(f"ADB server error: {result.stderr}")
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
