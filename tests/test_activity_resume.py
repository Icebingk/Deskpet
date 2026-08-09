from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from deskpet.app import DeskPetApp


class ActivityResumeTests(unittest.TestCase):
    def make_app(self) -> DeskPetApp:
        app = DeskPetApp.__new__(DeskPetApp)
        app.active_activity = None
        app.growth = SimpleNamespace(sleeping=False)
        app.behavior = SimpleNamespace(
            play_external=Mock(side_effect=lambda action, mode, now: (action, mode, now))
        )
        app._apply_behavior = Mock()
        app._active_timer_action = Mock(return_value=None)
        return app

    def test_timed_activity_resumes_before_other_persistent_states(self) -> None:
        app = self.make_app()
        now = time.monotonic()
        app.active_activity = {"animation": "149", "ends_at": now + 60}
        self.assertTrue(app._resume_interrupted_state(now))
        app.behavior.play_external.assert_called_once_with("149", "activity", now)

    def test_activity_settlement_uses_actual_elapsed_seconds(self) -> None:
        app = self.make_app()
        started_at = time.monotonic() - 180.0
        app.active_activity = {
            "action": "game_controller",
            "duration_minutes": 30,
            "started_at": started_at,
            "ends_at": started_at + 1800.0,
        }
        result = SimpleNamespace(level_up=None, message="已结算")
        app.growth.complete_timed_activity = Mock(return_value=result)

        settled = app._settle_active_activity(started_at + 180.0)

        self.assertIs(settled, result)
        self.assertIsNone(app.active_activity)
        app.growth.complete_timed_activity.assert_called_once_with(
            "game_controller", 30, 180.0
        )

    def test_sleep_resumes_after_drag(self) -> None:
        app = self.make_app()
        app.growth.sleeping = True
        now = time.monotonic()
        self.assertTrue(app._resume_interrupted_state(now))
        app.behavior.play_external.assert_called_once_with("160", "sleep", now)

    def test_pomodoro_animation_resumes_after_drag(self) -> None:
        app = self.make_app()
        app._active_timer_action.return_value = "148"
        now = time.monotonic()
        self.assertTrue(app._resume_interrupted_state(now))
        app.behavior.play_external.assert_called_once_with("148", "timer", now)


if __name__ == "__main__":
    unittest.main()