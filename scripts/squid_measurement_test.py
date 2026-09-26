"""
One-shot SQUID measurement test tool.

Connects to the SQUID sensor only and lets the operator trigger a single
X/Y/Z measurement on demand. No sample movement or degaussing is performed
here; real hardware communication testing is planned as a separate,
follow-up round after this tool is reviewed.
"""

import os
import sys

# scripts/ の親（プロジェクトルート）を sys.path に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.gui.squid_measurement_window import SquidMeasurementWindow
from src.squid_config import load_flux_quanta

SQUID_SETTING_PATH = os.path.join(project_root, "settings", "squid_setting.txt")


def main():
    """Launch the SQUID measurement test tool."""
    flux_quanta = load_flux_quanta(SQUID_SETTING_PATH)

    app = QApplication(sys.argv)
    window = SquidMeasurementWindow(flux_quanta)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
