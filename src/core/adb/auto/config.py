"""
Configuration dataclass for ADB automation
"""
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration for ADB automation"""
    
    # Screen capture settings
    capture_interval: float = 0.1
    
    # Template matching settings
    default_threshold: float = 0.8
    template_cache_size: int = 100
    
    # Retry settings
    max_retry_attempts: int = 3
    retry_delay: float = 0.5
    
    # Debug settings
    debug_mode: bool = False
    debug_fail_mode: bool = True
    
    # Feature flags
    auto_orientation_detection: bool = True
    
    # Template matching scales
    portrait_scales: tuple = (1.0, 1.1, 1.2, 1.3, 1.4, 1.5)
    landscape_scales: tuple = (1.0,)
    portrait_threshold_adjustment: float = 0.1
    min_threshold: float = 0.6
