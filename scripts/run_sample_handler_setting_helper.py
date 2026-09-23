#!/usr/bin/env python
"""
サンプルハンドラーの移動量設定補助ツールを起動するスクリプト。

ステップ数と実際の移動距離との関係を実測するために、サンプルハンドラーの
ポート接続・初期設定・移動指示・緊急停止・状態確認をまとめて行える GUI
(src/gui/sample_handler_setting_window.py) を起動する。
"""

import os
import sys

# プロジェクトルート (このファイルの1つ上の階層) を import パスに追加する
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
