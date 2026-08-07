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


