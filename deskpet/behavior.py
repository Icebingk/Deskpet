"""标签驱动的三层自然行为调度器。"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass

from .resources import resource_path


class ShuffleBag:
    """全部项目用完前不重复，避免连续抽到同一个动作。"""

    def __init__(self, items: list[str], randomizer: random.Random) -> None:
        if not items:
            raise ValueError("动作池不能为空")
        self.items = list(items)
        self.randomizer = randomizer
        self.remaining: list[str] = []
        self.last: str | None = None

    def next(self) -> str:
        if not self.remaining:
            self.remaining = list(self.items)
            self.randomizer.shuffle(self.remaining)
            if self.last and len(self.remaining) > 1 and self.remaining[-1] == self.last:
                self.remaining[0], self.remaining[-1] = self.remaining[-1], self.remaining[0]
        selected = self.remaining.pop()
        self.last = selected
        return selected


@dataclass(frozen=True)
class BehaviorChange:
    action: str
    mode: str


class BehaviorController:
    """控制基础待机、低频姿态、场景和互动之间的流转。"""

    def __init__(self, seed: int | None = None) -> None:
        self.manifest = json.loads(
            resource_path("action_manifest.json").read_text(encoding="utf-8")
        )
        self.actions: dict[str, dict[str, object]] = self.manifest["actions"]
        self.pools: dict[str, object] = self.manifest["pools"]
        self.timing: dict[str, object] = self.manifest["timing_seconds"]
        self.dialogues: dict[str, list[str]] = self.manifest.get("dialogues", {})
        self.randomizer = random.Random(seed)
        self.time_scale = max(0.001, float(os.environ.get("DESKPET_TIME_SCALE", "1")))

        self.base_actions = [str(item["action"]) for item in self.pools["base_idle"]]
        self.base_weights = [float(item["weight"]) for item in self.pools["base_idle"]]
        self.subtle_bag = ShuffleBag(list(self.pools["subtle_idle"]), self.randomizer)
        self.scene_bag = ShuffleBag(list(self.pools["scene_idle"]), self.randomizer)
        self.interaction_bag = ShuffleBag(list(self.pools["interaction"]), self.randomizer)
        self.roam_bag = ShuffleBag(list(self.pools["roam"]), self.randomizer)
        self.level = 10

        self.current_action = str(self.manifest["default_action"])
        self.mode = "base"
        self.scene_ends_at = 0.0
        self.subtle_cycles = max(1, int(self.timing.get("subtle_cycles", 1)))
        self.subtle_cycles_remaining = 0
        now = time.monotonic()
        self.last_special_at = now - self._seconds(float(self.timing["special_cooldown"]))
        self.quiet_until = 0.0
        self.base_variant_due = self._deadline(now, "base_variant")
        self.subtle_due = self._deadline(now, "subtle_idle")
        self.scene_due = self._deadline(now, "scene_idle")
        self.roam_due = self._deadline(now, "roam_idle")

    def set_level(self, level: int) -> None:
        """按等级缩小动作池；升级只解锁表现，不增强数值。"""
        self.level = max(1, min(10, int(level)))
        all_interactions = list(self.pools["interaction"])
        if self.level == 1:
            interactions = all_interactions[:4]
        elif self.level == 2:
            interactions = all_interactions[:6]
        elif self.level == 3:
            interactions = all_interactions[:8]
        else:
            interactions = all_interactions
        all_scenes = list(self.pools["scene_idle"])
        scenes = (
            all_scenes
            if self.level >= 3
            else [action for action in all_scenes if action not in ("105", "149")]
        )
        self.interaction_bag = ShuffleBag(interactions, self.randomizer)
        self.scene_bag = ShuffleBag(scenes, self.randomizer)

    def _seconds(self, value: float) -> float:
        return value * self.time_scale

    def _deadline(self, now: float, timing_name: str) -> float:
        low, high = self.timing[timing_name]
        return now + self._seconds(self.randomizer.uniform(float(low), float(high)))

    def _choose_base(self) -> str:
        return self.randomizer.choices(
            self.base_actions, weights=self.base_weights, k=1
        )[0]

    def _change(self, action: str, mode: str) -> BehaviorChange:
        self.current_action = action
        self.mode = mode
        return BehaviorChange(action, mode)

    def trigger_interaction(self, now: float | None = None) -> BehaviorChange:
        now = now if now is not None else time.monotonic()
        self.quiet_until = now + self._seconds(float(self.timing["post_interaction_quiet"]))
        self.subtle_due = self._deadline(self.quiet_until, "subtle_idle")
        self.scene_due = self._deadline(self.quiet_until, "scene_idle")
        self.roam_due = self._deadline(self.quiet_until, "roam_idle")
        return self._change(self.interaction_bag.next(), "interaction")

    def begin_drag(self) -> BehaviorChange:
        return self._change("109", "drag")

    def end_drag(
        self, action: str = "113", now: float | None = None
    ) -> BehaviorChange:
        now = now if now is not None else time.monotonic()
        self.quiet_until = now + self._seconds(float(self.timing["post_interaction_quiet"]))
        self.roam_due = self._deadline(self.quiet_until, "roam_idle")
        return self._change(action, "landing")

    def play_external(
        self, action: str, mode: str, now: float | None = None
    ) -> BehaviorChange:
        """播放照顾、需求、睡眠等由外部系统触发的动作。"""
        now = now if now is not None else time.monotonic()
        self.quiet_until = now + self._seconds(float(self.timing["post_interaction_quiet"]))
        self.subtle_due = self._deadline(self.quiet_until, "subtle_idle")
        self.scene_due = self._deadline(self.quiet_until, "scene_idle")
        self.roam_due = self._deadline(self.quiet_until, "roam_idle")
        return self._change(action, mode)

    def return_to_base(self, now: float | None = None) -> BehaviorChange:
        now = now if now is not None else time.monotonic()
        self.base_variant_due = self._deadline(now, "base_variant")
        return self._change(self._choose_base(), "base")

    def finish_roam(self, now: float | None = None) -> BehaviorChange:
        now = now if now is not None else time.monotonic()
        self.roam_due = self._deadline(now, "roam_idle")
        self.base_variant_due = self._deadline(now, "base_variant")
        return self._change(self._choose_base(), "base")

    def defer_roam(self, now: float | None = None) -> None:
        """Try again later when the pet is standing on the desktop floor."""
        now = now if now is not None else time.monotonic()
        self.roam_due = now + self._seconds(self.randomizer.uniform(60, 120))

    def dialogue_for(self, action: str) -> str:
        choices = self.dialogues.get(action)
        if not choices:
            return "我在这里～"
        return self.randomizer.choice(choices)

    def update(
        self,
        *,
        now: float,
        loop_completed: bool,
        finished: bool,
        user_active: bool,
    ) -> BehaviorChange | None:
        if self.mode == "subtle" and finished:
            if self.subtle_cycles_remaining > 0:
                self.subtle_cycles_remaining -= 1
                return self._change(self.current_action, "subtle")
            self.base_variant_due = self._deadline(now, "base_variant")
            return self._change(self._choose_base(), "base")

        if self.mode in ("interaction", "landing", "need", "neglected") and finished:
            self.base_variant_due = self._deadline(now, "base_variant")
            return self._change(self._choose_base(), "base")

        if self.mode == "scene":
            if loop_completed and now >= self.scene_ends_at:
                self.base_variant_due = self._deadline(now, "base_variant")
                self.scene_due = self._deadline(now, "scene_idle")
                return self._change(self._choose_base(), "base")
            return None

        if self.mode in (
            "drag",
            "falling",
            "sequence",
            "sleep",
            "timer",
            "roam",
            "edge_hide",
        ):
            return None

        if self.mode != "base" or not loop_completed:
            return None

        special_ready = (
            now >= self.quiet_until
            and now - self.last_special_at
            >= self._seconds(float(self.timing["special_cooldown"]))
        )
        if special_ready and not user_active and now >= self.roam_due:
            self.last_special_at = now
            self.roam_due = self._deadline(now, "roam_idle")
            return self._change(self.roam_bag.next(), "roam")
        if special_ready and not user_active and now >= self.scene_due:
            self.last_special_at = now
            low, high = self.timing["scene_duration"]
            self.scene_ends_at = now + self._seconds(
                self.randomizer.uniform(float(low), float(high))
            )
            return self._change(self.scene_bag.next(), "scene")
        if special_ready and not user_active and now >= self.subtle_due:
            self.last_special_at = now
            self.subtle_due = self._deadline(now, "subtle_idle")
            self.subtle_cycles_remaining = self.subtle_cycles - 1
            return self._change(self.subtle_bag.next(), "subtle")
        if now >= self.base_variant_due:
            self.base_variant_due = self._deadline(now, "base_variant")
            return self._change(self._choose_base(), "base")
        return None
