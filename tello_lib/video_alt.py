import av
import numpy as np
import threading
import time
import logging
from typing import Optional, Callable
from .models import VideoStreamState
from .exceptions import VideoStreamError

logger = logging.getLogger(__name__)

class VideoStream:
    def __init__(self):
        self._container = None
        self._running = False
        self._frame_callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        self._last_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._state = VideoStreamState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._frame_validation_threshold = 5  # Reduced threshold for faster startup
        self._last_frame_time = 0
        self._frame_timeout = 5.0  # Reduced timeout
        
        # Stream configuration
        self._stream_url = 'udp://0.0.0.0:11111'
        
    def start(self, frame_callback: Optional[Callable] = None, timeout: int = 15) -> bool:
        """Start video stream and wait for stable connection"""
        if self._state != VideoStreamState.DISCONNECTED:
            return False
            
        self._frame_callback = frame_callback
        self._running = True
        self._last_frame_time = time.time()
        
        try:
            # Configure stream options for low latency
            options = {
                'fflags': 'nobuffer',
                'flags': 'low_delay',
                'stimeout': '5000000',  # 5 second timeout
                'max_delay': '100000',   # Reduced max delay
                'buffer_size': '65535'   # Increased buffer size
            }

            # Connect to stream
            self._container = av.open(
                self._stream_url,
                mode='r',
                options=options
            )
            
            # Start video thread
            self._thread = threading.Thread(target=self._video_loop)
            self._thread.daemon = True
            self._thread.start()
            
            # Wait for stable stream
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self._state == VideoStreamState.STREAMING:
                    return True
                elif self._state == VideoStreamState.ERROR:
                    return False
                time.sleep(0.1)
            
            return False
            
        except Exception as e:
            logger.error(f"Error starting video stream: {e}")
            self.stop()
            return False

    def _video_loop(self):
        """Video capture loop"""
        try:
            stream = self._container.streams.video[0]
            stream.thread_type = 'AUTO'  # Let libav choose optimal threading
            
            frames = self._container.decode(stream)
            self._state = VideoStreamState.STREAMING
            
            for frame in frames:
                if not self._running:
                    break
                    
                try:
                    # Convert frame to numpy array
                    numpy_frame = frame.to_ndarray(format='bgr24')
                    
                    # Update frame
                    with self._frame_lock:
                        self._last_frame = numpy_frame
                        self._last_frame_time = time.time()
                    
                    # Call callback if set
                    if self._frame_callback:
                        try:
                            self._frame_callback(numpy_frame)
                        except Exception as e:
                            logger.error(f"Error in frame callback: {e}")
                    
                except Exception as e:
                    logger.warning(f"Frame conversion error: {e}")
                    continue
                
                # Small sleep to prevent CPU overload
                time.sleep(0.001)
                
        except Exception as e:
            logger.error(f"Error in video loop: {e}")
            self._state = VideoStreamState.ERROR
        
        self._running = False
        if self._container:
            self._container.close()
        self._container = None

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest video frame"""
        with self._frame_lock:
            return self._last_frame.copy() if self._last_frame is not None else None

    def stop(self):
        """Stop video stream"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)  # Add timeout to prevent hanging
        if self._container:
            self._container.close()
        self._container = None
        self._last_frame = None
        self._state = VideoStreamState.DISCONNECTED
