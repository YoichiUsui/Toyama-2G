"""
複数のコマンドを順番に送信し、各ステップの結果を逐次通知するワーカー。

シリアル通信は応答待ちでブロッキングになりうるため、GUI スレッドを
フリーズさせないよう QThread 上でこのワーカーを実行することを想定している。
1つでもステップが失敗した場合は、その時点で残りのステップを打ち切る。
"""

from typing import List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from src.serial_manager import SerialManager

# 1ステップの内容: (ログ表示用の説明文, 送信するコマンド文字列)
CommandStep = Tuple[str, str]


class CommandSequenceWorker(QObject):
    """デバイスへ一連のコマンドを順番に送信するワーカー。"""

    # 引数: (ステップ番号, ステップの説明) ステップの送信を開始したときに発行
    step_started = pyqtSignal(int, str)
    # 引数: (ステップ番号, 送信したコマンド, 受信した応答) 送受信に成功したときに発行
    step_succeeded = pyqtSignal(int, str, str)
    # 引数: (ステップ番号, 送信しようとしたコマンド, エラー内容) 送信に失敗したときに発行
    step_failed = pyqtSignal(int, str, str)
    # 引数: 全ステップが成功したかどうか
    sequence_finished = pyqtSignal(bool)
    # スレッド終了処理用
    finished = pyqtSignal()

    def __init__(
        self,
        manager: SerialManager,
        device_name: str,
        steps: List[CommandStep],
        response_timeout: Optional[float] = 1.0,
    ):
        """
        Args:
            manager: 送受信に使う SerialManager インスタンス
            device_name: 対象デバイス名 (例: "Sample Handler")
            steps: 先頭から順番に送信する (説明文, コマンド文字列) のリスト
            response_timeout: 各コマンドの応答待ちタイムアウト秒数
        """
        super().__init__()
        self.manager = manager
        self.device_name = device_name
        self.steps = steps
        self.response_timeout = response_timeout

    def run(self):
        """ステップを先頭から順番に実行する。1つでも失敗したらそこで打ち切る。"""
        all_succeeded = True

        for index, (description, command) in enumerate(self.steps):
            self.step_started.emit(index, description)

            if not self.manager.send_command(self.device_name, command):
                self.step_failed.emit(index, command, "コマンドの送信に失敗しました")
                all_succeeded = False
                break

            response = self.manager.receive_response(
                self.device_name, timeout=self.response_timeout
            )
            self.step_succeeded.emit(index, command, response)

        self.sequence_finished.emit(all_succeeded)
        self.finished.emit()
