"""
ADB Core Module

Provides ADB connection management and device control functionality.
"""

from .constants import (
    KEYCODE_HOME,
    KEYCODE_BACK, 
    KEYCODE_MENU,
    KEYCODE_VOLUME_UP,
    KEYCODE_VOLUME_DOWN,
    KEYCODE_POWER,
    KEYCODE_ENTER,
    EMULATOR_PORT_RANGES,
)
from .cache import DeviceCache
from .scanner import DeviceScanner, kill_adb_server
from .controller import ADBController

__all__ = [
    'ADBController',
    'DeviceCache',
    'DeviceScanner',
    'kill_adb_server',
    'KEYCODE_HOME',
    'KEYCODE_BACK',
    'KEYCODE_MENU',
    'KEYCODE_VOLUME_UP',
    'KEYCODE_VOLUME_DOWN',
    'KEYCODE_POWER',
    'KEYCODE_ENTER',
    'EMULATOR_PORT_RANGES',
]
