"""M2 养成数值、离线结算、照顾操作和原子存档。"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path


STAT_NAMES = {
    "fullness": "饱腹",
    "mood": "心情",
    "energy": "体力",
    "cleanliness": "清洁",
    "health": "健康",
    "affection": "好感",
}

LEVEL_THRESHOLDS = (0, 100, 260, 520, 900, 1400, 2100, 3000, 4200, 5600)

DEFAULT_STATE: dict[str, object] = {
    "schema_version": 2,
    "fullness": 80.0,
    "mood": 75.0,
    "energy": 80.0,
    "cleanliness": 85.0,
    "health": 100.0,
    "affection": 0.0,
    "xp": 0,
    "level": 1,
    "sleeping": False,
    "last_update": 0.0,
    "cooldowns": {},
    "pet_timestamps": [],
}

CARE_ACTION_ALIASES = {
    "feed": "feed_meal",
    "snack": "feed_icecream",
    "play": "game_controller",
    "pet": "game_pet",
}

CARE_ACTION_GROUPS = {
    "feed_meal": "food",
    "feed_icecream": "food",
    "exercise_warmup": "exercise",
    "exercise_cheer": "exercise",
    "exercise_run": "exercise",
    "work_notes": "work",
    "work_computer": "work",
    "work_office": "work",
    "game_pet": "game",
    "game_controller": "game",
    "game_comedy": "game",
}

CARE_OPTIONS = {
    "food": (
        ("feed_meal", "营养餐"),
        ("feed_icecream", "冰淇淋"),
    ),
    "exercise": (
        ("exercise_warmup", "热身弹跳"),
        ("exercise_cheer", "啦啦操"),
        ("exercise_run", "跑步"),
    ),
    "work": (
        ("work_notes", "写笔记"),
        ("work_computer", "电脑办公"),
        ("work_office", "上班中"),
    ),
    "game": (
        ("game_pet", "摸摸互动"),
        ("game_controller", "手柄游戏"),
        ("game_comedy", "一起说相声"),
    ),
}

ACTIVITY_DURATION_OPTIONS = {
    "exercise": (5, 15, 30),
    "work": (15, 30, 60),
    "game": (5, 15, 30),
}

ACTIVITY_BASE_MINUTES = {
    "exercise": 15,
    "work": 30,
    "game": 15,
}

ACTIVITY_LABELS = {
    action: label
    for category in ("exercise", "work", "game")
    for action, label in CARE_OPTIONS[category]
}

TIMED_CARE_ACTIONS = frozenset(ACTIVITY_LABELS)

ACTION_COOLDOWNS = {
    "food": 15 * 60,
    "exercise": 10 * 60,
    "work": 5 * 60,
    "game": 5 * 60,
    "bathe": 30 * 60,
    "treat": 60 * 60,
}

# 默认自然消耗为旧版的 2 倍；体力少量被动下降，运动消耗默认为 2 倍。
DEFAULT_NATURAL_DECAY_MULTIPLIER = 2.0
DEFAULT_PASSIVE_ENERGY_DECAY_PER_HOUR = 0.2
DEFAULT_EXERCISE_ENERGY_MULTIPLIER = 2.0


@dataclass(frozen=True)
class CareResult:
    accepted: bool
    message: str
    animations: tuple[str, ...] = ()
    level_up: int | None = None
    duration_minutes: int | None = None
    activity_label: str | None = None


class PetGrowth:
    """保存并更新桌宠的长期成长状态。"""

    def __init__(
        self,
        seed: int | None = None,
        *,
        natural_decay_multiplier: float = DEFAULT_NATURAL_DECAY_MULTIPLIER,
        passive_energy_decay_per_hour: float = DEFAULT_PASSIVE_ENERGY_DECAY_PER_HOUR,
        exercise_energy_multiplier: float = DEFAULT_EXERCISE_ENERGY_MULTIPLIER,
    ) -> None:
        override = os.environ.get("DESKPET_STATE_PATH")
        if override:
            self.path = Path(override)
        else:
            local_data = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            self.path = local_data / "LineDogDeskPet" / "pet_state.json"
        self.randomizer = random.Random(seed)
        self.configure(
            natural_decay_multiplier=natural_decay_multiplier,
            passive_energy_decay_per_hour=passive_energy_decay_per_hour,
            exercise_energy_multiplier=exercise_energy_multiplier,
        )
        self.state = dict(DEFAULT_STATE)
        self.offline_hours = 0.0
        self.dirty = False
        self._load()

    def configure(
        self,
        *,
        natural_decay_multiplier: float,
        passive_energy_decay_per_hour: float,
        exercise_energy_multiplier: float,
    ) -> None:
        """Apply and clamp user-configurable growth rates."""
        self.natural_decay_multiplier = max(
            0.0, min(5.0, float(natural_decay_multiplier))
        )
        self.passive_energy_decay_per_hour = max(
            0.0, min(2.0, float(passive_energy_decay_per_hour))
        )
        self.exercise_energy_multiplier = max(
            0.0, min(4.0, float(exercise_energy_multiplier))
        )

    @staticmethod
    def _clamp(value: float, maximum: float = 100.0) -> float:
        return max(0.0, min(maximum, value))

    @classmethod
    def _clamp_stat(cls, name: str, value: float) -> float:
        return cls._clamp(value, 1000.0 if name == "affection" else 100.0)

    @property
    def sleeping(self) -> bool:
        return bool(self.state["sleeping"])

    @property
    def level(self) -> int:
        return int(self.state["level"])

    def value(self, name: str) -> float:
        return float(self.state[name])

    def _load(self) -> None:
        now = time.time()
        loaded: dict[str, object] = {}
        try:
            candidate = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                loaded = candidate
        except (OSError, ValueError, TypeError):
            pass

        self.state = dict(DEFAULT_STATE)
        for name in STAT_NAMES:
            value = loaded.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.state[name] = self._clamp_stat(name, float(value))
        xp = loaded.get("xp")
        if isinstance(xp, int) and not isinstance(xp, bool):
            self.state["xp"] = max(0, xp)
        self.state["level"] = self._level_for_xp(int(self.state["xp"]))
        if isinstance(loaded.get("sleeping"), bool):
            self.state["sleeping"] = loaded["sleeping"]

        cooldowns = loaded.get("cooldowns")
        if isinstance(cooldowns, dict):
            self.state["cooldowns"] = {
                str(key): float(value)
                for key, value in cooldowns.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        pet_timestamps = loaded.get("pet_timestamps")
        if isinstance(pet_timestamps, list):
            self.state["pet_timestamps"] = [
                float(value)
                for value in pet_timestamps
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ][-3:]

        last_update = loaded.get("last_update")
        if isinstance(last_update, (int, float)) and 0 < float(last_update) <= now:
            elapsed = min(72 * 3600, now - float(last_update))
            self.offline_hours = elapsed / 3600
            self._apply_elapsed(elapsed)
        self.state["last_update"] = now
        self._prune(now)
        self.dirty = True

    def _apply_elapsed(self, elapsed_seconds: float) -> None:
        hours = max(0.0, elapsed_seconds) / 3600
        if hours <= 0:
            return
        self.state["fullness"] = self._clamp(
            self.value("fullness") - 1.2 * self.natural_decay_multiplier * hours
        )
        self.state["cleanliness"] = self._clamp(
            self.value("cleanliness")
            - 0.45 * self.natural_decay_multiplier * hours
        )
        if self.sleeping:
            self.state["energy"] = self._clamp(self.value("energy") + 12.0 * hours)
        else:
            self.state["energy"] = self._clamp(
                self.value("energy")
                - self.passive_energy_decay_per_hour * hours
            )
        self.state["mood"] = self._clamp(
            self.value("mood")
            - min(
                8.0 * self.natural_decay_multiplier,
                0.25 * self.natural_decay_multiplier * hours,
            )
        )

        health_delta = 0.0
        if self.value("fullness") < 15:
            health_delta -= 0.8 * self.natural_decay_multiplier * hours
        if self.value("energy") < 10:
            health_delta -= 0.6 * self.natural_decay_multiplier * hours
        if self.value("cleanliness") < 10:
            health_delta -= 0.4 * self.natural_decay_multiplier * hours
        if (
            health_delta == 0
            and self.value("fullness") >= 35
            and self.value("energy") >= 30
            and self.value("cleanliness") >= 30
        ):
            health_delta = min(2.0, 0.2 * hours)
        self.state["health"] = self._clamp(self.value("health") + health_delta)

    def update(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        previous = float(self.state.get("last_update", now))
        elapsed = max(0.0, min(60 * 60, now - previous))
        self._apply_elapsed(elapsed)
        self.state["last_update"] = now
        self._prune(now)
        if elapsed > 0:
            self.dirty = True

    def _prune(self, now: float) -> None:
        cooldowns = dict(self.state.get("cooldowns", {}))
        self.state["cooldowns"] = {
            key: value for key, value in cooldowns.items() if float(value) > now
        }
        timestamps = list(self.state.get("pet_timestamps", []))
        self.state["pet_timestamps"] = [
            float(value) for value in timestamps if now - float(value) < 5 * 60
        ][-3:]

    @staticmethod
    def _level_for_xp(xp: int) -> int:
        level = 1
        for index, threshold in enumerate(LEVEL_THRESHOLDS, start=1):
            if xp >= threshold:
                level = index
        return min(10, level)

    def _add(self, **changes: float) -> None:
        for name, amount in changes.items():
            self.state[name] = self._clamp_stat(name, self.value(name) + amount)

    def _add_xp(self, amount: int) -> int | None:
        old_level = self.level
        self.state["xp"] = max(0, int(self.state["xp"]) + amount)
        new_level = self._level_for_xp(int(self.state["xp"]))
        self.state["level"] = new_level
        return new_level if new_level > old_level else None

    def reward_xp(self, amount: int) -> int | None:
        """为番茄钟等 M3 工具增加经验并立即保存。"""
        level_up = self._add_xp(max(0, int(amount)))
        self.dirty = True
        self.save()
        return level_up

    def cooldown_remaining(self, action: str, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        normalized = CARE_ACTION_ALIASES.get(action, action)
        group = CARE_ACTION_GROUPS.get(normalized, normalized)
        legacy_keys = {
            "food": ("food", "feed", "snack", "feed_meal", "feed_icecream"),
            "exercise": (
                "exercise",
                "exercise_warmup",
                "exercise_cheer",
                "exercise_run",
            ),
            "work": (
                "work",
                "work_notes",
                "work_computer",
                "work_office",
            ),
            "game": (
                "game",
                "play",
                "pet",
                "game_pet",
                "game_controller",
                "game_comedy",
            ),
        }.get(group, (group,))
        cooldowns = dict(self.state.get("cooldowns", {}))
        until = max(float(cooldowns.get(key, 0.0)) for key in legacy_keys)
        return max(0.0, until - now)

    def _reject_cooldown(self, action: str, now: float) -> CareResult | None:
        remaining = self.cooldown_remaining(action, now)
        if remaining <= 0:
            return None
        minutes = max(1, int((remaining + 59) // 60))
        group = CARE_ACTION_GROUPS.get(action, action)
        name = {"food": "喂食", "exercise": "运动", "work": "工作", "game": "游戏"}.get(group, "这个操作")
        return CareResult(False, f"{name}还要等 {minutes} 分钟～")

    def perform(
        self,
        action: str,
        now: float | None = None,
        duration_minutes: int | None = None,
    ) -> CareResult:
        now = now if now is not None else time.time()
        action = CARE_ACTION_ALIASES.get(action, action)
        activity_group = CARE_ACTION_GROUPS.get(action)
        base_minutes = ACTIVITY_BASE_MINUTES.get(activity_group)
        duration: int | None = None
        duration_factor = 1.0
        if base_minutes is not None:
            if duration_minutes is None:
                duration = base_minutes
            else:
                try:
                    duration = max(1, min(180, int(duration_minutes)))
                except (TypeError, ValueError):
                    return CareResult(False, "活动时长无效，请重新选择。")
            duration_factor = duration / base_minutes
        scaled = lambda value: round(float(value) * duration_factor, 1)
        self.update(now)
        if self.sleeping and action != "sleep":
            return CareResult(False, "我正在睡觉，先把我叫醒吧～")

        rejected = self._reject_cooldown(action, now)
        if rejected:
            return rejected

        level_up: int | None = None
        animations: tuple[str, ...]
        if action == "feed_meal":
            if self.value("fullness") >= 92:
                return CareResult(False, "已经吃得很饱啦，晚点再喂我吧～")
            self._add(fullness=35, energy=12, health=3, mood=2)
            level_up = self._add_xp(4)
            animations = ("088", "147")
            message = "营养餐吃完啦！饱腹+35，体力+12，健康+3，心情+2"
        elif action == "feed_icecream":
            if self.value("fullness") >= 97:
                return CareResult(False, "肚子装不下冰淇淋啦～")
            self._add(fullness=10, energy=4, mood=14, health=-2, cleanliness=-3)
            level_up = self._add_xp(2)
            animations = ("162", "162", "162")
            message = "冰淇淋真开心！饱腹+10，体力+4，心情+14，健康-2，清洁-3"
        elif action == "game_pet":
            energy_cost = scaled(1)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，先休息一下再玩～")
            self._add(
                mood=scaled(5),
                affection=scaled(2),
                energy=-energy_cost,
                fullness=-scaled(1),
            )
            level_up = self._add_xp(max(1, round(2 * duration_factor)))
            animations = ("134",)
            message = (
                f"{duration} 分钟摸摸互动开始！"
                f"心情+{scaled(5):g}，好感+{scaled(2):g}，体力-{energy_cost:g}"
            )
        elif action == "exercise_warmup":
            energy_cost = scaled(3 * self.exercise_energy_multiplier)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，让我先睡一会儿～")
            self._add(
                mood=scaled(4),
                energy=-energy_cost,
                health=scaled(2),
                fullness=-scaled(2),
                cleanliness=-scaled(1),
            )
            level_up = self._add_xp(max(1, round(2 * duration_factor)))
            animations = ("108",)
            message = (
                f"{duration} 分钟热身开始！健康+{scaled(2):g}，"
                f"心情+{scaled(4):g}，体力-{energy_cost:g}"
            )
        elif action == "exercise_cheer":
            energy_cost = scaled(7 * self.exercise_energy_multiplier)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，让我先睡一会儿～")
            self._add(
                mood=scaled(10),
                energy=-energy_cost,
                health=scaled(3),
                fullness=-scaled(4),
                cleanliness=-scaled(2),
                affection=scaled(2),
            )
            level_up = self._add_xp(max(1, round(3 * duration_factor)))
            animations = ("030",)
            message = (
                f"{duration} 分钟啦啦操开始！心情+{scaled(10):g}，"
                f"健康+{scaled(3):g}，体力-{energy_cost:g}"
            )
        elif action == "exercise_run":
            energy_cost = scaled(14 * self.exercise_energy_multiplier)
            if self.value("energy") < energy_cost:
                return CareResult(False, f"跑步至少需要 {energy_cost:g} 点体力，先休息一下吧～")
            self._add(
                mood=scaled(7),
                energy=-energy_cost,
                health=scaled(5),
                fullness=-scaled(6),
                cleanliness=-scaled(5),
                affection=scaled(2),
            )
            level_up = self._add_xp(max(1, round(4 * duration_factor)))
            animations = ("179",)
            message = (
                f"{duration} 分钟跑步开始！健康+{scaled(5):g}，"
                f"心情+{scaled(7):g}，体力-{energy_cost:g}"
            )
        elif action == "work_notes":
            energy_cost = scaled(3)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，先休息一下再工作～")
            self._add(
                energy=-energy_cost,
                fullness=-scaled(2),
                mood=scaled(2),
                affection=scaled(1),
            )
            level_up = self._add_xp(max(1, round(4 * duration_factor)))
            animations = ("002",)
            message = (
                f"{duration} 分钟写笔记开始！经验+{max(1, round(4 * duration_factor))}，"
                f"体力-{energy_cost:g}"
            )
        elif action == "work_computer":
            energy_cost = scaled(5)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，先休息一下再工作～")
            self._add(
                energy=-energy_cost,
                fullness=-scaled(3),
                mood=scaled(1),
                cleanliness=-scaled(1),
            )
            level_up = self._add_xp(max(1, round(6 * duration_factor)))
            animations = ("115",)
            message = (
                f"{duration} 分钟电脑办公开始！经验+{max(1, round(6 * duration_factor))}，"
                f"体力-{energy_cost:g}"
            )
        elif action == "work_office":
            energy_cost = scaled(7)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，先休息一下再工作～")
            self._add(
                energy=-energy_cost,
                fullness=-scaled(4),
                mood=-scaled(1),
                affection=scaled(1),
            )
            level_up = self._add_xp(max(1, round(8 * duration_factor)))
            animations = ("148",)
            message = (
                f"{duration} 分钟上班开始！经验+{max(1, round(8 * duration_factor))}，"
                f"体力-{energy_cost:g}"
            )
        elif action == "game_controller":
            energy_cost = scaled(4)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，先休息一下再玩～")
            self._add(
                mood=scaled(8),
                energy=-energy_cost,
                fullness=-scaled(2),
                cleanliness=-scaled(1),
            )
            level_up = self._add_xp(max(1, round(3 * duration_factor)))
            animations = ("149",)
            message = (
                f"{duration} 分钟手柄游戏开始！心情+{scaled(8):g}，"
                f"体力-{energy_cost:g}"
            )
        elif action == "game_comedy":
            energy_cost = scaled(3)
            if self.value("energy") < energy_cost:
                return CareResult(False, "体力不够啦，先休息一下再玩～")
            self._add(
                mood=scaled(10),
                affection=scaled(3),
                energy=-energy_cost,
                fullness=-scaled(2),
            )
            level_up = self._add_xp(max(1, round(4 * duration_factor)))
            animations = ("164",)
            message = (
                f"{duration} 分钟说相声开始！心情+{scaled(10):g}，"
                f"好感+{scaled(3):g}，体力-{energy_cost:g}"
            )
        elif action == "bathe":
            if self.value("cleanliness") >= 92:
                return CareResult(False, "我现在很干净，不用重复洗澡啦～")
            self._add(cleanliness=55, mood=self.randomizer.choice((-3, 3)))
            level_up = self._add_xp(3)
            animations = ("158", "019")
            message = "洗好啦，变得香喷喷！"
        elif action == "sleep":
            if self.sleeping:
                self.state["sleeping"] = False
                animations = ("037",)
                message = "我醒啦，精神好多了！"
            else:
                self.state["sleeping"] = True
                animations = ("199", "160")
                message = "晚安，我要好好补充体力～"
        elif action == "treat":
            if self.value("health") >= 60:
                return CareResult(False, "我现在很健康，不需要吃药～")
            self._add(health=25, mood=-2)
            animations = ("150",)
            message = "吃过药会慢慢好起来的。"
        else:
            return CareResult(False, "这个照顾动作还没有准备好。")

        cooldown_key = CARE_ACTION_GROUPS.get(action, action)
        cooldown = ACTION_COOLDOWNS.get(cooldown_key)
        if cooldown:
            cooldowns = dict(self.state.get("cooldowns", {}))
            cooldowns[cooldown_key] = now + cooldown
            self.state["cooldowns"] = cooldowns
        self.state["last_update"] = now
        self.dirty = True
        if level_up:
            message += f" 升到 {level_up} 级啦！"
        self.save()
        return CareResult(
            True,
            message,
            animations,
            level_up,
            duration_minutes=duration,
            activity_label=ACTIVITY_LABELS.get(action),
        )

    def suggested_need(self) -> tuple[str, str] | None:
        if self.sleeping:
            return None
        if self.value("health") < 35:
            return "131", "我好像感冒了，一直在流鼻涕……"
        if self.value("mood") < 20:
            return "035", "今天有一点难过，可以陪陪我吗？"
        if self.value("energy") < 10:
            return "118", "困得睁不开眼啦，我想睡觉……"
        if self.value("cleanliness") < 25:
            return "158", "身上灰扑扑的，该洗澡啦～"
        if self.value("fullness") < 20:
            return "120", "肚子咕咕叫啦～"
        if self.value("energy") < 25:
            return self.randomizer.choice(("118", "199")), "有一点累，想歇一会儿。"
        return None

    def unlocked_features(self) -> tuple[str, ...]:
        """返回已经达到等级门槛的表现层解锁项。"""
        unlocked = ["基础互动", "正餐", "休息"]
        if self.level >= 2:
            unlocked.append("音乐动作")
        if self.level >= 3:
            unlocked.append("场景待机")
        if self.level >= 4:
            unlocked.append("爱心动作与黄色皮肤")
        if self.level >= 5:
            unlocked.append("伙伴依偎")
        if self.level >= 6:
            unlocked.append("双宠互动")
        if self.level >= 7:
            unlocked.append("特殊移动")
        if self.level >= 8:
            unlocked.append("幼崽事件")
        if self.level >= 9:
            unlocked.append("节日与隐藏对话")
        if self.level >= 10:
            unlocked.append("全动作自由选择")
        return tuple(unlocked)

    def status_text(self) -> str:
        sleep_text = "睡眠中" if self.sleeping else "清醒"
        return (
            f"Lv.{self.level} {sleep_text}｜经验{int(self.state['xp'])}｜"
            f"饱腹{self.value('fullness'):.0f} 心情{self.value('mood'):.0f} "
            f"体力{self.value('energy'):.0f}｜清洁{self.value('cleanliness'):.0f} "
            f"健康{self.value('health'):.0f} 好感{self.value('affection'):.0f}"
        )

    def offline_message(self) -> str | None:
        if self.offline_hours < 0.25:
            return None
        if self.offline_hours < 1:
            duration = f"{max(1, round(self.offline_hours * 60))} 分钟"
        else:
            duration = f"{self.offline_hours:.1f} 小时"
        return f"你离开了 {duration}，我的状态已经结算好啦。"

    def save(self) -> bool:
        if not self.dirty:
            return True
        serializable = dict(self.state)
        serializable["schema_version"] = 2
        serializable["last_update"] = time.time()
        for name in STAT_NAMES:
            serializable[name] = round(float(serializable[name]), 3)
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError:
            return False
        self.state["last_update"] = serializable["last_update"]
        self.dirty = False
        return True
