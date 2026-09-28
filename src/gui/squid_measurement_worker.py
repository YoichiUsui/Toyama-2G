"""
Worker thread for performing a single-shot SQUID measurement.

A measurement of one axis requires four commands in sequence (see
docs/magnetometer.md and docs/SQUID_Commands.pdf):

    <axis>LC  latch the current count
    <axis>SC  send the latched count to the PC
    <axis>LD  latch the current analog data
    <axis>SD  send the latched analog data to the PC

Only the "S" (send) commands trigger a response from the SQUID electronics;
"L" (latch) commands are fire-and-forget. This worker runs the whole
sequence off the GUI thread so the window stays responsive while waiting
for each response.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from src.device import SQUID


class SquidMeasurementWorker(QObject):
    """Worker that runs the latch/send command sequence for one axis."""

    log_message = pyqtSignal(str)
    measurement_done = pyqtSignal(str, int, float)  # axis, count, analog_data
    error_occurred = pyqtSignal(str, str)  # axis, message
    finished = pyqtSignal()

    def __init__(self, squid: SQUID, axis: str):
        """
        Initialize the worker.

        Args:
            squid: Connected SQUID device instance.
            axis: Axis to measure, one of "X", "Y", "Z".
        """
        super().__init__()
        self.squid = squid
        self.axis = axis

    def run(self):
        """Execute the latch/send sequence and emit the result."""
        try:
            count = self._latch_and_send(latch_cmd="LC", send_cmd="SC")
            data = self._latch_and_send(latch_cmd="LD", send_cmd="SD")
            self.measurement_done.emit(self.axis, int(count), float(data))
        except (ValueError, ConnectionError) as e:
            self.error_occurred.emit(self.axis, str(e))
        finally:
            self.finished.emit()

    def _latch_and_send(self, latch_cmd: str, send_cmd: str) -> str:
        """
        Run one latch+send pair (e.g. "LC"/"SC" or "LD"/"SD") and return the
        raw response string sent back by the SQUID electronics.
        """
        latch_command = f"{self.axis}{latch_cmd}"
        if not self.squid.send_command(latch_command):
            raise ConnectionError(f"Failed to send {latch_command} to SQUID")
        self.log_message.emit(f"[SQUID] >> {latch_command}")

        send_command = f"{self.axis}{send_cmd}"
        if not self.squid.send_command(send_command):
            raise ConnectionError(f"Failed to send {send_command} to SQUID")
        self.log_message.emit(f"[SQUID] >> {send_command}")

        response = self.squid.receive_response()
        if not response:
            raise ValueError(f"No response to {send_command} (timeout)")
        self.log_message.emit(f"[SQUID] << {response}")

        return response
