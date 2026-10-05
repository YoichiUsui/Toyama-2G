"""
サンプルハンドラーへの接続確認を行うワーカー。

ポートを開いただけでは、そのポートに本当にサンプルハンドラーが繋がっているかは
分からない (誤ったポートを選んでも開くことはできる)。そこで接続確認コマンドを
送り、期待どおりの応答が返るかで判断する。
GUI スレッドをブロックしないよう QThread 上で実行することを想定している。
"""

from PyQt6.QtCore import QObject, pyqtSignal

from src.device import SampleHandler
from src.serial_manager import SerialManager


class ConnectionCheckWorker(QObject):
    """接続確認コマンドを送り、応答を判定するワーカー。"""

    # 引数: (送信したコマンド) 送信直前に発行
    check_started = pyqtSignal(str)
    # 引数: (判定 "ok"/"warning"/"timeout", 説明文, 受信した生データの表示用文字列)
    check_finished = pyqtSignal(str, str, str)
    # スレッド終了処理用
    finished = pyqtSignal()

    def __init__(
        self,
        manager: SerialManager,
        device_name: str,
        handler: SampleHandler,
        response_timeout: float = 1.0,
    ):
        """
        Args:
            manager: 送受信に使う SerialManager インスタンス
            device_name: 対象デバイス名 (例: "Sample Handler")
            handler: コマンド文字列・応答判定を持つ SampleHandler インスタンス
            response_timeout: 無通信とみなす秒数
        """
        super().__init__()
        self.manager = manager
        self.device_name = device_name
        self.handler = handler
        self.response_timeout = response_timeout

    def run(self):
        """接続確認コマンドを送信し、応答を判定する。"""
        command = self.handler.CONNECTION_CHECK_COMMAND
        try:
            # 前回の通信の残りが応答に混ざらないよう、先に受信バッファを空にする
            self.manager.clear_input_buffer(self.device_name)

            self.check_started.emit(command)
            if not self.manager.send_command(self.device_name, command):
                self.check_finished.emit("timeout", "接続確認コマンドの送信に失敗しました。", "")
                return

            raw = self.manager.receive_raw(
                self.device_name,
                expected_line_count=len(self.handler.CONNECTION_CHECK_EXPECTED_LINES),
                timeout=self.response_timeout,
            )
            status, message = self.handler.check_connection_response(raw)
            self.check_finished.emit(status, message, repr(raw))
        except Exception as e:
            self.check_finished.emit("timeout", f"接続確認中に例外が発生しました: {e}", "")
        finally:
            self.finished.emit()
