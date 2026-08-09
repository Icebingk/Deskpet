"""M4 environment helpers: local day phase and optional weather summaries."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentState:
    phase: str
    label: str
    tint: tuple[int, int, int]


def local_environment(now: float | None = None) -> EnvironmentState:
    hour = time.localtime(now).tm_hour
    if 6 <= hour < 10:
        return EnvironmentState("morning", "早晨", (255, 239, 210))
    if 10 <= hour < 17:
        return EnvironmentState("day", "白天", (255, 255, 255))
    if 17 <= hour < 20:
        return EnvironmentState("evening", "傍晚", (255, 225, 207))
    return EnvironmentState("night", "夜晚", (222, 228, 255))
