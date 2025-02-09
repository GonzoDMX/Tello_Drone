# Tello Drone Library

A Python library for controlling DJI Tello drones with a clean, thread-safe API.

## Features

- Command queueing with priority handling
- Video stream management
- Status monitoring
- Safe takeoff and landing procedures
- Comprehensive error handling

## Installation

```bash
pip install -e .
```

## Usage

```python
from tello_lib.controller import TelloController

drone = TelloController()

if drone.connect():
    # Start video stream
    drone.start_video_stream()
    
    # Take off
    if drone.takeoff():
        # Perform flight operations
        drone.move("forward", 50)
        drone.rotate("cw", 90)
        
        # Land
        drone.land()
    
    # Cleanup
    drone.cleanup()
```

## License

MIT License
