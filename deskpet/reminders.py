"""M3 倒计时、闹钟、番茄钟、健康提醒和便签到期调度。"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

from .persistence import DeskPetDatabase


@dataclass(frozen=True)
class ReminderEvent:
    category: str
    message: str
    reward_xp: int = 0
    alarm: bool = False


class ReminderManager:
    HEALTH_DEFINITIONS = {
        "sedentary": ("久坐", "坐久啦，起来活动一下吧～", 60),
        "water": ("喝水", "该喝口水啦～", 70),
        "eyes": ("护眼", "看看远处，让眼睛休息一下吧～", 45),
    }

    def __init__(self, database: DeskPetDatabase, settings: dict[str, object]) -> None:
        self.database = database
        now = time.time()
        self.health_due: dict[str, float] = {}
        for key, (_title, _message, default_minutes) in self.HEALTH_DEFINITIONS.items():
            minutes = self._interval(settings, key, default_minutes)
            self.health_due[key] = now + minutes * 60
        self.next_poll = 0.0

    @staticmethod
    def _interval(settings: dict[str, object], key: str, default: int) -> int:
        value = settings.get(f"reminder_{key}_minutes", default)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(5, min(240, int(value)))
        return default

    @staticmethod
    def _enabled(settings: dict[str, object], key: str) -> bool:
        value = settings.get(f"reminder_{key}", True)
        return bool(value)

    def start_countdown(self, title: str, minutes: int) -> int:
        minutes = max(1, min(24 * 60, int(minutes)))
        seconds = minutes * 60
        return self.database.add_timer(
            "countdown", title or "倒计时", time.time() + seconds, seconds
        )

    @staticmethod
    def _next_alarm(hour: int, minute: int, weekdays: tuple[int, ...]) -> float:
        now = dt.datetime.now()
        for day_offset in range(0, 8):
            candidate_date = now.date() + dt.timedelta(days=day_offset)
            candidate = dt.datetime.combine(candidate_date, dt.time(hour, minute))
            if candidate <= now:
                continue
            if weekdays and candidate.weekday() not in weekdays:
                continue
            return candidate.timestamp()
        return (now + dt.timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ).timestamp()

    def schedule_alarm(
        self, title: str, hour: int, minute: int, weekdays: tuple[int, ...] = ()
    ) -> int:
        hour = max(0, min(23, int(hour)))
        minute = max(0, min(59, int(minute)))
        weekdays = tuple(sorted({day for day in weekdays if 0 <= day <= 6}))
        ends_at = self._next_alarm(hour, minute, weekdays)
        return self.database.add_timer(
            "alarm",
            title or "闹钟",
            ends_at,
            max(1, round(ends_at - time.time())),
            {"hour": hour, "minute": minute, "weekdays": list(weekdays)},
        )

    def start_pomodoro(
        self, work_minutes: int = 25, short_minutes: int = 5, long_minutes: int = 15
    ) -> int:
        self.database.cancel_kind("pomodoro_")
        work_minutes = max(1, min(180, int(work_minutes)))
        short_minutes = max(1, min(60, int(short_minutes)))
        long_minutes = max(1, min(120, int(long_minutes)))
        seconds = work_minutes * 60
        return self.database.add_timer(
            "pomodoro_work",
            "番茄钟 · 第 1 轮专注",
            time.time() + seconds,
            seconds,
            {
                "round": 1,
                "work": work_minutes,
                "short": short_minutes,
                "long": long_minutes,
            },
        )

    def stop_pomodoro(self) -> int:
        return self.database.cancel_kind("pomodoro_")

    def _continue_pomodoro(self, timer: dict[str, object]) -> None:
        metadata = dict(timer.get("metadata") or {})
        round_number = max(1, int(metadata.get("round", 1)))
        work = max(1, int(metadata.get("work", 25)))
        short = max(1, int(metadata.get("short", 5)))
        long = max(1, int(metadata.get("long", 15)))
        if timer["kind"] == "pomodoro_work":
            break_minutes = long if round_number >= 4 else short
            seconds = break_minutes * 60
            break_name = "长休息" if round_number >= 4 else "休息"
            self.database.add_timer(
                "pomodoro_break",
                f"番茄钟 · {break_name}",
                time.time() + seconds,
                seconds,
                {"round": round_number, "work": work, "short": short, "long": long},
            )
        elif round_number < 4:
            next_round = round_number + 1
            seconds = work * 60
            self.database.add_timer(
                "pomodoro_work",
                f"番茄钟 · 第 {next_round} 轮专注",
                time.time() + seconds,
                seconds,
                {"round": next_round, "work": work, "short": short, "long": long},
            )

    def _repeat_alarm(self, timer: dict[str, object]) -> None:
        metadata = dict(timer.get("metadata") or {})
        weekdays = tuple(int(day) for day in metadata.get("weekdays", []))
        if not weekdays:
            return
        self.schedule_alarm(
            str(timer["title"]),
            int(metadata.get("hour", 0)),
            int(metadata.get("minute", 0)),
            weekdays,
        )

    def _timer_events(self, now: float) -> list[ReminderEvent]:
        events: list[ReminderEvent] = []
        for timer in self.database.due_timers(now):
            kind = str(timer["kind"])
            if kind == "countdown":
                events.append(
                    ReminderEvent("countdown", f"{timer['title']}：时间到啦！", alarm=True)
                )
            elif kind == "alarm":
                events.append(ReminderEvent("alarm", f"闹钟：{timer['title']}", alarm=True))
                self._repeat_alarm(timer)
            elif kind == "pomodoro_work":
                round_number = int(dict(timer.get("metadata") or {}).get("round", 1))
                events.append(
                    ReminderEvent(
                        "pomodoro",
                        f"第 {round_number} 轮专注完成，休息一下吧！",
                        reward_xp=5,
                        alarm=True,
                    )
                )
                self._continue_pomodoro(timer)
            elif kind == "pomodoro_break":
                round_number = int(dict(timer.get("metadata") or {}).get("round", 1))
                if round_number >= 4:
                    message = "四轮番茄钟完成，今天很专注！"
                else:
                    message = "休息结束，准备开始下一轮吧！"
                events.append(ReminderEvent("pomodoro", message, alarm=True))
                self._continue_pomodoro(timer)
        return events

    def _health_events(
        self, now: float, settings: dict[str, object]
    ) -> list[ReminderEvent]:
        if not bool(settings.get("health_reminders", True)):
            return []
        due_messages: list[str] = []
        for key, (_title, message, default_minutes) in self.HEALTH_DEFINITIONS.items():
            if not self._enabled(settings, key):
                continue
            if now >= self.health_due[key]:
                due_messages.append(message.rstrip("～！。"))
                self.health_due[key] = now + self._interval(settings, key, default_minutes) * 60
        if not due_messages:
            return []
        return [ReminderEvent("health", "；".join(due_messages) + "～")]

    def _note_events(self, now: float) -> list[ReminderEvent]:
        events: list[ReminderEvent] = []
        for note in self.database.due_notes(now):
            summary = str(note["content"]).replace("\n", " ").strip()[:28]
            text = f"待办到期：{note['title']}"
            if summary:
                text += f"（{summary}）"
            events.append(ReminderEvent("note", text, alarm=True))
        return events

    def tick(
        self, settings: dict[str, object], now: float | None = None
    ) -> list[ReminderEvent]:
        now = now if now is not None else time.time()
        if now < self.next_poll:
            return []
        self.next_poll = now + 1.0
        events = self._timer_events(now)
        events.extend(self._note_events(now))
        events.extend(self._health_events(now, settings))
        return events

    def active_summary(self) -> str:
        timers = self.database.active_timers()
        if not timers:
            return "当前没有运行中的计时"
        timer = timers[0]
        remaining = max(0, int(float(timer["ends_at"]) - time.time()))
        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        clock = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        return f"{timer['title']} · {clock}"
