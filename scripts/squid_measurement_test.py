"""
SQUID sensor and sample-handler single-sample measurement tool.

Loads the configured device ports and motion parameters, then launches the
measurement GUI.
"""

import os
import sys
from pathlib import Path

# scripts/ の親（プロジェクトルート）を sys.path に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.gui.squid_measurement_window import SquidMeasurementWindow
from src.squid_config import load_flux_quanta
from src.measurement_settings import load_measurement_settings

SETTINGS_DIRECTORY = Path(project_root) / "settings"
SQUID_SETTING_PATH = SETTINGS_DIRECTORY / "squid_setting.txt"


def main():
    """Launch the SQUID measurement test tool."""
    app = QApplication(sys.argv)
    try:
        flux_quanta = load_flux_quanta(SQUID_SETTING_PATH)
        settings = load_measurement_settings(SETTINGS_DIRECTORY)
    except (OSError, UnicodeError, ValueError) as error:
        QMessageBox.critical(None, "設定エラー", str(error))
        return 1

    window = SquidMeasurementWindow(flux_quanta, settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
