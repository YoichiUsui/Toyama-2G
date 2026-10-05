#!/usr/bin/env python
"""
サンプルハンドラーの移動量設定補助ツールを起動するスクリプト。

ステップ数と実際の移動距離との関係を実測するために、サンプルハンドラーの
ポート接続・初期設定・移動指示・緊急停止・状態確認をまとめて行える GUI
(src/gui/sample_handler_setting_window.py) を起動する。
"""

import os
import sys

# scripts/ の親（プロジェクトルート）を sys.path に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.gui.sample_handler_setting_window import SampleHandlerSettingWindow


def main():
    """アプリケーションを起動する。"""
    app = QApplication(sys.argv)
    window = SampleHandlerSettingWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
