"""Windows 透明窗口、层级、多显示器、鼠标穿透和全局热键。"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

from .constants import (
    APP_TITLE,
    MENU_AUTOSTART,
    MENU_CLICK_THROUGH,
    MENU_DEFAULT_SIZE,
    MENU_CONTROL_PANEL,
    MENU_EDGE_SNAP,
    MENU_EXIT,
    MENU_GRAVITY,
    MENU_GROW,
    MENU_HEALTH_REMINDERS,
    MENU_HIDE,
    MENU_HOME,
    MENU_PAUSE,
    MENU_SHRINK,
    MENU_TOPMOST,
    MENU_WINDOW_COLLISION,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)

WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20
LWA_COLORKEY = 0x00000001
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080
ERROR_ALREADY_EXISTS = 183
SW_HIDE = 0
SW_RESTORE = 9
SW_SHOWNOACTIVATE = 4
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MONITOR_DEFAULTTONEAREST = 2
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000


class Point(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class Rect(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", Rect),
        ("rcWork", Rect),
        ("dwFlags", wintypes.DWORD),
    )


class Message(ctypes.Structure):
    _fields_ = (
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", Point),
        ("lPrivate", wintypes.DWORD),
    )


class SingleInstance:
    """防止重复启动；第二次启动时唤回已有桌宠。"""

    MUTEX_NAME = r"Local\LineDogDeskPet.SingleInstance"

    def __init__(self) -> None:
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        mutex_name = os.environ.get("DESKPET_MUTEX_NAME", self.MUTEX_NAME)
        self.handle = self.kernel32.CreateMutexW(None, False, mutex_name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    @staticmethod
    def activate_existing() -> None:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


class GlobalHotkeys:
    """在线程消息队列中接收全局快捷键，不阻塞 Pygame 主循环。"""

    DEFINITIONS = {
        1: ("toggle_visibility", ord("D")),
        2: ("toggle_click_through", ord("T")),
        3: ("summon", ord("P")),
        4: ("toggle_pause", 0x20),
    }

    def __init__(self) -> None:
        self.events = {name: threading.Event() for name, _ in self.DEFINITIONS.values()}
        self.failed: list[str] = []
        self.ready = threading.Event()
        self.thread_id = 0
        self.thread = threading.Thread(target=self._run, name="DeskPetHotkeys", daemon=True)
        self.thread.start()
        self.ready.wait(1.5)

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self.thread_id = int(kernel32.GetCurrentThreadId())
        user32.RegisterHotKey.argtypes = (
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(Message),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.GetMessageW.restype = wintypes.BOOL

        registered: list[int] = []
        for hotkey_id, (name, virtual_key) in self.DEFINITIONS.items():
            if user32.RegisterHotKey(
                None,
                hotkey_id,
                MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                virtual_key,
            ):
                registered.append(hotkey_id)
            else:
                self.failed.append(name)
        self.ready.set()

        message = Message()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                definition = self.DEFINITIONS.get(int(message.wParam))
                if definition:
                    self.events[definition[0]].set()
        for hotkey_id in registered:
            user32.UnregisterHotKey(None, hotkey_id)

    def consume(self, name: str) -> bool:
        event = self.events[name]
        if not event.is_set():
            return False
        event.clear()
        return True

    def close(self) -> None:
        if not self.thread_id:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostThreadMessageW.argtypes = (
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self.thread.join(timeout=1.5)


class Win32Window:
    """透明窗口、置顶、穿透、拖动和原生右键菜单。"""

    def __init__(
        self,
        hwnd: int,
        color_key: tuple[int, int, int],
        initial_position: tuple[int, int] | None = None,
        topmost: bool = True,
        click_through: bool = False,
    ) -> None:
        self.hwnd = hwnd
        self.color_key = color_key
        self.user32 = ctypes.windll.user32
        self.is_topmost = topmost
        self.click_through = click_through
        self.is_visible = True
        self.dragging = False
        self.drag_moved = False
        self.drag_offset = (0, 0)
        self.press_point = (0, 0)
        self.last_topmost_assertion = 0.0
        self._configure_api()
        self._configure_window(initial_position)

    def _configure_api(self) -> None:
        self.user32.SetWindowPos.argtypes = (
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        )
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.user32.SetLayeredWindowAttributes.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            wintypes.BYTE,
            wintypes.DWORD,
        )
        self.user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        self.user32.GetCursorPos.argtypes = (ctypes.POINTER(Point),)
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(Rect))
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.MonitorFromRect.argtypes = (ctypes.POINTER(Rect), wintypes.DWORD)
        self.user32.MonitorFromRect.restype = wintypes.HANDLE
        self.user32.GetMonitorInfoW.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(MonitorInfo),
        )
        self.user32.GetMonitorInfoW.restype = wintypes.BOOL
        self.user32.SetCapture.argtypes = (wintypes.HWND,)
        self.user32.SetCapture.restype = wintypes.HWND
        self.user32.ReleaseCapture.restype = wintypes.BOOL
        self.user32.CreatePopupMenu.restype = wintypes.HANDLE
        self.user32.AppendMenuW.argtypes = (
            wintypes.HANDLE,
            wintypes.UINT,
            ctypes.c_size_t,
            wintypes.LPCWSTR,
        )
        self.user32.AppendMenuW.restype = wintypes.BOOL
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.get_window_long = self.user32.GetWindowLongPtrW
            self.set_window_long = self.user32.SetWindowLongPtrW
            self.get_window_long.restype = ctypes.c_ssize_t
            self.set_window_long.restype = ctypes.c_ssize_t
            value_type = ctypes.c_ssize_t
        else:
            self.get_window_long = self.user32.GetWindowLongW
            self.set_window_long = self.user32.SetWindowLongW
            self.get_window_long.restype = wintypes.LONG
            self.set_window_long.restype = wintypes.LONG
            value_type = wintypes.LONG
        self.get_window_long.argtypes = (wintypes.HWND, ctypes.c_int)
        self.set_window_long.argtypes = (wintypes.HWND, ctypes.c_int, value_type)

    @staticmethod
    def _colorref(rgb: tuple[int, int, int]) -> int:
        red, green, blue = rgb
        return red | (green << 8) | (blue << 16)

    def _configure_window(self, initial_position: tuple[int, int] | None) -> None:
        style = self.get_window_long(self.hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        style = style | WS_EX_TOPMOST if self.is_topmost else style & ~WS_EX_TOPMOST
        style = style | WS_EX_TRANSPARENT if self.click_through else style & ~WS_EX_TRANSPARENT
        self.set_window_long(self.hwnd, GWL_EXSTYLE, style)
        self.user32.SetLayeredWindowAttributes(
            self.hwnd, self._colorref(self.color_key), 0, LWA_COLORKEY
        )
        self.set_topmost(self.is_topmost)
        if initial_position is None:
            initial_position = self.default_position()
        self.move(*self.clamp_to_visible_screen(*initial_position))

    def virtual_screen(self) -> tuple[int, int, int, int]:
        return (
            self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )

    def work_area_for(self, x: int, y: int) -> Rect:
        candidate = Rect(x, y, x + WINDOW_WIDTH, y + WINDOW_HEIGHT)
        monitor = self.user32.MonitorFromRect(
            ctypes.byref(candidate), MONITOR_DEFAULTTONEAREST
        )
        monitor_info = MonitorInfo()
        monitor_info.cbSize = ctypes.sizeof(MonitorInfo)
        if monitor and self.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return monitor_info.rcWork
        virtual_x, virtual_y, virtual_width, virtual_height = self.virtual_screen()
        return Rect(
            virtual_x,
            virtual_y,
            virtual_x + virtual_width,
            virtual_y + virtual_height,
        )

    def clamp_to_visible_screen(self, x: int, y: int) -> tuple[int, int]:
        work_area = self.work_area_for(x, y)
        max_x = max(work_area.left, work_area.right - WINDOW_WIDTH)
        max_y = max(work_area.top, work_area.bottom - WINDOW_HEIGHT)
        return (
            max(work_area.left, min(max_x, x)),
            max(work_area.top, min(max_y, y)),
        )

    def default_position(self) -> tuple[int, int]:
        position = (
            self.user32.GetSystemMetrics(0) - WINDOW_WIDTH - 36,
            self.user32.GetSystemMetrics(1) - WINDOW_HEIGHT - 76,
        )
        return self.clamp_to_visible_screen(*position)

    def _has_topmost_style(self) -> bool:
        return bool(self.get_window_long(self.hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)

    def set_topmost(self, enabled: bool) -> bool:
        style = self.get_window_long(self.hwnd, GWL_EXSTYLE)
        desired_style = style | WS_EX_TOPMOST if enabled else style & ~WS_EX_TOPMOST
        if desired_style != style:
            self.set_window_long(self.hwnd, GWL_EXSTYLE, desired_style)
        order = HWND_TOPMOST if enabled else HWND_NOTOPMOST
        succeeded = bool(
            self.user32.SetWindowPos(
                self.hwnd,
                order,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        )
        self.last_topmost_assertion = time.monotonic()
        if succeeded and self._has_topmost_style() == enabled:
            self.is_topmost = enabled
            return True
        return False

    def ensure_topmost(self, force: bool = False) -> bool:
        if not self.is_topmost or not self.is_visible:
            return True
        now = time.monotonic()
        if not force and now - self.last_topmost_assertion < 2.0:
            return True
        if force or not self._has_topmost_style():
            return self.set_topmost(True)
        succeeded = bool(
            self.user32.SetWindowPos(
                self.hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        )
        self.last_topmost_assertion = now
        return succeeded

    def set_click_through(self, enabled: bool) -> bool:
        style = self.get_window_long(self.hwnd, GWL_EXSTYLE)
        desired = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
        self.set_window_long(self.hwnd, GWL_EXSTYLE, desired)
        self.user32.SetWindowPos(
            self.hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE
            | SWP_NOSIZE
            | SWP_NOZORDER
            | SWP_NOACTIVATE
            | SWP_FRAMECHANGED,
        )
        actual = bool(self.get_window_long(self.hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT)
        if actual == enabled:
            self.click_through = enabled
            return True
        return False

    def move(self, x: int, y: int) -> None:
        self.user32.SetWindowPos(
            self.hwnd,
            0,
            int(x),
            int(y),
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )

    def cursor(self) -> Point:
        point = Point()
        self.user32.GetCursorPos(ctypes.byref(point))
        return point

    def rect(self) -> Rect:
        rect = Rect()
        self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        return rect

    def position(self) -> tuple[int, int]:
        rect = self.rect()
        return rect.left, rect.top

    def start_drag(self) -> None:
        point = self.cursor()
        rect = self.rect()
        self.dragging = True
        self.drag_moved = False
        self.press_point = (point.x, point.y)
        self.drag_offset = (point.x - rect.left, point.y - rect.top)
        self.user32.SetCapture(self.hwnd)

    def update_drag(self) -> None:
        if not self.dragging:
            return
        point = self.cursor()
        moved_x = abs(point.x - self.press_point[0])
        moved_y = abs(point.y - self.press_point[1])
        if moved_x > 6 or moved_y > 6:
            self.drag_moved = True
        if self.drag_moved:
            self.move(point.x - self.drag_offset[0], point.y - self.drag_offset[1])

    def finish_drag(self) -> tuple[bool, bool]:
        was_dragging = self.dragging
        moved = self.drag_moved
        self.dragging = False
        self.drag_moved = False
        if was_dragging:
            self.user32.ReleaseCapture()
        return was_dragging and not moved, moved

    def hide(self) -> None:
        self.user32.ShowWindow(self.hwnd, SW_HIDE)
        self.is_visible = False

    def show(self) -> None:
        self.user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.is_visible = True
        self.ensure_topmost(force=True)

    def summon(self) -> None:
        self.show()
        self.move(*self.default_position())

    def popup_menu(
        self,
        health_reminders: bool,
        paused: bool,
        gravity: bool,
        window_collision: bool,
        edge_snap: bool,
        autostart: bool,
    ) -> int:
        menu = self.user32.CreatePopupMenu()
        self.user32.AppendMenuW(menu, MF_STRING, MENU_CONTROL_PANEL, "打开控制面板")
        self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_SHRINK, "缩小")
        self.user32.AppendMenuW(menu, MF_STRING, MENU_DEFAULT_SIZE, "恢复默认大小")
        self.user32.AppendMenuW(menu, MF_STRING, MENU_GROW, "放大")
        self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        topmost_text = "关闭强力置顶" if self.is_topmost else "开启强力置顶"
        click_text = "关闭鼠标穿透（Ctrl+Alt+T）" if self.click_through else "开启鼠标穿透（Ctrl+Alt+T）"
        reminder_text = "关闭健康提醒" if health_reminders else "开启健康提醒"
        pause_text = "恢复主动动作" if paused else "暂停主动动作"
        self.user32.AppendMenuW(menu, MF_STRING, MENU_TOPMOST, topmost_text)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_CLICK_THROUGH, click_text)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_PAUSE, pause_text)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_HEALTH_REMINDERS, reminder_text)
        gravity_text = "关闭重力" if gravity else "开启重力"
        collision_text = "关闭窗口表面碰撞" if window_collision else "开启窗口表面碰撞"
        snap_text = "关闭屏幕边缘吸附" if edge_snap else "开启屏幕边缘吸附"
        self.user32.AppendMenuW(menu, MF_STRING, MENU_GRAVITY, gravity_text)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_WINDOW_COLLISION, collision_text)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_EDGE_SNAP, snap_text)
        autostart_text = "关闭开机自启" if autostart else "开启开机自启"
        self.user32.AppendMenuW(menu, MF_STRING, MENU_AUTOSTART, autostart_text)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_HOME, "回到桌面右下角")
        self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        self.user32.AppendMenuW(menu, MF_STRING, MENU_HIDE, "隐藏桌宠（Ctrl+Alt+D 召回）")
        self.user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, "退出程序")
        point = self.cursor()
        self.user32.SetForegroundWindow(self.hwnd)
        command = self.user32.TrackPopupMenu(
            menu,
            TPM_RETURNCMD | TPM_NONOTIFY,
            point.x,
            point.y,
            0,
            self.hwnd,
            None,
        )
        self.user32.DestroyMenu(menu)
        return int(command)
