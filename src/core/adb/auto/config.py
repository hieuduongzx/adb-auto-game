"""
Configuration and metrics classes for ADB automation
"""
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class PerformanceMetrics:
    """Track performance metrics for template matching"""
    
    template_matches: int = 0
    template_failures: int = 0
    avg_match_time: float = 0.0
    total_operations: int = 0
    
    def get_success_rate(self) -> float:
        """Calculate success rate percentage"""
        total = self.template_matches + self.template_failures
        if total == 0:
            return 0.0
        return self.template_matches / total
    
    def update_match_time(self, match_time: float):
        """Update average match time with new sample"""
        self.template_matches += 1
        self.avg_match_time = (
            self.avg_match_time * (self.template_matches - 1) + match_time
        ) / self.template_matches
    
    def update_failure(self):
        """Record a template matching failure"""
        self.template_failures += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary"""
        return {
            "template_matches": self.template_matches,
            "template_failures": self.template_failures,
            "success_rate": self.get_success_rate(),
            "avg_match_time": self.avg_match_time,
            "total_operations": self.total_operations,
        }


@dataclass
class Config:
    """Configuration for ADB automation"""
    
    # Screen capture settings
    capture_interval: float = 0.1
    
    # Template matching settings
    default_threshold: float = 0.7
    template_cache_size: int = 100
    
    # Retry settings
    max_retry_attempts: int = 3
    retry_delay: float = 0.5
    
    # Debug settings
    debug_mode: bool = False
    debug_fail_mode: bool = True
    
    # Feature flags
    auto_orientation_detection: bool = True
    performance_tracking: bool = True
    
    # Template matching scales
    portrait_scales: tuple = (1.0, 1.1, 1.2, 1.3, 1.4, 1.5)
    landscape_scales: tuple = (0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25)
    portrait_threshold_adjustment: float = 0.1
    min_threshold: float = 0.6
