"""Configuration and position arithmetic for the sample measurement workflow."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from src.device import SampleHandler
from src.home_settings import HomeSettings, load_home_settings


POSITION_MODULUS = 1 << 24
POSITION_MAX = POSITION_MODULUS - 1

_SETTING_LINE = re.compile(r"^\s*([^:]+)\s*:\s*(.*?)\s*$")


@dataclass(frozen=True)
class MeasurementSettings:
    """Validated device ports and motion parameters loaded from settings/."""

    squid_port: str
    sample_handler_port: str
    home: HomeSettings
    squid_position: int
    first_sample_position: int
    background_position: int
    moving_velocity: int
    measurement_velocity: int

    @property
    def sample_displacement(self) -> int:
        """Negative-side travel from home to put the first sample at the SQUID."""
        return (
            wrap_position(self.squid_position)
            - wrap_position(self.first_sample_position)
        ) % POSITION_MODULUS

    @property
    def background_displacement(self) -> int:
        """Negative-side travel distance that puts the first sample at background."""
        squid = wrap_position(self.squid_position)
        background = wrap_position(self.background_position)
        clockwise_distance = abs(squid - background)
        return min(clockwise_distance, POSITION_MODULUS - clockwise_distance)

    @property
    def background_to_sample_displacement(self) -> int:
        """Signed travel from the background position to the sample position."""
        return self.sample_displacement - self.background_displacement


def wrap_position(value: int) -> int:
    """Normalize a position to the sample handler's 24-bit position range."""
    return value % POSITION_MODULUS


def direction_and_amount(displacement: int) -> Tuple[bool, int]:
    """
    Convert signed travel into a direction flag and a non-negative amount.

    Positive displacement means travel toward the negative side from home.
    """
    return displacement < 0, abs(displacement)


def _read_key_values(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    with path.open("r", encoding="utf-8") as settings_file:
        for line in settings_file:
            match = _SETTING_LINE.match(line)
            if not match:
                continue
            key, value = match.groups()
            key = key.strip()
            if key in values:
                raise ValueError(f"{path.name} の設定 '{key}' が重複しています。")
            values[key] = value
    return values


def _integer_setting(values: Dict[str, str], key: str, path: Path) -> int:
    value = values.get(key, "")
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"{path.name} の '{key}' は整数で指定してください。")
    return int(value)


def _position_setting(values: Dict[str, str], key: str, path: Path) -> int:
    value = _integer_setting(values, key, path)
    if not 0 <= value <= POSITION_MAX:
        raise ValueError(
            f"{path.name} の '{key}' は0から{POSITION_MAX}の範囲で指定してください。"
        )
    return value


def load_measurement_settings(settings_directory: Path) -> MeasurementSettings:
    """Load and validate the settings required for a sample measurement."""
    ports_path = settings_directory / "port_names.txt"
    handler_path = settings_directory / "samplehandler_setting.txt"

    ports = _read_key_values(ports_path)
    squid_port = ports.get("SQUID", "")
    sample_handler_port = ports.get("Sample Handler", "")
    if not squid_port or not sample_handler_port:
        raise ValueError(
            "port_names.txt に SQUID と Sample Handler のポートを設定してください。"
        )
    if squid_port == sample_handler_port:
        raise ValueError("SQUID と Sample Handler に異なるポートを設定してください。")

    handler_values = _read_key_values(handler_path)
    home = load_home_settings(handler_path)
    squid_position = _position_setting(
        handler_values,
        "SQUID position (absolute count from the home side limit switch)",
        handler_path,
    )
    first_sample_position = _position_setting(
        handler_values,
        "1st sample position in the home position(absolute count from the home side limit switch)",
        handler_path,
    )
    background_position = _position_setting(
        handler_values, "background position", handler_path
    )
    moving_velocity = _integer_setting(handler_values, "moving velocity", handler_path)
    measurement_velocity = _integer_setting(
        handler_values, "measurement velocity", handler_path
    )
    for key, velocity in (
        ("moving velocity", moving_velocity),
        ("measurement velocity", measurement_velocity),
    ):
        if not SampleHandler.SPEED_MIN <= velocity <= SampleHandler.SPEED_MAX:
            raise ValueError(
                f"{handler_path.name} の '{key}' は"
                f"{SampleHandler.SPEED_MIN}から{SampleHandler.SPEED_MAX}の範囲で指定してください。"
            )

    return MeasurementSettings(
        squid_port=squid_port,
        sample_handler_port=sample_handler_port,
        home=home,
        squid_position=squid_position,
        first_sample_position=first_sample_position,
        background_position=background_position,
        moving_velocity=moving_velocity,
        measurement_velocity=measurement_velocity,
    )
