import socket
import threading
import time
import logging
import numpy as np
from typing import Optional, Tuple
from .models import DroneState, DroneStatus, CommandPriority
from .command_handler import CommandHandler
from .video import VideoStream
from .exceptions import (
    DroneConnectionError,
    CommandError,
    VideoStreamError,
    TakeoffError,
    LandingError,
    MovementError,
    RotationError,
    SpeedCommandError
)

logger = logging.getLogger(__name__)


class TelloController:
    # Define the status update mapping at class level
    STATUS_UPDATES = [
        (0, lambda status, v: setattr(status, 'pitch', int(v))),
        (1, lambda status, v: setattr(status, 'roll', int(v))),
        (2, lambda status, v: setattr(status, 'yaw', int(v))),
        (3, lambda status, v: setattr(status.velocity, 'x', float(v))),
        (4, lambda status, v: setattr(status.velocity, 'y', float(v))),
        (5, lambda status, v: setattr(status.velocity, 'z', float(v))),
        (6, lambda status, v: setattr(status.temperature, 'low', int(v))),
        (7, lambda status, v: setattr(status.temperature, 'high', int(v))),
        (8, lambda status, v: setattr(status, 'time_of_flight', int(v))),
        (9, lambda status, v: setattr(status, 'altitude', int(v))),
        (10, lambda status, v: setattr(status, 'battery', int(v))),
        (11, lambda status, v: setattr(status, 'barometric_pressure', float(v))),
        (12, lambda status, v: setattr(status, 'time', int(v))),
        (13, lambda status, v: setattr(status.acceleration, 'x', float(v))),
        (14, lambda status, v: setattr(status.acceleration, 'y', float(v))),
        (15, lambda status, v: setattr(status.acceleration, 'z', float(v)))
    ]

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
        self.MIN_ALTITUDE = 10

    def connect(self) -> bool:
        """Initialize connection to the drone"""
        try:
            logger.info("Starting command handler...")
            # Start command handler and wait for threads to initialize
            self._command_handler.start()

            logger.info("Sending initial command to enter SDK mode...")
            # Enter SDK mode
            response = self._command_handler.send_command(
                "command",
                priority=CommandPriority.HIGH
            )

            if response == "ok":
                logger.info("Successfully entered SDK mode")

                # Start status monitoring
                self._running = True
                self._status_thread.start()

                self._status.state = DroneState.CONNECTED
                return True
            else:
                raise DroneConnectionError(f"Unexpected response during connection: {response}")

        except DroneConnectionError as e:
            logger.error(f"Failed to connect to drone: {e}")
            self._status.state = DroneState.ERROR
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            self._status.state = DroneState.ERROR
            return False

    def disconnect(self) -> bool:
        """Disconnect from the drone and cleanup resources"""
        try:
            # Stop status monitoring
            self._running = False
            if self._status_thread.is_alive():
                self._status_thread.join()

            # Cleanup resources
            self._video.stop()
            self._command_handler.stop()
            self._status_socket.close()

            self._status.state = DroneState.DISCONNECTED
            return True
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
            return False

    def _parse_speed(self, speed_str: str) -> int:
        """Parse speed response from drone"""
        try:
            # Remove any non-digit characters except decimal point
            num = ''.join(c for c in speed_str if c.isdigit() or c == '.')
            return int(float(num))
        except Exception as e:
            logger.error(f"Failed to parse speed: {speed_str} - {e}")
            return 0

    def _status_loop(self):
        """Status monitoring loop"""
        self._status_socket.settimeout(1.0)

        while self._running:
            try:
                data, _ = self._status_socket.recvfrom(1024)
                raw_status = data.decode('utf-8').strip()
                logger.debug(f"Status Message: {raw_status}")
                
                values = [item.split(':')[1] for item in raw_status.split(';') if ':' in item]
                
                # Use self.STATUS_UPDATES or DroneController.STATUS_UPDATES
                for idx, update_func in self.STATUS_UPDATES:
                    try:
                        if idx < len(values):
                            update_func(self._status, values[idx])
                    except ValueError:
                        continue
                
                # self.log_status()
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Status update failed: {e}")

    def log_status(self):
        """Log all drone status values for debugging"""
        logger.info(
            f"Drone[BAT:{self._status.battery}% "
            f"POS(p:{self._status.pitch}° r:{self._status.roll}° y:{self._status.yaw}°) "
            #f"VEL({self._status.velocity.x:.1f},{self._status.velocity.y:.1f},{self._status.velocity.z:.1f}) "
            #f"ACC({self._status.acceleration.x:.1f},{self._status.acceleration.y:.1f},{self._status.acceleration.z:.1f}) "
            f"ALT:{self._status.altitude}cm TOF:{self._status.time_of_flight}cm "
            f"TEMP({self._status.temperature.low}°C,{self._status.temperature.high}°C) "
            #f"BARO:{self._status.barometric_pressure:.1f}hPa "
            f"TIME:{self._status.time} STATE:{self._status.state.name}]"
        )

    def start_video_stream(self, timeout: int = 15) -> bool:
        """Start video stream"""
        try:
            response = self._command_handler.send_command(
                "streamon",
                priority=CommandPriority.NORMAL
            )

            if response == "ok":
                logger.info("Video streamon command accepted")
                # Start and wait for video stream
                return self._video.start(timeout=timeout)
            else:
                raise VideoStreamError(f"Unexpected response to video streamon command: {response}")

        except VideoStreamError as e:
            logger.error(f"Video stream error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start video stream: {e}")
            return False

    def stop_video_stream(self) -> bool:
        """Stop video stream"""
        try:
            self._video.stop()
            response = self._command_handler.send_command(
                "streamoff",
                priority=CommandPriority.NORMAL
            )

            if response == "ok":
                logger.info("Video streamoff command accepted")
                return True
            else:
                raise VideoStreamError(f"Unexpected response to video streamoff command: {response}")
                
        except VideoStreamError as e:
            logger.error(f"Video stream error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start video stream: {e}")
            return False

    def takeoff(self) -> bool:
        """Take off the drone"""
        try:
            if self._status.state != DroneState.CONNECTED:
                raise CommandError("Drone must be connected before takeoff")
            
            response = self._command_handler.send_command(
                "takeoff",
                priority=CommandPriority.HIGH
            )
            
            if response is None:
                raise TakeoffError("No response received for takeoff command")
                
            if response == "ok" or "error No valid imu" in response:
                # Verify takeoff
                time.sleep(2)
                if self.get_height() > self.MIN_ALTITUDE:
                    self._status.state = DroneState.FLYING
                    if "error No valid imu" in response:
                        self._status.state = DroneState.FLYING_UNSTABLE
                    logger.info("Takeoff confirmed - drone is airborne")
                    return True
                else:
                    raise TakeoffError(f"Failed to gain altitude")
            else:
                raise TakeoffError(f"Unexpected response to takeoff: {response}")
            return False
                
        except TakeoffError as e:
            logger.error(f"Takeoff error: {e}")
            # Check if drone is actually flying despite the error
            if self.get_height() > self.MIN_ALTITUDE:
                logger.warning("Drone appears to be flying despite takeoff command error")
                self._status.state = DroneState.FLYING
                return True
            return False


    def land(self) -> bool:
        """Land the drone"""
        try:
            response = self._command_handler.send_command(
                "land",
                priority=CommandPriority.EMERGENCY
            )

            if response is None:
                raise LandingError("No response received for land command")

            if response == "ok":
                # Verify landing
                time.sleep(3)
                if self.get_height() <= self.MIN_ALTITUDE:
                    self._status.state = DroneState.LANDED
                    logger.info("Landing confirmed - drone is on ground")
                    return True
            elif "error No valid imu" in response:
                raise LandingError("Drone reporting unstable conditions during landing - IMU error")
            else:
                raise LandingError(f"Unexpected response to land command: {response}")
            return False
                
        except LandingError as e:
            logger.error(f"Landing error: {e}")
            # Check if drone actually landed despite the error
            if self.get_height() <= self.MIN_ALTITUDE:
                logger.warning("Drone appears to have landed despite command error")
                self._status.state = DroneState.LANDED
                return True
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
                priority=CommandPriority.NORMAL
            )

            if response is None:
                raise MovementError("No response received for movement command")

            if response == "ok":
                logger.info(f"Movement command {direction} {distance}cm completed")
                return True
            elif "error No valid imu" in response:
                raise MovementError("Drone reporting unstable conditions - IMU error") 
            else:
                raise MovementError(f"Unexpected response to movement command: {response}")
            return False

        except MovementError as e:
            logger.error(f"Movement error: {e}")
            return False
        except Exception as e:
            logger.error(f"Movement command failed: {e}")
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
                priority=CommandPriority.NORMAL
            )

            if response is None:
                raise RotationError("No response received for rotation command")

            if response == "ok":
                logger.info(f"Rotation command {direction} {degrees}° completed")
                return True
            elif "error No valid imu" in response:
                raise RotationError("Drone reporting unstable conditions - IMU error")
            else:
                raise RotationError(f"Unexpected response to rotation command: {response}")
            return False

        except RotationError as e:
            logger.error(f"Rotation error: {e}")
            return False
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
                priority=CommandPriority.NORMAL
            )

            if response is None:
                raise SpeedCommandError("No response received for speed command")

            if response == "ok":
                self._status.speed = speed
                logger.info(f"Speed set to {speed} cm/s")
                return True
            elif "error No valid imu" in response:
                raise SpeedCommandError("Drone reporting unstable conditions - IMU error")
            else:
                raise SpeedCommandError(f"Unexpected response to speed command: {response}")
            return False

        except SpeedCommandError as e:
            logger.error(f"Speed command error: {e}")
            return False
        except Exception as e:
            logger.error(f"Speed command failed: {e}")
            return False

    def get_speed(self) -> int:
        """Get current speed in centimeters per second"""
        try:
            response = self._command_handler.send_command(
                "speed?",
                priority=CommandPriority.LOW
            )

            if response is None:
                raise SpeedCommandError("No response received for speed query")

            speed = self._parse_speed(response)
            if speed is not None:
                self._status.speed = speed  # Update cached speed
                return speed
            else:
                raise SpeedCommandError(f"Could not parse speed from response: {response}")
            return False

        except SpeedCommandError as e:
            logger.error(f"Speed query error: {e}")
            return self._status.speed
        except Exception as e:
            logger.error(f"Speed query failed: {e}")
            return self._status.speed

    def get_battery(self) -> int:
        """Get battery percentage"""
        return self._status.battery

    def get_height(self) -> int:
        """Get current height in centimeters"""
        return self._status.altitude

    def get_status(self) -> DroneStatus:
        """Get current drone status"""
        return self._status

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest video frame"""
        return self._video.get_frame()
