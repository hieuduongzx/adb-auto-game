"""
Constants for ADB operations
"""
import os
from typing import Dict, List

# Key codes for ADB input
KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_MENU = 82
KEYCODE_VOLUME_UP = 24
KEYCODE_VOLUME_DOWN = 25
KEYCODE_POWER = 26
KEYCODE_ENTER = 66

# Cache settings
CACHE_EXPIRY_TIME = 60  # Cache expires after 60 seconds

# Default ADB server settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5037

# Emulator port ranges
EMULATOR_PORT_RANGES: Dict[str, List[str]] = {
    "mumu": [f"127.0.0.1:{port}" for port in range(16000, 17001)],  # MuMu Player
    "ldplayer": [f"127.0.0.1:{port}" for port in range(5555, 5580)],  # LDPlayer
    "bluestacks": [f"127.0.0.1:{port}" for port in range(5555, 5565)],  # BlueStacks
    "nox": [f"127.0.0.1:{port}" for port in range(62001, 62100)],  # Nox Player
    "memu": [f"127.0.0.1:{port}" for port in range(21503, 21600)],  # MEmu
    "general": [f"127.0.0.1:{port}" for port in range(5555, 5580)],  # General emulators
}

# All emulator ports combined (deduplicated, order preserved)
_seen: set = set()
ALL_EMULATOR_PORTS = []
for ports in EMULATOR_PORT_RANGES.values():
    for p in ports:
        if p not in _seen:
            _seen.add(p)
            ALL_EMULATOR_PORTS.append(p)
del _seen

# Common app mappings
COMMON_APPS = {
    "com.android.chrome": "Chrome",
    "com.tencent.mm": "WeChat",
    "com.whatsapp": "WhatsApp",
    "com.facebook.katana": "Facebook",
    "com.instagram.android": "Instagram",
    "com.twitter.android": "Twitter",
    "com.netflix.mediaclient": "Netflix",
    "com.spotify.music": "Spotify",
    "com.google.android.youtube": "YouTube",
    "com.google.android.gm": "Gmail",
    "com.android.vending": "Google Play Store",
    "com.android.settings": "Settings",
    "com.android.launcher3": "Launcher",
    "com.android.systemui": "System UI",
    "com.miui.home": "MIUI Launcher",
    "com.huawei.android.launcher": "EMUI Launcher",
    "com.samsung.android.launcher": "Samsung Launcher",
}


def get_adb_path() -> str:
    """Get the path to ADB executable"""
    # this file: <root>/src/core/adb/constants.py -> up 3 levels to root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    return os.path.join(root_dir, "vendor", "adb", "adb.exe")
