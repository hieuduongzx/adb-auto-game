"""
ADB Automation Module

Provides game automation functionality using ADB and template matching.
"""

from .config import Config, PerformanceMetrics
from .template_matcher import TemplateMatcher
from .visualizer import DebugVisualizer
from .automation import ADBGameAutomation

__all__ = [
    'Config',
    'PerformanceMetrics',
    'TemplateMatcher',
    'DebugVisualizer',
    'ADBGameAutomation',
]
