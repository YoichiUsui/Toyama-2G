## 目的
2G社の超電導磁力計システムを、シリアル通信により制御する一連のコード (GUI含む）を作成する

## Project knowledge
- **ファイル構造:**
  - `src/` – Application source code
  - `config/` - Setting files for the software
  - `docs/` – All documentation
  - `scripts/` – manual one-shot tests

## 磁力計システムの説明

[`docs/magnetometer.md`](docs/matnetometer.md)
磁力計の構成と通信規格、通信コマンドについての記述

## サンプルハンドラー 移動量設定補助ツール

ステップ数と実際の移動距離との関係を実測するための補助 GUI。
以下のコマンドで起動する。

```
python scripts/run_sample_handler_setting_helper.py
```

レイアウトの例は [`docs/移動量設定補助画面.jpg`](docs/移動量設定補助画面.jpg) を参照。
なお、このツールは実機との通信テストが未実施の状態で作成されているため、
通信の進行状況をメッセージ欄に逐次表示し、どの段階で失敗したかを追いやすくしている。
