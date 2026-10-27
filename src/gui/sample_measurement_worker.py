"""Background worker for homing and the single-sample measurement sequence."""

import math
import time
from typing import Callable, Dict

from PyQt6.QtCore import QObject, pyqtSignal

from src.device import SampleHandler
from src.measurement_settings import (
    MeasurementSettings,
    direction_and_amount,
    POSITION_MAX,
)
from src.serial_manager import SerialManager

SAMPLE_HANDLER = "Sample Handler"
SQUID = "SQUID"
HOME_SPEED = 500
HOME_SEEK_TIMEOUT_SEC = 100.0
HOME_RETRACT_TIMEOUT_SEC = 5.0
MEASUREMENT_MOVE_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 0.1
RESPONSE_TIMEOUT_SEC = 1.0


class SampleMeasurementWorker(QObject):
    """Perform one home or measurement operation without blocking the GUI."""

    log_message = pyqtSignal(str)
    position_updated = pyqtSignal(int)
    results_cleared = pyqtSignal()
    result_section = pyqtSignal(str, dict)
    operation_succeeded = pyqtSignal(str, int)
    operation_failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        manager: SerialManager,
        handler: SampleHandler,
        settings: MeasurementSettings,
        flux_quanta: Dict[str, float],
        operation: str,
        starting_position: int = 0,
    ):
        super().__init__()
        self.manager = manager
        self.handler = handler
        self.settings = settings
        self.flux_quanta = flux_quanta
        self.operation = operation
        self.starting_position = starting_position
        self.handler_moving = False
        self.move_start_position = None

    def run(self):
        """Run the selected operation and report all errors to the window."""
        try:
            if self.operation == "home":
                position = self._home()
                self.operation_succeeded.emit("home", position)
            elif self.operation == "measure":
                position = self._measure()
                self.operation_succeeded.emit("measure", position)
            elif self.operation == "initialize":
                position = self._initialize()
                self.operation_succeeded.emit("initialize", position)
            else:
                raise ValueError(f"Unknown operation: {self.operation}")
        except Exception as error:
            if self.handler_moving:
                self._stop_handler()
            self.operation_failed.emit(
                str(error) or f"予期しない処理エラーが発生しました: {type(error).__name__}"
            )
        finally:
            self.finished.emit()

    def _send_handler(self, command: str, description: str) -> str:
        self.log_message.emit(f"[Sample Handler] >> {description}: {command}")
        if not self.manager.send_command(SAMPLE_HANDLER, command):
            raise ConnectionError(f"サンプルハンドラーへの送信に失敗しました: {command}")
        return self.manager.receive_response(
            SAMPLE_HANDLER, timeout=RESPONSE_TIMEOUT_SEC
        )

    def _query_status(self) -> str:
        response = self._send_handler(
            self.handler.cmd_query_move_status(), "移動状態確認"
        ).strip()
        if not response:
            raise ConnectionError("サンプルハンドラーの移動状態応答がありません。")
        self.log_message.emit(f"[Sample Handler] << 移動状態: {response}")
        return response

    def _query_position(self) -> int:
        response = self._send_handler(
            self.handler.cmd_query_position(), "現在位置確認"
        )
        position = self.handler.parse_numeric_response(response)
        if position is None:
            raise ConnectionError(
                f"サンプルハンドラーの現在位置を読み取れません: {response!r}"
            )
        position %= POSITION_MAX + 1
        self.position_updated.emit(position)
        self.log_message.emit(f"[Sample Handler] << 現在位置: {position}")
        return position

    def _initialize(self) -> int:
        """Apply the helper's safe defaults and display the actual current position."""
        self._send_handler(
            self.handler.cmd_set_acceleration(SampleHandler.ACCELERATION_DEFAULT),
            "加速度設定",
        )
        self._send_handler(
            self.handler.cmd_set_speed(self.settings.moving_velocity),
            "通常移動速度設定",
        )
        self._send_handler(
            self.handler.cmd_set_direction(False), "初期移動方向設定"
        )
        return self._query_position()

    def _start_move(self, direction_positive: bool, amount: int):
        if not 0 <= amount <= POSITION_MAX:
            raise ValueError(f"移動量が範囲外です: {amount}")
        # 移動開始前の位置を記録し、%の「5」が前回の完了状態でないか後で確認する。
        self.move_start_position = self._query_position()
        self._send_handler(
            self.handler.cmd_set_direction(direction_positive), "移動方向設定"
        )
        self._send_handler(self.handler.cmd_set_move_amount(amount), "移動量設定")
        self.handler_moving = True
        self._send_handler(self.handler.cmd_execute_move(), "移動開始")

    def _still_at_move_start(self) -> bool:
        """True if the handler position is unchanged since the move command was sent."""
        if self.move_start_position is None:
            return False
        return self._query_position() == self.move_start_position

    def _wait_for_move(self, deadline: float, successful_codes=("5",)):
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("サンプルハンドラーの移動がタイムアウトしました。")
            status = self._query_status()
            if status in successful_codes:
                if status == "5" and self._still_at_move_start():
                    # 位置が動いていないので、この5は前回の完了状態とみなして待ち続ける。
                    self.log_message.emit(
                        "[警告] %が5を返しましたが位置が未変化のため、移動開始を待ちます。"
                    )
                    time.sleep(POLL_INTERVAL_SEC)
                    continue
                self.handler_moving = False
                return status
            if status in ("2", "7"):
                self.handler_moving = False
                raise ConnectionError(
                    f"移動が異常終了しました: {self.handler.describe_move_status(status)}"
                )
            if status != "G":
                raise ConnectionError(f"移動状態の応答が不正です: {status!r}")
            time.sleep(POLL_INTERVAL_SEC)

    def _move_displacement(
        self,
        displacement: int,
        timeout_sec: float,
        description: str,
    ) -> int:
        """Move by signed travel, splitting only when the device limit requires it."""
        positive, remaining = direction_and_amount(displacement)
        if remaining == 0:
            self.log_message.emit(f"[進行] {description}: 移動量は0です。")
            return self._query_position()

        deadline = time.monotonic() + timeout_sec
        while remaining:
            amount = min(remaining, POSITION_MAX)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{description}が{timeout_sec:g}秒で完了しませんでした。")
            self.log_message.emit(
                f"[進行] {description}: {'+' if positive else '-'}方向へ{amount}移動します。"
            )
            self._start_move(positive, amount)
            self._wait_for_move(deadline)
            remaining -= amount
        return self._query_position()

    def _home(self) -> int:
        self.manager.clear_input_buffer(SAMPLE_HANDLER)
        self.log_message.emit("[進行] ホーム側リミットスイッチを探します。")
        self._send_handler(
            self.handler.cmd_set_direction(self.settings.home.side == "+"),
            "ホーム方向設定",
        )
        self._send_handler(self.handler.cmd_set_speed(HOME_SPEED), "ホーム速度設定")
        self.handler_moving = True
        self._send_handler(self.handler.cmd_move_until_limit(), "リミットスイッチ検出")
        seek_deadline = time.monotonic() + HOME_SEEK_TIMEOUT_SEC
        while True:
            if time.monotonic() >= seek_deadline:
                raise TimeoutError("100秒以内にホーム側リミットスイッチへ到達しませんでした。")
            status = self._query_status()
            if status == "1":
                # すでにリミットスイッチに当たっている場合、Hl直後の%に1(illegal command)が
                # 返ることがある。もう一度%を送り、7なら正常、再度1ならエラーとする。
                self.log_message.emit("[警告] %に1が返りました。もう一度状態を確認します。")
                time.sleep(POLL_INTERVAL_SEC)
                status = self._query_status()
                if status == "1":
                    self.handler_moving = False
                    raise ConnectionError(
                        "ホーム動作中の%に対し、2回続けて1(illegal command)が返りました。"
                    )
            if status == "7":
                self.handler_moving = False
                break
            if status in ("2", "5"):
                self.handler_moving = False
                raise ConnectionError(
                    "ホーム側リミットスイッチ到達前に移動が終了しました: "
                    f"{self.handler.describe_move_status(status)}"
                )
            if status != "G":
                raise ConnectionError(f"移動状態の応答が不正です: {status!r}")
            time.sleep(POLL_INTERVAL_SEC)

        retract_positive = self.settings.home.side != "+"
        self._send_handler(
            self.handler.cmd_set_direction(retract_positive), "ホーム位置方向設定"
        )
        self._send_handler(
            self.handler.cmd_set_move_amount(self.settings.home.position),
            "ホーム位置移動量設定",
        )
        self.handler_moving = True
        self.move_start_position = self._query_position()
        self._send_handler(self.handler.cmd_execute_move(), "ホーム位置へ移動")
        self._wait_for_move(time.monotonic() + HOME_RETRACT_TIMEOUT_SEC)
        self._send_handler(
            self.handler.cmd_set_speed(self.settings.moving_velocity),
            "通常移動速度設定",
        )
        return self._query_position()

    def _measure_axis(self, axis: str, flux_quanta: float) -> Dict[str, int | float]:
        count = self._latch_and_send(axis, "LC", "SC", int)
        analog = self._latch_and_send(axis, "LD", "SD", float)
        magnetization = (count + analog) * flux_quanta
        return {
            "count": count,
            "analog": analog,
            "magnetization": magnetization,
        }

    def _latch_and_send(
        self,
        axis: str,
        latch: str,
        send: str,
        convert: Callable[[str], int | float],
    ) -> int | float:
        latch_command = f"{axis}{latch}"
        self.log_message.emit(f"[SQUID] >> {latch_command}")
        if not self.manager.send_command(SQUID, latch_command):
            raise ConnectionError(f"SQUIDへの送信に失敗しました: {latch_command}")

        send_command = f"{axis}{send}"
        self.log_message.emit(f"[SQUID] >> {send_command}")
        if not self.manager.send_command(SQUID, send_command):
            raise ConnectionError(f"SQUIDへの送信に失敗しました: {send_command}")
        response = self.manager.receive_response(SQUID)
        if not response:
            raise ConnectionError(f"SQUIDの応答がありません: {send_command}")
        try:
            value = convert(response.strip())
        except ValueError as error:
            raise ValueError(
                f"SQUIDの応答を数値に変換できません ({send_command}): {response!r}"
            ) from error
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"SQUIDのアナログ応答が有限値ではありません: {response!r}")
        self.log_message.emit(f"[SQUID] << {send_command}: {value}")
        return value

    def _measure(self) -> int:
        self._send_handler(
            self.handler.cmd_set_speed(self.settings.measurement_velocity),
            "測定速度設定",
        )
        self.results_cleared.emit()

        background_position = self._move_displacement(
            self.settings.background_displacement,
            MEASUREMENT_MOVE_TIMEOUT_SEC,
            "バックグラウンド位置への移動",
        )
        if not self.manager.send_command(SQUID, "ARC"):
            raise ConnectionError("SQUIDカウントをリセットできませんでした。")
        self.log_message.emit("[SQUID] >> ARC (カウントリセット)")
        background = {
            axis: self._measure_axis(axis, self.flux_quanta[axis])
            for axis in ("X", "Y", "Z")
        }
        self.result_section.emit("バックグラウンド測定", background)

        sample_position = self._move_displacement(
            self.settings.background_to_sample_displacement,
            MEASUREMENT_MOVE_TIMEOUT_SEC,
            "サンプル位置への移動",
        )
        sample = {
            axis: self._measure_axis(axis, self.flux_quanta[axis])
            for axis in ("X", "Y", "Z")
        }
        self.result_section.emit("サンプル測定", sample)

        corrected = {
            axis: sample[axis]["magnetization"]
            - background[axis]["magnetization"]
            for axis in ("X", "Y", "Z")
        }
        self.result_section.emit("バックグラウンド補正後", corrected)

        # Reverse the total home-to-sample travel; this restores the pre-measurement position.
        start_position = self._move_displacement(
            -self.settings.sample_displacement,
            MEASUREMENT_MOVE_TIMEOUT_SEC,
            "測定開始位置への復帰",
        )
        if start_position != self.starting_position:
            raise ConnectionError(
                "測定開始位置へ正確に戻れませんでした。"
                f"開始時: {self.starting_position} / 復帰後: {start_position}"
            )
        self.log_message.emit(
            f"[進行] 測定開始位置へ復帰しました (バックグラウンド位置: {background_position}, "
            f"サンプル測定後の位置: {sample_position})。"
        )
        return start_position

    def _stop_handler(self):
        """Stop a move after a failure without attempting to return to any position."""
        try:
            if not self.manager.send_command(SAMPLE_HANDLER, self.handler.cmd_stop()):
                self.log_message.emit("[エラー] サンプルハンドラーへのQ送信に失敗しました。")
        except Exception as error:
            self.log_message.emit(f"[エラー] 停止コマンドの送信中に失敗しました: {error}")
        finally:
            self.handler_moving = False
