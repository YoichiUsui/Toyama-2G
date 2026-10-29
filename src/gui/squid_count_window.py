"""
Main window for the SQUID single-shot measurement test tool.

This tool connects to the SQUID sensor only (no sample handler / degausser
motion is involved) and lets the operator trigger one measurement per axis
on demand. See docs/SQUID測定テストUI.jpg for the UI layout this window
follows.
"""

from datetime import datetime
from typing import Dict, Optional

import serial.tools.list_ports
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.device import SQUID
from src.gui.squid_measurement_worker import SquidMeasurementWorker

AXES = ("X", "Y", "Z")


class SquidMeasurementWindow(QMainWindow):
    """Window for running one-shot SQUID measurements on X, Y and Z."""

    def __init__(self, flux_quanta: Dict[str, float]):
        """
        Initialize the window.

        Args:
            flux_quanta: Flux quanta calibration constant for each axis,
                as loaded from settings/squid_setting.txt.
        """
        super().__init__()
        self.setWindowTitle("SQUID測定テストツール")
        self.setGeometry(100, 100, 800, 600)

        self.flux_quanta = flux_quanta
        self.squid = SQUID()

        # Worker/thread pair kept alive while a measurement is in progress.
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[SquidMeasurementWorker] = None

        # Populated by init_ui(); kept here for type hints / readability.
        self.count_displays: Dict[str, QLineEdit] = {}
        self.data_displays: Dict[str, QLineEdit] = {}
        self.magnetization_displays: Dict[str, QLineEdit] = {}
        self.measure_buttons: Dict[str, QPushButton] = {}

        self.init_ui()
        self.refresh_ports()

    def init_ui(self):
        """Build the widget layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        main_layout.addWidget(self.create_flux_quanta_group())
        main_layout.addWidget(self.create_connection_group())
        main_layout.addWidget(self.create_measurement_group())
        main_layout.addWidget(self.create_log_group())

        self.statusBar().showMessage("Ready")

    def create_flux_quanta_group(self) -> QGroupBox:
        """Read-only display of the flux quanta loaded from the config file."""
        group = QGroupBox("Flux Quanta（設定ファイルより）")
        layout = QHBoxLayout()
        group.setLayout(layout)

        for axis in AXES:
            layout.addWidget(QLabel(f"{axis} flux quanta:"))
            display = QLineEdit(f"{self.flux_quanta[axis]:.4g}")
            display.setReadOnly(True)
            layout.addWidget(display)

        return group

    def create_connection_group(self) -> QGroupBox:
        """Port selection and connect/disconnect button."""
        group = QGroupBox("接続")
        layout = QHBoxLayout()
        group.setLayout(layout)

        layout.addWidget(QLabel("ポート:"))
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo)

        self.connect_btn = QPushButton("接続")
        self.connect_btn.clicked.connect(self.on_connect_clicked)
        layout.addWidget(self.connect_btn)

        return group

    def create_measurement_group(self) -> QGroupBox:
        """Count reset button, per-axis measurement buttons and results."""
        group = QGroupBox("測定")
        layout = QGridLayout()
        group.setLayout(layout)

        self.reset_btn = QPushButton("SQUIDカウントリセット")
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        self.reset_btn.setEnabled(False)
        layout.addWidget(self.reset_btn, 0, 0, 1, 3)

        for col, axis in enumerate(AXES):
            measure_btn = QPushButton(f"{axis}測定")
            measure_btn.setEnabled(False)
            measure_btn.clicked.connect(
                lambda checked=False, a=axis: self.on_measure_clicked(a)
            )
            self.measure_buttons[axis] = measure_btn
            layout.addWidget(measure_btn, 1, col)

        for col, axis in enumerate(AXES):
            layout.addWidget(QLabel(f"{axis}カウント:"), 2, col)
            count_display = QLineEdit()
            count_display.setReadOnly(True)
            self.count_displays[axis] = count_display
            layout.addWidget(count_display, 3, col)

        for col, axis in enumerate(AXES):
            layout.addWidget(QLabel(f"{axis}データ:"), 4, col)
            data_display = QLineEdit()
            data_display.setReadOnly(True)
            self.data_displays[axis] = data_display
            layout.addWidget(data_display, 5, col)

        for col, axis in enumerate(AXES):
            layout.addWidget(QLabel(f"{axis}磁化:"), 6, col)
            magnetization_display = QLineEdit()
            magnetization_display.setReadOnly(True)
            self.magnetization_displays[axis] = magnetization_display
            layout.addWidget(magnetization_display, 7, col)

        return group

    def create_log_group(self) -> QGroupBox:
        """Communication status / error log window."""
        group = QGroupBox("通信状況・エラーメッセージ")
        layout = QVBoxLayout()
        group.setLayout(layout)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)

        return group

    # -- Port / connection handling -----------------------------------

    def refresh_ports(self):
        """Populate the port combo box with the currently available ports."""
        ports = sorted(p.device for p in serial.tools.list_ports.comports())
        self.port_combo.clear()
        self.port_combo.addItems(ports)

    def on_connect_clicked(self):
        """Handle the connect/disconnect button."""
        if self.squid.is_connected():
            self.squid.disconnect()
            self.log_append("[SQUID] Disconnected")
            self.update_connection_status(False)
            return

        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "ポートを選択してください")
            return

        if self.squid.connect(port):
            self.log_append(f"[SQUID] Connected to {port}")
            self.update_connection_status(True)
        else:
            QMessageBox.critical(self, "接続エラー", f"{port} への接続に失敗しました")
            self.log_append(f"[SQUID] Connection failed on {port}")

    def update_connection_status(self, is_connected: bool):
        """Enable/disable the buttons that require a live connection."""
        self.connect_btn.setText("切断" if is_connected else "接続")
        self.reset_btn.setEnabled(is_connected)
        for measure_btn in self.measure_buttons.values():
            measure_btn.setEnabled(is_connected)

    # -- Count reset ----------------------------------------------------

    def on_reset_clicked(self):
        """Reset the SQUID sensor's counters via the ARC command."""
        if self.squid.send_command("ARC"):
            self.log_append("[SQUID] >> ARC (count reset)")
        else:
            self.log_append("[SQUID] ERROR: Failed to send ARC")

    # -- Measurement ------------------------------------------------------

    def on_measure_clicked(self, axis: str):
        """Start a background measurement of the given axis."""
        self.set_measure_buttons_enabled(False)
        self.statusBar().showMessage(f"Measuring {axis}...")

        self.worker_thread = QThread()
        self.worker = SquidMeasurementWorker(self.squid, axis)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.log_message.connect(self.log_append)
        self.worker.measurement_done.connect(self.on_measurement_done)
        self.worker.error_occurred.connect(self.on_measurement_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(
            lambda: self.set_measure_buttons_enabled(True)
        )

        self.worker_thread.start()

    def on_measurement_done(self, axis: str, count: int, data: float):
        """Display the measured count/data and the resulting magnetization."""
        self.count_displays[axis].setText(str(count))
        self.data_displays[axis].setText(str(data))

        magnetization = (count + data) * self.flux_quanta[axis]
        self.magnetization_displays[axis].setText(f"{magnetization:.6g}")

        self.statusBar().showMessage("Ready")

    def on_measurement_error(self, axis: str, message: str):
        """Report a failed measurement without crashing the tool."""
        self.log_append(f"[SQUID] ERROR ({axis}): {message}")
        self.statusBar().showMessage("Ready")

    def set_measure_buttons_enabled(self, enabled: bool):
        """Enable/disable all measurement buttons at once."""
        for measure_btn in self.measure_buttons.values():
            measure_btn.setEnabled(enabled)

    # -- Logging / cleanup ------------------------------------------------

    def log_append(self, message: str):
        """Append a timestamped message to the log window."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        """Ensure the SQUID connection is closed when the window closes."""
        if self.squid.is_connected():
            self.squid.disconnect()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()
