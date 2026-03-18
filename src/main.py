"""
Main application entry point.
Launches the Serial Device Communication Test Tool.
"""

import sys
from PySide2.QtWidgets import QApplication
from src.gui.main_window import MainWindow


def main():
    """Launch the application."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # PySide2 / PyQt5 は exec_(), PyQt6 は exec()
    if hasattr(app, "exec_"):
        status = app.exec_()
    else:
        status = app.exec()

    sys.exit(status)


if __name__ == "__main__":
    main()
