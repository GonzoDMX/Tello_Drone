class CommandError(Exception):
    """Raised when a drone command fails"""
    pass

class VideoStreamError(Exception):
    """Raised when video stream encounters an error"""
    pass

class DroneConnectionError(Exception):
    """Raised when connection to drone fails"""
    pass
