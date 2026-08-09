from __future__ import annotations

import unittest

import pygame

from deskpet.hud import PetHud


class HudEdgeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.font.init()

    def setUp(self) -> None:
        self.hud = PetHud()
        self.character = pygame.Rect(92, 280, 112, 112)

    def test_right_edge_moves_buttons_to_character_left(self) -> None:
        self.hud._layout(self.character, visible_horizontal=(0, 204))
        buttons = tuple(self.hud.button_rects.values())
        self.assertTrue(all(rect.right <= self.character.left for rect in buttons))
        self.assertTrue(all(rect.right <= 197 for rect in buttons))
        self.assertLessEqual(self.hud.card_rect.right, 196)

    def test_left_edge_keeps_buttons_on_character_right(self) -> None:
        self.hud._layout(self.character, visible_horizontal=(92, 340))
        buttons = tuple(self.hud.button_rects.values())
        self.assertTrue(all(rect.left >= self.character.right for rect in buttons))
        self.assertTrue(all(rect.left >= 99 and rect.right <= 333 for rect in buttons))
        self.assertGreaterEqual(self.hud.card_rect.left, 100)

    def test_activity_selection_opens_duration_menu(self) -> None:
        self.hud.visible = True
        self.hud.open_menu = "exercise"
        self.hud._layout(self.character)
        selected = self.hud.action_at(
            self.hud.button_rects["exercise_warmup"].center
        )
        self.assertEqual(selected, "__menu__")
        self.assertEqual(self.hud.open_menu, "duration")

        self.hud._layout(self.character)
        result = self.hud.action_at(self.hud.button_rects["duration:30"].center)
        self.assertEqual(result, "activity:exercise_warmup:30")
        self.assertIsNone(self.hud.open_menu)

    def test_pet_is_inside_game_menu(self) -> None:
        self.hud.open_menu = None
        self.hud._layout(self.character)
        self.assertNotIn("pet", self.hud.button_rects)

        self.hud.open_menu = "game"
        self.hud._layout(self.character)
        self.assertIn("game_pet", self.hud.button_rects)

    def test_tool_menu_returns_builtin_tool_action(self) -> None:
        self.hud.visible = True
        self.hud.open_menu = "tool"
        self.hud._layout(self.character)
        result = self.hud.action_at(self.hud.button_rects["tool:calculator"].center)
        self.assertEqual(result, "tool:calculator")


