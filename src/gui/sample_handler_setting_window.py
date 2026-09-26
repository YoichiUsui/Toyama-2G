"""
サンプルハンドラーの移動量設定補助ツール。

ステップ数と実際の移動距離との関係を実測するために、サンプルハンドラーの
ポート接続・初期設定・移動指示・緊急停止・状態確認をまとめて行える GUI。
レイアウトの例は docs/移動量設定補助画面.jpg を参照。

注意: 実機との通信テストはこのツールの作成時点では行えていない。
そのため、通信の各ステップの進行状況をメッセージ欄に逐次表示し、
実機テストの際にどの段階で失敗したかを把握しやすくしている。
"""

from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.device import SampleHandler
from src.gui.command_sequence_worker import CommandSequenceWorker, CommandStep
from src.serial_manager import SerialManager

# 移動量の入力可能範囲 (issue の「必要な機能」の補足に記載の範囲)
MOVE_AMOUNT_INPUT_MIN = 0
MOVE_AMOUNT_INPUT_MAX = 20000

# アイドル状態時に「移動が正常終了したか」「現在位置」を確認する頻度のデフォルト値・範囲
DEFAULT_POLL_INTERVAL_SEC = 1.0
POLL_INTERVAL_MIN_SEC = 0.1
POLL_INTERVAL_MAX_SEC = 60.0


