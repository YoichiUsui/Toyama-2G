"""Settings used by the sample-handler home operation."""

import re
from dataclasses import dataclass
from pathlib import Path


HOME_POSITION_MAX = 10000


@dataclass(frozen=True)
class HomeSettings:
    """Validated direction and distance for moving away from the home limit."""

    side: str
    position: int


def parse_home_settings(contents: str) -> HomeSettings:
    """Parse and validate the home settings from the sample-handler settings file."""
    values = {}
    for line_number, line in enumerate(contents.splitlines(), start=1):
        key, separator, value = line.partition(":")
        key = key.strip()
        if key not in ("home side", "home position"):
            continue
        if not separator:
            raise ValueError(f"設定ファイルの{line_number}行目に ':' がありません。")
        if key in values:
            raise ValueError(f"設定 '{key}' が重複しています。")
        values[key] = value.strip()

    side = values.get("home side")
    if side not in ("+", "-"):
        raise ValueError("home side は '+' または '-' に設定してください。")

    position_text = values.get("home position", "")
    if not re.fullmatch(r"[0-9]+", position_text):
        raise ValueError("home position は1から10000までの整数に設定してください。")
    position = int(position_text)
    if not 1 <= position <= HOME_POSITION_MAX:
        raise ValueError("home position は1から10000までの整数に設定してください。")

    return HomeSettings(side=side, position=position)


def load_home_settings(path: Path) -> HomeSettings:
    """Read and validate home settings from a UTF-8 settings file."""
    return parse_home_settings(path.read_text(encoding="utf-8"))
