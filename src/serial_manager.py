"""
Serial device manager for handling multiple devices.
Provides device management, port enumeration, and connection handling.
"""

from typing import Dict, List, Optional, Tuple
import serial.tools.list_ports
from src.device import SerialDevice, SampleHandler, Degausser, SQUID


class SerialManager:
    """Manager for multiple serial devices."""

    def __init__(self):
        """Initialize the serial manager."""
        self.devices: Dict[str, SerialDevice] = {
            "Sample Handler": SampleHandler(),
            "Degausser": Degausser(),
            "SQUID": SQUID(),
        }

    def list_ports(self) -> List[str]:
        """
        List all available serial ports.

        Returns:
            List of available port names
        """
        ports = []
        for port_info in serial.tools.list_ports.comports():
            ports.append(port_info.device)
        return sorted(ports)

    def get_device(self, device_name: str) -> Optional[SerialDevice]:
        """
        Get a device by name.

        Args:
            device_name: Name of the device

        Returns:
            SerialDevice instance or None if not found
        """
        return self.devices.get(device_name)

    def get_all_device_names(self) -> List[str]:
        """Get all registered device names."""
        return list(self.devices.keys())

    def connect(self, device_name: str, port: str) -> bool:
        """
        Connect a device to a specific port.

        Args:
            device_name: Name of the device
            port: Serial port to connect to

        Returns:
            True if connection successful, False otherwise
        """
        device = self.get_device(device_name)
        if not device:
            print(f"Device {device_name} not found")
            return False

        return device.connect(port)

    def disconnect(self, device_name: str) -> bool:
        """
        Disconnect a device.

        Args:
            device_name: Name of the device

        Returns:
            True if disconnection successful, False otherwise
        """
        device = self.get_device(device_name)
        if not device:
            print(f"Device {device_name} not found")
            return False

        return device.disconnect()

    def is_device_connected(self, device_name: str) -> bool:
        """
        Check if a device is connected.

        Args:
            device_name: Name of the device

        Returns:
            True if connected, False otherwise
        """
        device = self.get_device(device_name)
        if not device:
            return False

        return device.is_connected()

    def send_command(self, device_name: str, command: str) -> bool:
        """
        Send a command to a device.

        Args:
            device_name: Name of the device
            command: Command string to send

        Returns:
            True if send successful, False otherwise
        """
        device = self.get_device(device_name)
        if not device:
            print(f"Device {device_name} not found")
            return False

        return device.send_command(command)

    def receive_response(
        self, device_name: str, timeout: Optional[float] = None
    ) -> str:
        """
        Receive response from a device.

        Args:
            device_name: Name of the device
            timeout: Optional timeout in seconds

        Returns:
            Response string
        """
        device = self.get_device(device_name)
        if not device:
            return ""

        return device.receive_response(timeout)

    def get_connection_command(self, device_name: str) -> str:
        """Get the connection command for a device."""
        device = self.get_device(device_name)
        if not device:
            return ""

        return device.get_connection_command()

    def get_status_command(self, device_name: str) -> str:
        """Get the status command for a device."""
        device = self.get_device(device_name)
        if not device:
            return ""

        return device.get_status_command()

    def disconnect_all(self) -> None:
        """Disconnect all connected devices."""
        for device in self.devices.values():
            if device.is_connected():
                device.disconnect()
