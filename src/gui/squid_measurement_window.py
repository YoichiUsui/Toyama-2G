"""GUI for one-sample SQUID measurements with a configured sample handler."""

from datetime import datetime
from typing import Dict, Optional, Tuple

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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.device import SQUID, SampleHandler
from src.gui.connection_check_worker import ConnectionCheckWorker
from src.gui.sample_measurement_worker import SampleMeasurementWorker
from src.measurement_settings import MeasurementSettings
from src.serial_manager import SerialManager

SAMPLE_HANDLER_NAME = "Sample Handler"
SQUID_NAME = "SQUID"


class SquidMeasurementWindow(QMainWindow):
    """Window for homing the sample handler and measuring one sample."""

    def __init__(
        self,
        flux_quanta: Dict[str, float],
        settings: MeasurementSettings,
        serial_manager: Optional[SerialManager] = None,
    ):
        super().__init__()
        self.setWindowTitle("SQUIDサンプル測定")
        self.setGeometry(100, 100, 820, 650)

        self.flux_quanta = flux_quanta
        self.settings = settings
        self.serial_manager = serial_manager or SerialManager()
        squid = self.serial_manager.get_device(SQUID_NAME)
        handler = self.serial_manager.get_device(SAMPLE_HANDLER_NAME)
        if not isinstance(squid, SQUID) or not isinstance(handler, SampleHandler):
            raise RuntimeError("測定に必要なシリアルデバイスを初期化できません。")
        self.squid = squid
        self.handler = handler

        self.connection_verified = False
        self.homed = False
        self.faulted = False
        self.current_position: Optional[int] = None
        self.active_operation: Optional[str] = None
        self.operation_result: Optional[Tuple[bool, str, int]] = None
        self.connection_result = ("timeout", "", "")
        self.worker_thread: Optional[QThread] = None
        self.worker = None

        self.init_ui()
        self.connect_devices()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.addWidget(self.create_flux_quanta_group())
        main_layout.addWidget(self.create_connection_group())
        main_layout.addWidget(self.create_measurement_group())
        main_layout.addWidget(self.create_result_group())
        main_layout.addWidget(self.create_log_group())
        self.statusBar().showMessage("接続を確認しています")

    def create_flux_quanta_group(self) -> QGroupBox:
        group = QGroupBox("Flux Quanta（設定ファイルより）")
        layout = QHBoxLayout(group)
        for axis in ("X", "Y", "Z"):
            layout.addWidget(QLabel(f"{axis} flux quanta:"))
            display = QLineEdit(f"{self.flux_quanta[axis]:.4g}")
            display.setReadOnly(True)
            layout.addWidget(display)
        return group

    def create_connection_group(self) -> QGroupBox:
        group = QGroupBox("接続")
        layout = QHBoxLayout(group)
        self.connection_label = QLabel(
            f"SQUID: {self.settings.squid_port} / "
            f"Sample Handler: {self.settings.sample_handler_port}"
        )
        layout.addWidget(self.connection_label)
        self.position_label = QLabel("現在位置: -")
        layout.addWidget(self.position_label)
        self.home_btn = QPushButton("ホーム")
        self.home_btn.setEnabled(False)
        self.home_btn.clicked.connect(self.on_home_clicked)
        layout.addWidget(self.home_btn)
        return group

    def create_measurement_group(self) -> QGroupBox:
        group = QGroupBox("測定操作")
        layout = QGridLayout(group)
        self.reset_btn = QPushButton("SQUIDカウントリセット")
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        layout.addWidget(self.reset_btn, 0, 0)

        self.measure_btn = QPushButton("測定")
        self.measure_btn.setEnabled(False)
        self.measure_btn.clicked.connect(self.on_measure_clicked)
        layout.addWidget(self.measure_btn, 0, 1)
        self.state_label = QLabel("ホーム完了後に測定できます")
        layout.addWidget(self.state_label, 1, 0, 1, 2)
        return group

    def create_result_group(self) -> QGroupBox:
        group = QGroupBox("測定結果")
        layout = QVBoxLayout(group)
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        layout.addWidget(self.result_display)
        return group

    def create_log_group(self) -> QGroupBox:
        group = QGroupBox("通信状況・エラーメッセージ")
        layout = QVBoxLayout(group)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)
        return group

    def connect_devices(self):
        """Connect the configured ports before allowing any device operation."""
        self.log_append(
            f"[進行] SQUID {self.settings.squid_port} と"
            f"サンプルハンドラー {self.settings.sample_handler_port} に接続します。"
        )
        if not self.serial_manager.connect(SQUID_NAME, self.settings.squid_port):
            self._connection_failed(
                f"SQUID ポート {self.settings.squid_port} への接続に失敗しました。"
            )
            return
        if not self.serial_manager.connect(
            SAMPLE_HANDLER_NAME, self.settings.sample_handler_port
        ):
            self._connection_failed(
                "サンプルハンドラーポート "
                f"{self.settings.sample_handler_port} への接続に失敗しました。"
            )
            return

        self.log_append("[進行] 両デバイスに接続しました。ハンドラーを確認します。")
        self.connection_result = ("timeout", "", "")
        worker = ConnectionCheckWorker(
            self.serial_manager, SAMPLE_HANDLER_NAME, self.handler
        )
        worker.check_started.connect(
            lambda command: self.log_append(
                f"[Sample Handler] >> 接続確認: {self.format_for_log(command)}"
            )
        )
        worker.check_finished.connect(self.on_connection_check_result)
        self._start_thread(worker, self.on_connection_check_thread_finished)

    def on_connection_check_result(self, status: str, message: str, raw: str):
        self.connection_result = (status, message, raw)

    def on_connection_check_thread_finished(self):
        self.worker_thread = None
        self.worker = None
        status, message, raw = self.connection_result
        self.log_append(f"[Sample Handler] << 接続確認: {raw or '(応答なし)'}")
        if status == "timeout":
            self._connection_failed(message or "サンプルハンドラーが応答しません。")
            return

        self.connection_verified = True
        if status == "warning":
            self.log_append(f"[警告] {message}")
            QMessageBox.warning(self, "接続確認の警告", message)
        else:
            self.log_append(f"[進行] {message}")

        self.start_operation("initialize")

    def _connection_failed(self, message: str):
        self.connection_verified = False
        self.serial_manager.disconnect_all()
        self.log_append(f"[エラー] {message}")
        self.statusBar().showMessage("接続できません")
        QMessageBox.critical(self, "接続エラー", message)
        self.refresh_controls()

    def on_home_clicked(self):
        if not self.connection_verified or self.active_operation:
            return
        self.start_operation("home")

    def on_measure_clicked(self):
        if not self.homed or self.faulted or self.active_operation:
            return
        self.start_operation("measure")

    def on_reset_clicked(self):
        if not self.homed or self.faulted or self.active_operation:
            return
        if self.serial_manager.send_command(SQUID_NAME, "ARC"):
            self.log_append("[SQUID] >> ARC (カウントリセット)")
        else:
            self.enter_fault("[SQUID] カウントリセットコマンドを送信できませんでした。")

    def start_operation(self, operation: str):
        self.operation_result = None
        if operation == "initialize":
            self.active_operation = operation
            self.refresh_controls()
            worker = SampleMeasurementWorker(
                self.serial_manager,
                self.handler,
                self.settings,
                self.flux_quanta,
                operation,
            )
        else:
            self.active_operation = operation
            if operation == "measure":
                self.state_label.setText("測定中")
            else:
                self.state_label.setText("ホーム動作中")
            self.refresh_controls()
            worker = SampleMeasurementWorker(
                self.serial_manager,
                self.handler,
                self.settings,
                self.flux_quanta,
                operation,
                self.current_position or 0,
            )

        worker.log_message.connect(self.log_append)
        worker.position_updated.connect(self.update_position)
        worker.results_cleared.connect(self.result_display.clear)
        worker.result_section.connect(self.display_result_section)
        worker.operation_succeeded.connect(self.on_operation_succeeded)
        worker.operation_failed.connect(self.on_operation_failed)
        self.statusBar().showMessage(
            "現在位置を確認しています" if operation == "initialize" else operation
        )
        self._start_thread(worker, self.on_operation_thread_finished)

    def on_operation_succeeded(self, operation: str, position: int):
        self.operation_result = (True, operation, position)

    def on_operation_failed(self, message: str):
        self.operation_result = (False, message, self.current_position or 0)

    def on_operation_thread_finished(self):
        self.worker_thread = None
        self.worker = None
        result = self.operation_result
        operation = self.active_operation
        self.active_operation = None
        if result is None:
            self.enter_fault("処理結果を受け取れませんでした。")
            return

        success, detail, position = result
        if not success:
            if operation == "initialize":
                self.enter_fault(f"現在位置を取得できませんでした: {detail}")
            else:
                self.enter_fault(detail)
            return

        if operation == "initialize":
            self.connection_verified = True
            self.homed = False
            self.faulted = False
            self.state_label.setText("ホーム動作が必要です")
            self.statusBar().showMessage("接続済み")
        elif operation == "home":
            self.homed = True
            self.faulted = False
            self.state_label.setText("ホーム完了")
            self.log_append("[進行] ホーム動作が正常に完了しました。測定可能です。")
            self.statusBar().showMessage("ホーム完了")
        elif operation == "measure":
            self.homed = True
            self.faulted = False
            self.state_label.setText("測定完了")
            self.statusBar().showMessage("測定完了")
        self.update_position(position)
        self.refresh_controls()

    def enter_fault(self, message: str):
        self.homed = False
        self.faulted = True
        self.state_label.setText("エラー: ホームボタンで復旧してください")
        self.statusBar().showMessage("エラー")
        self.log_append(f"[エラー] {message}")
        self.refresh_controls()
        QMessageBox.critical(self, "測定エラー", message)

    def refresh_controls(self):
        busy = self.active_operation is not None
        can_home = self.connection_verified and not busy
        can_operate = self.homed and not self.faulted and not busy
        self.home_btn.setEnabled(can_home)
        self.reset_btn.setEnabled(can_operate)
        self.measure_btn.setEnabled(can_operate)

    def update_position(self, position: int):
        self.current_position = position
        self.position_label.setText(f"現在位置: {position}")

    def display_result_section(self, title: str, values: dict):
        self.result_display.append(title)
        if title == "バックグラウンド補正後":
            for axis in ("X", "Y", "Z"):
                self.result_display.append(f"  {axis}: {values[axis]:.6g}")
            return
        for axis in ("X", "Y", "Z"):
            result = values[axis]
            self.result_display.append(
                f"  {axis}: count={result['count']}, analog={result['analog']:.6g}, "
                f"磁化={result['magnetization']:.6g}"
            )
        self.result_display.append("")

    def _start_thread(self, worker, on_thread_finished):
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(on_thread_finished)
        self.worker_thread = thread
        self.worker = worker
        thread.start()

    def format_for_log(self, payload: str) -> str:
        return payload.replace("\r", r"\r").replace("\n", r"\n")

    def log_append(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.wait()
        self.serial_manager.disconnect_all()
        event.accept()
