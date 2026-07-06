"""
Worker thread for non-blocking serial communication.
Handles command sending and response receiving in a separate thread.
"""

from PySide2.QtCore import QObject, Signal
from src.serial_manager import SerialManager

# PySide2 では Signal を使い、微妙な互換性のためにエイリアスを作成
pyqtSignal = Signal


class SerialWorker(QObject):
    """Worker for serial communication in a separate thread."""

    command_sent = pyqtSignal(str, str)
    response_received = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str, str)
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
            payload = self.manager.prepare_command(self.device_name, self.command)

            # Send the command
            if not self.manager.send_command(self.device_name, self.command):
                self.error_occurred.emit(
                    self.device_name,
                    f"Failed to send command to {self.device_name}"
                )
                self.finished.emit()
                return

            self.command_sent.emit(self.device_name, payload)

            # Receive the response
            response = self.manager.receive_response(self.device_name, timeout=1.0)

            if response:
                self.response_received.emit(self.device_name, response)
            else:
                self.response_received.emit(self.device_name, "")

        except Exception as e:
            self.error_occurred.emit(
                self.device_name, f"Communication error: {str(e)}"
            )

        finally:
            self.finished.emit()