class SampleHandlerSettingWindow(QMainWindow):
    """サンプルハンドラーの移動量設定を補助するためのウィンドウ。"""

    DEVICE_NAME = "Sample Handler"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("サンプルハンドラー 移動量設定補助")
        self.setGeometry(100, 100, 700, 700)

        self.serial_manager = SerialManager()
        # コマンド文字列の組み立て・応答の解析だけに使うインスタンス
        # (実際の送受信は self.serial_manager 経由で行う)
        self.handler = SampleHandler()

        # 複数コマンドを順番に送信する処理が同時に走らないようにするフラグ。
        # True の間は新しい操作の開始をスキップする。
        self.is_busy = False

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[CommandSequenceWorker] = None

        # 移動方向は問い合わせコマンドが存在しないため、最後に送信した内容を
        # ここで保持しておき、表示に利用する。
        self.last_known_direction_positive: Optional[bool] = None

        # アイドル状態時に「%」「VP」を確認するためのタイマー。
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(int(DEFAULT_POLL_INTERVAL_SEC * 1000))
        self.poll_timer.timeout.connect(self.on_poll_tick)

        self.init_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def init_ui(self):
        """ウィンドウ全体のレイアウトを構築する。"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        main_layout.addWidget(self.create_connection_group())
        main_layout.addWidget(self.create_current_setting_group())
        main_layout.addWidget(self.create_status_group())
        main_layout.addWidget(self.create_move_group())
        main_layout.addWidget(self.create_message_group())

        self.statusBar().showMessage("Ready")

    def create_connection_group(self) -> QGroupBox:
        """ポート選択・接続の欄を作成する。"""
        group = QGroupBox("ポート接続")
        layout = QHBoxLayout()

        layout.addWidget(QLabel("ポート:"))
        self.port_combo = QComboBox()
        self.port_combo.addItems(self.serial_manager.list_ports())
        layout.addWidget(self.port_combo)

        self.connect_btn = QPushButton("選択＆接続")
        self.connect_btn.clicked.connect(self.on_select_and_connect)
        layout.addWidget(self.connect_btn)

        group.setLayout(layout)
        return group

    def create_current_setting_group(self) -> QGroupBox:
        """現在のサンプルハンドラーの設定 (加速度・速度・移動方向) の表示欄を作成する。"""
        group = QGroupBox("現在のサンプルハンドラーの設定")
        layout = QGridLayout()

        self.acceleration_label = QLabel("加速度: -")
        self.speed_label = QLabel("速度: -")
        self.direction_label = QLabel("移動方向: -")
        layout.addWidget(self.acceleration_label, 0, 0)
        layout.addWidget(self.speed_label, 0, 1)
        layout.addWidget(self.direction_label, 0, 2)

        layout.addWidget(QLabel("ステータス確認間隔（秒）:"), 1, 0)
        self.poll_interval_input = QDoubleSpinBox()
        self.poll_interval_input.setRange(POLL_INTERVAL_MIN_SEC, POLL_INTERVAL_MAX_SEC)
        self.poll_interval_input.setSingleStep(0.1)
        self.poll_interval_input.setValue(DEFAULT_POLL_INTERVAL_SEC)
        self.poll_interval_input.valueChanged.connect(self.on_poll_interval_changed)
        layout.addWidget(self.poll_interval_input, 1, 1)

        group.setLayout(layout)
        return group

    def create_status_group(self) -> QGroupBox:
        """現在位置・移動終了状態の表示欄を作成する。"""
        group = QGroupBox("移動状態")
        layout = QHBoxLayout()

        self.position_label = QLabel("現在位置: -")
        layout.addWidget(self.position_label)

        self.move_status_label = QLabel("移動状態: -")
        layout.addWidget(self.move_status_label)

        group.setLayout(layout)
        return group

    def create_move_group(self) -> QGroupBox:
        """移動量・移動方向の入力と、決定・移動・停止ボタンの欄を作成する。"""
        group = QGroupBox("移動の設定・実行")
        layout = QGridLayout()

        layout.addWidget(QLabel("移動量:"), 0, 0)
        self.move_amount_input = QSpinBox()
        self.move_amount_input.setRange(MOVE_AMOUNT_INPUT_MIN, MOVE_AMOUNT_INPUT_MAX)
        layout.addWidget(self.move_amount_input, 0, 1)

        layout.addWidget(QLabel("移動方向:"), 1, 0)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["プラス", "マイナス"])
        layout.addWidget(self.direction_combo, 1, 1)

        self.decide_btn = QPushButton("決定")
        self.decide_btn.setEnabled(False)
        self.decide_btn.clicked.connect(self.on_decide_clicked)
        layout.addWidget(self.decide_btn, 1, 2)

        self.move_btn = QPushButton("移動")
        self.move_btn.setEnabled(False)
        self.move_btn.clicked.connect(self.on_move_clicked)
        layout.addWidget(self.move_btn, 2, 0)

        self.stop_btn = QPushButton("緊急停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("background-color: #d9534f; color: white;")
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        layout.addWidget(self.stop_btn, 2, 1)

        group.setLayout(layout)
        return group

    def create_message_group(self) -> QGroupBox:
        """進行・エラーメッセージの表示欄を作成する。"""
        group = QGroupBox("進行・エラーメッセージ")
        layout = QVBoxLayout()

        self.message_display = QTextEdit()
        self.message_display.setReadOnly(True)
        layout.addWidget(self.message_display)

        group.setLayout(layout)
        return group

    # ------------------------------------------------------------------
    # 接続処理
    # ------------------------------------------------------------------

    def on_select_and_connect(self):
        """選択したポートへ接続し、続けて初期設定を行う。"""
        if self.is_busy:
            self.log_append("[SYSTEM] 他の処理が実行中のため、接続操作をスキップしました。")
            return

        if self.is_connected():
            self.log_append("[SYSTEM] 既に接続されています。")
            return

        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "エラー", "ポートを選択してください")
            return

        self.log_append(f"[進行] ポート {port} への接続を試みます...")

        if not self.serial_manager.connect(self.DEVICE_NAME, port):
            self.log_append(f"[エラー] ポート {port} への接続に失敗しました。")
            QMessageBox.critical(self, "接続エラー", f"{port} への接続に失敗しました")
            return

        self.log_append(f"[進行] ポート {port} に接続しました。初期設定を開始します。")

        init_steps: List[CommandStep] = [
            (
                f"加速度をデフォルト値({SampleHandler.ACCELERATION_DEFAULT})に設定",
                self.handler.cmd_set_acceleration(SampleHandler.ACCELERATION_DEFAULT),
            ),
            (
                f"速度をデフォルト値({SampleHandler.SPEED_DEFAULT})に設定",
                self.handler.cmd_set_speed(SampleHandler.SPEED_DEFAULT),
            ),
            (
                "現在位置を0に設定",
                self.handler.cmd_set_current_position(SampleHandler.POSITION_DEFAULT),
            ),
            ("移動方向を「プラス」に設定", self.handler.cmd_set_direction(True)),
        ]
        self.run_command_sequence(init_steps, on_finished=self.after_initial_setup)

    def after_initial_setup(self, success: bool):
        """初期設定シーケンス完了後の処理。"""
        if success:
            self.log_append("[進行] 初期設定が完了しました。")
            self.set_controls_enabled(True)
            self.poll_timer.start()
        else:
            self.log_append(
                "[エラー] 初期設定が途中で失敗しました。"
                "上のログでどのステップまで成功したかを確認してください。"
            )

    def is_connected(self) -> bool:
        """サンプルハンドラーに接続済みかどうかを返す。"""
        return self.serial_manager.is_device_connected(self.DEVICE_NAME)

    def set_controls_enabled(self, enabled: bool):
        """決定・移動・停止ボタンの有効/無効を切り替える。"""
        self.decide_btn.setEnabled(enabled)
        self.move_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 移動の設定・実行・停止
    # ------------------------------------------------------------------

    def on_decide_clicked(self):
        """入力された移動量・移動方向をサンプルハンドラーに設定する。"""
        if not self.is_connected():
            QMessageBox.warning(self, "エラー", "サンプルハンドラーに接続してください")
            return

        amount = self.move_amount_input.value()
        is_positive = self.direction_combo.currentText() == "プラス"

        steps: List[CommandStep] = [
            (f"移動量を{amount}に設定", self.handler.cmd_set_move_amount(amount)),
            (
                f"移動方向を「{'プラス' if is_positive else 'マイナス'}」に設定",
                self.handler.cmd_set_direction(is_positive),
            ),
        ]
        self.run_command_sequence(steps)

    def on_move_clicked(self):
        """設定済みの移動量・移動方向で移動を実行する。"""
        if not self.is_connected():
            QMessageBox.warning(self, "エラー", "サンプルハンドラーに接続してください")
            return

        steps: List[CommandStep] = [("移動を実行", self.handler.cmd_execute_move())]
        self.run_command_sequence(steps, on_finished=self.after_move)

    def after_move(self, success: bool):
        """移動コマンド送信後の処理。実際の移動完了はステータス確認により後追いで分かる。"""
        if success:
            self.log_append(
                "[進行] 移動コマンドを送信しました。"
                "移動の完了状況はステータス確認により追って表示されます。"
            )
        else:
            self.log_append("[エラー] 移動コマンドの送信に失敗しました。")

    def on_stop_clicked(self):
        """緊急停止コマンドを送信する。"""
        if not self.is_connected():
            QMessageBox.warning(self, "エラー", "サンプルハンドラーに接続してください")
            return

        steps: List[CommandStep] = [("緊急停止を実行", self.handler.cmd_stop())]
        self.run_command_sequence(steps)

    # ------------------------------------------------------------------
    # アイドル状態時のステータス確認
    # ------------------------------------------------------------------

    def on_poll_interval_changed(self, value: float):
        """ステータス確認間隔の変更を反映する。"""
        self.poll_timer.setInterval(int(value * 1000))

    def on_poll_tick(self):
        """アイドル状態時に、移動が正常終了したかと現在位置を確認する。"""
        if not self.is_connected() or self.is_busy:
            return

        steps: List[CommandStep] = [
            ("移動状態を確認", self.handler.cmd_query_move_status()),
            ("現在位置を確認", self.handler.cmd_query_position()),
        ]
        self.run_command_sequence(steps)

    # ------------------------------------------------------------------
    # コマンド送信の共通処理
    # ------------------------------------------------------------------

    def run_command_sequence(
        self, steps: List[CommandStep], on_finished=None
    ):
        """
        (説明文, コマンド) のリストを順番に送信する。

        既に他のシーケンスが実行中の場合、シリアルポートへの同時アクセスを
        避けるためにこの操作はスキップされる。

        Args:
            steps: 送信するステップのリスト
            on_finished: 全ステップ完了後に呼び出すコールバック (成功したかを bool で受け取る)
        """
        if self.is_busy:
            self.log_append("[SYSTEM] 現在別の処理が実行中のため、この操作はスキップされました。")
            return

        if not steps:
            return

        self.is_busy = True

        self.worker_thread = QThread()
        self.worker = CommandSequenceWorker(self.serial_manager, self.DEVICE_NAME, steps)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.step_started.connect(self.on_step_started)
        self.worker.step_succeeded.connect(self.on_step_succeeded)
        self.worker.step_failed.connect(self.on_step_failed)
        self.worker.sequence_finished.connect(
            lambda success: self.on_sequence_finished(success, on_finished)
        )
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def on_step_started(self, index: int, description: str):
        self.log_append(f"[進行] {description} ...")

    def on_step_succeeded(self, index: int, command: str, response: str):
        self.log_append(f"[送信] {self.format_for_log(command)}")
        self.log_append(f"[受信] {response if response else '(応答なし)'}")
        self.update_state_from_command(command, response)

    def on_step_failed(self, index: int, command: str, error: str):
        self.log_append(
            f"[エラー] コマンド {self.format_for_log(command)} の送信に失敗しました: {error}"
        )

    def on_sequence_finished(self, success: bool, on_finished):
        self.is_busy = False
        if on_finished is not None:
            on_finished(success)

    # ------------------------------------------------------------------
    # 表示の更新
    # ------------------------------------------------------------------

    def update_state_from_command(self, command: str, response: str):
        """送信したコマンド・受信した応答の内容に応じて画面上の表示を更新する。"""
        if command.startswith("A") and command[1:].isdigit():
            self.set_acceleration_display(SampleHandler.parse_numeric_response(command))
        elif command.startswith("B") and command[1:].isdigit():
            self.set_speed_display(SampleHandler.parse_numeric_response(command))
        elif command.startswith("Z") and command[1:].isdigit():
            self.set_position_display(SampleHandler.parse_numeric_response(command))
        elif command in ("+", "-"):
            self.set_direction_display(command == "+")
        elif command == self.handler.cmd_query_acceleration():
            self.set_acceleration_display(SampleHandler.parse_numeric_response(response))
        elif command == self.handler.cmd_query_speed():
            self.set_speed_display(SampleHandler.parse_numeric_response(response))
        elif command == self.handler.cmd_query_position():
            self.set_position_display(SampleHandler.parse_numeric_response(response))
        elif command == self.handler.cmd_query_move_status():
            self.set_move_status_display(response)

    def set_acceleration_display(self, value: Optional[int]):
        self.acceleration_label.setText(f"加速度: {value if value is not None else '-'}")

    def set_speed_display(self, value: Optional[int]):
        self.speed_label.setText(f"速度: {value if value is not None else '-'}")

    def set_direction_display(self, is_positive: bool):
        self.last_known_direction_positive = is_positive
        self.direction_label.setText(f"移動方向: {'プラス' if is_positive else 'マイナス'}")

    def set_position_display(self, value: Optional[int]):
        self.position_label.setText(f"現在位置: {value if value is not None else '-'}")

    def set_move_status_display(self, response: str):
        self.move_status_label.setText(
            f"移動状態: {SampleHandler.describe_move_status(response)}"
        )

    # ------------------------------------------------------------------
    # 共通ユーティリティ
    # ------------------------------------------------------------------

    def format_for_log(self, payload: str) -> str:
        """制御文字をログ上で見える形にして返す。"""
        return payload.replace("\r", r"\r").replace("\n", r"\n")

    def log_append(self, message: str):
        """進行・エラーメッセージ欄にタイムスタンプ付きでメッセージを追加する。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.message_display.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        """ウィンドウを閉じるときに、タイマーとスレッドと接続を後片付けする。"""
        self.poll_timer.stop()
        self.serial_manager.disconnect_all()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()
