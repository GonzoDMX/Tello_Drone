from enum import Enum
from dataclasses import dataclass
from typing import Optional
from queue import PriorityQueue
import time

class DroneState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    FLYING = "flying"
    FLYING_UNSTABLE = "flying_unstable"
    LANDED = "landed"
    ERROR = "error"

class VideoStreamState(Enum):
    DISCONNECTED = "disconnected"
    INITIALIZING = "initializing"
    STREAMING = "streaming"
    ERROR = "error"

@dataclass
class Coordinate:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

@dataclass
class Temperature:
    low: int = 0
    high: int = 0


@dataclass
class DroneStatus:
    def __init__(self):
        self.velocity = Coordinate()
        self.acceleration = Coordinate()
        self.temperature = Temperature()
        self.pitch: int = 0
        self.roll: int = 0
        self.yaw: int = 0
        self.altitude: int = 0
        self.barometric_pressure: float = 0.0
        self.time_of_flight: int = 0
        self.time: int = 0
        self.battery: int = 0
        self.state: DroneState = DroneState.DISCONNECTED

@dataclass
class Command:
    command: str
    priority: int  # Lower number = higher priority
    timestamp: float
    expected_response: Optional[str] = None
    timeout: float = 7.0
    retries: int = 3

    def __lt__(self, other):
        # For PriorityQueue ordering
        return self.priority < other.priority

class CommandPriority:
    EMERGENCY = 0  # Emergency commands (land, emergency stop)
    HIGH = 1       # Critical flight commands (takeoff)
    NORMAL = 2     # Regular commands (move, rotate)
    LOW = 3        # Status queries (battery, height)
