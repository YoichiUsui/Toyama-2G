"""
Loader for the SQUID sensor configuration file (settings/squid_setting.txt).

The file lists the flux quanta calibration constants for each axis, one per
line, in the form "<axis> flux quanta:<TAB><value>". These constants are
used to convert the raw count + analog data measured from the SQUID sensor
into a magnetization value (see docs/magnetometer.md for the formula).
"""

import re
from typing import Dict

# Matches lines like "X flux quanta:\t-3.40e-5"
_FLUX_QUANTA_LINE = re.compile(
    r"^\s*([XYZ])\s*flux quanta\s*:\s*([-+0-9.eE]+)\s*$"
)


def load_flux_quanta(path: str) -> Dict[str, float]:
    """
    Read the SQUID setting file and return the flux quanta for each axis.

    Args:
        path: Path to the squid_setting.txt file.

    Returns:
        Dict mapping "X", "Y", "Z" to their flux quanta value.

    Raises:
        ValueError: If the file does not contain all three axes.
    """
    flux_quanta: Dict[str, float] = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            match = _FLUX_QUANTA_LINE.match(line)
            if match:
                axis, value = match.groups()
                flux_quanta[axis] = float(value)

    missing = [axis for axis in ("X", "Y", "Z") if axis not in flux_quanta]
    if missing:
        raise ValueError(
            f"squid_setting.txt is missing flux quanta for: {', '.join(missing)}"
        )

    return flux_quanta
