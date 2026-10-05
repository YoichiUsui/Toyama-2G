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

from PyQt6.QtCore import QObject, QThread, QTimer
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
from src.gui.connection_check_worker import ConnectionCheckWorker
from src.serial_manager import SerialManager

# 移動量の入力可能範囲 (issue の「必要な機能」の補足に記載の範囲)
MOVE_AMOUNT_INPUT_MIN = 0
MOVE_AMOUNT_INPUT_MAX = 20000

# 移動コマンド送信後、移動が終わるまで「移動が正常終了したか」「現在位置」を確認する頻度の
# デフォルト値・範囲。(アイドル中は確認しない: 確認コマンドと新規コマンドが衝突して
# 新規コマンドが受け付けられないことが実機テストで判明したため)
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

        # 接続確認と初期設定が成功し、操作を受け付けてよい状態か。
        # 接続確認でタイムアウトした場合などは False のままにして、操作を受け付けない。
        self.is_ready = False

        # 移動コマンドを送信してから、移動終了の応答が返るまでの間 True。
        self.is_moving = False

        # 処理実行中に緊急停止が押された場合、その処理が終わり次第すぐ停止を送るための印。
        self.pending_stop = False

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[QObject] = None

        # ワーカーから受け取った結果。スレッドが完全に終了してから使う。
        self.connection_check_result = ("timeout", "", "")
        self.sequence_success = False
        self.sequence_on_finished = None

        # 移動方向は問い合わせコマンドが存在しないため、最後に送信した内容を
        # ここで保持しておき、表示に利用する。
        self.last_known_direction_positive: Optional[bool] = None

        # 移動中だけ「%」「VP」を確認するためのタイマー。移動コマンド送信後に開始し、
        # 移動が終わったら止める。
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

        layout.addWidget(QLabel("ステータス確認間隔（秒・移動中のみ）:"), 1, 0)
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
        # 初期設定の移動方向に合わせて、入力欄の初期選択も揃えておく
        self.direction_combo.setCurrentText(
            "プラス" if SampleHandler.DIRECTION_POSITIVE_DEFAULT else "マイナス"
        )
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
        """選択したポートへ接続し、接続確認、初期設定の順に進める。"""
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

        # ポートを開けただけでは、サンプルハンドラーが繋がっている保証はない
        # (誤ったポートでも開ける)。接続確認コマンドの応答で確かめる。
        self.log_append(f"[進行] ポート {port} を開きました。サンプルハンドラーとの接続を確認します。")
        self.is_ready = False
        self.refresh_controls()
        self.start_connection_check()

    def start_connection_check(self):
        """接続確認コマンドを別スレッドで送信する。"""
        self.is_busy = True
        self.connection_check_result = ("timeout", "接続確認の結果を受け取れませんでした。", "")

        worker = ConnectionCheckWorker(
            self.serial_manager, self.DEVICE_NAME, self.handler
        )
        worker.check_started.connect(self.on_connection_check_started)
        worker.check_finished.connect(self.on_connection_check_result)
        self.start_worker_thread(worker, self.on_connection_check_thread_finished)

    def start_worker_thread(self, worker: QObject, on_thread_finished):
        """
        ワーカーを別スレッドで開始する。

        後続の処理 (on_thread_finished) は、ワーカーの完了通知ではなく
        「スレッドが完全に終了した後」に呼ぶ。完了通知の時点では、スレッドはまだ
        終了処理中であり、そこで次のスレッドを作って self.worker_thread を
        差し替えると、実行中の QThread が破棄されてアプリが異常終了する。
        """
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(on_thread_finished)

        self.worker_thread = thread
        self.worker = worker
        thread.start()

    def on_connection_check_started(self, command: str):
        self.log_append(f"[送信] {self.format_for_log(command)} (接続確認)")

    def on_connection_check_result(self, status: str, message: str, raw_text: str):
        """接続確認の結果を保存しておく。判定は、スレッド終了後に行う。"""
        self.connection_check_result = (status, message, raw_text)

    def on_connection_check_thread_finished(self):
        """接続確認のスレッドが終了した後、結果に応じて次の処理に進む。"""
        self.is_busy = False
        status, message, raw_text = self.connection_check_result
        self.log_append(f"[受信] {raw_text if raw_text else '(応答なし)'}")

        if status == "timeout":
            # 応答がない = サンプルハンドラーに繋がっていない可能性が高い。
            # 以降の操作を受け付けないよう、ポートを閉じて操作できない状態のままにする。
            self.log_append(f"[エラー] {message}")
            self.log_append(
                "[エラー] 接続トラブルと判断し、ポートを閉じました。"
                "ポートの選択や配線を確認してから、もう一度「選択＆接続」を押してください。"
            )
            self.serial_manager.disconnect(self.DEVICE_NAME)
            QMessageBox.critical(
                self,
                "接続トラブル",
                "サンプルハンドラーから応答がありませんでした。\n"
                "ポートが正しいか、接続を確認してください。",
            )
            return

        if status == "warning":
            # 応答は届いているので続行するが、気づけるよう警告を出す。
            self.log_append(f"[警告] {message}")
            QMessageBox.warning(self, "接続確認の警告", message)
        else:
            self.log_append(f"[進行] {message}")

        self.start_initial_setup()

    def start_initial_setup(self):
        """初期設定 (加速度・速度・移動方向) を送信する。現在位置は変更しない。"""
        self.log_append("[進行] 初期設定を開始します。")

        direction_text = "プラス" if SampleHandler.DIRECTION_POSITIVE_DEFAULT else "マイナス"
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
                f"移動方向を「{direction_text}」に設定",
                self.handler.cmd_set_direction(SampleHandler.DIRECTION_POSITIVE_DEFAULT),
            ),
            # 現在位置は書き換えず、装置が保持している値を表示に反映するだけにする
            ("現在位置を確認", self.handler.cmd_query_position()),
        ]
        self.run_command_sequence(init_steps, on_finished=self.after_initial_setup)

    def after_initial_setup(self, success: bool):
        """初期設定シーケンス完了後の処理。"""
        if success:
            self.log_append("[進行] 初期設定が完了しました。")
            self.is_ready = True
            self.refresh_controls()
        else:
            self.log_append(
                "[エラー] 初期設定が途中で失敗しました。"
                "上のログでどのステップまで成功したかを確認してください。"
            )

    def is_connected(self) -> bool:
        """サンプルハンドラーに接続済みかどうかを返す。"""
        return self.serial_manager.is_device_connected(self.DEVICE_NAME)

    def refresh_controls(self):
        """
        決定・移動・停止ボタンの有効/無効を現在の状態に合わせて更新する。

        - 接続確認・初期設定が済んでいない間は、すべて無効
        - 移動中は、新規コマンドの衝突を避けるため 決定・移動 を無効にし、停止だけ有効
        """
        self.decide_btn.setEnabled(self.is_ready and not self.is_moving)
        self.move_btn.setEnabled(self.is_ready and not self.is_moving)
        self.stop_btn.setEnabled(self.is_ready)

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
        """移動コマンド送信後の処理。移動が終わるまで状況確認を続ける。"""
        if not success:
            self.log_append("[エラー] 移動コマンドの送信に失敗しました。")
            return

        self.log_append(
            "[進行] 移動コマンドを送信しました。"
            "正常終了またはリミットスイッチの応答が返るまで状況確認を続けます。"
        )
        self.is_moving = True
        self.refresh_controls()
        self.poll_timer.start()

    def finish_moving(self, reason: str):
        """状況確認を止め、移動中の状態を終了する。"""
        if not self.is_moving:
            return
        self.poll_timer.stop()
        self.is_moving = False
        self.refresh_controls()
        self.log_append(f"[進行] 状況確認を終了しました ({reason})。")

    def on_stop_clicked(self):
        """緊急停止コマンドを送信する。"""
        if not self.is_connected():
            QMessageBox.warning(self, "エラー", "サンプルハンドラーに接続してください")
            return

        # 状況確認が停止コマンドと衝突しないよう、先に定期確認を止める
        self.poll_timer.stop()

        if self.is_busy:
            # 他のコマンドを送受信している最中に割り込むとシリアル通信が壊れるため、
            # その処理が終わった直後に停止を送る。
            self.log_append("[SYSTEM] 通信処理の完了を待って、すぐに緊急停止を送信します。")
            self.pending_stop = True
            return

        self.send_stop()

    def send_stop(self):
        """停止コマンドを送り、停止後の状態と位置を確認する。"""
        steps: List[CommandStep] = [
            ("緊急停止を実行", self.handler.cmd_stop()),
            ("停止後の移動状態を確認", self.handler.cmd_query_move_status()),
            ("停止後の現在位置を確認", self.handler.cmd_query_position()),
        ]
        self.run_command_sequence(steps, on_finished=self.after_stop)

    def after_stop(self, success: bool):
        """停止シーケンス後の処理。停止後は状況確認を続けず、操作を再び受け付ける。"""
        if success:
            self.log_append("[進行] 緊急停止を送信しました。")
        else:
            self.log_append("[エラー] 緊急停止の送信に失敗しました。")
        self.finish_moving("緊急停止")

    # ------------------------------------------------------------------
    # 移動中の状況確認
    # ------------------------------------------------------------------

    def on_poll_interval_changed(self, value: float):
        """ステータス確認間隔の変更を反映する。"""
        self.poll_timer.setInterval(int(value * 1000))

    def on_poll_tick(self):
        """移動中に、移動が終わったかと現在位置を確認する。"""
        if not self.is_connected() or not self.is_moving or self.is_busy:
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
        self.sequence_success = False
        self.sequence_on_finished = on_finished

        worker = CommandSequenceWorker(self.serial_manager, self.DEVICE_NAME, steps)
        worker.step_started.connect(self.on_step_started)
        worker.step_succeeded.connect(self.on_step_succeeded)
        worker.step_failed.connect(self.on_step_failed)
        worker.sequence_finished.connect(self.on_sequence_result)
        self.start_worker_thread(worker, self.on_sequence_thread_finished)

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

    def on_sequence_result(self, success: bool):
        """シーケンスの成否を保存しておく。後続処理は、スレッド終了後に行う。"""
        self.sequence_success = success

    def on_sequence_thread_finished(self):
        """シーケンスのスレッドが終了した後の処理。"""
        self.is_busy = False
        on_finished = self.sequence_on_finished
        self.sequence_on_finished = None
        if on_finished is not None:
            on_finished(self.sequence_success)

        # 処理中に緊急停止が押されていたら、ここで直ちに停止を送る
        if self.pending_stop and not self.is_busy:
            self.pending_stop = False
            self.send_stop()

    # ------------------------------------------------------------------
    # 表示の更新
    # ------------------------------------------------------------------

    def update_state_from_command(self, command: str, response: str):
        """送信したコマンド・受信した応答の内容に応じて画面上の表示を更新する。"""
        if command.startswith("A") and command[1:].isdigit():
            self.set_acceleration_display(SampleHandler.parse_numeric_response(command))
        elif command.startswith("M") and command[1:].isdigit():
            self.set_speed_display(SampleHandler.parse_numeric_response(command))
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
            # 正常終了・リミットスイッチ停止などの応答が返ったら、状況確認を終える
            code = response.strip()
            if code in SampleHandler.MOVE_FINISHED_CODES:
                self.finish_moving(SampleHandler.describe_move_status(code))

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
        self.pending_stop = False
        self.serial_manager.disconnect_all()
        try:
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
        except RuntimeError:
            # スレッドは既に終了・破棄済み (deleteLater 済み) なので、何もしなくてよい
            pass
        event.accept()
