#!/usr/bin/env python3
import cv2
import numpy as np
import time
import signal
import sys
import logging
import threading
from queue import Queue, Empty  # Import Empty exception explicitly
from typing import Optional
from tello_lib.controller import TelloController
from tello_lib.models import DroneState

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class TelloVideoProcessor:
    def __init__(self):
        self.frame_queue = Queue(maxsize=1)  # Only keep latest frame
        self.stop_event = threading.Event()
        self.latest_frame = None
        self.processing_results = Queue(maxsize=1)  # For ArUco/obstacle detection results
        self.stream_ready = threading.Event()
        self.consecutive_failures = 0
        self.MAX_FAILURES = 10
        
        # Initialize ArUco detector
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

    def video_processor_thread(self, drone: TelloController):
        """Thread for handling video processing"""
        frame_count = 0
        start_time = time.time()
        
        while not self.stop_event.is_set():
            try:
                frame = drone.get_frame()
                if frame is not None:
                    # Reset failure counter on successful frame
                    self.consecutive_failures = 0
                    
                    # Count FPS for first few frames
                    frame_count += 1
                    if frame_count == 30:
                        elapsed = time.time() - start_time
                        fps = frame_count / elapsed
                        if fps >= 5:
                            self.stream_ready.set()
                        logger.info(f"Video stream FPS: {fps:.1f}")
                    
                    # Process and display frame
                    try:
                        processed_frame = self.process_frame(frame)
                        if processed_frame is not None and not self.stop_event.is_set():  # Check stop event again
                            cv2.imshow('Tello Video Feed', processed_frame)
                            key = cv2.waitKey(1) & 0xFF
                            if key == ord('q'):
                                logger.info("User requested video stop")
                                self.stop_event.set()
                                break  # Exit the loop immediately
                    except cv2.error as e:
                        logger.warning(f"OpenCV error while processing frame: {e}")
                        continue
                    
                else:
                    self.consecutive_failures += 1
                    if self.consecutive_failures >= self.MAX_FAILURES:
                        logger.error("Too many consecutive frame failures")
                        self.stop_event.set()
                        break  # Exit the loop immediately
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Error in video processor thread: {e}")
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.MAX_FAILURES:
                    logger.error("Too many consecutive frame failures")
                    self.stop_event.set()
                    break  # Exit the loop immediately
                time.sleep(0.1)
        
        # Cleanup when exiting the thread
        cv2.destroyWindow('Tello Video Feed')

    def process_frame(self, frame):
        """Process frame for ArUco markers and obstacles"""
        try:
            # Convert to grayscale for ArUco detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # ArUco detection using new API
            corners, ids, rejected = self.aruco_detector.detectMarkers(gray)
            
            # If markers are detected
            if ids is not None:
                # Draw markers on frame
                frame = cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                marker_positions = self._calculate_marker_positions(corners, ids)
                try:
                    # Use put_nowait to prevent blocking
                    self.processing_results.put_nowait({
                        'type': 'aruco',
                        'positions': marker_positions
                    })
                except Queue.Full:
                    pass  # Skip if queue is full
            
            return frame
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return frame  # Return original frame on error

    def _calculate_marker_positions(self, corners, ids):
        """Calculate 3D positions of detected ArUco markers"""
        marker_positions = []
        for i, corner in enumerate(corners):
            center = np.mean(corner[0], axis=0)
            marker_positions.append({
                'id': ids[i][0],
                'center': center
            })
        return marker_positions

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get the most recent processed frame"""
        try:
            return self.frame_queue.get_nowait()
        except Empty:  # Use imported Empty exception
            return None

    def stop(self):
        """Gracefully stop the video processor"""
        self.stop_event.set()
        # Give a small delay for the thread to cleanup
        time.sleep(0.5)
        try:
            cv2.destroyAllWindows()
        except:
            pass

    def wait_for_stream_ready(self, timeout=15):
        """Wait for video stream to stabilize"""
        return self.stream_ready.wait(timeout=timeout)

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

        # Test increase elevation
        #logger.info("Testing increase elevation...")
        #if not drone.move("up", 100):
        #    logger.error("❌ Failed to increase elevation")
        #    return False
        #logger.info("✅ Increase elevation successful")

        # Test rotation
        logger.info("Testing rotation...")
        if not drone.rotate("cw", 360):
            logger.error("❌ Rotation failed")
            return False
        logger.info("✅ Rotation successful")
        


        # Test rotation
        #logger.info("Testing rotation...")
        #if not drone.rotate("cw", 180):
        #    logger.error("❌ Rotation failed")
        #    return False
        #logger.info("✅ Rotation successful")
        
        return True
        
    except Exception as e:
        logger.error(f"Flight sequence failed: {e}")
        return False

def signal_handler(sig, frame):
    logger.info("Ctrl+C pressed. Starting emergency landing...")
    sys.exit(0)

def main():
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create drone controller and video processor
    drone = TelloController()
    video_processor = TelloVideoProcessor()
    video_thread = None
    
    try:
        # Connect to drone
        logger.info("Connecting to drone...")
        if not drone.connect():
            logger.error("Failed to connect to drone")
            return
        logger.info("✅ Connected to drone")
        
        # Wait for first status data to be logged
        time.sleep(3)
        
        # Check battery
        battery = drone.get_battery()
        logger.info(f"Battery level: {battery}%")
        if battery < 10:
            logger.error("Battery too low for flight test!")
            return
        
        # Start video stream
        logger.info("Starting video stream...")
        if not drone.start_video_stream():
            logger.error("Failed to start video stream")
            return
        
        # Start video processing thread
        video_thread = threading.Thread(
            target=video_processor.video_processor_thread,
            args=(drone,),
            daemon=True
        )
        video_thread.start()
        
        # Wait for video stream to stabilize
        if not video_processor.wait_for_stream_ready(timeout=15):
            logger.error("Video stream failed to stabilize within timeout")
            return
        
        logger.info("✅ Video stream started and stable")
        
        time.sleep(5)
        
        # Run test flight sequence
        logger.info("Starting test flight sequence...")
        flight_success = test_flight_sequence(drone)
        
        if flight_success:
            logger.info("✅ Flight test completed successfully")
        else:
            logger.error("❌ Flight test failed")
            return
        
        # After test flight, continue processing video until user quits
        logger.info("Test flight complete. Press 'q' in video window to quit...")
        while not video_processor.stop_event.is_set():
            try:
                result = video_processor.processing_results.get_nowait()
                if result['type'] == 'aruco':
                    logger.info(f"Detected markers: {result['positions']}")
            except Empty:
                pass
            
            # Add a small sleep to prevent CPU spinning
            time.sleep(0.1)
            
            # Check if window was closed
            try:
                if cv2.getWindowProperty('Tello Video Feed', cv2.WND_PROP_VISIBLE) < 1:
                    video_processor.stop_event.set()
                    break
            except:
                pass
        
    except KeyboardInterrupt:
        logger.warning("\nProgram interrupted by user")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        # Stop video processing
        video_processor.stop()
        if video_thread and video_thread.is_alive():
            video_thread.join(timeout=2)
        
        # Emergency landing if still flying
        if drone.get_status().state == DroneState.FLYING:
            logger.warning("Emergency landing initiated...")
            drone.land()
        
        # Stop video
        logger.info("Stopping video stream...")
        drone.stop_video_stream()
        
        # Cleanup
        logger.info("Cleaning up...")
        drone.disconnect()
        cv2.destroyAllWindows()
        logger.info("Cleanup complete")

if __name__ == "__main__":
    main()
