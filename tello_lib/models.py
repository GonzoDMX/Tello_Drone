from enum import Enum
from dataclasses import dataclass
from typing import Optional
from queue import PriorityQueue
import time

class DroneState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    FLYING = "flying"
    LANDED = "landed"
    ERROR = "error"

class VideoStreamState(Enum):
    DISCONNECTED = "disconnected"
    INITIALIZING = "initializing"
    STREAMING = "streaming"
    ERROR = "error"

@dataclass
class DroneStatus:
    battery: int = 0
    speed: int = 0
    flight_time: int = 0
    state: DroneState = DroneState.DISCONNECTED
    height: int = 0

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
