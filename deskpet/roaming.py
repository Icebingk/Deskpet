"""Natural horizontal roaming for movement GIF actions."""

from __future__ import annotations

import random

from .constants import CHARACTER_CENTER_X, CHARACTER_FLOOR
from .window_win32 import Win32Window


class ScreenRoamer:
    """Move the pet window along the bottom of its current monitor."""

    MIN_DISTANCE = 160
    FLOOR_TOLERANCE = 12

    def __init__(self, window: Win32Window, seed: int | None = None) -> None:
        self.window = window
        self.randomizer = random.Random(seed)
        self.active = False
        self.direction = -1
        self.target_x = 0
        self.speed = 95.0

    @property
    def facing_right(self) -> bool:
        return self.active and self.direction > 0

    def start(
        self,
        sprite_width: int,
        *,
        speed_range: tuple[float, float] = (85.0, 115.0),
    ) -> bool:
        x, y = self.window.position()
        work = self.window.work_area_for(x, y)
        floor_y = work.bottom - CHARACTER_FLOOR
        if abs(y - floor_y) > self.FLOOR_TOLERANCE:
            return False

        sprite_width = max(1, int(sprite_width))
        half_width = sprite_width // 2
        left_x = work.left - (CHARACTER_CENTER_X - half_width)
        right_x = work.right - (
            CHARACTER_CENTER_X + sprite_width - half_width
        )
        if right_x <= left_x:
            return False

        edge_margin = max(80, sprite_width)
        if x <= left_x + edge_margin:
            target_x = right_x
        elif x >= right_x - edge_margin:
            target_x = left_x
        else:
            target_x = self.randomizer.choice((left_x, right_x))
            if abs(target_x - x) < self.MIN_DISTANCE:
                target_x = right_x if target_x == left_x else left_x

        if abs(target_x - x) < self.MIN_DISTANCE:
            return False

        self.active = True
        self.target_x = int(target_x)
        self.direction = 1 if target_x > x else -1
        low_speed, high_speed = sorted(
            (max(20.0, float(speed_range[0])), max(20.0, float(speed_range[1])))
        )
        self.speed = self.randomizer.uniform(low_speed, high_speed)
        return True

    def update(self, elapsed: float) -> bool:
        """Advance one frame and return True after reaching the target edge."""
        if not self.active:
            return True
        x, y = self.window.position()
        difference = self.target_x - x
        step = max(1, round(self.speed * min(max(elapsed, 0.0), 0.08)))
        if abs(difference) <= step:
            self.window.move(self.target_x, y)
            return True
        self.window.move(x + (step if difference > 0 else -step), y)
        return False

    def stop(self) -> None:
        self.active = False
