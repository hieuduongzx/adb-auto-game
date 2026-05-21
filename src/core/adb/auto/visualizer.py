"""
Debug visualization utilities
"""
import cv2
import numpy as np
from typing import Tuple
from src.utils import log_error


class DebugVisualizer:
    """Handles debug visualization for gestures and template matching"""
    
    WINDOW_TEMPLATE = "Template Matching Debug"
    WINDOW_GESTURE = "Gesture Debug"
    
    def __init__(self):
        self.enabled = False
        self.show_failures = False
    
    def enable(self, show_failures: bool = False):
        """Enable debug visualization"""
        self.enabled = True
        self.show_failures = show_failures
    
    def disable(self):
        """Disable debug visualization"""
        self.enabled = False
    
    def show_template_match(
        self,
        screen: np.ndarray,
        match_location: Tuple[int, int],
        template_shape: Tuple[int, int],
        scale: float,
        confidence: float,
        template_name: str,
        is_match: bool = True
    ):
        """Visualize template matching result"""
        if not self.enabled:
            return
        
        if not is_match and not self.show_failures:
            return
        
        try:
            debug_img = screen.copy()
            
            # Calculate rectangle coordinates
            x, y = match_location
            w = int(template_shape[1] * scale)
            h = int(template_shape[0] * scale)
            
            # Color based on match/fail
            color = (0, 255, 0) if is_match else (0, 0, 255)
            
            # Draw rectangle
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), color, 2)
            
            # Add text
            text = f"Conf: {confidence:.3f} Scale: {scale:.2f} {template_name}"
            cv2.putText(
                debug_img, text, (max(0, x - 40), max(20, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2
            )
            
            # Resize and show
            display_img = cv2.resize(debug_img, (0, 0), fx=0.5, fy=0.5)
            cv2.imshow(self.WINDOW_TEMPLATE, display_img)
            cv2.waitKey(1)
            
        except Exception as e:
            log_error(f"Error in template visualization: {e}")
    
    def show_tap(
        self,
        screen: np.ndarray,
        x: int,
        y: int,
        tap_count: int = 1
    ):
        """Visualize tap gesture"""
        if not self.enabled:
            return
        
        try:
            debug_img = screen.copy()
            cv2.circle(debug_img, (x, y), 20, (0, 255, 255), 3)
            cv2.circle(debug_img, (x, y), 6, (0, 255, 0), -1)
            cv2.putText(
                debug_img, f"Tap x{tap_count} @{x},{y}",
                (max(0, x - 80), max(20, y - 25)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
            )
            
            display_img = cv2.resize(debug_img, (0, 0), fx=0.5, fy=0.5)
            cv2.imshow(self.WINDOW_GESTURE, display_img)
            cv2.waitKey(1)
            
        except Exception as e:
            log_error(f"Error in tap visualization: {e}")
    
    def show_swipe(
        self,
        screen: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int
    ):
        """Visualize swipe gesture"""
        if not self.enabled:
            return
        
        try:
            debug_img = screen.copy()
            cv2.arrowedLine(debug_img, (x1, y1), (x2, y2), (255, 0, 0), 3, tipLength=0.15)
            cv2.circle(debug_img, (x1, y1), 8, (0, 255, 255), -1)
            cv2.circle(debug_img, (x2, y2), 8, (0, 165, 255), -1)
            cv2.putText(
                debug_img, f"Swipe {duration}ms",
                (min(x1, x2), max(20, min(y1, y2) - 15)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2
            )
            
            display_img = cv2.resize(debug_img, (0, 0), fx=0.5, fy=0.5)
            cv2.imshow(self.WINDOW_GESTURE, display_img)
            cv2.waitKey(1)
            
        except Exception as e:
            log_error(f"Error in swipe visualization: {e}")
    
    def show_drag(
        self,
        screen: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int
    ):
        """Visualize drag gesture"""
        if not self.enabled:
            return
        
        try:
            debug_img = screen.copy()
            cv2.arrowedLine(debug_img, (x1, y1), (x2, y2), (0, 128, 255), 3, tipLength=0.15)
            cv2.circle(debug_img, (x1, y1), 10, (0, 255, 255), 2)
            cv2.circle(debug_img, (x2, y2), 10, (0, 140, 255), 2)
            cv2.putText(
                debug_img, f"Drag {duration}ms",
                (min(x1, x2), max(20, min(y1, y2) - 15)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 128, 255), 2
            )
            
            display_img = cv2.resize(debug_img, (0, 0), fx=0.5, fy=0.5)
            cv2.imshow(self.WINDOW_GESTURE, display_img)
            cv2.waitKey(1)
            
        except Exception as e:
            log_error(f"Error in drag visualization: {e}")
    
    def close(self):
        """Close all debug windows"""
        try:
            cv2.destroyWindow(self.WINDOW_TEMPLATE)
            cv2.destroyWindow(self.WINDOW_GESTURE)
        except cv2.error:
            # Windows may not exist if visualizer was never enabled
            pass
