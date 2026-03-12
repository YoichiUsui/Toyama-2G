"""
Worker thread for non-blocking serial communication.
Handles command sending and response receiving in a separate thread.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from src.serial_manager import SerialManager


class SerialWorker(QObject):
    """Worker for serial communication in a separate thread."""

    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, manager: SerialManager, device_name: str, command: str):
        """
        Initialize the worker.

        Args:
            manager: SerialManager instance
            device_name: Name of the device to communicate with
            command: Command to send
        """
        super().__init__()
        self.manager = manager
        self.device_name = device_name
        self.command = command

    def run(self):
        """Execute the communication task."""
        try:
            # Send the command
            if not self.manager.send_command(self.device_name, self.command):
                self.error_occurred.emit(
                    f"Failed to send command to {self.device_name}"
                )
                self.finished.emit()
                return

            # Receive the response
            response = self.manager.receive_response(self.device_name, timeout=1.0)

            if response:
                self.response_received.emit(response)
            else:
                self.response_received.emit("")

        except Exception as e:
            self.error_occurred.emit(f"Communication error: {str(e)}")

        finally:
            self.finished.emit()
