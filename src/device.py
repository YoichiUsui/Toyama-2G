"""
Serial device communication module.
Defines base class and device-specific implementations for serial communication.
"""

import serial
import time
from abc import ABC, abstractmethod
from typing import Optional


class SerialDevice(ABC):
    """Base class for serial devices with common communication parameters."""

    # Common communication parameters
    BAUD_RATE = 1200
    PARITY = serial.PARITY_NONE
    STOPBITS = serial.STOPBITS_ONE
    BYTESIZE = serial.EIGHTBITS
    TIMEOUT = 1.0  # 1 second timeout

    def __init__(self, device_name: str):
        """
        Initialize the serial device.

        Args:
            device_name: Name of the device (e.g., 'Sample Handler')
        """
        self.device_name = device_name
        self.port: Optional[str] = None
        self.serial_port: Optional[serial.Serial] = None

    def connect(self, port: str) -> bool:
        """
        Connect to the device on the specified port.

        Args:
            port: Serial port name (e.g., 'COM1')

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=self.BAUD_RATE,
                parity=self.PARITY,
                stopbits=self.STOPBITS,
                bytesize=self.BYTESIZE,
                timeout=self.TIMEOUT,
            )
            self.port = port
            time.sleep(0.5)  # Wait for device to stabilize
            return True
        except serial.SerialException as e:
            print(f"Failed to connect to {self.device_name} on {port}: {e}")
            return False

    def disconnect(self) -> bool:
        """
        Disconnect from the device.

        Returns:
            True if disconnection successful, False otherwise
        """
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                self.port = None
                return True
            return False
        except serial.SerialException as e:
            print(f"Failed to disconnect from {self.device_name}: {e}")
            return False

    def is_connected(self) -> bool:
        """Check if device is currently connected."""
        return self.serial_port is not None and self.serial_port.is_open

    def normalize_command(self, command: str) -> str:
        """Normalize a command string before sending it to the device."""
        return command

    def send_command(self, command: str) -> bool:
        """
        Send a command to the device.

        Args:
            command: Command string to send

        Returns:
            True if send successful, False otherwise
        """
        if not self.is_connected():
            print(f"Device {self.device_name} is not connected")
            return False

        try:
            payload = self.normalize_command(command)
            self.serial_port.write(payload.encode())
            return True
        except serial.SerialException as e:
            print(f"Failed to send command to {self.device_name}: {e}")
            return False

    def receive_response(self, timeout: Optional[float] = None) -> str:
        """
        Receive response from the device.

        Args:
            timeout: Read timeout in seconds (uses device default if None)

        Returns:
            Response string, or empty string if no response
        """
        if not self.is_connected():
            print(f"Device {self.device_name} is not connected")
            return ""

        try:
            original_timeout = self.serial_port.timeout
            if timeout is not None:
                self.serial_port.timeout = timeout

            response = b""
            start_time = time.time()
            while True:
                byte = self.serial_port.read(1)
                if not byte:
                    break
                response += byte
                # Check for common terminators
                if response.endswith(b"\r\n") or response.endswith(b"\r"):
                    break
                # Simple timeout check
                if time.time() - start_time > (timeout or self.TIMEOUT):
                    break

            if timeout is not None:
                self.serial_port.timeout = original_timeout

            return response.decode(errors="ignore").strip()
        except serial.SerialException as e:
            print(f"Failed to receive from {self.device_name}: {e}")
            return ""

    @abstractmethod
    def get_connection_command(self) -> str:
        """Get the command string to establish connection."""
        pass

    @abstractmethod
    def get_status_command(self) -> str:
        """Get the command string to query device status."""
        pass


class SampleHandler(SerialDevice):
    """
    Sample Handler serial device implementation.

    通信コマンドの詳細は docs/magnetometer.md の
    「サンプルハンドラーの通信コマンド」を参照。
    """

    # 加速度 (A コマンド) : 0-127 の整数。デフォルトは 5。数値が大きいほど加速度が大きい。
    ACCELERATION_MIN = 0
    ACCELERATION_MAX = 127
    ACCELERATION_DEFAULT = 5

    # 速度 (B コマンド) : 50-5000 の整数。デフォルトは 1000。数値が大きいほど速度が大きい。
    SPEED_MIN = 50
    SPEED_MAX = 5000
    SPEED_DEFAULT = 1000

    # 現在位置・移動量 (Z, N, P コマンド) : 0-16777215 の整数。
    POSITION_MIN = 0
    POSITION_MAX = 16777215
    POSITION_DEFAULT = 0

    MOVE_AMOUNT_MIN = 0
    MOVE_AMOUNT_MAX = 16777215

    # 「%」コマンドで返される移動終了コードの意味 (docs/magnetometer.md 参照)
    MOVE_STATUS_MESSAGES = {
        "2": "パラメータエラー",
        "5": "正常終了",
        "7": "リミットスイッチで停止（正常終了ではない）",
        "G": "移動中",
    }

    def __init__(self):
        super().__init__("Sample Handler")

    def get_connection_command(self) -> str:
        """Connection command for Sample Handler."""
        return "@0,"

    def get_status_command(self) -> str:
        """Status query command for Sample Handler."""
        return "?"

    # ------------------------------------------------------------------
    # 設定コマンド (デバイスの状態を変更するコマンド)
    # ------------------------------------------------------------------

    def cmd_set_acceleration(self, value: int) -> str:
        """加速度を設定するコマンド文字列を作成する (Azzz)。"""
        if not (self.ACCELERATION_MIN <= value <= self.ACCELERATION_MAX):
            raise ValueError(
                f"加速度は{self.ACCELERATION_MIN}から{self.ACCELERATION_MAX}の範囲で指定してください: {value}"
            )
        return f"A{value:03d}"

    def cmd_set_speed(self, value: int) -> str:
        """速度を設定するコマンド文字列を作成する (Bdddd)。"""
        if not (self.SPEED_MIN <= value <= self.SPEED_MAX):
            raise ValueError(
                f"速度は{self.SPEED_MIN}から{self.SPEED_MAX}の範囲で指定してください: {value}"
            )
        return f"B{value:04d}"

    def cmd_set_current_position(self, value: int) -> str:
        """現在位置を value として設定し直すコマンド文字列を作成する (Zrrrrrr)。"""
        if not (self.POSITION_MIN <= value <= self.POSITION_MAX):
            raise ValueError(
                f"現在位置は{self.POSITION_MIN}から{self.POSITION_MAX}の範囲で指定してください: {value}"
            )
        return f"Z{value:06d}"

    def cmd_set_move_amount(self, value: int) -> str:
        """移動量を設定するコマンド文字列を作成する (Nrrrrrr)。"""
        if not (self.MOVE_AMOUNT_MIN <= value <= self.MOVE_AMOUNT_MAX):
            raise ValueError(
                f"移動量は{self.MOVE_AMOUNT_MIN}から{self.MOVE_AMOUNT_MAX}の範囲で指定してください: {value}"
            )
        return f"N{value:06d}"

    def cmd_set_direction(self, is_positive: bool) -> str:
        """移動方向を設定するコマンド文字列を作成する (「プラス」なら +、「マイナス」なら -)。"""
        return "+" if is_positive else "-"

    def cmd_move_to_position(self, value: int) -> str:
        """指定した位置へ移動するために必要な移動方向・移動量を設定させるコマンド文字列を作成する (Prrrrrr)。"""
        if not (self.POSITION_MIN <= value <= self.POSITION_MAX):
            raise ValueError(
                f"移動先の位置は{self.POSITION_MIN}から{self.POSITION_MAX}の範囲で指定してください: {value}"
            )
        return f"P{value:06d}"

    # ------------------------------------------------------------------
    # 実行・停止コマンド
    # ------------------------------------------------------------------

    def cmd_execute_move(self) -> str:
        """設定した内容で移動を実行するコマンド文字列 (G)。"""
        return "G"

    def cmd_stop(self) -> str:
        """移動を途中で停止するコマンド文字列 (Q)。"""
        return "Q"

    # ------------------------------------------------------------------
    # 問い合わせコマンド (デバイスの状態を変更しないコマンド)
    # ------------------------------------------------------------------

    def cmd_query_move_status(self) -> str:
        """移動が正常終了したかを問い合わせるコマンド文字列 (%)。"""
        return "%"

    def cmd_query_acceleration(self) -> str:
        """現在の加速度設定を問い合わせるコマンド文字列 (VA)。"""
        return "VA"

    def cmd_query_speed(self) -> str:
        """現在の速度設定を問い合わせるコマンド文字列 (VB)。"""
        return "VB"

    def cmd_query_remaining_steps(self) -> str:
        """現在の移動であと何ステップ残っているかを問い合わせるコマンド文字列 (VG)。"""
        return "VG"

    def cmd_query_position(self) -> str:
        """現在位置を問い合わせるコマンド文字列 (VP)。"""
        return "VP"

    # ------------------------------------------------------------------
    # レスポンス解析
    # ------------------------------------------------------------------

    @staticmethod
    def parse_numeric_response(response: str) -> Optional[int]:
        """
        VA・VB・VP・VG などの応答（あるいは A005 のような送信コマンド自体）から
        数値部分を取り出す。

        応答の正確なフォーマットが文書化されていないため、含まれる数字だけを
        取り出す形で寛容に解析する。数値が見つからない場合は None を返す。
        """
        digits = "".join(ch for ch in response if ch.isdigit())
        if not digits:
            return None
        return int(digits)

    @classmethod
    def describe_move_status(cls, response: str) -> str:
        """「%」コマンドへの応答を人が読める説明文に変換する。"""
        code = response.strip()
        return cls.MOVE_STATUS_MESSAGES.get(code, f"不明な応答: {response!r}")


class Degausser(SerialDevice):
    """Degausser serial device implementation."""

    def __init__(self):
        super().__init__("Degausser")

    def normalize_command(self, command: str) -> str:
        """Always terminate Degausser commands with a single CR."""
        return command.rstrip("\r\n") + "\r"

    def get_connection_command(self) -> str:
        """Connection command for Degausser."""
        return "DSS"

    def get_status_command(self) -> str:
        """Status query command for Degausser."""
        return "DSS"


class SQUID(SerialDevice):
    """SQUID serial device implementation."""

    def __init__(self):
        super().__init__("SQUID")

    def normalize_command(self, command: str) -> str:
        """Always terminate SQUID commands with a single CR."""
        return command.rstrip("\r\n") + "\r"

    def get_connection_command(self) -> str:
        """Connection command for SQUID."""
        return "YSSL"

    def get_status_command(self) -> str:
        """Status query command for SQUID."""
        return "YSSL"
