from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from deskpet.behavior import BehaviorController
from deskpet.growth import (
    ACTIVITY_DURATION_OPTIONS,
    CARE_OPTIONS,
    DEFAULT_STATE,
    PetGrowth,
)
from deskpet.settings import DEFAULT_SETTINGS, SettingsStore


class GrowthDecayTests(unittest.TestCase):
    def make_growth(self, root: str) -> PetGrowth:
        state_path = str(Path(root) / "state.json")
        with patch.dict(os.environ, {"DESKPET_STATE_PATH": state_path}):
            growth = PetGrowth(seed=1)
        growth.state = dict(DEFAULT_STATE)
        return growth

    def test_awake_decay_is_doubled_with_slow_passive_energy_loss(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            growth = self.make_growth(root)
            growth._apply_elapsed(3600)
            self.assertAlmostEqual(growth.value("fullness"), 77.6)
            self.assertAlmostEqual(growth.value("cleanliness"), 84.1)
            self.assertAlmostEqual(growth.value("mood"), 74.5)
            self.assertAlmostEqual(growth.value("energy"), 79.8)

    def test_sleep_restores_energy(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            growth = self.make_growth(root)
            growth.state["sleeping"] = True
            growth.state["energy"] = 40.0
            growth._apply_elapsed(3600)
            self.assertAlmostEqual(growth.value("energy"), 64.0)

    def test_food_restores_energy_and_exercise_uses_default_duration(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            growth = self.make_growth(root)
            now = time.time()
            growth.state["last_update"] = now
            feed = growth.perform("feed_meal", now=now)
            self.assertTrue(feed.accepted)
            self.assertAlmostEqual(growth.value("energy"), 100.0)

            growth.state["cooldowns"] = {}
            exercise = growth.perform("exercise_warmup", now=now)
            self.assertTrue(exercise.accepted)
            self.assertEqual(exercise.duration_minutes, 15)
            self.assertAlmostEqual(growth.value("energy"), 94.0)

    def test_selected_work_and_game_duration_scales_results(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            growth = self.make_growth(root)
            now = time.time()
            growth.state["last_update"] = now

            work = growth.perform("work_notes", now=now, duration_minutes=60)
            self.assertTrue(work.accepted)
            self.assertEqual(work.duration_minutes, 60)
            self.assertEqual(work.activity_label, "写笔记")
            self.assertAlmostEqual(growth.value("energy"), 74.0)
            self.assertEqual(int(growth.state["xp"]), 8)

            growth.state["cooldowns"] = {}
            game = growth.perform("game_pet", now=now, duration_minutes=30)
            self.assertTrue(game.accepted)
            self.assertEqual(game.duration_minutes, 30)
            self.assertEqual(game.activity_label, "摸摸互动")
            self.assertAlmostEqual(growth.value("energy"), 72.0)
            self.assertAlmostEqual(growth.value("mood"), 89.0)

    def test_activity_categories_expose_expected_duration_choices(self) -> None:
        self.assertIn(("game_pet", "摸摸互动"), CARE_OPTIONS["game"])
        self.assertEqual(ACTIVITY_DURATION_OPTIONS["work"], (15, 30, 60))
        self.assertEqual(ACTIVITY_DURATION_OPTIONS["exercise"], (5, 15, 30))
        self.assertEqual(ACTIVITY_DURATION_OPTIONS["game"], (5, 15, 30))

    def test_user_can_override_growth_rates(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            growth = self.make_growth(root)
            growth.configure(
                natural_decay_multiplier=1.0,
                passive_energy_decay_per_hour=1.0,
                exercise_energy_multiplier=1.5,
            )
            growth._apply_elapsed(3600)
            self.assertAlmostEqual(growth.value("fullness"), 78.8)
            self.assertAlmostEqual(growth.value("cleanliness"), 84.55)
            self.assertAlmostEqual(growth.value("mood"), 74.75)
            self.assertAlmostEqual(growth.value("energy"), 79.0)

    def test_online_update_supports_a_full_hour_interval(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            growth = self.make_growth(root)
            growth.state["last_update"] = 1000.0
            growth.update(now=4600.0)
            self.assertAlmostEqual(growth.value("fullness"), 77.6)
            self.assertAlmostEqual(growth.value("energy"), 79.8)



class GrowthSettingsTests(unittest.TestCase):
    def test_growth_defaults_and_saved_overrides(self) -> None:
        self.assertEqual(DEFAULT_SETTINGS["growth_tick_minutes"], 10)
        with tempfile.TemporaryDirectory() as root:
            settings_path = str(Path(root) / "settings.json")
            with patch.dict(os.environ, {"DESKPET_SETTINGS_PATH": settings_path}):
                store = SettingsStore()
                settings = dict(DEFAULT_SETTINGS)
                settings.update(
                    growth_tick_minutes=20,
                    natural_decay_multiplier=1.25,
                    passive_energy_decay_per_hour=0.4,
                    exercise_energy_multiplier=1.5,
                )
                self.assertTrue(store.save(settings))
                loaded = store.load()
            self.assertEqual(loaded["growth_tick_minutes"], 20)
            self.assertEqual(loaded["natural_decay_multiplier"], 1.25)


            self.assertEqual(loaded["passive_energy_decay_per_hour"], 0.4)
            self.assertEqual(loaded["exercise_energy_multiplier"], 1.5)
class RandomActionTimingTests(unittest.TestCase):
    def test_scene_duration_is_between_50_and_150_seconds(self) -> None:
        with patch.dict(os.environ, {"DESKPET_TIME_SCALE": "1"}):
            behavior = BehaviorController(seed=1)
        now = time.monotonic()
        behavior.mode = "base"
        behavior.quiet_until = 0.0
        behavior.last_special_at = now - 1000.0
        behavior.roam_due = now + 1000.0
        behavior.scene_due = now - 1.0
        behavior.subtle_due = now + 1000.0

        change = behavior.update(
            now=now,
            loop_completed=True,
            finished=False,
            user_active=False,
        )

        self.assertIsNotNone(change)
        self.assertEqual(change.mode, "scene")
        self.assertGreaterEqual(behavior.scene_ends_at - now, 50.0)
        self.assertLessEqual(behavior.scene_ends_at - now, 150.0)

    def test_subtle_action_plays_two_complete_cycles(self) -> None:
        with patch.dict(os.environ, {"DESKPET_TIME_SCALE": "1"}):
            behavior = BehaviorController(seed=1)
        now = time.monotonic()
        behavior.mode = "base"
        behavior.quiet_until = 0.0
        behavior.last_special_at = now - 1000.0
        behavior.roam_due = now + 1000.0
        behavior.scene_due = now + 1000.0
        behavior.subtle_due = now - 1.0

        first = behavior.update(
            now=now,
            loop_completed=True,
            finished=False,
            user_active=False,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first.mode, "subtle")

        replay = behavior.update(
            now=now + 1.0,
            loop_completed=False,
            finished=True,
            user_active=False,
        )
        self.assertIsNotNone(replay)
        self.assertEqual(replay.mode, "subtle")
        self.assertEqual(replay.action, first.action)

        returned = behavior.update(
            now=now + 2.0,
            loop_completed=False,
            finished=True,
            user_active=False,
        )
        self.assertIsNotNone(returned)
        self.assertEqual(returned.mode, "base")


if __name__ == "__main__":
    unittest.main()
