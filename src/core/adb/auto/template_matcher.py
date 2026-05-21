"""
Template matching functionality
"""
import cv2
import numpy as np
import threading
from typing import Tuple, Optional, List, Dict
from src.utils import log_error, log_info, log_warning


class TemplateMatcher:
    """Handles template loading and matching operations"""
    
    def __init__(self, cache_size: int = 100):
        self._cache: Dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()
        self._max_cache_size = cache_size
    
    def load(self, template_path: str, grayscale: bool = False) -> Optional[np.ndarray]:
        """Load template image with caching"""
        cache_key = f"{template_path}_{grayscale}"
        
        # Check cache first
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key].copy()
        
        # Load from disk
        try:
            if grayscale:
                template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            else:
                template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            
            if template is None:
                log_error(f"Could not load template: {template_path}")
                return None
            
            # Cache it
            with self._cache_lock:
                if len(self._cache) >= self._max_cache_size:
                    # Remove oldest entry (FIFO)
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]
                
                self._cache[cache_key] = template.copy()
            
            return template
            
        except Exception as e:
            log_error(f"Error loading template {template_path}: {e}")
            return None
    
    def clear_cache(self):
        """Clear template cache"""
        with self._cache_lock:
            self._cache.clear()
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        with self._cache_lock:
            return {
                "cache_size": len(self._cache),
                "max_size": self._max_cache_size,
                "templates": list(self._cache.keys()),
            }
    
    def match(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        threshold: float = 0.8,
        use_grayscale: bool = False,
        multi_scale: bool = False,
        scales: Optional[List[float]] = None,
    ) -> Optional[Tuple[int, int, float, float]]:
        """
        Match template in screen
        
        Returns:
            Tuple of (center_x, center_y, confidence, scale) or None
        """
        try:
            # Prepare images
            if use_grayscale and len(screen.shape) == 3:
                screen_processed = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            else:
                screen_processed = screen.copy()
            
            # Ensure consistent data types
            screen_processed = screen_processed.astype(np.uint8)
            template = template.astype(np.uint8)
            
            best_match = None
            best_confidence = 0.0
            best_scale = 1.0
            
            # Determine scales to use
            if multi_scale and scales:
                scale_list = scales
            else:
                scale_list = [1.0]
            
            # Try each scale
            for scale in scale_list:
                # Resize template
                if scale != 1.0:
                    h, w = template.shape[:2]
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    
                    # Skip invalid sizes
                    if new_w > screen_processed.shape[1] or new_h > screen_processed.shape[0]:
                        continue
                    if new_w < 10 or new_h < 10:
                        continue
                    
                    template_scaled = cv2.resize(
                        template, (new_w, new_h), interpolation=cv2.INTER_AREA
                    )
                else:
                    template_scaled = template
                
                # Perform matching
                result = cv2.matchTemplate(
                    screen_processed, template_scaled, cv2.TM_CCOEFF_NORMED
                )
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                
                if max_val > best_confidence:
                    best_confidence = max_val
                    best_match = max_loc
                    best_scale = scale
            
            # Check threshold
            if best_confidence >= threshold:
                # Calculate center point
                h, w = template.shape[:2]
                center_x = int(best_match[0] + (w * best_scale) // 2)
                center_y = int(best_match[1] + (h * best_scale) // 2)
                
                return (center_x, center_y, best_confidence, best_scale)
            
            return None
            
        except Exception as e:
            log_error(f"Error in template matching: {e}")
            return None
    
    def match_all(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        threshold: float = 0.8,
        use_grayscale: bool = False,
    ) -> List[Tuple[int, int, float]]:
        """
        Find all template matches in screen
        
        Returns:
            List of (center_x, center_y, confidence) tuples
        """
        try:
            # Prepare images
            if use_grayscale and len(screen.shape) == 3:
                screen_processed = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            else:
                screen_processed = screen.copy()
            
            screen_processed = screen_processed.astype(np.uint8)
            template = template.astype(np.uint8)
            
            # Perform matching
            result = cv2.matchTemplate(
                screen_processed, template, cv2.TM_CCOEFF_NORMED
            )
            
            # Find all locations above threshold
            locations = np.where(result >= threshold)
            
            # Build candidates list
            candidates = []
            template_h, template_w = template.shape[:2]
            
            for pt in zip(*locations[::-1]):
                x, y = pt
                confidence = result[y, x]
                center_x = x + template_w // 2
                center_y = y + template_h // 2
                candidates.append((center_x, center_y, confidence))
            
            # Sort by confidence
            candidates.sort(key=lambda x: x[2], reverse=True)
            
            # Non-maximum suppression
            min_distance = max(template_w, template_h) * 0.8
            matches = []
            
            for candidate in candidates:
                x, y, confidence = candidate
                
                # Check for duplicates
                is_duplicate = False
                for existing in matches:
                    ex, ey, _ = existing
                    distance = np.sqrt((x - ex) ** 2 + (y - ey) ** 2)
                    if distance < min_distance:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    matches.append(candidate)
            
            # Log results
            if len(matches) > 10:
                log_warning(f"Found {len(matches)} matches - possible false positives")
            else:
                log_info(f"Found {len(matches)} instances")
            
            return matches
            
        except Exception as e:
            log_error(f"Error finding all templates: {e}")
            return []
