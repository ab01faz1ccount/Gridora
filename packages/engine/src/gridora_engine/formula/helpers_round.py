from __future__ import annotations

from .functions.helpers import round_half_up


def round_to(x: float, digits: int) -> float:
    return round_half_up(x, digits)
