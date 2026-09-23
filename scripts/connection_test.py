"""
Main application entry point.
Launches the Serial Device Communication Test Tool.
"""

import sys
import os

# scripts/ の親（プロジェクトルート）を sys.path に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
from PyQt6.QtWidgets import QApplication
from src.gui.main_window import MainWindow


def main():
    """Launch the application."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
