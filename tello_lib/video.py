import cv2
import threading
import time
import logging
import numpy as np
from typing import Optional, Callable
from .models import VideoStreamState
from .exceptions import VideoStreamError

logger = logging.getLogger(__name__)

class VideoStream:
    def __init__(self):
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._frame_callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        self._last_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._state = VideoStreamState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._consecutive_valid_frames = 0
        self._frame_validation_threshold = 30
        self._last_frame_time = 0
        self._frame_timeout = 5.0

    def start(self, frame_callback: Optional[Callable] = None, timeout: int = 15) -> bool:
        """
        Start video stream and wait for stable connection
        
        Args:
            frame_callback: Optional callback for frame processing
            timeout: Maximum time to wait for stable stream in seconds
            
        Returns:
            bool: True if stream stabilized, False otherwise
        """
        with self._state_lock:
            if self._state != VideoStreamState.DISCONNECTED:
                return False
            self._state = VideoStreamState.INITIALIZING
        
        self._frame_callback = frame_callback
        self._running = True
        self._consecutive_valid_frames = 0
        self._last_frame_time = time.time()
        
        try:
            self._cap = cv2.VideoCapture("udp://0.0.0.0:11111", cv2.CAP_FFMPEG)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            if not self._cap.isOpened():
                logger.error("Failed to open video capture")
                self.stop()
                return False
            
            self._thread = threading.Thread(target=self._video_loop)
            self._thread.daemon = True
            self._thread.start()
            
            # Wait for stable stream
            start_time = time.time()
            while time.time() - start_time < timeout:
                with self._state_lock:
                    if self._state == VideoStreamState.STREAMING:
                        return True
                    elif self._state == VideoStreamState.ERROR:
                        return False
                time.sleep(0.1)
            
            logger.error("Video stream failed to stabilize within timeout")
            self.stop()
            return False
            
        except Exception as e:
            logger.error(f"Error starting video stream: {e}")
            self.stop()
            return False

    def _video_loop(self):
        """Video capture loop"""
        while self._running and self._cap and self._cap.isOpened():
            try:
                ret, frame = self._cap.read()
                current_time = time.time()
                
                if ret and frame is not None and frame.size > 0:
                    with self._frame_lock:
                        self._last_frame = frame
                        self._last_frame_time = current_time
                    
                    if self._frame_callback:
                        self._frame_callback(frame)
                    
                    with self._state_lock:
                        if self._state == VideoStreamState.INITIALIZING:
                            self._consecutive_valid_frames += 1
                            if self._consecutive_valid_frames >= self._frame_validation_threshold:
                                self._state = VideoStreamState.STREAMING
                                logger.info("Video stream stabilized")
                        elif self._state == VideoStreamState.STREAMING:
                            self._consecutive_valid_frames = min(
                                self._consecutive_valid_frames + 1,
                                self._frame_validation_threshold + 10
                            )
                else:
                    if current_time - self._last_frame_time > self._frame_timeout:
                        logger.warning("Video stream timeout detected")
                        with self._state_lock:
                            self._state = VideoStreamState.ERROR
                        break
                    
                    with self._state_lock:
                        self._consecutive_valid_frames = max(0, self._consecutive_valid_frames - 2)
                        if (self._state == VideoStreamState.STREAMING and 
                            self._consecutive_valid_frames < self._frame_validation_threshold):
                            self._state = VideoStreamState.ERROR
                            logger.warning("Video stream destabilized")
                
                time.sleep(0.001)
                
            except Exception as e:
                logger.error(f"Error in video loop: {e}")
                with self._state_lock:
                    self._state = VideoStreamState.ERROR
                break

        self._running = False
        if self._cap:
            self._cap.release()
        self._cap = None

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest video frame"""
        with self._frame_lock:
            return self._last_frame.copy() if self._last_frame is not None else None

    def get_state(self) -> VideoStreamState:
        """Get current stream state"""
        with self._state_lock:
            return self._state

    def stop(self):
        """Stop video stream"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
        if self._cap:
            self._cap.release()
        self._cap = None
        self._last_frame = None
        with self._state_lock:
            self._state = VideoStreamState.DISCONNECTED
