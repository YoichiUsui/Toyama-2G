import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.home_settings import HomeSettings
from src.measurement_settings import (
    MeasurementSettings,
    direction_and_amount,
    load_measurement_settings,
    wrap_position,
)


class MeasurementSettingsTests(unittest.TestCase):
    def test_repository_settings_and_signed_measurement_displacements(self):
        root = Path(__file__).resolve().parents[1]
        settings = load_measurement_settings(root / "settings")

        self.assertEqual(settings.squid_port, "COM6")
        self.assertEqual(settings.sample_handler_port, "COM5")
        self.assertEqual(settings.sample_displacement, 89800)
        self.assertEqual(settings.background_displacement, 4934)
        self.assertEqual(settings.background_to_sample_displacement, 84866)

    def test_positions_wrap_at_24_bits(self):
        self.assertEqual(wrap_position(16777216), 0)
        self.assertEqual(wrap_position(-1), 16777215)
        settings = MeasurementSettings(
            squid_port="COM1",
            sample_handler_port="COM2",
            home=HomeSettings(side="+", position=100),
            squid_position=0,
            first_sample_position=16777215,
            background_position=16777215,
            moving_velocity=2000,
            measurement_velocity=1000,
        )
        self.assertEqual(settings.sample_displacement, 1)
        self.assertEqual(settings.background_displacement, 1)

    def test_displacement_becomes_nonnegative_amount_and_direction(self):
        self.assertEqual(direction_and_amount(89800), (False, 89800))
        self.assertEqual(direction_and_amount(4934), (False, 4934))
        self.assertEqual(direction_and_amount(-4934), (True, 4934))
        self.assertEqual(direction_and_amount(0), (False, 0))

    def test_rejects_same_device_port(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "port_names.txt").write_text(
                "SQUID: COM1\nSample Handler: COM1\n", encoding="utf-8"
            )
            (directory / "samplehandler_setting.txt").write_text(
                "home side: +\n"
                "home position: 100\n"
                "SQUID position (absolute count from the home side limit switch): 1000\n"
                "1st sample position in the home position(absolute count from the home side limit switch): 100\n"
                "background position: 1200\n"
                "moving velocity: 2000\n"
                "measurement velocity: 1000\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "異なるポート"):
                load_measurement_settings(directory)


class SampleMeasurementWorkerTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock

        from src.device import SampleHandler
        from src.gui.sample_measurement_worker import SampleMeasurementWorker

        self.manager = Mock()
        self.manager.send_command.return_value = True
        self.manager.receive_response.side_effect = ["125", "0.5"]
        self.settings = MeasurementSettings(
            squid_port="COM1",
            sample_handler_port="COM2",
            home=HomeSettings(side="+", position=100),
            squid_position=1000,
            first_sample_position=100,
            background_position=1200,
            moving_velocity=2000,
            measurement_velocity=1000,
        )
        self.worker = SampleMeasurementWorker(
            self.manager,
            SampleHandler(),
            self.settings,
            {"X": 2.0, "Y": 3.0, "Z": 4.0},
            "measure",
        )
        self.worker.log_message.connect(lambda _message: None)

    def test_axis_measurement_combines_count_and_analog_before_calibration(self):
        result = self.worker._measure_axis("X", 2.0)

        self.assertEqual(result, {"count": 125, "analog": 0.5, "magnetization": 251.0})
        self.assertEqual(
            [call.args[1] for call in self.manager.send_command.call_args_list],
            ["XLC", "XSC", "XLD", "XSD"],
        )

    def test_home_seeks_configured_limit_then_retracts_and_sets_motion_speed(self):
        self.worker._send_handler = Mock()
        self.worker._query_status = Mock(side_effect=["G", "7", "5"])
        self.worker._query_position = Mock(return_value=100)

        position = self.worker._home()

        self.assertEqual(position, 100)
        self.assertEqual(
            [call.args[0] for call in self.worker._send_handler.call_args_list],
            ["+", "M0500", "Hl", "-", "N000100", "G", "M2000"],
        )
        self.manager.clear_input_buffer.assert_called_once_with("Sample Handler")

    def test_move_uses_nonnegative_amount_and_direction_separately(self):
        from unittest.mock import patch

        self.manager.receive_response.side_effect = None
        self.manager.receive_response.return_value = ""
        self.worker._query_status = lambda: "5"
        self.worker._query_position = lambda: 123
        with patch("src.gui.sample_measurement_worker.time.monotonic", return_value=1):
            self.worker._move_displacement(89800, 120, "sample")

        self.assertEqual(
            [call.args[1] for call in self.manager.send_command.call_args_list],
            ["-", "N089800", "G"],
        )

    def test_measurement_moves_bg_sample_and_back_then_computes_correction(self):
        self.worker.starting_position = 1234
        self.worker._send_handler = Mock()
        self.worker._move_displacement = Mock(side_effect=[2345, 3456, 1234])
        self.worker._measure_axis = Mock(
            side_effect=[
                {"count": 1, "analog": 0.0, "magnetization": 10.0},
                {"count": 2, "analog": 0.0, "magnetization": 20.0},
                {"count": 3, "analog": 0.0, "magnetization": 30.0},
                {"count": 4, "analog": 0.0, "magnetization": 15.0},
                {"count": 5, "analog": 0.0, "magnetization": 23.0},
                {"count": 6, "analog": 0.0, "magnetization": 35.0},
            ]
        )
        sections = []
        self.worker.result_section.connect(
            lambda title, values: sections.append((title, values))
        )

        position = self.worker._measure()

        self.assertEqual(position, 1234)
        self.assertEqual(
            [call.args[0] for call in self.worker._move_displacement.call_args_list],
            [200, 700, -900],
        )
        self.assertEqual(
            sections[-1],
            ("バックグラウンド補正後", {"X": 5.0, "Y": 3.0, "Z": 5.0}),
        )
        self.manager.send_command.assert_called_once_with("SQUID", "ARC")


class SampleMeasurementWindowControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.device import SQUID, SampleHandler
        from src.gui.squid_measurement_window import SquidMeasurementWindow

        self.manager = Mock()
        self.manager.get_device.side_effect = lambda name: (
            SQUID() if name == "SQUID" else SampleHandler()
        )
        self.settings = MeasurementSettings(
            squid_port="COM1",
            sample_handler_port="COM2",
            home=HomeSettings(side="+", position=100),
            squid_position=1000,
            first_sample_position=100,
            background_position=1200,
            moving_velocity=2000,
            measurement_velocity=1000,
        )
        with patch.object(SquidMeasurementWindow, "connect_devices"):
            self.window = SquidMeasurementWindow(
                {"X": 1.0, "Y": 1.0, "Z": 1.0},
                self.settings,
                self.manager,
            )

    def tearDown(self):
        self.window.close()

    def test_home_is_the_only_enabled_operation_until_homed_and_after_fault(self):
        self.window.connection_verified = True
        self.window.refresh_controls()
        self.assertTrue(self.window.home_btn.isEnabled())
        self.assertFalse(self.window.reset_btn.isEnabled())
        self.assertFalse(self.window.measure_btn.isEnabled())

        self.window.homed = True
        self.window.refresh_controls()
        self.assertTrue(self.window.reset_btn.isEnabled())
        self.assertTrue(self.window.measure_btn.isEnabled())

        self.window.homed = False
        self.window.faulted = True
        self.window.refresh_controls()
        self.assertTrue(self.window.home_btn.isEnabled())
        self.assertFalse(self.window.reset_btn.isEnabled())
        self.assertFalse(self.window.measure_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
