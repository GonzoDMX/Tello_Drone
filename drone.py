import socket
import threading
import time
import cv2
import numpy as np
from typing import Optional, Tuple, Callable
from enum import Enum
from dataclasses import dataclass
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DroneState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    FLYING = "flying"
    LANDED = "landed"
    ERROR = "error"

@dataclass
class DroneStatus:
    battery: int = 0
    speed: int = 0
    flight_time: int = 0
    state: DroneState = DroneState.DISCONNECTED

class CommandError(Exception):
    """Raised when a drone command fails"""
    pass

class VideoStreamState(Enum):
    DISCONNECTED = "disconnected"
    INITIALIZING = "initializing"
    STREAMING = "streaming"
    ERROR = "error"

class VideoStream:
    def __init__(self):
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._frame_callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        self._last_frame = None
        self._frame_lock = threading.Lock()
        self._state = VideoStreamState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._consecutive_valid_frames = 0
        self._frame_validation_threshold = 30  # Number of consecutive valid frames needed

    def start(self, frame_callback: Optional[Callable] = None, timeout: int = 10) -> bool:
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
            
            # Timeout reached without stable stream
            logger.error("Video stream failed to stabilize within timeout")
            self.stop()
            return False
            
        except Exception as e:
            logger.error(f"Error starting video stream: {e}")
            self.stop()
            return False

    def _video_loop(self):
        """Video capture loop with frame validation"""
        while self._running and self._cap and self._cap.isOpened():
            try:
                ret, frame = self._cap.read()
                if ret and frame is not None and frame.size > 0:
                    # Valid frame received
                    with self._frame_lock:
                        self._last_frame = frame
                    if self._frame_callback:
                        self._frame_callback(frame)
                    
                    # Update stream state based on frame validation
                    with self._state_lock:
                        if self._state == VideoStreamState.INITIALIZING:
                            self._consecutive_valid_frames += 1
                            if self._consecutive_valid_frames >= self._frame_validation_threshold:
                                self._state = VideoStreamState.STREAMING
                                logger.info("Video stream stabilized")
                        elif self._state == VideoStreamState.STREAMING:
                            self._consecutive_valid_frames = min(self._consecutive_valid_frames + 1, 
                                                               self._frame_validation_threshold + 10)
                else:
                    # Invalid frame received
                    with self._state_lock:
                        self._consecutive_valid_frames = max(0, self._consecutive_valid_frames - 2)
                        if (self._state == VideoStreamState.STREAMING and 
                            self._consecutive_valid_frames < self._frame_validation_threshold):
                            self._state = VideoStreamState.ERROR
                            logger.warning("Video stream destabilized")
            except Exception as e:
                logger.error(f"Error in video loop: {e}")
                with self._state_lock:
                    self._state = VideoStreamState.ERROR

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame"""
        with self._frame_lock:
            return self._last_frame.copy() if self._last_frame is not None else None

    def stop(self):
        """Stop video stream"""
        self._running = False
        if self._thread:
            self._thread.join()
        if self._cap:
            self._cap.release()
        self._cap = None
        self._last_frame = None

class TelloController:
    def __init__(self):
        # Command socket
        self._cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_socket.bind(('', 8889))
        self._cmd_socket.settimeout(2.0)
        self._tello_addr = ('192.168.10.1', 8889)
        
        # Status socket
        self._status_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._status_socket.bind(('', 8890))
        
        # Internal state
        self._status = DroneStatus()
        self._video = VideoStream()
        self._command_lock = threading.Lock()
        self._running = False
        
        # Initialize threads
        self._status_thread = threading.Thread(target=self._status_loop)
        self._status_thread.daemon = True

    def _parse_height(self, height_str: str) -> int:
        """
        Parse height response from drone
        
        Args:
            height_str: Height string from drone (e.g. '8dm')
            
        Returns:
            int: Height in centimeters
        """
        try:
            # Remove any non-digit characters except decimal point
            num = ''.join(c for c in height_str if c.isdigit() or c == '.')
            if 'dm' in height_str:
                # Convert decimeters to centimeters
                return int(float(num) * 10)
            return int(float(num))
        except Exception as e:
            logger.error(f"Failed to parse height: {height_str} - {e}")
            return 0

    def _is_flying(self, height_str: str) -> bool:
        """
        Check if drone is flying based on height
        
        Args:
            height_str: Height string from drone
            
        Returns:
            bool: True if drone appears to be flying
        """
        return self._parse_height(height_str) > 10  # Consider > 10cm as flying

    def connect(self) -> bool:
        """Initialize connection to the drone"""
        try:
            # Enter SDK mode
            response = self._send_command("command")
            if response != "ok":
                raise CommandError("Failed to enter SDK mode")
            
            # Start status thread
            self._running = True
            self._status_thread.start()
            
            self._status.state = DroneState.CONNECTED
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to drone: {e}")
            self._status.state = DroneState.ERROR
            return False

    def _send_command(self, command: str, timeout: float = 7.0, retries: int = 3) -> str:
        """
        Send command to drone and wait for response with retries
        
        Args:
            command: Command string to send
            timeout: Timeout for response in seconds
            retries: Number of retry attempts
            
        Returns:
            str: Response from drone
            
        Raises:
            CommandError: If command fails after all retries
        """
        with self._command_lock:
            last_error = None
            for attempt in range(retries):
                try:
                    logger.debug(f"Sending command: {command} (attempt {attempt + 1}/{retries})")
                    self._cmd_socket.sendto(command.encode('utf-8'), self._tello_addr)
                    response, _ = self._cmd_socket.recvfrom(3000)
                    response_str = response.decode('utf-8').strip()
                    logger.debug(f"Received response: {response_str}")
                    return response_str
                except socket.timeout:
                    last_error = f"Command timed out: {command}"
                    logger.warning(f"Command timeout (attempt {attempt + 1}/{retries})")
                    # If this is a critical command, verify drone state
                    if command in ["takeoff", "land"]:
                        # Give the drone a moment to process
                        time.sleep(1)
                        try:
                            # Check if the drone is flying
                            self._cmd_socket.sendto("speed?".encode('utf-8'), self._tello_addr)
                            _, _ = self._cmd_socket.recvfrom(3000)
                            # If we get a response, the drone is responsive
                            if command == "takeoff":
                                self._status.state = DroneState.FLYING
                                return "ok"
                        except:
                            pass
                except Exception as e:
                    last_error = f"Command failed: {command} - {str(e)}"
                    logger.warning(f"Command error (attempt {attempt + 1}/{retries}): {e}")
                
                # Wait before retry
                if attempt < retries - 1:
                    time.sleep(1)
            
            raise CommandError(last_error)

    def _status_loop(self):
        """Status monitoring loop"""
        while self._running:
            try:
                data, _ = self._status_socket.recvfrom(1024)
                status_data = data.decode('utf-8').strip().split(';')
                
                # Update status object (implement parsing logic)
                # This is a simplified version
                for item in status_data:
                    if "bat:" in item:
                        self._status.battery = int(item.split(':')[1])
                    elif "time" in item:
                        self._status.flight_time = int(item.split(':')[1])
            except Exception as e:
                logger.error(f"Status update failed: {e}")

    def start_video_stream(self, timeout: int = 10) -> bool:
        """
        Start the video stream and wait for it to stabilize
        
        Args:
            timeout: Maximum time to wait for stable stream in seconds
            
        Returns:
            bool: True if stream started and stabilized, False otherwise
        """
        try:
            if self._status.state == DroneState.ERROR:
                return False
                
            # Send streamon command
            response = self._send_command("streamon")
            if response != "ok":
                logger.error("Failed to send streamon command")
                return False
                
            # Start and wait for video stream to stabilize
            return self._video.start(timeout=timeout)
            
        except Exception as e:
            logger.error(f"Failed to start video stream: {e}")
            return False
            
    def stop_video_stream(self) -> bool:
        """Stop the video stream"""
        try:
            self._video.stop()
            response = self._send_command("streamoff")
            return response == "ok"
        except Exception as e:
            logger.error(f"Failed to stop video stream: {e}")
            return False
            
    def takeoff(self) -> bool:
        """
        Take off the drone with state verification
        
        Returns:
            bool: True if takeoff successful, False otherwise
        """
        try:
            if self._status.state != DroneState.CONNECTED:
                raise CommandError("Drone must be connected before takeoff")
            
            # Send takeoff command with longer timeout
            response = self._send_command("takeoff", timeout=10.0)
            
            if response == "ok":
                # Verify takeoff was successful
                time.sleep(2)  # Give drone time to get airborne
                try:
                    # Check if drone is responsive and flying
                    height_response = self._send_command("height?", timeout=2.0)
                    if height_response and self._is_flying(height_response):
                        self._status.state = DroneState.FLYING
                        logger.info("Takeoff confirmed - drone is airborne")
                        return True
                except Exception as e:
                    logger.warning(f"Could not verify takeoff height: {e}")
                    # If height check fails but earlier response was ok,
                    # assume takeoff was successful
                    self._status.state = DroneState.FLYING
                    return True
            
            logger.error("Takeoff command failed")
            return False
            
        except Exception as e:
            logger.error(f"Takeoff failed: {e}")
            # Check if drone is actually flying despite the error
            try:
                height_response = self._send_command("height?", timeout=2.0)
                if height_response and self._is_flying(height_response):
                    logger.warning("Drone appears to be flying despite takeoff command error")
                    self._status.state = DroneState.FLYING
                    return True
            except:
                pass
            return False

    def land(self) -> bool:
        """Land the drone"""
        try:
            if self._status.state != DroneState.FLYING:
                raise CommandError("Drone must be flying to land")
            
            response = self._send_command("land")
            if response == "ok":
                self._status.state = DroneState.LANDED
                # Stop video stream after landing
                self._send_command("streamoff")
                self._video.stop()
                return True
            return False
        except Exception as e:
            logger.error(f"Landing failed: {e}")
            return False

    def move(self, direction: str, distance: int) -> bool:
        """Move the drone in a direction"""
        if direction not in ['up', 'down', 'left', 'right', 'forward', 'back']:
            raise ValueError("Invalid direction")
        if not 20 <= distance <= 500:
            raise ValueError("Distance must be between 20 and 500 cm")
        
        try:
            response = self._send_command(f"{direction} {distance}")
            return response == "ok"
        except Exception as e:
            logger.error(f"Move command failed: {e}")
            return False

    def rotate(self, direction: str, degrees: int) -> bool:
        """Rotate the drone"""
        if direction not in ['cw', 'ccw']:
            raise ValueError("Invalid rotation direction")
        if not 1 <= degrees <= 360:
            raise ValueError("Degrees must be between 1 and 360")
        
        try:
            response = self._send_command(f"{direction} {degrees}")
            return response == "ok"
        except Exception as e:
            logger.error(f"Rotation command failed: {e}")
            return False

    def set_speed(self, speed: int) -> bool:
        """Set drone speed"""
        if not 1 <= speed <= 100:
            raise ValueError("Speed must be between 1 and 100 cm/s")
        
        try:
            response = self._send_command(f"speed {speed}")
            if response == "ok":
                self._status.speed = speed
                return True
            return False
        except Exception as e:
            logger.error(f"Speed command failed: {e}")
            return False

    def get_battery(self) -> int:
        """Get battery percentage"""
        try:
            response = self._send_command("battery?")
            return int(response)
        except Exception:
            return self._status.battery

    def get_status(self) -> DroneStatus:
        """Get current drone status"""
        return self._status

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest video frame"""
        return self._video.get_frame()

    def cleanup(self):
        """Clean up resources"""
        self._running = False
        if self._status_thread.is_alive():
            self._status_thread.join()
        self._video.stop()
        self._cmd_socket.close()
        self._status_socket.close()
