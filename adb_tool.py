#!/usr/bin/env python3
"""
ADB Utility Tool - Command line interface for ADB operations
Usage: python adb_tool.py [command] [options]
"""

import sys
import os
import argparse
import time
from typing import Optional, List

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.adb import ADBController, DeviceScanner
from src.core.adb.constants import EMULATOR_PORT_RANGES
from src.utils import log_error, log_info, log_success, log_warning, log_normal


def print_header(text: str):
    """Print formatted header"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def cmd_check(args):
    """Check ADB connection status"""
    print_header("ADB Connection Check")
    
    try:
        controller = ADBController(device_id=args.device)
        if controller.device:
            log_success("✓ ADB connection successful")
            log_info(f"Device: {controller.device_id}")
            
            # Get device info
            name = controller.get_device_name()
            app = controller.get_current_app()
            width, height = controller.get_screen_size()
            
            log_info(f"Name: {name}")
            log_info(f"Screen: {width}x{height}")
            if app:
                app_name = controller.get_app_name(app)
                log_info(f"Current App: {app_name} ({app})")
        else:
            log_error("✗ Failed to connect to ADB device")
            return 1
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_scan(args):
    """Scan for emulator devices"""
    print_header("Scanning for Emulator Devices")
    
    scanner = DeviceScanner()
    
    # Check if scanning specific emulator
    if args.emulator:
        if args.emulator not in EMULATOR_PORT_RANGES:
            log_error(f"Unknown emulator type: {args.emulator}")
            log_info(f"Supported: {', '.join(EMULATOR_PORT_RANGES.keys())}")
            return 1
        
        log_info(f"Scanning {args.emulator} emulator ports...")
        found = scanner.scan_emulator(args.emulator)
    else:
        log_info("Scanning all emulator ports...")
        found = scanner.scan_all(stop_on_first=False)
    
    if found:
        log_success(f"\nFound {len(found)} device(s):")
        for serial, host in found:
            print(f"  • {serial} on {host}")
            
            # Optionally fetch current running app
            if args.with_app:
                try:
                    ctrl = ADBController(device_id=serial)
                    if ctrl.device:
                        app = ctrl.get_current_app()
                        if app:
                            app_name = ctrl.get_app_name(app)
                            print(f"      App: {app_name}")
                            print(f"      Package: {app}")
                        else:
                            print("      App: (none / unable to detect)")
                    else:
                        print("      App: (failed to connect)")
                except Exception as e:
                    print(f"      App: (error: {e})")
    else:
        log_warning("No devices found")
        return 1
    
    return 0


def cmd_list(args):
    """List connected ADB devices"""
    print_header("Connected ADB Devices")
    
    try:
        controller = ADBController()
        devices = controller.client.devices()
        
        if not devices:
            log_warning("No devices connected")
            return 1
        
        log_success(f"Found {len(devices)} device(s):\n")
        
        for i, device in enumerate(devices, 1):
            print(f"{i}. Serial: {device.serial}")
            
            # Try to get device name
            try:
                controller.device = device
                controller.device_id = device.serial
                name = controller.get_device_name()
                print(f"   Name: {name}")
            except:
                pass
            
            # Get current app
            try:
                app = controller.get_current_app()
                if app:
                    app_name = controller.get_app_name(app)
                    print(f"   App: {app_name}")
                    print(f"   Package: {app}")
            except:
                pass
            
            print()
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_info(args):
    """Show detailed device info"""
    print_header("Device Information")
    
    try:
        controller = ADBController(device_id=args.device)
        
        if not controller.device:
            log_error("No device connected")
            return 1
        
        # Basic info
        print(f"Device ID: {controller.device_id}")
        print(f"Device Name: {controller.get_device_name()}")
        
        # Screen info
        width, height = controller.get_screen_size()
        print(f"\nScreen Size: {width}x{height}")
        print(f"Orientation: {'Portrait' if width < height else 'Landscape'}")
        
        # Current app
        app = controller.get_current_app()
        if app:
            print(f"\nCurrent App:")
            print(f"  Package: {app}")
            print(f"  Name: {controller.get_app_name(app)}")
        
        # ADB server status
        print(f"\nADB Server:")
        print(f"  Host: {controller.host}")
        print(f"  Port: {controller.port}")
        
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_screenshot(args):
    """Take a screenshot"""
    print_header("Screenshot")
    
    try:
        controller = ADBController(device_id=args.device)
        
        if not controller.device:
            log_error("No device connected")
            return 1
        
        # Generate filename
        if args.output:
            filename = args.output
        else:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
        
        # Capture screen
        data = controller.capture_screen_raw()
        if data:
            with open(filename, 'wb') as f:
                f.write(data)
            log_success(f"✓ Screenshot saved: {filename}")
        else:
            log_error("Failed to capture screenshot")
            return 1
            
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_tap(args):
    """Tap on screen coordinates"""
    try:
        controller = ADBController(device_id=args.device)
        
        if not controller.device:
            log_error("No device connected")
            return 1
        
        x, y = args.x, args.y
        log_info(f"Tapping at ({x}, {y})...")
        
        if controller.tap(x, y):
            log_success("✓ Tap successful")
        else:
            log_error("✗ Tap failed")
            return 1
            
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_swipe(args):
    """Swipe from one point to another"""
    try:
        controller = ADBController(device_id=args.device)
        
        if not controller.device:
            log_error("No device connected")
            return 1
        
        x1, y1, x2, y2 = args.x1, args.y1, args.x2, args.y2
        duration = args.duration
        
        log_info(f"Swiping from ({x1}, {y1}) to ({x2}, {y2}) in {duration}ms...")
        
        if controller.swipe(x1, y1, x2, y2, duration):
            log_success("✓ Swipe successful")
        else:
            log_error("✗ Swipe failed")
            return 1
            
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_shell(args):
    """Execute ADB shell command"""
    try:
        controller = ADBController(device_id=args.device)
        
        if not controller.device:
            log_error("No device connected")
            return 1
        
        command = ' '.join(args.command)
        log_info(f"Executing: {command}")
        
        result = controller.device.shell(command)
        print(result)
        
    except Exception as e:
        log_error(f"Error: {e}")
        return 1
    
    return 0


def cmd_restart(args):
    """Restart ADB server"""
    print_header("Restarting ADB Server")
    
    scanner = DeviceScanner()
    if scanner.restart_adb_server():
        log_success("✓ ADB server restarted successfully")
    else:
        log_error("✗ Failed to restart ADB server")
        return 1
    
    return 0


def show_menu():
    """Hiển thị menu tương tác"""
    print_header("ADB Tool - Menu Chính")
    print("1. Check         - Kiểm tra kết nối ADB")
    print("2. Scan          - Quét thiết bị emulator")
    print("3. List          - Liệt kê thiết bị đã kết nối")
    print("4. Info          - Thông tin chi tiết thiết bị")
    print("5. Screenshot    - Chụp màn hình")
    print("6. Tap           - Chạm vào tọa độ (x y)")
    print("7. Swipe         - Vuốt màn hình (x1 y1 x2 y2)")
    print("8. Shell         - Thực thi lệnh shell")
    print("9. Restart       - Khởi động lại ADB server")
    print("0. Exit          - Thoát chương trình")
    print(f"{'='*60}\n")


def interactive_mode():
    """Chế độ menu tương tác"""
    class MockArgs:
        def __init__(self):
            self.device: str | None = None
            self.emulator: str | None = None
            self.output: str | None = None
            self.x = self.y = 0
            self.x1 = self.y1 = self.x2 = self.y2 = 0
            self.duration = 300
            self.command: list[str] = []
            self.with_app: bool = False
    
    while True:
        show_menu()
        choice = input("Chọn chức năng (0-9): ").strip()
        
        args = MockArgs()
        
        if choice == '0':
            print("Tạm biệt!")
            break
        elif choice == '1':
            args.device = input("Device ID (Enter để bỏ qua): ").strip() or None
            cmd_check(args)
        elif choice == '2':
            emu = input("Emulator (bluestacks/nox/ldplayer/memu/mumu) hoặc Enter để quét tất: ").strip()
            args.emulator = emu if emu else None
            with_app = input("Hiện app đang chạy của mỗi device? (y/N): ").strip().lower()
            args.with_app = with_app == 'y'
            cmd_scan(args)
        elif choice == '3':
            cmd_list(args)
        elif choice == '4':
            args.device = input("Device ID (Enter để bỏ qua): ").strip() or None
            cmd_info(args)
        elif choice == '5':
            args.device = input("Device ID (Enter để bỏ qua): ").strip() or None
            args.output = input("Output filename (Enter để tự động): ").strip() or None
            cmd_screenshot(args)
        elif choice == '6':
            try:
                args.x = int(input("X coordinate: "))
                args.y = int(input("Y coordinate: "))
                args.device = input("Device ID (Enter để bỏ qua): ").strip() or None
                cmd_tap(args)
            except ValueError:
                log_error("Tọa độ phải là số!")
        elif choice == '7':
            try:
                args.x1 = int(input("Start X: "))
                args.y1 = int(input("Start Y: "))
                args.x2 = int(input("End X: "))
                args.y2 = int(input("End Y: "))
                dur = input("Duration ms (Enter=300): ").strip()
                args.duration = int(dur) if dur else 300
                args.device = input("Device ID (Enter để bỏ qua): ").strip() or None
                cmd_swipe(args)
            except ValueError:
                log_error("Tọa độ phải là số!")
        elif choice == '8':
            args.device = input("Device ID (Enter để bỏ qua): ").strip() or None
            cmd = input("Lệnh shell: ").strip()
            if cmd:
                args.command = cmd.split()
                cmd_shell(args)
        elif choice == '9':
            cmd_restart(args)
        else:
            log_error("Lựa chọn không hợp lệ!")
        
        input("\nNhấn Enter để tiếp tục...")


def main():
    parser = argparse.ArgumentParser(
        description='ADB Utility Tool - Command line interface for ADB operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python adb_tool.py -m                  # Chạy chế độ menu tương tác
  python adb_tool.py check              # Check ADB connection
  python adb_tool.py scan               # Scan all emulator ports
  python adb_tool.py scan -e ldplayer   # Scan LDPlayer only
  python adb_tool.py scan --with-app    # Scan and show current app per device
  python adb_tool.py list               # List connected devices
  python adb_tool.py info               # Show device info
  python adb_tool.py screenshot         # Take screenshot
  python adb_tool.py tap 500 1000       # Tap at coordinates
  python adb_tool.py swipe 500 1000 500 500 # Swipe up
  python adb_tool.py shell ls -la       # Run shell command
  python adb_tool.py restart            # Restart ADB server
        '''
    )
    
    parser.add_argument('-m', '--menu', action='store_true',
                       help='Chạy chế độ menu tương tác (interactive mode)')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check ADB connection status')
    check_parser.add_argument('-d', '--device', help='Specific device ID')
    
    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan for emulator devices')
    scan_parser.add_argument('-e', '--emulator', choices=list(EMULATOR_PORT_RANGES.keys()),
                            help='Scan specific emulator type')
    scan_parser.add_argument('--with-app', action='store_true',
                            help='Also show the current running app for each device found')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List connected devices')
    
    # Info command
    info_parser = subparsers.add_parser('info', help='Show detailed device info')
    info_parser.add_argument('-d', '--device', help='Specific device ID')
    
    # Screenshot command
    screenshot_parser = subparsers.add_parser('screenshot', help='Take a screenshot')
    screenshot_parser.add_argument('-d', '--device', help='Specific device ID')
    screenshot_parser.add_argument('-o', '--output', help='Output filename')
    
    # Tap command
    tap_parser = subparsers.add_parser('tap', help='Tap on screen coordinates')
    tap_parser.add_argument('x', type=int, help='X coordinate')
    tap_parser.add_argument('y', type=int, help='Y coordinate')
    tap_parser.add_argument('-d', '--device', help='Specific device ID')
    
    # Swipe command
    swipe_parser = subparsers.add_parser('swipe', help='Swipe gesture')
    swipe_parser.add_argument('x1', type=int, help='Start X coordinate')
    swipe_parser.add_argument('y1', type=int, help='Start Y coordinate')
    swipe_parser.add_argument('x2', type=int, help='End X coordinate')
    swipe_parser.add_argument('y2', type=int, help='End Y coordinate')
    swipe_parser.add_argument('-d', '--device', help='Specific device ID')
    swipe_parser.add_argument('-t', '--duration', type=int, default=300,
                             help='Duration in milliseconds (default: 300)')
    
    # Shell command
    shell_parser = subparsers.add_parser('shell', help='Execute ADB shell command')
    shell_parser.add_argument('-d', '--device', help='Specific device ID')
    shell_parser.add_argument('command', nargs='+', help='Shell command to execute')
    
    # Restart command
    restart_parser = subparsers.add_parser('restart', help='Restart ADB server')
    
    args = parser.parse_args()
    
    # Nếu có command thì chạy command mode
    if args.command:
        # Route to appropriate command
        commands = {
            'check': cmd_check,
            'scan': cmd_scan,
            'list': cmd_list,
            'info': cmd_info,
            'screenshot': cmd_screenshot,
            'tap': cmd_tap,
            'swipe': cmd_swipe,
            'shell': cmd_shell,
            'restart': cmd_restart,
        }
        
        if args.command in commands:
            return commands[args.command](args)
        else:
            log_error(f"Unknown command: {args.command}")
            return 1
    
    # Mặc định chạy menu tương tác
    interactive_mode()
    return 0


if __name__ == '__main__':
    sys.exit(main())
