"""
Serial device communication module.
Defines base class and device-specific implementations for serial communication.
"""

import serial
import time
from abc import ABC, abstractmethod
from typing import Optional


class SerialDevice(ABC):
    """Base class for serial devices with common communication parameters."""

    # Common communication parameters
    BAUD_RATE = 1200
    PARITY = serial.PARITY_NONE
    STOPBITS = serial.STOPBITS_ONE
    BYTESIZE = serial.EIGHTBITS
    TIMEOUT = 1.0  # 1 second timeout

    def __init__(self, device_name: str):
        """
        Initialize the serial device.

        Args:
            device_name: Name of the device (e.g., 'Sample Handler')
        """
        self.device_name = device_name
        self.port: Optional[str] = None
        self.serial_port: Optional[serial.Serial] = None

    def connect(self, port: str) -> bool:
        """
        Connect to the device on the specified port.

        Args:
            port: Serial port name (e.g., 'COM1')

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=self.BAUD_RATE,
                parity=self.PARITY,
                stopbits=self.STOPBITS,
                bytesize=self.BYTESIZE,
                timeout=self.TIMEOUT,
            )
            self.port = port
            time.sleep(0.5)  # Wait for device to stabilize
            return True
        except serial.SerialException as e:
            print(f"Failed to connect to {self.device_name} on {port}: {e}")
            return False

    def disconnect(self) -> bool:
        """
        Disconnect from the device.

        Returns:
            True if disconnection successful, False otherwise
        """
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                self.port = None
                return True
            return False
        except serial.SerialException as e:
            print(f"Failed to disconnect from {self.device_name}: {e}")
            return False

    def is_connected(self) -> bool:
        """Check if device is currently connected."""
        return self.serial_port is not None and self.serial_port.is_open

    def send_command(self, command: str) -> bool:
        """
        Send a command to the device.

        Args:
            command: Command string to send

        Returns:
            True if send successful, False otherwise
        """
        if not self.is_connected():
            print(f"Device {self.device_name} is not connected")
            return False

        try:
            self.serial_port.write(command.encode())
            return True
        except serial.SerialException as e:
            print(f"Failed to send command to {self.device_name}: {e}")
            return False

    def receive_response(self, timeout: Optional[float] = None) -> str:
        """
        Receive response from the device.

        Args:
            timeout: Read timeout in seconds (uses device default if None)

        Returns:
            Response string, or empty string if no response
        """
        if not self.is_connected():
            print(f"Device {self.device_name} is not connected")
            return ""

        try:
            original_timeout = self.serial_port.timeout
            if timeout is not None:
                self.serial_port.timeout = timeout

            response = b""
            start_time = time.time()
            while True:
                byte = self.serial_port.read(1)
                if not byte:
                    break
                response += byte
                # Check for common terminators
                if response.endswith(b"\r\n") or response.endswith(b"\r"):
                    break
                # Simple timeout check
                if time.time() - start_time > (timeout or self.TIMEOUT):
                    break

            if timeout is not None:
                self.serial_port.timeout = original_timeout

            return response.decode(errors="ignore").strip()
        except serial.SerialException as e:
            print(f"Failed to receive from {self.device_name}: {e}")
            return ""

    @abstractmethod
    def get_connection_command(self) -> str:
        """Get the command string to establish connection."""
        pass

    @abstractmethod
    def get_status_command(self) -> str:
        """Get the command string to query device status."""
        pass


class SampleHandler(SerialDevice):
    """Sample Handler serial device implementation."""

    def __init__(self):
        super().__init__("Sample Handler")

    def get_connection_command(self) -> str:
        """Connection command for Sample Handler."""
        return "@0,"

    def get_status_command(self) -> str:
        """Status query command for Sample Handler."""
        return "?"


class Degausser(SerialDevice):
    """Degausser serial device implementation."""

    def __init__(self):
        super().__init__("Degausser")

    def get_connection_command(self) -> str:
        """Connection command for Degausser."""
        return "DSS\n\r"

    def get_status_command(self) -> str:
        """Status query command for Degausser."""
        return "DSS\n\r"


class SQUID(SerialDevice):
    """SQUID serial device implementation."""

    def __init__(self):
        super().__init__("SQUID")

    def get_connection_command(self) -> str:
        """Connection command for SQUID."""
        return "YSSL\n\r"

    def get_status_command(self) -> str:
        """Status query command for SQUID."""
        return "YSSL\n\r"
