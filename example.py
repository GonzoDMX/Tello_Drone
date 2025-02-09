from drone import TelloController, DroneState, VideoStreamState
import time
import cv2
import signal
import sys

def signal_handler(sig, frame):
    print('\nCtrl+C pressed. Landing drone...')
    sys.exit(0)

def main():
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    drone = TelloController()
    last_frame_time = time.time()

    try:
        if drone.connect():
            print("Connected to drone")
            
            # Start video stream first
            if drone.start_video_stream(timeout=15):
                print("Video stream stable")
                
                # Take off - now with better verification
                if drone.takeoff():
                    print("Takeoff confirmed")
                    
                    # Do flight operations
                    print("Hovering and displaying video feed...")
                    
                    # Show video feed with timeout detection
                    start_time = time.time()
                    while time.time() - start_time < 5:  # Run for 5 seconds
                        frame = drone.get_frame()
                        current_time = time.time()
                        
                        if frame is not None:
                            last_frame_time = current_time
                            cv2.imshow('Tello Video Feed', frame)
                            if cv2.waitKey(1) & 0xFF == ord('q'):
                                break
                        elif current_time - last_frame_time > 5:
                            print("Video stream timeout detected")
                            break
                        
                        # Small sleep to prevent tight loop
                        time.sleep(0.01)
                    
                    print("Landing...")
                    if not drone.land():
                        print("Warning: Landing failed!")
                else:
                    print("Takeoff failed or couldn't be verified")
            
            # Stop video stream
            print("Stopping video stream...")
            drone.stop_video_stream()
            
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Always try to land if we're flying
        if drone.get_status().state == DroneState.FLYING:
            print("Emergency landing...")
            drone.land()
        drone.cleanup()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
