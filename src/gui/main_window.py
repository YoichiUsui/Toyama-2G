"""
Main window for the Serial Device Test application.
Provides GUI for managing multiple serial devices and sending commands.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QLineEdit, QTextEdit, QGroupBox,
    QMessageBox, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont
from datetime import datetime
from typing import Optional
from src.serial_manager import SerialManager
from src.gui.worker import SerialWorker


class MainWindow(QMainWindow):
    """Main application window for serial device testing."""

    def __init__(self):
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle("Serial Device Communication Test Tool")
        self.setGeometry(100, 100, 1000, 700)

        self.serial_manager = SerialManager()
        self.current_device: Optional[str] = None
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[SerialWorker] = None

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Port and device selection section
        selection_group = self.create_selection_group()
        main_layout.addWidget(selection_group)

        # Command input section
        command_group = self.create_command_group()
        main_layout.addWidget(command_group)

        # Log section
        log_group = self.create_log_group()
        main_layout.addWidget(log_group)

        # Status bar
        self.statusBar().showMessage("Ready")

    def create_selection_group(self) -> QGroupBox:
        """Create the port and device selection group."""
        group = QGroupBox("Device Selection")
        layout = QGridLayout()

        # Port selection
        layout.addWidget(QLabel("Serial Port:"), 0, 0)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo, 0, 1)

        self.detect_btn = QPushButton("Detect Ports")
        self.detect_btn.clicked.connect(self.on_detect_ports)
        layout.addWidget(self.detect_btn, 0, 2)

        # Device selection
        layout.addWidget(QLabel("Device:"), 1, 0)
        self.device_combo = QComboBox()
        self.device_combo.addItems(self.serial_manager.get_all_device_names())
        self.device_combo.currentTextChanged.connect(self.on_device_selected)
        layout.addWidget(self.device_combo, 1, 1)

        # Connection status
        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setFont(QFont("Arial", 10))
        layout.addWidget(self.status_label, 1, 2)

        # Connect/Disconnect buttons
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.on_connect)
        layout.addWidget(self.connect_btn, 2, 0)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.disconnect_btn.setEnabled(False)
        layout.addWidget(self.disconnect_btn, 2, 1)

        group.setLayout(layout)
        return group

    def create_command_group(self) -> QGroupBox:
        """Create the command input group."""
        group = QGroupBox("Command Input")
        layout = QHBoxLayout()

        layout.addWidget(QLabel("Command:"))
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Enter command (e.g., @0, or DSS\\n\\r)")
        layout.addWidget(self.command_input)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send_command)
        self.send_btn.setEnabled(False)
        layout.addWidget(self.send_btn)

        group.setLayout(layout)
        return group

    def create_log_group(self) -> QGroupBox:
        """Create the response and log display group."""
        group = QGroupBox("Communication Log")
        layout = QVBoxLayout()

        # Response section
        layout.addWidget(QLabel("Latest Response:"))
        self.response_display = QTextEdit()
        self.response_display.setReadOnly(True)
        self.response_display.setMaximumHeight(150)
        layout.addWidget(self.response_display)

        # Log section
        layout.addWidget(QLabel("Communication Log:"))
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)

        group.setLayout(layout)
        return group

    def on_detect_ports(self):
        """Detect available serial ports."""
        ports = self.serial_manager.list_ports()
        self.port_combo.clear()
        if ports:
            self.port_combo.addItems(ports)
            self.statusBar().showMessage(f"Found {len(ports)} port(s)")
            self.log_append(f"[SYSTEM] Detected {len(ports)} port(s): {', '.join(ports)}")
        else:
            self.statusBar().showMessage("No ports found")
            self.log_append("[SYSTEM] No serial ports found")

    def on_device_selected(self, device_name: str):
        """Handle device selection change."""
        self.current_device = device_name
        is_connected = self.serial_manager.is_device_connected(device_name)
        self.update_connection_status(is_connected)

    def update_connection_status(self, is_connected: bool):
        """Update the connection status display."""
        if is_connected:
            self.status_label.setText(f"Status: Connected to {self.current_device}")
            self.status_label.setStyleSheet("color: green;")
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.send_btn.setEnabled(True)
        else:
            self.status_label.setText("Status: Disconnected")
            self.status_label.setStyleSheet("color: red;")
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.send_btn.setEnabled(False)

    def on_connect(self):
        """Handle connect button click."""
        if not self.current_device:
            QMessageBox.warning(self, "Error", "Please select a device")
            return

        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "Please select a port")
            return

        if self.serial_manager.connect(self.current_device, port):
            self.update_connection_status(True)
            self.log_append(f"[{self.current_device}] Connected to {port}")
            self.statusBar().showMessage(f"Connected to {self.current_device} on {port}")
        else:
            QMessageBox.critical(
                self, "Connection Error",
                f"Failed to connect to {self.current_device} on {port}"
            )
            self.log_append(f"[{self.current_device}] Connection failed on {port}")

    def on_disconnect(self):
        """Handle disconnect button click."""
        if not self.current_device:
            return

        if self.serial_manager.disconnect(self.current_device):
            self.update_connection_status(False)
            self.log_append(f"[{self.current_device}] Disconnected")
            self.statusBar().showMessage(f"Disconnected from {self.current_device}")
        else:
            QMessageBox.critical(
                self, "Disconnection Error",
                f"Failed to disconnect from {self.current_device}"
            )

    def on_send_command(self):
        """Handle send command button click."""
        if not self.current_device:
            QMessageBox.warning(self, "Error", "Please select a device")
            return

        if not self.serial_manager.is_device_connected(self.current_device):
            QMessageBox.warning(self, "Error", "Device is not connected")
            return

        command = self.command_input.text()
        if not command:
            QMessageBox.warning(self, "Error", "Please enter a command")
            return

        # Create and start worker thread for non-blocking communication
        self.worker_thread = QThread()
        self.worker = SerialWorker(
            self.serial_manager, self.current_device, command
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.response_received.connect(self.on_response_received)
        self.worker.error_occurred.connect(self.on_communication_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.send_btn.setEnabled(False)
        self.statusBar().showMessage("Sending command...")
        self.log_append(f"[{self.current_device}] >> {command}")

        self.worker_thread.start()

    def on_response_received(self, response: str):
        """Handle response received from device."""
        self.response_display.setText(response if response else "(No response)")
        if response:
            self.log_append(f"[{self.current_device}] << {response}")
        else:
            self.log_append(f"[{self.current_device}] << (No response - timeout)")
        self.send_btn.setEnabled(True)
        self.statusBar().showMessage("Ready")

    def on_communication_error(self, error: str):
        """Handle communication error."""
        QMessageBox.critical(self, "Communication Error", error)
        self.log_append(f"[{self.current_device}] ERROR: {error}")
        self.send_btn.setEnabled(True)
        self.statusBar().showMessage("Ready")

    def log_append(self, message: str):
        """Append a message to the communication log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.log_display.append(log_message)

    def closeEvent(self, event):
        """Handle window close event."""
        self.serial_manager.disconnect_all()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()
