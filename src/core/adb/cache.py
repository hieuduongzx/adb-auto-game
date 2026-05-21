"""
Device info caching system
"""
import time
import threading
from typing import Any, Callable, Optional


class DeviceCache:
    """Thread-safe cache for device information"""
    
    def __init__(self, expiry_time: int = 60):
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._expiry_time = expiry_time
    
    def get(self, device_id: str, cache_key: str, fetch_func: Callable[[], Any]) -> Any:
        """Get cached value or fetch new one if expired.
        Note: ``None`` results are not cached, so transient detection failures
        do not stick around for the full expiry window.
        """
        with self._lock:
            if device_id not in self._cache:
                self._cache[device_id] = {}
            
            cache_entry = self._cache[device_id].get(cache_key)
            if cache_entry and time.time() - cache_entry["timestamp"] < self._expiry_time:
                return cache_entry["value"]
        
        # Fetch new value outside lock
        value = fetch_func()
        
        # Cache it (skip caching for None to allow retries)
        if value is not None:
            with self._lock:
                if device_id not in self._cache:
                    self._cache[device_id] = {}
                self._cache[device_id][cache_key] = {
                    "value": value,
                    "timestamp": time.time(),
                }
        
        return value
    
    def clear(self, device_id: Optional[str] = None):
        """Clear cache for a specific device or all devices"""
        with self._lock:
            if device_id:
                if device_id in self._cache:
                    del self._cache[device_id]
            else:
                self._cache.clear()
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        with self._lock:
            return {
                "total_devices": len(self._cache),
                "keys_per_device": {k: len(v) for k, v in self._cache.items()},
            }


# Global cache instance
_global_cache = DeviceCache()


def get_cache() -> DeviceCache:
    """Get the global cache instance"""
    return _global_cache
