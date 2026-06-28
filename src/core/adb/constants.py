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

# Emulator ADB port ranges.
#
# We probe the *actual* per-instance ADB ports each emulator publishes rather
# than blindly sweeping a 1000-port range (which is slow and, under heavy
# parallel probing, can intermittently time out a real port). Sources:
#   • MuMu Player 12 — first instance 16384, each extra instance +32
#     (16384/16416/16448…). NB: MuMu 12 also answers on 7555, but that is the
#     *same* device as 16384, so probing it would just list MuMu twice — skip it.
#     https://www.mumuplayer.com/help/win/connect-adb.html
#   • LDPlayer 9 — first instance 5555, each extra instance +2
#     (5555/5557/5559…); also auto-registers as emulator-5554/5556/…
#     https://docs.maa.plus/en-us/manual/connection.html
EMULATOR_PORT_RANGES: Dict[str, List[str]] = {
    # MuMu 12: 16384 + 32*n (32 instances).
    "mumu": [f"127.0.0.1:{16384 + 32 * n}" for n in range(32)],
    # LDPlayer: 5555 + 2*n (32 instances).
    "ldplayer": [f"127.0.0.1:{5555 + 2 * n}" for n in range(32)],
    "bluestacks": [f"127.0.0.1:{port}" for port in range(5555, 5565)],  # BlueStacks
    "nox": [f"127.0.0.1:{port}" for port in range(62001, 62100)],  # Nox Player
    "memu": [f"127.0.0.1:{port}" for port in range(21503, 21600)],  # MEmu
    "general": [f"127.0.0.1:{port}" for port in range(5555, 5585)],  # General / misc
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
    # ``app_dir()`` is the project root from source and the folder next to the
    # .exe in a frozen build (where ``vendor/`` is shipped alongside).
    from src.utils import app_dir
    return os.path.join(app_dir(), "vendor", "adb", "adb.exe")
