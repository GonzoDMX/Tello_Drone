#!/usr/bin/env python3

import cv2
import time
import signal
import sys
import logging
from tello_lib.controller import TelloController
from tello_lib.models import DroneState

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def signal_handler(sig, frame):
    logger.info("Ctrl+C pressed. Starting emergency landing...")
    sys.exit(0)

def test_flight_sequence(drone: TelloController):
    """Test basic flight sequence"""
    
    try:
        # Take off
        logger.info("Taking off...")
        if not drone.takeoff():
            logger.error("❌ Takeoff failed")
            return False
        logger.info("✅ Takeoff successful")
        time.sleep(3)  # Stabilize after takeoff
        
        # Test rotation
        logger.info("Testing rotation...")
        if not drone.rotate("cw", 90):
            logger.error("❌ Rotation failed")
            return False
        logger.info("✅ Rotation successful")
        time.sleep(2)
        
        # Test movement
        logger.info("Testing forward movement...")
        if not drone.move("forward", 50):
            logger.error("❌ Forward movement failed")
            return False
        logger.info("✅ Forward movement successful")
        time.sleep(2)
        
        # Return to starting position
        logger.info("Returning to start...")
        if not drone.move("back", 50):
            logger.error("❌ Backward movement failed")
            return False
        if not drone.rotate("ccw", 90):
            logger.error("❌ Return rotation failed")
            return False
        logger.info("✅ Returned to starting position")
        
        return True
        
    except Exception as e:
        logger.error(f"Flight sequence failed: {e}")
        return False

def main():
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create drone controller
    drone = TelloController()
    cv2.namedWindow("Tello Video Feed", cv2.WINDOW_NORMAL)
    
    try:
        # Connect to drone
        logger.info("Connecting to drone...")
        if not drone.connect():
            logger.error("Failed to connect to drone")
            return
        logger.info("✅ Connected to drone")
        
        # Check battery
        battery = drone.get_battery()
        logger.info(f"Battery level: {battery}%")
        if battery < 20:
            logger.error("Battery too low for flight test!")
            return
        
        # Start video stream
        logger.info("Starting video stream...")
        if not drone.start_video_stream(timeout=15):
            logger.error("Failed to start video stream")
            return
        logger.info("✅ Video stream started")
        
        while True:
            frame = drone.get_frame()
            if frame is not None:
                cv2.imshow('Tello Video Feed', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        # Run flight sequence
        #success = test_flight_sequence(drone)
        #if success:
        #    logger.info("✅ Flight test completed successfully")
        #else:
        #    logger.error("❌ Flight test failed")
        
        # Land
        #logger.info("Landing...")
        #if not drone.land():
        #    logger.error("❌ Landing failed!")
        #else:
        #    logger.info("✅ Landing successful")
        
    except KeyboardInterrupt:
        logger.warning("\nProgram interrupted by user")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        # Emergency landing if still flying
        if drone.get_status().state == DroneState.FLYING:
            logger.warning("Emergency landing initiated...")
            drone.land()
        
        # Stop video
        logger.info("Stopping video stream...")
        drone.stop_video_stream()
        
        # Cleanup
        logger.info("Cleaning up...")
        drone.cleanup()
        cv2.destroyAllWindows()
        logger.info("Cleanup complete")

if __name__ == "__main__":
    main()
