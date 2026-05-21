"""
Core automation module.
"""

from .windows_auto import WindowsGameAutomation
from .adb.auto import ADBGameAutomation

__all__ = ['WindowsGameAutomation', 'ADBGameAutomation']
