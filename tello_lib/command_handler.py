import socket
import threading
import time
import logging
import queue
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from .models import Command, CommandPriority
from .exceptions import CommandError

logger = logging.getLogger(__name__)

@dataclass
class PendingCommand:
    """Represents a command waiting for response"""
    command: str
    timestamp: float
    expected_response: Optional[str]
    response_event: threading.Event
    response: Optional[str] = None
    message_id: int = 0  # For tracking in logs

class CommandType(Enum):
    REGULAR = "REGULAR"
    PING = "PING"
    UNKNOWN = "UNKNOWN"

class CommandHandler:
    def __init__(self, tello_addr: Tuple[str, int] = ('192.168.10.1', 8889)):
        # Setup command socket
        self._cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_socket.settimeout(10.0)
        self._cmd_socket.bind(('', 8889))
        self._tello_addr = tello_addr
        
        # Command synchronization
        self._command_lock = threading.Lock()
        self._last_command_time = 0
        
        # Ping control
        self._ping_interval = 12.0
        self._ping_thread = None
        self._running = False

    def _ping_loop(self):
        """Send periodic pings if needed"""
        while self._running:
            with self._command_lock:
                time_since_last = time.time() - self._last_command_time
                if time_since_last >= self._ping_interval:
                    logger.info("Sending keep-alive ping")
                    self.send_command("command", priority=CommandPriority.LOW)
            time.sleep(1)


    def send_command(self, command: str, priority: int = CommandPriority.NORMAL,
                    retries: int = 3) -> Optional[str]:
        """
        Send command and wait for response
        
        Args:
            command: Command string to send
            priority: Command priority (not used but kept for API compatibility)
            retries: Number of retry attempts
            
        Returns:
            Optional[str]: Raw command response if successful, None if command completely failed
        """
        with self._command_lock:
            attempt = 0
            while attempt < retries:
                try:
                    logger.info(f"Sending command: {command}")
                    self._cmd_socket.sendto(command.encode('utf-8'), self._tello_addr)
                    
                    try:
                        response, addr = self._cmd_socket.recvfrom(1024)
                        response_str = response.decode('utf-8').strip()
                        logger.info(f"Received response: '{response_str}'")

                        # Update last command time on any response
                        self._last_command_time = time.time()
                        
                        # Return whatever response we got
                        return response_str
                        
                    except socket.timeout:
                        logger.warning(f"Response timeout (attempt {attempt + 1}/{retries})")
                        attempt += 1
                        continue
                        
                except Exception as e:
                    logger.error(f"Command failed: {e}")
                    attempt += 1
                    continue
            
            logger.error(f"Command failed after {retries} attempts: {command}")
            return None

    def start(self):
        """Start command handler"""
        self._running = True
        self._last_command_time = time.time()
        self._ping_thread = threading.Thread(target=self._ping_loop)
        self._ping_thread.daemon = True
        self._ping_thread.start()

    def stop(self):
        """Stop command handler"""
        self._running = False
        if self._ping_thread and self._ping_thread.is_alive():
            self._ping_thread.join()
        if hasattr(self, '_cmd_socket'):
            self._cmd_socket.close()
