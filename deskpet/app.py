"""桌宠主循环：连接动画、自然行为、养成、桌面物理和窗口交互。"""

from __future__ import annotations

import ctypes
import datetime as dt
import os
import random
import time
from pathlib import Path

import pygame

from .animation import GifClip, GifLibrary
from .behavior import BehaviorChange, BehaviorController
from .constants import (
    APP_TITLE,
    BASE_CHARACTER_SIZE,
    CHARACTER_CENTER_X,
    CHARACTER_FLOOR,
    COLOR_KEY,
    DEFAULT_SCALE,
    DOUBLE_CLICK_SECONDS,
    FPS,
    MAX_SCALE,
    MENU_AUTOSTART,
    MENU_BATHE,
    MENU_CLICK_THROUGH,
    MENU_CONTROL_PANEL,
    MENU_DEFAULT_SIZE,
    MENU_EDGE_SNAP,
    MENU_EXIT,
    MENU_FEED,
    MENU_GRAVITY,
    MENU_GROW,
    MENU_HEALTH_REMINDERS,
    MENU_HIDE,
    MENU_HOME,
    MENU_PAUSE,
    MENU_PET,
    MENU_PLAY,
    MENU_SHRINK,
    MENU_SLEEP,
    MENU_SNACK,
    MENU_STATUS,
    MENU_TOPMOST,
    MENU_TREAT,
    MENU_WINDOW_COLLISION,
    MIN_SCALE,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from .control_panel import ControlPanelBridge
from .data_tools import create_backup, create_restore_point, restore_backup
from .dialogue import SpeechBubble
from .ai_chat import OptionalAiClient
from .environment import local_environment
from .growth import TIMED_CARE_ACTIONS, PetGrowth
from .hud import PetHud
from .persistence import DeskPetDatabase
from .physics import DesktopPhysics, PhysicsEvent
from .quick_tools import launch_builtin, launch_custom, validate_custom_target
from .reminders import ReminderManager
from .roaming import ScreenRoamer
from .settings import SettingsStore
from .sound import play_alarm, play_interaction
from .startup import is_enabled as autostart_is_enabled
from .startup import set_enabled as set_autostart
from .system_monitor import SystemMonitor
from .weather import WeatherClient
from .window_win32 import GlobalHotkeys, Win32Window


class DeskPetApp:
    NEGLECT_AFTER_SECONDS = 45 * 60
    NEGLECT_REPEAT_SECONDS = 3 * 60 * 60
    NEGLECT_STAGES = (
        (3 * 60 * 60, "003", 20.0),
        (90 * 60, "110", 14.0),
        (45 * 60, "107", 8.0),
    )

    HEALTH_MESSAGES = (
        "坐久啦，起来伸个懒腰吧～",
        "喝口水，顺便休息一下眼睛吧！",
        "看看远处，让眼睛放松一会儿～",
    )

    CARE_COMMANDS = {
        MENU_FEED: "feed",
        MENU_SNACK: "snack",
        MENU_PET: "pet",
        MENU_PLAY: "play",
        MENU_BATHE: "bathe",
        MENU_SLEEP: "sleep",
        MENU_TREAT: "treat",
    }

    def __init__(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass

        seed_text = os.environ.get("DESKPET_RANDOM_SEED")
        seed = int(seed_text) if seed_text and seed_text.lstrip("-").isdigit() else None

        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.character_scale = float(self.settings["scale"])
        self.health_reminders = bool(self.settings["health_reminders"])
        self.animation_speed = float(self.settings["animation_speed"])
        self.bubble_speed = int(self.settings["bubble_speed"])
        self.ai_api_key = os.environ.get("DESKPET_AI_API_KEY", "").strip()

        pygame.init()
        pygame.font.init()
        pygame.display.set_caption(APP_TITLE)
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.NOFRAME)
        saved_position = self.settings["position"]
        self.window = Win32Window(
            pygame.display.get_wm_info()["window"],
            COLOR_KEY,
            initial_position=saved_position if isinstance(saved_position, tuple) else None,
            topmost=bool(self.settings["topmost"]),
            click_through=bool(self.settings["click_through"]),
        )
        self.hotkeys = GlobalHotkeys()
        hotkey_warning = ""
        if self.window.click_through and "toggle_click_through" in self.hotkeys.failed:
            self.window.set_click_through(False)
            self.settings["click_through"] = False
            hotkey_warning = "穿透快捷键被占用，已自动关闭穿透"
        elif self.hotkeys.failed:
            hotkey_warning = "部分全局快捷键已被其他程序占用"

        self.behavior = BehaviorController(seed=seed)
        self.library = GifLibrary(self.behavior.actions, max_loaded=8)
        self.current_action = self.behavior.current_action
        self.current_mode = self.behavior.mode
        self.current_clip: GifClip = self.library.get(self.current_action)
        self.current_clip.reset()
        self.growth = PetGrowth(
            seed=seed,
            natural_decay_multiplier=float(self.settings["natural_decay_multiplier"]),
            passive_energy_decay_per_hour=float(
                self.settings["passive_energy_decay_per_hour"]
            ),
            exercise_energy_multiplier=float(
                self.settings["exercise_energy_multiplier"]
            ),
        )
        self.behavior.set_level(self.growth.level)
        self.physics = DesktopPhysics(
            self.window,
            gravity=bool(self.settings["gravity"]),
            window_collision=bool(self.settings["window_collision"]),
            edge_snap=bool(self.settings["edge_snap"]),
            sprite_width=round(BASE_CHARACTER_SIZE * self.character_scale),
        )
        self.roamer = ScreenRoamer(self.window, seed=seed)
        self.database = DeskPetDatabase()
        self.database.purge_deleted()
        self.reminders = ReminderManager(self.database, self.settings)
        self.system_monitor = SystemMonitor()
        self.control_panel = ControlPanelBridge()
        self.ai_client = OptionalAiClient()
        self.weather_client = WeatherClient()
        self.weather_summary = "天气未启用"
        self.next_weather_refresh = 0.0
        self.ai_history = [("你：" if item["role"] == "user" else "小狗：") + str(item["content"]) for item in self.database.recent_chat_messages()]
        self.ai_pending: dict[int, str] = {}
        self.settings["autostart"] = autostart_is_enabled()

        self.clock = pygame.time.Clock()
        self.running = True
        self.exit_animation_pending = False
        self.exit_animation_deadline = 0.0
        self.fullscreen_hidden = False
        self.fullscreen_quiet = False
        self.paused = False
        self.needs_redraw = True
        self.settings_dirty = False
        self.settings_save_due = 0.0
        self.pressed_on_character = False
        self.pending_single_click = False
        self.pending_single_click_due = 0.0
        self.last_user_activity = time.monotonic()
        self.last_neglect_at = self.last_user_activity - self.NEGLECT_REPEAT_SECONDS
        self.growth_tick_seconds = int(self.settings["growth_tick_minutes"]) * 60
        self.next_growth_tick = time.monotonic() + self.growth_tick_seconds
        self.growth_save_due = time.monotonic() + 60
        self.next_need_check = time.monotonic() + random.uniform(3 * 60, 6 * 60)
        self.active_activity: dict[str, object] | None = None
        self.action_queue: list[str] = []
        self.bubble = SpeechBubble()
        self.bubble.typing_speed = float(self.bubble_speed)
        self.hud = PetHud()
        self.panel_note_search = ""
        self.panel_show_deleted = False
        self.next_panel_push = 0.0
        greeting = self.growth.offline_message() or self._time_greeting()
        self.bubble.show(hotkey_warning or greeting, seconds=4.5)
        self.sprite_surface, self.sprite_rect = self._current_sprite()

        initial_physics = self.physics.release()
        if initial_physics.kind == "falling":
            self._apply_behavior(self.behavior.play_external("109", "falling"))
        if os.environ.get("DESKPET_TEST_OPEN_PANEL") == "1":
            self._open_control_panel()

    @staticmethod
    def _time_greeting() -> str:
        hour = time.localtime().tm_hour
        if 5 <= hour < 11:
            return "早上好，今天也一起加油！"
        if 11 <= hour < 14:
            return "到饭点啦，记得好好吃饭～"
        if 14 <= hour < 18:
            return "下午好，我安静陪着你。"
        if 18 <= hour < 23:
            return "晚上好，今天辛苦啦！"
        return "夜深啦，别忘了早点休息～"

    def _current_sprite(self) -> tuple[pygame.Surface, pygame.Rect]:
        target_size = round(BASE_CHARACTER_SIZE * self.character_scale)
        surface = self.current_clip.surface(target_size)
        if self.current_mode == "roam":
            action = self.behavior.actions.get(self.current_action, {})
            native_direction = str(action.get("native_direction", "left"))
            target_direction = "right" if self.roamer.facing_right else "left"
            if native_direction != target_direction:
                surface = pygame.transform.flip(surface, True, False)
        elif self.current_mode == "edge_hide":
            action = self.behavior.actions.get(self.current_action, {})
            native_edge = str(action.get("native_edge", "left"))
            target_edge = str(self.physics.snapped_edge or "left")
            if native_edge != target_edge:
                surface = pygame.transform.flip(surface, True, False)
        rect = surface.get_rect(midbottom=(CHARACTER_CENTER_X, CHARACTER_FLOOR))
        return surface, rect

    def _hit_character(self, position: tuple[int, int]) -> bool:
        if not self.sprite_rect.collidepoint(position):
            return False
        local_x = position[0] - self.sprite_rect.left
        local_y = position[1] - self.sprite_rect.top
        return self.sprite_surface.get_at((local_x, local_y)).a >= 128

    def _apply_behavior(self, change: BehaviorChange) -> None:
        if self.roamer.active and change.mode != "roam":
            self._stop_roaming()
        self.current_action = change.action
        self.current_mode = change.mode
        try:
            clip = self.library.get(change.action)
        except (FileNotFoundError, ValueError, KeyError):
            self._stop_roaming()
            fallback = str(self.behavior.manifest["default_action"])
            self.behavior.current_action = fallback
            self.behavior.mode = "base"
            self.current_action = fallback
            self.current_mode = "base"
            clip = self.library.get(fallback)
            self.bubble.show("有一个动作素材损坏，已经回到待机")
        self.current_clip = clip
        self.current_clip.reset()
        self.needs_redraw = True

    def _start_roaming(self, change: BehaviorChange, now: float) -> None:
        sprite_width = round(BASE_CHARACTER_SIZE * self.character_scale)
        action = self.behavior.actions.get(change.action, {})
        raw_speed = action.get("movement_speed", (85, 115))
        speed_range = (
            (float(raw_speed[0]), float(raw_speed[1]))
            if isinstance(raw_speed, list) and len(raw_speed) == 2
            else (85.0, 115.0)
        )
        if not self.roamer.start(sprite_width, speed_range=speed_range):
            self.behavior.defer_roam(now)
            self._apply_behavior(self.behavior.return_to_base(now))
            return
        self.physics.begin_external_motion()
        self._apply_behavior(change)

    def _stop_roaming(self, *, snap_to_edge: bool = True) -> None:
        if not self.roamer.active:
            return
        self.roamer.stop()
        self.physics.end_external_motion(snap_to_edge=snap_to_edge)
        self._mark_settings_dirty()

    def _start_sequence(self, actions: tuple[str, ...]) -> None:
        if not actions:
            return
        repeated_actions: list[str] = []
        persistent_actions = {"094", "148", "160"}
        for action in actions:
            repeats = 1 if action in persistent_actions else 2
            repeated_actions.extend([action] * repeats)
        self.action_queue = repeated_actions[1:]
        if repeated_actions[0] == "160" and self.growth.sleeping:
            first_mode = "sleep"
        elif repeated_actions[0] in ("094", "148"):
            first_mode = "timer"
        else:
            first_mode = "sequence"
        self._apply_behavior(self.behavior.play_external(repeated_actions[0], first_mode, time.monotonic()))

    def _advance_sequence(self) -> None:
        if self.action_queue:
            action = self.action_queue.pop(0)
            if action == "160" and self.growth.sleeping:
                mode = "sleep"
            elif action in ("094", "148"):
                mode = "timer"
            else:
                mode = "sequence"
            self._apply_behavior(self.behavior.play_external(action, mode, time.monotonic()))
        else:
            activity = self.active_activity
            if activity and time.monotonic() < float(activity["ends_at"]):
                self._apply_behavior(
                    self.behavior.play_external(str(activity["animation"]), "activity")
                )
            else:
                self._settle_active_activity(time.monotonic())
                self._apply_behavior(self.behavior.return_to_base())

    def _set_scale(self, scale: float) -> None:
        new_scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        if abs(new_scale - self.character_scale) < 0.001:
            return
        if self.roamer.active:
            self._apply_behavior(self.behavior.finish_roam())
        self.character_scale = new_scale
        self.library.clear_scale_caches()
        self.physics.set_sprite_width(round(BASE_CHARACTER_SIZE * self.character_scale))
        self.sprite_surface, self.sprite_rect = self._current_sprite()
        self._mark_settings_dirty()
        self.needs_redraw = True

    def _mark_settings_dirty(self) -> None:
        self.settings_dirty = True
        self.settings_save_due = time.monotonic() + 0.6

    def _save_settings(self) -> None:
        self.settings.update(
            {
                "position": self.window.position(),
                "scale": self.character_scale,
                "topmost": self.window.is_topmost,
                "health_reminders": self.health_reminders,
                "click_through": self.window.click_through,
                "animation_speed": self.animation_speed,
                "bubble_speed": self.bubble_speed,
                "gravity": self.physics.gravity,
                "window_collision": self.physics.window_collision,
                "edge_snap": self.physics.edge_snap,
            }
        )
        if self.settings_store.save(self.settings):
            self.settings_dirty = False

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.bubble.show("主动动作已暂停" if self.paused else "主动动作已恢复")
        self.needs_redraw = True

    def _toggle_click_through(self) -> None:
        enabled = not self.window.click_through
        if self.window.set_click_through(enabled):
            self.bubble.show(
                "鼠标穿透已开启，按 Ctrl+Alt+T 关闭"
                if enabled
                else "鼠标穿透已关闭"
            )
            self._mark_settings_dirty()
        else:
            self.bubble.show("鼠标穿透设置失败")
        self.needs_redraw = True

    def _resume_interrupted_state(self, now: float | None = None) -> bool:
        """Restore a persistent activity after drag/fall has finished."""
        now = now if now is not None else time.monotonic()
        activity = self.active_activity
        if activity and now < float(activity["ends_at"]):
            self._apply_behavior(
                self.behavior.play_external(str(activity["animation"]), "activity", now)
            )
            return True
        if self.growth.sleeping:
            self._apply_behavior(self.behavior.play_external("160", "sleep", now))
            return True
        timer_action = self._active_timer_action()
        if timer_action:
            self._apply_behavior(self.behavior.play_external(timer_action, "timer", now))
            return True
        return False


    def _handle_physics_event(self, event: PhysicsEvent, *, show_bubble: bool = True) -> None:
        if event.kind == "edge_hide":
            if self.current_mode == "base" and not self.growth.sleeping:
                self.action_queue.clear()
                self._apply_behavior(self.behavior.play_external("103", "edge_hide"))
            else:
                self.physics.reveal_edge()
            return
        if event.kind == "edge_show":
            if self.current_mode == "edge_hide":
                self._apply_behavior(self.behavior.return_to_base())
            return
        if event.kind == "falling":
            self.action_queue.clear()
            if self.current_mode != "falling":
                self._apply_behavior(self.behavior.play_external("109", "falling"))
            return
        if event.kind == "landed":
            action = event.landing_action or "113"
            if not self._resume_interrupted_state():
                self._apply_behavior(self.behavior.end_drag(action))
            if show_bubble and event.drop_distance >= 30:
                self.bubble.show(self.behavior.dialogue_for(action))
            self._mark_settings_dirty()

    def _summon(self) -> None:
        self.physics.begin_drag()
        self.window.summon()
        event = self.physics.release()
        self._handle_physics_event(event, show_bubble=False)
        self.bubble.show("我回到这里啦！")
        self._mark_settings_dirty()

    def _handle_hotkeys(self) -> None:
        if self.hotkeys.consume("toggle_visibility"):
            if self.window.is_visible:
                self.window.hide()
            else:
                self.window.show()
                self.bubble.show("我回来啦！")
                self.needs_redraw = True
        if self.hotkeys.consume("toggle_click_through"):
            self._toggle_click_through()
        if self.hotkeys.consume("summon"):
            self._summon()
        if self.hotkeys.consume("toggle_pause"):
            self._toggle_pause()

    def _perform_care(
        self, action: str, duration_minutes: int | None = None
    ) -> None:
        now = time.monotonic()
        if (
            self.active_activity
            and now >= float(self.active_activity["ends_at"])
        ):
            self._settle_active_activity(now)
        if self.active_activity and action == "sleep":
            self._settle_active_activity(now)
        if (
            self.active_activity
            and (action in TIMED_CARE_ACTIONS or action in ("pet", "play"))
        ):
            remaining_seconds = float(self.active_activity["ends_at"]) - now
            remaining = max(1, int((remaining_seconds + 59) // 60))
            self.bubble.show(
                f"正在{self.active_activity['label']}，还剩约 {remaining} 分钟～",
                seconds=4.2,
            )
            self.needs_redraw = True
            return

        result = self.growth.perform(action, duration_minutes=duration_minutes)
        self.bubble.show(result.message, seconds=5.0)
        self.physics.note_activity()
        if result.accepted:
            play_interaction(bool(self.settings.get("interaction_sound", False)))
            if result.level_up:
                self.behavior.set_level(result.level_up)
            if (
                result.duration_minutes
                and result.activity_label
                and result.animations
            ):
                now = time.monotonic()
                self.active_activity = {
                    "action": action,
                    "label": result.activity_label,
                    "animation": result.animations[0],
                    "started_at": now,
                    "duration_minutes": result.duration_minutes,
                    "ends_at": now + result.duration_minutes * 60,
                }
                self.action_queue.clear()
                self._apply_behavior(
                    self.behavior.play_external(result.animations[0], "activity", now)
                )
            else:
                if action == "sleep":
                    self.active_activity = None
                self._start_sequence(result.animations)
            self.last_user_activity = time.monotonic()
            self.last_neglect_at = self.last_user_activity - self.NEGLECT_REPEAT_SECONDS
        self.needs_redraw = True

    def _settle_active_activity(self, now: float) -> CareResult | None:
        activity = self.active_activity
        if not activity:
            return None
        self.active_activity = None
        result = self.growth.complete_timed_activity(
            str(activity["action"]),
            int(activity["duration_minutes"]),
            max(0.0, now - float(activity["started_at"])),
        )
        if result.level_up:
            self.behavior.set_level(result.level_up)
        return result


    def _stop_active_activity(self) -> None:
        activity = self.active_activity
        if not activity:
            self.bubble.show("当前没有进行中的活动")
            return
        result = self._settle_active_activity(time.monotonic())
        self.action_queue.clear()
        self._apply_behavior(self.behavior.return_to_base())
        self.bubble.show(result.message if result else "活动已结束", seconds=4.5)
        self.needs_redraw = True

    def _launch_hud_tool(self, tool_id: str) -> None:
        if tool_id == "control_panel":
            self._open_control_panel()
            message = "控制面板已打开"
        else:
            _ok, message = launch_builtin(tool_id)
        self.bubble.show(message, seconds=3.5)
        self.physics.note_activity()
        self.last_user_activity = time.monotonic()
        self.last_neglect_at = self.last_user_activity - self.NEGLECT_REPEAT_SECONDS
        self.needs_redraw = True

    def _activity_status_text(self, now: float | None = None) -> str | None:
        activity = self.active_activity
        if not activity:
            return None
        now = now if now is not None else time.monotonic()
        remaining_seconds = max(0.0, float(activity["ends_at"]) - now)
        remaining_minutes = max(1, int((remaining_seconds + 59) // 60))
        return f"{activity['label']}·{remaining_minutes}分"

    def _panel_snapshot(self, message: str | None = None) -> dict[str, object]:
        current_settings = dict(self.settings)
        current_settings.update(
            {
                "scale": self.character_scale,
                "animation_speed": self.animation_speed,
                "bubble_speed": self.bubble_speed,
                "topmost": self.window.is_topmost,
                "click_through": self.window.click_through,
                "gravity": self.physics.gravity,
                "window_collision": self.physics.window_collision,
                "edge_snap": self.physics.edge_snap,
            }
        )
        growth = {
            "level": self.growth.level,
            "mode": "睡眠中" if self.growth.sleeping else "清醒",
            "xp": int(self.growth.state["xp"]),
            **{name: self.growth.value(name) for name in (
                "fullness",
                "mood",
                "energy",
                "cleanliness",
                "health",
                "affection",
            )},
        }
        snapshot: dict[str, object] = {
            "growth": growth,
            "settings": current_settings,
            "system": self.system_monitor.snapshot.to_dict(),
            "timer_summary": self.reminders.active_summary(),
            "timers": self.database.active_timers(),
            "notes": self.database.list_notes(
                self.panel_note_search, include_deleted=self.panel_show_deleted
            ),
            "environment": local_environment().label,
            "weather": self.weather_summary,
            "ai_history": chr(10).join(self.ai_history[-12:]),
        }
        if message:
            snapshot["message"] = message
        return snapshot

    def _open_control_panel(self) -> None:
        self.control_panel.open(self._panel_snapshot())
        self.last_user_activity = time.monotonic()
        self.last_neglect_at = self.last_user_activity - self.NEGLECT_REPEAT_SECONDS

    @staticmethod
    def _integer(value: object, minimum: int, maximum: int, label: str) -> int:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}必须填写整数") from error
        if not minimum <= parsed <= maximum:
            raise ValueError(f"{label}必须在 {minimum}～{maximum} 之间")
        return parsed

    @staticmethod
    def _number(
        value: object, minimum: float, maximum: float, label: str
    ) -> float:
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}必须填写数字") from error
        if not minimum <= parsed <= maximum:
            raise ValueError(f"{label}必须在 {minimum:g}～{maximum:g} 之间")
        return parsed

    def _apply_panel_settings(self, values: dict[str, object]) -> str:
        ai_enabled = bool(values.get("ai_enabled", self.settings.get("ai_enabled", False)))
        ai_base_url = str(values.get("ai_base_url", self.settings.get("ai_base_url", ""))).strip()
        ai_model = str(values.get("ai_model", self.settings.get("ai_model", ""))).strip()
        submitted_key = str(values.get("ai_api_key", "")).strip()
        if ai_enabled:
            if not ai_base_url.startswith(("https://", "http://")):
                raise ValueError("启用 AI 时，接口地址必须以 http:// 或 https:// 开头")
            if not ai_model:
                raise ValueError("启用 AI 时必须填写模型名")
            if submitted_key:
                self.ai_api_key = submitted_key
            if not self.ai_api_key:
                raise ValueError("启用 AI 时必须填写 API 密钥")
        weather_enabled = bool(values.get("weather_enabled", self.settings.get("weather_enabled", False)))
        weather_city = str(values.get("weather_city", self.settings.get("weather_city", ""))).strip()[:80]
        fullscreen_policy = str(values.get("fullscreen_policy", self.settings.get("fullscreen_policy", "quiet")))
        if fullscreen_policy not in ("hide", "quiet", "ignore"):
            raise ValueError("全屏策略无效")
        if weather_enabled and not weather_city:
            raise ValueError("启用天气时请填写城市")
        scale = float(values.get("scale", self.character_scale))
        speed = float(values.get("animation_speed", self.animation_speed))
        bubble_speed = self._integer(values.get("bubble_speed", 18), 10, 30, "气泡速度")
        intervals = {
            key: self._integer(values.get(key, default), 5, 240, label)
            for key, default, label in (
                ("reminder_sedentary_minutes", 60, "久坐间隔"),
                ("reminder_water_minutes", 70, "喝水间隔"),
                ("reminder_eyes_minutes", 45, "护眼间隔"),
            )
        }
        growth_settings = {
            "growth_tick_minutes": self._integer(
                values.get("growth_tick_minutes", 10), 1, 60, "状态结算周期"
            ),
            "natural_decay_multiplier": self._number(
                values.get("natural_decay_multiplier", 2.0),
                0.0,
                5.0,
                "自然消耗倍率",
            ),
            "passive_energy_decay_per_hour": self._number(
                values.get("passive_energy_decay_per_hour", 0.2),
                0.0,
                2.0,
                "体力自然消耗",
            ),
            "exercise_energy_multiplier": self._number(
                values.get("exercise_energy_multiplier", 2.0),
                0.0,
                4.0,
                "运动体力倍率",
            ),
        }
        self._set_scale(scale)
        self.animation_speed = max(0.5, min(1.5, speed))
        self.bubble_speed = bubble_speed
        self.bubble.typing_speed = float(bubble_speed)

        old_gravity = self.physics.gravity
        old_collision = self.physics.window_collision
        self.physics.gravity = bool(values.get("gravity", self.physics.gravity))
        self.physics.window_collision = bool(
            values.get("window_collision", self.physics.window_collision)
        )
        self.physics.edge_snap = bool(values.get("edge_snap", self.physics.edge_snap))
        if (old_gravity, old_collision) != (
            self.physics.gravity,
            self.physics.window_collision,
        ):
            self.physics.support = None
            event = self.physics.release()
            self._handle_physics_event(event, show_bubble=False)
        elif self.physics.edge_snap:
            self.physics.snap_to_edge()

        requested_topmost = bool(values.get("topmost", self.window.is_topmost))
        if requested_topmost != self.window.is_topmost:
            self.window.set_topmost(requested_topmost)
        requested_click = bool(values.get("click_through", self.window.click_through))
        if requested_click != self.window.click_through:
            self.window.set_click_through(requested_click)

        for key in (
            "alarm_sound",
            "interaction_sound",
            "reminder_sedentary",
            "reminder_water",
            "reminder_eyes",
        ):
            self.settings[key] = bool(values.get(key, self.settings.get(key, True)))
        self.settings.update(intervals)
        self.settings.update(
            {
                "ai_enabled": ai_enabled,
                "ai_base_url": ai_base_url[:500],
                "ai_model": ai_model[:200],
                "weather_enabled": weather_enabled,
                "weather_city": weather_city,
                "fullscreen_policy": fullscreen_policy,
            }
        )
        self.growth.update()
        self.settings.update(growth_settings)
        self.growth.configure(
            natural_decay_multiplier=float(
                growth_settings["natural_decay_multiplier"]
            ),
            passive_energy_decay_per_hour=float(
                growth_settings["passive_energy_decay_per_hour"]
            ),
            exercise_energy_multiplier=float(
                growth_settings["exercise_energy_multiplier"]
            ),
        )
        self.growth_tick_seconds = int(growth_settings["growth_tick_minutes"]) * 60
        self.next_growth_tick = time.monotonic() + self.growth_tick_seconds

        requested_autostart = bool(
            values.get("autostart", self.settings.get("autostart", False))
        )
        if requested_autostart != bool(self.settings.get("autostart", False)):
            if not set_autostart(requested_autostart):
                raise ValueError("开机自启设置失败")
            self.settings["autostart"] = requested_autostart
        self._mark_settings_dirty()
        self._save_settings()
        return "设置已经应用"

    def _handle_panel_commands(self) -> None:
        for item in self.control_panel.poll_commands():
            command = str(item.get("command", ""))
            message = ""
            try:
                if command == "care":
                    self._perform_care(str(item.get("action", "")))
                    message = "照顾动作已执行"
                elif command == "start_countdown":
                    minutes = self._integer(item.get("minutes"), 1, 1440, "倒计时分钟")
                    self.reminders.start_countdown(str(item.get("title", "")), minutes)
                    message = f"倒计时已开始：{minutes} 分钟"
                elif command == "start_alarm":
                    parts = str(item.get("time", "")).strip().split(":")
                    if len(parts) != 2:
                        raise ValueError("闹钟时间格式应为 HH:MM")
                    hour = self._integer(parts[0], 0, 23, "小时")
                    minute = self._integer(parts[1], 0, 59, "分钟")
                    weekday_text = str(item.get("weekdays", "")).strip()
                    weekdays: tuple[int, ...] = ()
                    if weekday_text:
                        weekdays = tuple(
                            self._integer(value, 1, 7, "星期") - 1
                            for value in weekday_text.split(",")
                            if value.strip()
                        )
                    self.reminders.schedule_alarm(
                        str(item.get("title", "")), hour, minute, weekdays
                    )
                    message = f"闹钟已设置为 {hour:02d}:{minute:02d}"
                elif command == "start_pomodoro":
                    work = self._integer(item.get("work"), 1, 180, "专注时间")
                    short = self._integer(item.get("short"), 1, 60, "短休时间")
                    long = self._integer(item.get("long"), 1, 120, "长休时间")
                    self.reminders.start_pomodoro(work, short, long)
                    self._apply_behavior(self.behavior.play_external("148", "timer"))
                    message = "四轮番茄钟已开始"
                elif command == "stop_pomodoro":
                    self.reminders.stop_pomodoro()
                    if self.current_mode == "timer":
                        self._apply_behavior(self.behavior.return_to_base())
                    message = "番茄钟已停止"
                elif command == "cancel_timer":
                    timer_id = self._integer(item.get("timer_id"), 1, 2_000_000_000, "计时编号")
                    message = "计时已取消" if self.database.cancel_timer(timer_id) else "计时已经结束"
                elif command == "search_notes":
                    self.panel_note_search = str(item.get("search", ""))[:100]
                    message = "便签列表已筛选"
                elif command == "show_deleted_notes":
                    self.panel_show_deleted = bool(item.get("enabled", False))
                    message = "正在显示最近删除" if self.panel_show_deleted else "正在显示当前便签"
                elif command == "add_note":
                    due_text = str(item.get("due", "")).strip()
                    due_at = None
                    if due_text:
                        try:
                            due_at = dt.datetime.strptime(
                                due_text, "%Y-%m-%d %H:%M"
                            ).timestamp()
                        except ValueError as error:
                            raise ValueError("到期时间格式应为 YYYY-MM-DD HH:MM") from error
                    priority = {"低": 0, "普通": 1, "高": 2}.get(
                        str(item.get("priority", "普通")), 1
                    )
                    self.database.add_note(
                        str(item.get("title", "")),
                        str(item.get("content", "")),
                        due_at,
                        priority,
                    )
                    message = "便签已保存"
                elif command in ("toggle_note", "postpone_note", "delete_or_restore_note"):
                    note_id = self._integer(item.get("note_id"), 1, 2_000_000_000, "便签编号")
                    if command == "toggle_note":
                        self.database.toggle_note(note_id)
                        message = "待办状态已更新"
                    elif command == "postpone_note":
                        self.database.postpone_note(note_id)
                        message = "已延期一天"
                    elif bool(item.get("deleted", False)):
                        self.database.restore_note(note_id)
                        message = "便签已恢复"
                    else:
                        self.database.delete_note(note_id)
                        message = "便签已移入最近删除"
                elif command == "export_notes":
                    destination = str(item.get("destination", "")).strip()
                    if destination:
                        count = self.database.export_notes(Path(destination))
                        message = f"已导出 {count} 条便签"
                elif command == "backup_data":
                    destination = Path(str(item.get("destination", "")).strip())
                    if not str(destination): raise ValueError("请选择备份位置")
                    self.database.connection.commit()
                    create_backup(destination, {"settings.json": self.settings_store.path, "pet_state.json": self.growth.path, "deskpet.db": self.database.path})
                    message = "本地数据已备份"
                elif command == "restore_data":
                    source = Path(str(item.get("source", "")).strip())
                    if not source.exists(): raise ValueError("备份文件不存在")
                    self.database.connection.commit()
                    restore_point = create_restore_point(
                        self.settings_store.path.parent / "backups",
                        {"settings.json": self.settings_store.path, "pet_state.json": self.growth.path, "deskpet.db": self.database.path},
                    )
                    self.database.close()
                    restore_backup(source, {"settings.json": self.settings_store.path, "pet_state.json": self.growth.path, "deskpet.db": self.database.path})
                    self.running = False
                    message = f"数据已恢复，已创建恢复前备份：{restore_point.name}"
                elif command == "apply_weather":
                    enabled = bool(item.get("enabled", False))
                    city = str(item.get("city", "")).strip()[:80]
                    if enabled and not city:
                        raise ValueError("启用天气时请填写城市")
                    self.settings["weather_enabled"] = enabled
                    self.settings["weather_city"] = city
                    self._mark_settings_dirty()
                    self._save_settings()
                    if enabled:
                        self.weather_client.refresh(city)
                        message = "正在刷新天气……"
                    else:
                        self.weather_summary = "天气未启用"
                        message = "天气已关闭"
                elif command == "ai_chat":
                    message_text = str(item.get("message", "")).strip()
                    if not bool(self.settings.get("ai_enabled", False)):
                        raise ValueError("请先在 AI（可选）页启用并应用配置")
                    if not message_text:
                        raise ValueError("请输入想对小狗说的话")
                    request_id = self.ai_client.submit(message_text, {
                        "base_url": str(self.settings["ai_base_url"]),
                        "model": str(self.settings["ai_model"]),
                        "api_key": self.ai_api_key,
                    })
                    self.ai_pending[request_id] = message_text
                    self.ai_history.append("你：" + message_text[:300])
                    self.database.add_chat_message("user", message_text)
                    message = "正在向 AI 发送消息……"
                elif command == "clear_ai_data":
                    self.database.clear_ai_data()
                    self.ai_history.clear()
                    message = "AI 对话和记忆已清除"
                elif command == "apply_settings":
                    values = item.get("values")
                    if not isinstance(values, dict):
                        raise ValueError("设置数据无效")
                    message = self._apply_panel_settings(values)
                elif command == "launch_tool":
                    _ok, message = launch_builtin(str(item.get("tool", "")))
                elif command == "launch_custom":
                    _ok, message = launch_custom(str(item.get("target", "")))
                elif command == "save_custom_tool":
                    name = str(item.get("name", "")).strip()[:40]
                    if not name:
                        raise ValueError("请填写快捷工具名称")
                    valid, target = validate_custom_target(str(item.get("target", "")))
                    if not valid:
                        raise ValueError(target)
                    tools = list(self.settings.get("custom_tools", []))
                    tools = [tool for tool in tools if tool.get("name") != name]
                    tools.append({"name": name, "target": target})
                    self.settings["custom_tools"] = tools[-12:]
                    self._mark_settings_dirty()
                    message = "自定义快捷工具已保存"
            except (OSError, ValueError) as error:
                message = str(error) or "操作失败"
            if message:
                self.control_panel.push_snapshot(self._panel_snapshot(message))

    def _toggle_physics(self, command: int) -> None:
        if command == MENU_GRAVITY:
            self.physics.gravity = not self.physics.gravity
            if self.physics.gravity:
                event = self.physics.release()
                self._handle_physics_event(event, show_bubble=False)
            else:
                self.physics.falling = False
                self.physics.snap_to_edge()
            self.bubble.show("重力已开启" if self.physics.gravity else "重力已关闭")
        elif command == MENU_WINDOW_COLLISION:
            self.physics.window_collision = not self.physics.window_collision
            self.physics.support = None
            if self.physics.gravity:
                event = self.physics.release()
                self._handle_physics_event(event, show_bubble=False)
            self.bubble.show(
                "现在可以落在其他窗口顶部"
                if self.physics.window_collision
                else "窗口表面碰撞已关闭"
            )
        elif command == MENU_EDGE_SNAP:
            self.physics.edge_snap = not self.physics.edge_snap
            if self.physics.edge_snap:
                self.physics.snap_to_edge()
            self.bubble.show(
                "屏幕边缘吸附已开启" if self.physics.edge_snap else "屏幕边缘吸附已关闭"
            )
        self._mark_settings_dirty()
        self.needs_redraw = True

    def _request_exit(self) -> None:
        if self.exit_animation_pending:
            return
        self.exit_animation_pending = True
        self.exit_animation_deadline = time.monotonic() + 4.0
        self.action_queue.clear()
        self.active_activity = None
        self.hud.visible = False
        self._apply_behavior(self.behavior.play_external("103", "exit"))
        self.bubble.show("我先躲起来啦，下次见～", seconds=3.0)
        self.needs_redraw = True

    def _handle_menu(self) -> None:
        self.pending_single_click = False
        command = self.window.popup_menu(
            self.health_reminders,
            self.paused,
            self.physics.gravity,
            self.physics.window_collision,
            self.physics.edge_snap,
            bool(self.settings.get("autostart", False)),
        )
        self.last_user_activity = time.monotonic()
        self.last_neglect_at = self.last_user_activity - self.NEGLECT_REPEAT_SECONDS
        if command == MENU_CONTROL_PANEL:
            self._open_control_panel()
        elif command == MENU_SHRINK:
            self._set_scale(self.character_scale - 0.1)
        elif command == MENU_DEFAULT_SIZE:
            self._set_scale(DEFAULT_SCALE)
        elif command == MENU_GROW:
            self._set_scale(self.character_scale + 0.1)
        elif command == MENU_TOPMOST:
            enabled = not self.window.is_topmost
            if self.window.set_topmost(enabled):
                self.bubble.show("强力置顶已开启" if enabled else "置顶已关闭")
                self._mark_settings_dirty()
            else:
                self.bubble.show("置顶设置失败，请再试一次")
        elif command == MENU_CLICK_THROUGH:
            self._toggle_click_through()
        elif command == MENU_PAUSE:
            self._toggle_pause()
        elif command == MENU_HEALTH_REMINDERS:
            self.health_reminders = not self.health_reminders
            self.bubble.show("健康提醒已开启" if self.health_reminders else "健康提醒已关闭")
            self._mark_settings_dirty()
        elif command == MENU_AUTOSTART:
            requested = not bool(self.settings.get("autostart", False))
            if set_autostart(requested):
                self.settings["autostart"] = requested
                self.bubble.show("开机自启已开启" if requested else "开机自启已关闭")
                self._mark_settings_dirty()
            else:
                self.bubble.show("开机自启设置失败")
        elif command in (MENU_GRAVITY, MENU_WINDOW_COLLISION, MENU_EDGE_SNAP):
            self._toggle_physics(command)
        elif command == MENU_HOME:
            self._summon()
        elif command == MENU_HIDE:
            self.window.hide()
        elif command == MENU_EXIT:
            self._request_exit()
        self.needs_redraw = True

    def _handle_character_click(self) -> None:
        now = time.monotonic()
        if self.pending_single_click and now <= self.pending_single_click_due:
            self.pending_single_click = False
            self._open_control_panel()
        else:
            self.pending_single_click = True
            self.pending_single_click_due = now + DOUBLE_CLICK_SECONDS

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.last_user_activity = time.monotonic()
                self.last_neglect_at = self.last_user_activity - self.NEGLECT_REPEAT_SECONDS
                self.physics.note_activity()
                if event.button == 1:
                    hud_action = self.hud.action_at(event.pos)
                    if hud_action == "__menu__":
                        self.needs_redraw = True
                    elif hud_action and hud_action.startswith("activity:"):
                        _prefix, action, minutes = hud_action.split(":", 2)
                        self._perform_care(action, int(minutes))
                    elif hud_action == "stop_activity":
                        self._stop_active_activity()
                    elif hud_action and hud_action.startswith("tool:"):
                        self._launch_hud_tool(hud_action.partition(":")[2])
                    elif hud_action:
                        self._perform_care(hud_action)
                    elif self._hit_character(event.pos):
                        self.pressed_on_character = True
                        self.window.start_drag()
                elif event.button == 3 and self._hit_character(event.pos):
                    self._handle_menu()
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.pressed_on_character:
                    was_click, moved = self.window.finish_drag()
                    if was_click:
                        self._handle_character_click()
                    elif moved:
                        self.pending_single_click = False
                        physics_event = self.physics.release(self.window.drag_velocity)
                        self._handle_physics_event(physics_event)
                    self.pressed_on_character = False
            elif event.type == pygame.MOUSEWHEEL:
                if self._hit_character(pygame.mouse.get_pos()):
                    self._set_scale(self.character_scale + event.y * 0.08)
            elif event.type == pygame.MOUSEMOTION:
                self.needs_redraw = True
            elif event.type in (
                pygame.WINDOWFOCUSGAINED,
                pygame.WINDOWFOCUSLOST,
                pygame.WINDOWSHOWN,
                pygame.WINDOWRESTORED,
            ):
                self.window.ensure_topmost(force=True)

    def _update_growth(self, now: float) -> None:
        if now >= self.next_growth_tick:
            self.growth.update()
            self.next_growth_tick = now + self.growth_tick_seconds
        if now >= self.growth_save_due:
            self.growth.save()
            self.growth_save_due = now + 60

        if (
            now >= self.next_need_check
            and not self.paused
            and self.window.is_visible
            and self.current_mode == "base"
            and now - self.last_user_activity >= 30
        ):
            need = self.growth.suggested_need()
            if need:
                action, message = need
                self.action_queue.clear()
                self._apply_behavior(self.behavior.play_external(action, "need"))
                self.bubble.show(message, seconds=5.0)
                self.needs_redraw = True
                self.next_need_check = now + 30 * 60
            else:
                self.next_need_check = now + random.uniform(5 * 60, 9 * 60)

        if (
            not self.paused
            and self.window.is_visible
            and not self.growth.sleeping
            and not self.active_activity
            and self.current_mode == "base"
            and now - self.last_user_activity >= self.NEGLECT_AFTER_SECONDS
            and now - self.last_neglect_at >= self.NEGLECT_REPEAT_SECONDS
        ):
            self._trigger_neglect(now)

    @classmethod
    def _neglect_stage(cls, idle_seconds: float) -> tuple[str, float]:
        for threshold, action, mood_loss in cls.NEGLECT_STAGES:
            if idle_seconds >= threshold:
                return action, mood_loss
        return "107", 8.0

    def _trigger_neglect(self, now: float) -> None:
        """按冷落时长播放对应的生气反馈并扣除一次心情。"""
        action, mood_loss = self._neglect_stage(now - self.last_user_activity)
        self.last_neglect_at = now
        self.action_queue.clear()
        self.growth.apply_neglect(mood_loss)
        self._apply_behavior(self.behavior.play_external(action, "neglected", now))
        self.bubble.show(self.behavior.dialogue_for(action), seconds=5.0)
        self.needs_redraw = True

    def _active_timer_action(self) -> str | None:
        for timer in self.database.active_timers():
            if timer["kind"] == "pomodoro_work":
                return "148"
            if timer["kind"] == "pomodoro_break":
                return "094"
        return None

    def _update_m3_services(self, now: float) -> None:
        if bool(self.settings.get("weather_enabled", False)) and now >= self.next_weather_refresh:
            city = str(self.settings.get("weather_city", "")).strip()
            if city:
                self.weather_client.refresh(city)
                self.next_weather_refresh = now + 1800
        for weather in self.weather_client.poll():
            self.weather_summary = weather.error or weather.summary
        for reply in self.ai_client.poll():
            self.ai_pending.pop(reply.request_id, None)
            text = reply.error or reply.text
            self.ai_history.append("小狗：" + text[:800])
            self.database.add_chat_message("assistant", text)
            self.bubble.show(text, seconds=7.0)
            self.needs_redraw = True
        events = self.reminders.tick(self.settings)
        if events:
            message = "；".join(event.message.rstrip("。！～") for event in events) + "！"
            self.bubble.show(message, seconds=8.0)
            if any(event.alarm for event in events):
                play_alarm(bool(self.settings.get("alarm_sound", True)))
            reward = sum(event.reward_xp for event in events)
            if reward:
                level_up = self.growth.reward_xp(reward)
                if level_up:
                    self.behavior.set_level(level_up)
            timer_action = self._active_timer_action()
            if self.current_mode not in ("drag", "falling", "sleep", "activity"):
                if timer_action:
                    self._start_sequence(("138", timer_action))
                else:
                    self._apply_behavior(self.behavior.play_external("138", "interaction"))
            self.physics.note_activity()
            self.needs_redraw = True

        _snapshot, alerts = self.system_monitor.update(now)
        if alerts and self.current_mode not in ("drag", "falling", "sleep", "activity"):
            self.bubble.show("；".join(alerts), seconds=7.0)
            self._apply_behavior(self.behavior.play_external("091", "interaction"))
            self.needs_redraw = True

        if self.control_panel.is_created and now >= self.next_panel_push:
            self.control_panel.push_snapshot(self._panel_snapshot())
            self.next_panel_push = now + 2.0

    def _update(self, elapsed: float) -> None:
        now = time.monotonic()
        self._handle_hotkeys()
        fullscreen = self.window.foreground_window_is_fullscreen()
        policy = str(self.settings.get("fullscreen_policy", "quiet"))
        self.fullscreen_quiet = fullscreen and policy == "quiet"
        if fullscreen and policy == "hide" and self.window.is_visible:
            self.window.hide()
            self.fullscreen_hidden = True
        elif self.fullscreen_hidden and not fullscreen:
            self.window.show()
            self.fullscreen_hidden = False
        self.control_panel.pump()
        self._handle_panel_commands()
        window_x, window_y = self.window.position()
        work_area = self.window.work_area_for(window_x, window_y)
        visible_horizontal = (
            max(0, work_area.left - window_x),
            min(WINDOW_WIDTH, work_area.right - window_x),
        )

        hud_activity_changed = self.hud.set_activity_active(
            bool(self.active_activity and now < float(self.active_activity["ends_at"]))
        )
        mouse_position = pygame.mouse.get_pos()
        hud_changed = self.hud.update(
            mouse_position,
            self.sprite_rect,
            visible_horizontal=visible_horizontal,
            now=now,
            force_hide=self.window.dragging or self.window.click_through,
            character_hover=self._hit_character(mouse_position),
        )
        if hud_changed or hud_activity_changed:
            self.needs_redraw = True

        if self.pending_single_click and now >= self.pending_single_click_due:
            self.pending_single_click = False
            if self.growth.sleeping:
                self._perform_care("sleep")
            else:
                change = self.behavior.trigger_interaction(now)
                self._apply_behavior(change)
                self.bubble.show(self.behavior.dialogue_for(change.action))
                self.last_user_activity = now

        self.window.update_drag()
        if self.window.dragging and self.window.drag_moved and self.current_mode != "drag":
            self.pending_single_click = False
            self._stop_roaming(snap_to_edge=False)
            self.physics.begin_drag()
            self.action_queue.clear()
            self._apply_behavior(self.behavior.begin_drag())

        roaming_this_tick = self.current_mode == "roam"
        if roaming_this_tick:
            if not self.paused and self.window.is_visible and self.roamer.update(elapsed):
                self._apply_behavior(self.behavior.finish_roam(now))
            physics_event = None
        else:
            physics_event = self.physics.update(
                elapsed,
                user_active=(
                    self.window.dragging
                    or self.pending_single_click
                    or now - self.last_user_activity < 1.0
                ),
                bubble_visible=self.bubble.visible(now) or self.hud.visible,
            )
        if physics_event:
            self._handle_physics_event(physics_event)

        # “全屏静默”只抑制打扰行为，不能暂停 GIF 的逐帧更新；否则最大化窗口
        # 被误判为全屏时，角色会停在某一帧，看起来像动画卡住。
        if not self.paused and self.window.is_visible:
            action_definition = self.behavior.actions.get(self.current_action, {})
            activity_loops = bool(action_definition.get("activity_loop", True))
            # 定时活动默认持续循环；特殊素材可在结尾停住。
            finished = self.current_clip.update(
                elapsed * self.animation_speed,
                force_loop=self.current_mode == "activity" and activity_loops,
            )
            if self.exit_animation_pending:
                if (
                    finished
                    or self.current_clip.loop_completed
                    or now >= self.exit_animation_deadline
                ):
                    self.running = False
                self.needs_redraw = self.needs_redraw or self.current_clip.frame_changed
                return
            if self.current_mode == "activity":
                activity = self.active_activity
                if not activity or now >= float(activity["ends_at"]):
                    label = str(activity["label"]) if activity else "活动"
                    result = self._settle_active_activity(now)
                    self._apply_behavior(self.behavior.return_to_base(now))
                    self.bubble.show(result.message if result else f"{label}结束啦，辛苦了～", seconds=4.5)
                elif finished and activity_loops:
                    self.current_clip.reset()
            elif self.current_mode == "sequence" and finished:
                self._advance_sequence()
            elif self.current_mode == "need" and (
                finished or self.current_clip.loop_completed
            ):
                self._apply_behavior(self.behavior.return_to_base(now))
            else:
                user_active = (
                    self.window.dragging
                    or self.pending_single_click
                    or now - self.last_user_activity < 20 * self.behavior.time_scale
                )
                change = self.behavior.update(
                    now=now,
                    loop_completed=self.current_clip.loop_completed,
                    finished=finished,
                    user_active=user_active,
                )
                if change:
                    if change.mode == "roam":
                        self._start_roaming(change, now)
                    else:
                        self._apply_behavior(change)
            self.needs_redraw = self.needs_redraw or self.current_clip.frame_changed

        self._update_growth(now)
        self._update_m3_services(now)

        if self.bubble.needs_redraw(now):
            self.needs_redraw = True
        self.window.ensure_topmost()
        if self.settings_dirty and now >= self.settings_save_due:
            self._save_settings()

    def _render(self) -> None:
        if not self.window.is_visible or not self.needs_redraw:
            return
        self.screen.fill(COLOR_KEY)
        self.sprite_surface, self.sprite_rect = self._current_sprite()
        self.screen.blit(self.sprite_surface, self.sprite_rect)
        self.hud.draw(
            self.screen,
            self.growth,
            show_card=not self.bubble.visible(),
            activity_text=self._activity_status_text(),
            weather_text=(
                self.weather_summary
                if bool(self.settings.get("weather_enabled", False))
                else None
            ),
        )
        self.bubble.draw(self.screen, self.sprite_rect)
        pygame.display.flip()
        self.needs_redraw = False

    def run(self, max_seconds: float | None = None) -> None:
        started = time.monotonic()
        try:
            while self.running:
                if max_seconds is not None and time.monotonic() - started >= max_seconds:
                    self.running = False
                    continue
                elapsed = self.clock.tick(FPS if self.window.is_visible else 5) / 1000
                self._handle_events()
                self._update(elapsed)
                self._render()
        finally:
            self._save_settings()
            self.growth.save()
            self.control_panel.close()
            self.database.close()
            self.hotkeys.close()
            pygame.quit()
