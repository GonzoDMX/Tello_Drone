class CommandError(Exception):
    """Raised when a drone command fails"""
    pass

class VideoStreamError(Exception):
    """Raised when video stream encounters an error"""
    pass

class DroneConnectionError(Exception):
    """Raised when connection to drone fails"""
    pass
    
class TakeoffError(CommandError):
    """Raised when takeoff command fails but drone state is uncertain"""
    pass
    
class LandingError(CommandError):
    """Raised when landing command fails but drone state is uncertain"""
    pass

class MovementError(CommandError):
    """Raised when movement command fails or returns unexpected response"""
    pass

class RotationError(CommandError):
    """Raised when rotation command fails or returns unexpected response"""
    pass

class SpeedCommandError(CommandError):
    """Raised when speed command/query fails or returns unexpected response"""
    pass
