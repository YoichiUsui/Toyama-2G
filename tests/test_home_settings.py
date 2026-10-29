import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.device import SampleHandler
from src.gui.sample_handler_setting_window import SampleHandlerSettingWindow
from src.home_settings import (
    HOME_POSITION_MAX,
    HomeSettings,
    load_home_settings,
    parse_home_settings,
)


class HomeSettingsTests(unittest.TestCase):
    def test_parses_home_settings_and_ignores_other_settings(self):
        settings = parse_home_settings(
            "home side: -\n"
            "home position: 10000\n"
            "moving velocity: 4000\n"
        )

        self.assertEqual(settings.side, "-")
        self.assertEqual(settings.position, HOME_POSITION_MAX)

    def test_rejects_missing_or_invalid_home_side(self):
        for contents in (
            "home position: 100\n",
            "home side: positive\nhome position: 100\n",
        ):
            with self.subTest(contents=contents):
                with self.assertRaises(ValueError):
                    parse_home_settings(contents)

    def test_rejects_missing_non_integer_and_out_of_range_positions(self):
        for contents in (
            "home side: +\n",
            "home side: +\nhome position: 1.5\n",
            "home side: +\nhome position: 0\n",
            f"home side: +\nhome position: {HOME_POSITION_MAX + 1}\n",
        ):
            with self.subTest(contents=contents):
                with self.assertRaises(ValueError):
                    parse_home_settings(contents)

    def test_rejects_duplicate_home_keys(self):
        with self.assertRaises(ValueError):
            parse_home_settings("home side: +\nhome side: -\nhome position: 100\n")

    def test_repository_settings_file_has_valid_home_settings(self):
        settings_path = (
            Path(__file__).resolve().parents[1]
            / "settings"
            / "samplehandler_setting.txt"
        )
        settings = load_home_settings(settings_path)

        self.assertEqual(settings.side, "+")
        self.assertEqual(settings.position, 1302)


class SampleHandlerHomeCommandTests(unittest.TestCase):
    def test_limit_seek_command(self):
        self.assertEqual(SampleHandler().cmd_move_until_limit(), "Hl")

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch(
            "src.gui.sample_handler_setting_window.SerialManager"
        ) as manager_type:
            self.manager = manager_type.return_value
            self.manager.is_device_connected.return_value = True
            self.window = SampleHandlerSettingWindow()
        self.window.is_ready = True
        self.window.refresh_controls()
        self.run_sequence = Mock()
        self.window.run_command_sequence = self.run_sequence

    def tearDown(self):
        self.window.close()

    def test_home_button_is_disabled_when_not_connected(self):
        self.manager.is_device_connected.return_value = False
        self.window.refresh_controls()
        self.assertFalse(self.window.home_btn.isEnabled())

        self.manager.is_device_connected.return_value = True
        self.window.refresh_controls()
        self.assertTrue(self.window.home_btn.isEnabled())

    def test_home_sequence_seeks_then_moves_opposite_without_zeroing_position(self):
        with patch(
            "src.gui.sample_handler_setting_window.load_home_settings",
            return_value=HomeSettings(side="+", position=1300),
        ):
            self.window.on_home_clicked()

        first_steps = self.run_sequence.call_args.args[0]
        self.assertEqual([step[1] for step in first_steps], ["+", "M0500"])

        self.window.after_home_seek_setup(True)
        seek_steps = self.run_sequence.call_args.args[0]
        self.assertEqual([step[1] for step in seek_steps], ["Hl"])

        self.window.after_home_seek_started(True)
        self.window.home_last_status_code = "7"
        self.window.after_home_poll(True)
        retract_steps = self.run_sequence.call_args.args[0]
        self.assertEqual([step[1] for step in retract_steps], ["-", "N001300"])

        self.window.after_home_retract_setup(True)
        move_steps = self.run_sequence.call_args.args[0]
        self.assertEqual([step[1] for step in move_steps], ["G"])
        commands = [
            step[1]
            for call in self.run_sequence.call_args_list
            for step in call.args[0]
        ]
        self.assertNotIn("Z000000", commands)

        self.window.after_home_move_started(True)
        self.window.home_last_status_code = "5"
        self.window.after_home_poll(True)
        position_steps = self.run_sequence.call_args.args[0]
        self.assertEqual([step[1] for step in position_steps], ["VP"])
        self.window.on_step_succeeded(0, "VP", "1234")
        self.window.after_home_position_query(True)
        self.assertEqual(self.window.position_label.text(), "現在位置: 1234")
        self.assertFalse(self.window.is_moving)
        self.assertIsNone(self.window.home_phase)

    def test_home_timeout_stops_with_q_and_uses_required_deadlines(self):
        with patch(
            "src.gui.sample_handler_setting_window.load_home_settings",
            return_value=HomeSettings(side="-", position=1),
        ):
            self.window.on_home_clicked()
        self.window.after_home_seek_setup(True)
        self.assertEqual(self.window.home_timeout_timer.interval(), 100000)

        self.window.home_deadline = 0
        self.window.on_home_timeout()
        stop_steps = self.run_sequence.call_args.args[0]
        self.assertEqual([step[1] for step in stop_steps], ["Q", "%", "VP"])
        self.assertEqual(self.window.home_phase, "aborting")
        self.assertFalse(self.window.home_timeout_timer.isActive())

        self.window.after_stop(True)
        self.assertIsNone(self.window.home_phase)
        self.assertFalse(self.window.is_moving)

        with patch(
            "src.gui.sample_handler_setting_window.load_home_settings",
            return_value=HomeSettings(side="-", position=1),
        ):
            self.window.on_home_clicked()
        self.window.after_home_seek_setup(True)
        self.window.after_home_seek_started(True)
        self.window.home_last_status_code = "7"
        self.window.after_home_poll(True)
        self.window.after_home_retract_setup(True)
        self.assertEqual(self.window.home_timeout_timer.interval(), 5000)
        self.window.home_timeout_timer.stop()


if __name__ == "__main__":
    unittest.main()
