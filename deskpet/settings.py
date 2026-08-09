"""桌宠设置的校验、迁移和原子保存。"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .constants import DEFAULT_SCALE, MAX_SCALE, MIN_SCALE


DEFAULT_SETTINGS: dict[str, object] = {
    "schema_version": 5,
    "position": None,
    "scale": DEFAULT_SCALE,
    "topmost": True,
    "health_reminders": True,
    "click_through": False,
    "animation_speed": 1.0,
    "gravity": True,
    "window_collision": True,
    "edge_snap": True,
    "bubble_speed": 18,
    "alarm_sound": True,
    "interaction_sound": False,
    "autostart": False,
    "reminder_sedentary": True,
    "reminder_water": True,
    "reminder_eyes": True,
    "reminder_sedentary_minutes": 60,
    "reminder_water_minutes": 70,
    "reminder_eyes_minutes": 45,
    "fullscreen_policy": "quiet",
    "growth_tick_minutes": 10,
    "natural_decay_multiplier": 2.0,
    "passive_energy_decay_per_hour": 0.2,
    "exercise_energy_multiplier": 2.0,
    "custom_tools": [],
    "ai_enabled": False,
    "ai_base_url": "",
    "ai_model": "",
    "weather_enabled": False,
    "weather_city": "",
}


class SettingsStore:
    """把当前设置保存在用户的 LocalAppData 中。"""

    def __init__(self) -> None:
        override = os.environ.get("DESKPET_SETTINGS_PATH")
        if override:
            self.path = Path(override)
        else:
            local_data = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            self.path = local_data / "LineDogDeskPet" / "settings.json"

    def _quarantine_broken(self) -> None:
        """Keep a copy of an invalid settings file before using defaults."""
        if not self.path.is_file():
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.stem}.broken-{stamp}{self.path.suffix}")
        try:
            shutil.copy2(self.path, target)
        except OSError:
            pass


    def load(self) -> dict[str, object]:
        settings = dict(DEFAULT_SETTINGS)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return settings
        except (OSError, ValueError, TypeError):
            self._quarantine_broken()
            return settings
        if not isinstance(data, dict):
            self._quarantine_broken()
            return settings

        position = data.get("position")
        if (
            isinstance(position, list)
            and len(position) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) for value in position)
        ):
            settings["position"] = (position[0], position[1])

        scale = data.get("scale")
        if isinstance(scale, (int, float)) and not isinstance(scale, bool):
            settings["scale"] = max(MIN_SCALE, min(MAX_SCALE, float(scale)))

        for key in (
            "topmost",
            "health_reminders",
            "click_through",
            "gravity",
            "window_collision",
            "edge_snap",
            "alarm_sound",
            "interaction_sound",
            "autostart",
            "reminder_sedentary",
            "reminder_water",
            "reminder_eyes",
            "ai_enabled",
            "weather_enabled",
        ):
            if isinstance(data.get(key), bool):
                settings[key] = data[key]

        speed = data.get("animation_speed")
        if isinstance(speed, (int, float)) and not isinstance(speed, bool):
            settings["animation_speed"] = max(0.5, min(1.5, float(speed)))
        bubble_speed = data.get("bubble_speed")
        if isinstance(bubble_speed, (int, float)) and not isinstance(bubble_speed, bool):
            settings["bubble_speed"] = max(10, min(30, int(bubble_speed)))
        for key, default in (
            ("reminder_sedentary_minutes", 60),
            ("reminder_water_minutes", 70),
            ("reminder_eyes_minutes", 45),
        ):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                settings[key] = max(5, min(240, int(value)))
            else:
                settings[key] = default
        growth_tick = data.get("growth_tick_minutes")
        if isinstance(growth_tick, (int, float)) and not isinstance(growth_tick, bool):
            settings["growth_tick_minutes"] = max(1, min(60, int(growth_tick)))
        for key, default, maximum in (
            ("natural_decay_multiplier", 2.0, 5.0),
            ("passive_energy_decay_per_hour", 0.2, 2.0),
            ("exercise_energy_multiplier", 2.0, 4.0),
        ):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                settings[key] = max(0.0, min(maximum, float(value)))
            else:
                settings[key] = default

        for key in ("ai_base_url", "ai_model", "weather_city"):
            value = data.get(key)
            if isinstance(value, str):
                settings[key] = value.strip()[:500]
        policy = data.get("fullscreen_policy")
        if policy in ("hide", "quiet", "ignore"):
            settings["fullscreen_policy"] = policy
        custom_tools = data.get("custom_tools")
        if isinstance(custom_tools, list):
            settings["custom_tools"] = [
                {"name": str(item["name"])[:40], "target": str(item["target"])[:1000]}
                for item in custom_tools[:12]
                if isinstance(item, dict) and item.get("name") and item.get("target")
            ]
        return settings

    def save(self, settings: dict[str, object]) -> bool:
        serializable = {
            "schema_version": 5,
            "position": list(settings["position"]) if settings.get("position") else None,
            "scale": round(float(settings.get("scale", DEFAULT_SCALE)), 3),
            "topmost": bool(settings.get("topmost", True)),
            "health_reminders": bool(settings.get("health_reminders", True)),
            "click_through": bool(settings.get("click_through", False)),
            "animation_speed": round(float(settings.get("animation_speed", 1.0)), 2),
            "gravity": bool(settings.get("gravity", True)),
            "window_collision": bool(settings.get("window_collision", True)),
            "edge_snap": bool(settings.get("edge_snap", True)),
            "bubble_speed": max(10, min(30, int(settings.get("bubble_speed", 18)))),
            "alarm_sound": bool(settings.get("alarm_sound", True)),
            "interaction_sound": bool(settings.get("interaction_sound", False)),
            "autostart": bool(settings.get("autostart", False)),
            "reminder_sedentary": bool(settings.get("reminder_sedentary", True)),
            "reminder_water": bool(settings.get("reminder_water", True)),
            "reminder_eyes": bool(settings.get("reminder_eyes", True)),
            "reminder_sedentary_minutes": max(5, min(240, int(settings.get("reminder_sedentary_minutes", 60)))),
            "reminder_water_minutes": max(5, min(240, int(settings.get("reminder_water_minutes", 70)))),
            "reminder_eyes_minutes": max(5, min(240, int(settings.get("reminder_eyes_minutes", 45)))),
            "fullscreen_policy": str(settings.get("fullscreen_policy", "quiet")),
            "growth_tick_minutes": max(
                1, min(60, int(settings.get("growth_tick_minutes", 10)))
            ),
            "natural_decay_multiplier": round(
                max(0.0, min(5.0, float(settings.get("natural_decay_multiplier", 2.0)))),
                2,
            ),
            "passive_energy_decay_per_hour": round(
                max(0.0, min(2.0, float(settings.get("passive_energy_decay_per_hour", 0.2)))),
                2,
            ),
            "exercise_energy_multiplier": round(
                max(0.0, min(4.0, float(settings.get("exercise_energy_multiplier", 2.0)))),
                2,
            ),
            "custom_tools": list(settings.get("custom_tools", []))[:12],
            "ai_enabled": bool(settings.get("ai_enabled", False)),
            "ai_base_url": str(settings.get("ai_base_url", "")).strip()[:500],
            "ai_model": str(settings.get("ai_model", "")).strip()[:200],
            "weather_enabled": bool(settings.get("weather_enabled", False)),
            "weather_city": str(settings.get("weather_city", "")).strip()[:80],
        }
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError:
            return False
        return True
