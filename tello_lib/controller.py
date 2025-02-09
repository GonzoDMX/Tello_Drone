import socket
import threading
import time
import logging
import numpy as np
from typing import Optional, Tuple
from .models import DroneState, DroneStatus, CommandPriority
from .command_handler import CommandHandler
from .video import VideoStream
from .exceptions import DroneConnectionError, CommandError, VideoStreamError

logger = logging.getLogger(__name__)

class TelloController:
    def __init__(self):
        self._status = DroneStatus()
        self._command_handler = CommandHandler()
        self._video = VideoStream()
        
        # Status socket
        self._status_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._status_socket.bind(('', 8890))
        
        # Status monitoring
        self._running = False
        self._status_thread = threading.Thread(target=self._status_loop)
        self._status_thread.daemon = True

    def connect(self) -> bool:
        """
        Initialize connection to the drone
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            logger.info("Starting command handler...")
            # Start command handler
            self._command_handler.start()
            
            # Give time for handler to initialize
            time.sleep(0.5)
            
            logger.info("Sending initial command to enter SDK mode...")
            # Enter SDK mode
            response = self._command_handler.send_command(
                "command",
                priority=CommandPriority.HIGH,
                expected_response="ok",
                timeout=10.0,
                retries=5
            )

            if not response:
                raise DroneConnectionError("Failed to enter SDK mode")
            
            logger.info("Successfully entered SDK mode")
            
            # Start status monitoring
            self._running = True
            self._status_thread.start()
            
            self._status.state = DroneState.CONNECTED
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to drone: {e}")
            self._status.state = DroneState.ERROR
            return False

    def _parse_height(self, height_str: str) -> int:
        """Parse height response from drone"""
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
        """Check if drone is flying based on height"""
        return self._parse_height(height_str) > 10  # Consider > 10cm as flying

    def _status_loop(self):
        """Status monitoring loop"""
        self._status_socket.settimeout(1.0)
        while self._running:
            try:
                data, _ = self._status_socket.recvfrom(1024)
                raw_status = data.decode('utf-8').strip()
                logger.info(f"Status Message: {raw_status}")
                status_data = raw_status.split(';')
                
                for item in status_data:
                    if ":" not in item:
                        continue
                    key, value = item.split(':')
                    key = key.strip()
                    value = value.strip()
                    
                    try:
                        if key == "bat":
                            self._status.battery = int(value)
                        elif key == "h":
                            self._status.height = self._parse_height(value)
                        elif key == "time":
                            self._status.flight_time = int(value)
                    except ValueError:
                        continue
                        
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Status update failed: {e}")

    def start_video_stream(self, timeout: int = 15) -> bool:
        """Start video stream"""
        try:
            # Send streamon command
            response = self._command_handler.send_command(
                "streamon",
                priority=CommandPriority.NORMAL,
                expected_response="ok",
                timeout=5.0
            )
            
            if not response:
                return False
            
            # Start and wait for video stream
            return self._video.start(timeout=timeout)
            
        except Exception as e:
            logger.error(f"Failed to start video stream: {e}")
            return False

    def stop_video_stream(self) -> bool:
        """Stop video stream"""
        try:
            self._video.stop()
            response = self._command_handler.send_command(
                "streamoff",
                priority=CommandPriority.NORMAL,
                expected_response="ok",
                timeout=5.0
            )
            return response is not None
        except Exception as e:
            logger.error(f"Failed to stop video stream: {e}")
            return False

    def takeoff(self) -> bool:
        """Take off the drone"""
        try:
            if self._status.state != DroneState.CONNECTED:
                raise CommandError("Drone must be connected before takeoff")
            
            response = self._command_handler.send_command(
                "takeoff",
                priority=CommandPriority.HIGH,
                expected_response="ok",
                timeout=10.0
            )
            
            if response:
                # Verify takeoff
                time.sleep(2)
                height_response = self._command_handler.send_command(
                    "height?",
                    priority=CommandPriority.LOW,
                    timeout=2.0
                )
                
                if height_response and self._is_flying(height_response):
                    self._status.state = DroneState.FLYING
                    logger.info("Takeoff confirmed - drone is airborne")
                    return True
                else:
                    # If height check fails but initial response was ok,
                    # assume takeoff was successful
                    self._status.state = DroneState.FLYING
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Takeoff failed: {e}")
            # Check if drone is actually flying despite the error
            try:
                height_response = self._command_handler.send_command(
                    "height?",
                    priority=CommandPriority.LOW,
                    timeout=2.0
                )
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
            # Land command is sent with emergency priority
            response = self._command_handler.send_command(
                "land",
                priority=CommandPriority.EMERGENCY,
                expected_response="ok",
                timeout=10.0
            )
            
            if response:
                self._status.state = DroneState.LANDED
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
            response = self._command_handler.send_command(
                f"{direction} {distance}",
                priority=CommandPriority.NORMAL,
                expected_response="ok"
            )
            return response is not None
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
            response = self._command_handler.send_command(
                f"{direction} {degrees}",
                priority=CommandPriority.NORMAL,
                expected_response="ok"
            )
            return response is not None
        except Exception as e:
            logger.error(f"Rotation command failed: {e}")
            return False

    def set_speed(self, speed: int) -> bool:
        """Set drone speed"""
        if not 1 <= speed <= 100:
            raise ValueError("Speed must be between 1 and 100 cm/s")
        
        try:
            response = self._command_handler.send_command(
                f"speed {speed}",
                priority=CommandPriority.NORMAL,
                expected_response="ok"
            )
            if response:
                self._status.speed = speed
                return True
            return False
        except Exception as e:
            logger.error(f"Speed command failed: {e}")
            return False

    def get_battery(self) -> int:
        """Get battery percentage"""
        try:
            response = self._command_handler.send_command(
                "battery?",
                priority=CommandPriority.LOW
            )
            return int(response) if response else self._status.battery
        except:
            return self._status.battery

    def get_height(self) -> int:
        """Get current height in centimeters"""
        try:
            response = self._command_handler.send_command(
                "height?",
                priority=CommandPriority.LOW
            )
            return self._parse_height(response) if response else self._status.height
        except:
            return self._status.height

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
        self._command_handler.stop()
        self._status_socket.close()
