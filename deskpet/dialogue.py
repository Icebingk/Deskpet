"""不遮挡角色的中文打字机气泡。"""

from __future__ import annotations

import time

import pygame

from .constants import WINDOW_WIDTH


class SpeechBubble:
    def __init__(self) -> None:
        try:
            self.font = pygame.font.Font(r"C:\Windows\Fonts\msyh.ttc", 16)
        except FileNotFoundError:
            self.font = pygame.font.Font(None, 18)
        self.text = ""
        self.started_at = 0.0
        self.until = 0.0
        self.typing_speed = 18.0
        self.last_visible_count = -1

    def show(self, text: str, seconds: float = 3.2) -> None:
        cleaned = " ".join(text.split())
        self.text = cleaned[:80] + ("……" if len(cleaned) > 80 else "")
        self.started_at = time.monotonic()
        self.until = self.started_at + seconds
        self.last_visible_count = -1

    def visible(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return bool(self.text and now < self.until)

    def needs_redraw(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        if not self.visible(now):
            return self.last_visible_count != -2
        visible_count = min(len(self.text), int((now - self.started_at) * self.typing_speed))
        if visible_count != self.last_visible_count:
            self.last_visible_count = visible_count
            return True
        return False

    def _wrap(self, text: str, max_width: int, max_lines: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for character in text:
            candidate = current + character
            if current and self.font.size(candidate)[0] > max_width:
                lines.append(current)
                current = character
                if len(lines) >= max_lines:
                    break
            else:
                current = candidate
        if current and len(lines) < max_lines:
            lines.append(current)
        consumed = sum(len(line) for line in lines)
        if consumed < len(text) and lines:
            lines[-1] = lines[-1][:-1] + "…" if lines[-1] else "…"
        return lines or [""]

    def draw(self, screen: pygame.Surface, character_rect: pygame.Rect) -> None:
        now = time.monotonic()
        if not self.visible(now):
            self.last_visible_count = -2
            return
        visible_count = min(len(self.text), int((now - self.started_at) * self.typing_speed))
        visible_text = self.text[: max(1, visible_count)]
        max_lines = 2 if character_rect.top < 105 else 4
        lines = self._wrap(visible_text, WINDOW_WIDTH - 62, max_lines)
        rendered = [self.font.render(line, True, (48, 38, 43)) for line in lines]
        line_height = self.font.get_linesize()
        width = min(WINDOW_WIDTH - 28, max(surface.get_width() for surface in rendered) + 32)
        height = line_height * len(rendered) + 20
        left = (WINDOW_WIDTH - width) // 2
        top = max(10, character_rect.top - height - 14)
        bubble_rect = pygame.Rect(left, top, width, height)

        pygame.draw.rect(screen, (255, 250, 248), bubble_rect, border_radius=15)
        pygame.draw.rect(screen, (77, 61, 68), bubble_rect, 2, border_radius=15)
        tail_x = max(left + 22, min(character_rect.centerx, bubble_rect.right - 22))
        tail = (
            (tail_x - 8, bubble_rect.bottom - 1),
            (tail_x + 8, bubble_rect.bottom - 1),
            (tail_x, bubble_rect.bottom + 9),
        )
        pygame.draw.polygon(screen, (255, 250, 248), tail)
        pygame.draw.lines(screen, (77, 61, 68), False, tail, 2)
        for index, surface in enumerate(rendered):
            target = surface.get_rect(
                centerx=bubble_rect.centerx,
                top=bubble_rect.top + 10 + index * line_height,
            )
            screen.blit(surface, target)
