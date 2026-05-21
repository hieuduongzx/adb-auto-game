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
from .scanner import DeviceScanner
from .controller import ADBController

__all__ = [
    'ADBController',
    'DeviceCache',
    'DeviceScanner',
    'KEYCODE_HOME',
    'KEYCODE_BACK',
    'KEYCODE_MENU',
    'KEYCODE_VOLUME_UP',
    'KEYCODE_VOLUME_DOWN',
    'KEYCODE_POWER',
    'KEYCODE_ENTER',
    'EMULATOR_PORT_RANGES',
]
