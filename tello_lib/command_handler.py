import socket
import threading
import time
import logging
from typing import Optional, Tuple
from .models import Command, CommandPriority
from .exceptions import CommandError

logger = logging.getLogger(__name__)

class CommandHandler:
    def __init__(self, tello_addr: Tuple[str, int] = ('192.168.10.1', 8889)):
        # Setup command socket
        self._cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_socket.bind(('', 8889))
        self._cmd_socket.settimeout(2.0)
        self._tello_addr = tello_addr
        self._command_lock = threading.Lock()

    def start(self):
        """No-op for backwards compatibility"""
        pass

    def stop(self):
        """Clean up resources"""
        self._cmd_socket.close()

    def send_command(self, command: str, priority: int = CommandPriority.NORMAL,
                    expected_response: Optional[str] = None,
                    timeout: float = 7.0, retries: int = 3) -> Optional[str]:
        """
        Send command to drone and wait for response
        
        Args:
            command: Command string to send
            priority: Command priority (not used but kept for API compatibility)
            expected_response: Expected response string
            timeout: Command timeout in seconds
            retries: Number of retry attempts
            
        Returns:
            Optional[str]: Command response if successful, None if command failed
        """
        with self._command_lock:
            try:
                logger.debug(f"Sending command: {command}")
                self._cmd_socket.sendto(command.encode('utf-8'), self._tello_addr)
                
                # Wait for response
                response, _ = self._cmd_socket.recvfrom(3000)
                response_str = response.decode('utf-8')
                logger.debug(f"Received response: {response_str}")
                
                # Validate response if expected_response is set
                if expected_response and response_str != expected_response:
                    logger.warning(f"Unexpected response: {response_str}, expected: {expected_response}")
                    return None
                    
                return response_str
                
            except socket.timeout:
                logger.warning(f"Command timed out: {command}")
                return None
            except Exception as e:
                logger.error(f"Command failed: {command} - {e}")
                return None
