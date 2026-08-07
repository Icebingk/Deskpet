"""M2 桌面物理：重力、窗口表面碰撞、支撑跟随和屏幕边缘吸附。"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

from .constants import (
    BASE_CHARACTER_SIZE,
    CHARACTER_CENTER_X,
    CHARACTER_FLOOR,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from .window_win32 import GWL_EXSTYLE, WS_EX_TOOLWINDOW, Rect, Win32Window


@dataclass
class SurfaceTarget:
    top: int
    left: int
    right: int
    hwnd: int | None = None


@dataclass(frozen=True)
class PhysicsEvent:
    kind: str
    landing_action: str | None = None
    drop_distance: float = 0.0


class DesktopPhysics:
    """让桌宠落到普通窗口顶部；没有窗口时落到当前屏幕底部。"""

    GRAVITY_ACCELERATION = 1800.0
    MAX_FALL_SPEED = 1600.0
    EDGE_SNAP_DISTANCE = 32
    SUPPORT_POLL_SECONDS = 0.20

    EXCLUDED_CLASSES = {
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "DV2ControlHost",
    }

    def __init__(
        self,
        window: Win32Window,
        *,
        gravity: bool = True,
        window_collision: bool = True,
        edge_snap: bool = True,
        sprite_width: int = BASE_CHARACTER_SIZE,
    ) -> None:
        self.window = window
        self.user32 = ctypes.windll.user32
        self.gravity = gravity
        self.window_collision = window_collision
        self.edge_snap = edge_snap
        self.sprite_width = sprite_width
        self.falling = False
        self.velocity_y = 0.0
        self.fall_y = 0.0
        self.fall_started_y = 0.0
        self.target: SurfaceTarget | None = None
        self.support: SurfaceTarget | None = None
        self.next_support_poll = 0.0
        self.snapped_edge: str | None = None
        self.snapped_full_x: int | None = None
        self.edge_idle_since = time.monotonic()
        self.edge_peeked = False
        self._configure_api()

    def _configure_api(self) -> None:
        self.user32.IsWindow.argtypes = (wintypes.HWND,)
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.IsIconic.argtypes = (wintypes.HWND,)
        self.user32.IsIconic.restype = wintypes.BOOL
        self.user32.GetClassNameW.argtypes = (
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        )
        self.user32.GetClassNameW.restype = ctypes.c_int

    def set_sprite_width(self, width: int) -> None:
        self.sprite_width = max(1, min(WINDOW_WIDTH, int(width)))

    def begin_drag(self) -> None:
        self.begin_external_motion()

    def begin_external_motion(self) -> None:
        """Suspend falling, support following and edge hiding during roaming."""
        self.note_activity()
        self.falling = False
        self.velocity_y = 0.0
        self.target = None
        self.support = None
        self.snapped_edge = None
        self.snapped_full_x = None
        self.edge_peeked = False

    def end_external_motion(self, *, snap_to_edge: bool = True) -> None:
        self.falling = False
        self.velocity_y = 0.0
        self.target = None
        self.support = None
        if snap_to_edge:
            self.snap_to_edge()

    def _window_rect(self, hwnd: int) -> Rect | None:
        if (
            not hwnd
            or hwnd == self.window.hwnd
            or not self.user32.IsWindow(hwnd)
            or not self.user32.IsWindowVisible(hwnd)
            or self.user32.IsIconic(hwnd)
        ):
            return None
        rect = Rect()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return rect

    def _class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def _window_surfaces(self, foot_x: int, foot_y: int) -> list[SurfaceTarget]:
        if not self.window_collision:
            return []
        surfaces: list[SurfaceTarget] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd: int, _lparam: int) -> bool:
            rect = self._window_rect(int(hwnd))
            if rect is None or self._class_name(int(hwnd)) in self.EXCLUDED_CLASSES:
                return True
            if self.window.get_window_long(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width < 100 or height < 60:
                return True
            if not (rect.left + 12 <= foot_x <= rect.right - 12):
                return True
            if rect.top < foot_y - 3:
                return True
            surfaces.append(
                SurfaceTarget(rect.top, rect.left, rect.right, int(hwnd))
            )
            return True

        self.user32.EnumWindows(visit, 0)
        return surfaces

    def _target_below(self, x: int, y: int) -> SurfaceTarget:
        foot_x = x + CHARACTER_CENTER_X
        foot_y = y + CHARACTER_FLOOR
        candidates = self._window_surfaces(foot_x, foot_y)
        work = self.window.work_area_for(x, y)
        candidates = [
            item for item in candidates if item.top - CHARACTER_FLOOR >= work.top - 4
        ]
        if candidates:
            return min(candidates, key=lambda item: item.top)
        return SurfaceTarget(work.bottom, work.left, work.right, None)

    def release(self) -> PhysicsEvent:
        """拖动结束后开始下落；关闭重力时只执行边缘吸附。"""
        x, y = self.window.position()
        self.support = None
        if not self.gravity or not self.window_collision:
            self.falling = False
            self.snap_to_edge()
            return PhysicsEvent("landed", "004", 0.0)

        self.target = self._target_below(x, y)
        target_y = self.target.top - CHARACTER_FLOOR
        if target_y <= y + 1:
            self.window.move(x, target_y)
            self._finish_landing(self.target)
            return PhysicsEvent("landed", "004", 0.0)

        self.falling = True
        self.velocity_y = 0.0
        self.fall_y = float(y)
        self.fall_started_y = float(y)
        return PhysicsEvent("falling")

    def _refresh_fall_target(self, x: int, y: int) -> None:
        if self.target is None:
            self.target = self._target_below(x, y)
            return
        if self.target.hwnd is None:
            work = self.window.work_area_for(x, y)
            self.target = SurfaceTarget(work.bottom, work.left, work.right, None)
            return
        rect = self._window_rect(self.target.hwnd)
        foot_x = x + CHARACTER_CENTER_X
        if rect is None or not (rect.left <= foot_x <= rect.right):
            self.target = self._target_below(x, y)
            return
        self.target = SurfaceTarget(rect.top, rect.left, rect.right, self.target.hwnd)

    def _finish_landing(self, target: SurfaceTarget) -> None:
        self.falling = False
        self.velocity_y = 0.0
        self.target = None
        self.support = target if target.hwnd is not None else None
        self.next_support_poll = time.monotonic() + self.SUPPORT_POLL_SECONDS
        self.snap_to_edge()

    @staticmethod
    def _landing_action(distance: float) -> str:
        if distance < 80:
            return "004"
        if distance < 260:
            return "113"
        return "135"

    def update(
        self,
        elapsed: float,
        *,
        user_active: bool = False,
        bubble_visible: bool = False,
    ) -> PhysicsEvent | None:
        if self.window.dragging:
            return None
        if self.falling:
            x, current_y = self.window.position()
            self._refresh_fall_target(x, current_y)
            assert self.target is not None
            target_y = float(self.target.top - CHARACTER_FLOOR)
            self.velocity_y = min(
                self.MAX_FALL_SPEED,
                self.velocity_y + self.GRAVITY_ACCELERATION * min(elapsed, 0.08),
            )
            self.fall_y += self.velocity_y * min(elapsed, 0.08)
            if self.fall_y >= target_y:
                self.fall_y = target_y
                self.window.move(x, round(self.fall_y))
                distance = max(0.0, self.fall_y - self.fall_started_y)
                landed_target = self.target
                self._finish_landing(landed_target)
                return PhysicsEvent(
                    "landed", self._landing_action(distance), distance
                )
            self.window.move(x, round(self.fall_y))
            return None

        if self.support is not None and time.monotonic() >= self.next_support_poll:
            self.next_support_poll = time.monotonic() + self.SUPPORT_POLL_SECONDS
            hwnd = self.support.hwnd
            rect = self._window_rect(hwnd or 0)
            x, y = self.window.position()
            foot_x = x + CHARACTER_CENTER_X
            if rect is None or not (rect.left <= foot_x <= rect.right):
                self.support = None
                if self.gravity:
                    event = self.release()
                    return event
                return None
            delta_x = rect.left - self.support.left
            delta_y = rect.top - self.support.top
            if delta_x or delta_y:
                self.window.move(x + delta_x, y + delta_y)
                if self.snapped_full_x is not None:
                    self.snapped_full_x += delta_x
            self.support = SurfaceTarget(rect.top, rect.left, rect.right, hwnd)
        return self._update_edge_peek(
            elapsed, user_active=user_active, bubble_visible=bubble_visible
        )

    def snap_to_edge(self) -> bool:
        if not self.edge_snap:
            return False
        x, y = self.window.position()
        work = self.window.work_area_for(x, y)
        left_offset = CHARACTER_CENTER_X - self.sprite_width // 2
        right_offset = CHARACTER_CENTER_X + self.sprite_width - self.sprite_width // 2
        visible_left = x + left_offset
        visible_right = visible_left + self.sprite_width
        new_x = x
        edge: str | None = None
        if abs(visible_left - work.left) <= self.EDGE_SNAP_DISTANCE:
            new_x = work.left - left_offset
            edge = "left"
        elif abs(work.right - visible_right) <= self.EDGE_SNAP_DISTANCE:
            new_x = work.right - right_offset
            edge = "right"
        if new_x != x:
            self.window.move(new_x, y)
        self.snapped_edge = edge
        self.snapped_full_x = new_x if edge else None
        self.edge_idle_since = time.monotonic()
        self.edge_peeked = False
        return edge is not None

    def note_activity(self) -> None:
        """记录用户操作；下一次物理更新会让花盆躲藏动作结束。"""
        self.edge_idle_since = time.monotonic()

    def reveal_edge(self) -> None:
        """取消边缘躲藏，并从现在重新计算空闲时间。"""
        self.edge_peeked = False
        self.edge_idle_since = time.monotonic()

    def _cursor_near_pet(self) -> bool:
        if not self.snapped_edge:
            return False
        point = self.window.cursor()
        rect = self.window.rect()
        work = self.window.work_area_for(rect.left, rect.top)
        near_horizontal = (
            point.x <= work.left + 72
            if self.snapped_edge == "left"
            else point.x >= work.right - 72
        )
        return near_horizontal and rect.top - 30 <= point.y <= rect.bottom + 30

    def _update_edge_peek(
        self, elapsed: float, *, user_active: bool, bubble_visible: bool
    ) -> PhysicsEvent | None:
        del elapsed
        if not self.edge_snap or not self.snapped_edge or self.snapped_full_x is None:
            return
        if user_active or bubble_visible or self._cursor_near_pet():
            self.edge_idle_since = time.monotonic()
            if self.edge_peeked:
                self.edge_peeked = False
                return PhysicsEvent("edge_show")
            return
        if self.edge_peeked:
            return
        if time.monotonic() - self.edge_idle_since < 3.0:
            return
        self.edge_peeked = True
        return PhysicsEvent("edge_hide")
