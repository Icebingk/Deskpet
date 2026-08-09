"""M3 悬停状态卡和角色右侧照顾按钮列。"""

from __future__ import annotations

import time

import pygame

from .constants import WINDOW_HEIGHT, WINDOW_WIDTH
from .growth import ACTIVITY_DURATION_OPTIONS, CARE_OPTIONS, PetGrowth


class PetHud:
    """鼠标靠近角色时显示紧凑状态与常用照顾操作。"""

    MAIN_BUTTONS = (
        ("food_menu", "吃饭 ›", (255, 230, 184)),
        ("exercise_menu", "运动 ›", (207, 238, 255)),
        ("work_menu", "工作 ›", (255, 222, 169)),
        ("game_menu", "游戏 ›", (226, 218, 255)),
        ("tool_menu", "工具 ›", (224, 230, 235)),
        ("bathe", "洗澡", (200, 239, 232)),
        ("sleep", "睡觉", (221, 228, 245)),
        ("treat", "治疗", (226, 239, 204)),
    )

    SUBMENU_COLORS = {
        "food": (255, 230, 184),
        "exercise": (207, 238, 255),
        "work": (255, 222, 169),
        "game": (226, 218, 255),
        "tool": (224, 230, 235),
        "duration": (235, 228, 218),
    }

    TOOL_OPTIONS = (
        ("tool:control_panel", "控制面板"),
        ("tool:calculator", "计算器"),
        ("tool:notepad", "记事本"),
        ("tool:screenshot", "截图工具"),
        ("tool:explorer", "资源管理器"),
    )

    BAR_ITEMS = (
        ("fullness", "饱", (244, 174, 91)),
        ("mood", "心", (240, 137, 166)),
        ("energy", "体", (94, 183, 229)),
        ("cleanliness", "净", (93, 196, 181)),
        ("health", "健", (119, 190, 112)),
    )

    def __init__(self) -> None:
        font_path = r"C:\Windows\Fonts\msyh.ttc"
        try:
            self.font = pygame.font.Font(font_path, 12)
            self.small_font = pygame.font.Font(font_path, 10)
            self.title_font = pygame.font.Font(font_path, 13)
        except FileNotFoundError:
            self.font = pygame.font.Font(None, 15)
            self.small_font = pygame.font.Font(None, 13)
            self.title_font = pygame.font.Font(None, 16)
        self.visible = False
        self.visible_until = 0.0
        self.card_rect = pygame.Rect(0, 0, 0, 0)
        self.button_rects: dict[str, pygame.Rect] = {}
        self.hovered_action: str | None = None
        self.last_mouse = (-1000, -1000)
        self.open_menu: str | None = None
        self.pending_action: str | None = None
        self.pending_category: str | None = None

    def _active_buttons(self) -> tuple[tuple[str, str, tuple[int, int, int]], ...]:
        back = (("menu_back", "‹ 返回", (232, 228, 226)),)
        if (
            self.open_menu == "duration"
            and self.pending_category in ACTIVITY_DURATION_OPTIONS
            and self.pending_action
        ):
            color = self.SUBMENU_COLORS["duration"]
            options = tuple(
                (f"duration:{minutes}", f"{minutes} 分钟", color)
                for minutes in ACTIVITY_DURATION_OPTIONS[self.pending_category]
            )
            return back + options
        if self.open_menu == "tool":
            color = self.SUBMENU_COLORS["tool"]
            return back + tuple(
                (action, label, color) for action, label in self.TOOL_OPTIONS
            )
        if self.open_menu in CARE_OPTIONS:
            color = self.SUBMENU_COLORS[self.open_menu]
            options = tuple(
                (action, label, color) for action, label in CARE_OPTIONS[self.open_menu]
            )
            return back + options
        return self.MAIN_BUTTONS

    def _layout(
        self,
        character_rect: pygame.Rect,
        visible_horizontal: tuple[int, int] | None = None,
    ) -> None:
        if visible_horizontal is None:
            visible_left, visible_right = 0, WINDOW_WIDTH
        else:
            visible_left = max(0, min(WINDOW_WIDTH, int(visible_horizontal[0])))
            visible_right = max(0, min(WINDOW_WIDTH, int(visible_horizontal[1])))
        if visible_right <= visible_left:
            visible_left, visible_right = 0, WINDOW_WIDTH

        button_width, button_height, gap = 68, 22, 3
        buttons = self._active_buttons()
        total_height = len(buttons) * button_height + (len(buttons) - 1) * gap
        right_candidate = character_rect.right + 8
        left_candidate = character_rect.left - button_width - 8
        if right_candidate + button_width <= visible_right - 7:
            button_left = right_candidate
        elif left_candidate >= visible_left + 7:
            button_left = left_candidate
        else:
            button_left = max(
                visible_left + 7,
                min(visible_right - button_width - 7, right_candidate),
            )
        button_top = max(10, min(WINDOW_HEIGHT - total_height - 8, character_rect.bottom - total_height))
        self.button_rects = {
            action: pygame.Rect(
                button_left,
                button_top + index * (button_height + gap),
                button_width,
                button_height,
            )
            for index, (action, _label, _color) in enumerate(buttons)
        }

        # Determine the button position first, then reserve that column for it.
        # The status card never covers a visible action button.
        card_width, card_height = 174, 68
        card_min_left = visible_left + 8
        card_max_left = max(card_min_left, visible_right - card_width - 8)
        preferred_left = max(
            card_min_left,
            min(card_max_left, character_rect.centerx - card_width // 2),
        )
        preferred_top = max(8, character_rect.top - card_height - 9)
        button_column = pygame.Rect(button_left, button_top, button_width, total_height)

        candidate_lefts = (
            preferred_left,
            button_column.left - card_width - 8,
            button_column.right + 8,
        )
        card_rect: pygame.Rect | None = None
        for candidate_left in candidate_lefts:
            if not card_min_left <= candidate_left <= card_max_left:
                continue
            candidate = pygame.Rect(candidate_left, preferred_top, card_width, card_height)
            if not candidate.colliderect(button_column):
                card_rect = candidate
                break

        if card_rect is None:
            # On narrow displays, lift the card above the complete button column.
            card_top = max(8, min(preferred_top, button_column.top - card_height - 8))
            card_rect = pygame.Rect(preferred_left, card_top, card_width, card_height)
        self.card_rect = card_rect
    def update(
        self,
        mouse_position: tuple[int, int],
        character_rect: pygame.Rect,
        *,
        visible_horizontal: tuple[int, int] | None = None,
        now: float | None = None,
        force_hide: bool = False,
    ) -> bool:
        now = now if now is not None else time.monotonic()
        previous = self.visible
        previous_hover = self.hovered_action
        self._layout(character_rect, visible_horizontal)
        self.last_mouse = mouse_position
        inside = character_rect.inflate(18, 18).collidepoint(mouse_position)
        inside = inside or self.card_rect.collidepoint(mouse_position)
        inside = inside or any(rect.collidepoint(mouse_position) for rect in self.button_rects.values())
        if inside:
            self.visible_until = now + 0.65
        self.visible = not force_hide and now < self.visible_until
        if not self.visible:
            self.open_menu = None
            self.pending_action = None
            self.pending_category = None
        self.hovered_action = None
        if self.visible:
            for action, rect in self.button_rects.items():
                if rect.collidepoint(mouse_position):
                    self.hovered_action = action
                    break
        return previous != self.visible or previous_hover != self.hovered_action

    def action_at(self, position: tuple[int, int]) -> str | None:
        if not self.visible:
            return None
        menu_actions = {
            "food_menu": "food",
            "exercise_menu": "exercise",
            "work_menu": "work",
            "game_menu": "game",
            "tool_menu": "tool",
        }
        for action, rect in self.button_rects.items():
            if not rect.collidepoint(position):
                continue
            if action in menu_actions:
                self.open_menu = menu_actions[action]
                self.pending_action = None
                self.pending_category = None
                self.visible_until = time.monotonic() + 2.5
                return "__menu__"
            if action == "menu_back":
                if self.open_menu == "duration" and self.pending_category:
                    self.open_menu = self.pending_category
                else:
                    self.open_menu = None
                self.pending_action = None
                self.pending_category = None
                self.visible_until = time.monotonic() + 1.0
                return "__menu__"
            if self.open_menu == "duration" and action.startswith("duration:"):
                minutes = int(action.partition(":")[2])
                selected = self.pending_action
                self.open_menu = None
                self.pending_action = None
                self.pending_category = None
                return f"activity:{selected}:{minutes}" if selected else None
            if self.open_menu in ACTIVITY_DURATION_OPTIONS:
                self.pending_action = action
                self.pending_category = self.open_menu
                self.open_menu = "duration"
                self.visible_until = time.monotonic() + 2.5
                return "__menu__"
            self.open_menu = None
            self.pending_action = None
            self.pending_category = None
            return action
        return None

    @staticmethod
    def _text(
        screen: pygame.Surface,
        font: pygame.font.Font,
        text: str,
        color: tuple[int, int, int],
        *,
        left: int,
        centery: int,
    ) -> None:
        surface = font.render(text, True, color)
        screen.blit(surface, surface.get_rect(left=left, centery=centery))

    def _draw_card(
        self,
        screen: pygame.Surface,
        growth: PetGrowth,
        activity_text: str | None = None,
    ) -> None:
        shadow = self.card_rect.move(2, 3)
        pygame.draw.rect(screen, (211, 198, 202), shadow, border_radius=12)
        pygame.draw.rect(screen, (255, 251, 247), self.card_rect, border_radius=12)
        pygame.draw.rect(screen, (113, 91, 99), self.card_rect, 1, border_radius=12)

        state_text = activity_text or ("睡眠中" if growth.sleeping else "陪伴中")
        title = f"Lv.{growth.level}  {state_text}"
        self._text(
            screen,
            self.title_font,
            title,
            (67, 53, 60),
            left=self.card_rect.left + 9,
            centery=self.card_rect.top + 13,
        )
        if activity_text is None:
            affection = self.small_font.render(
                f"♡ {growth.value('affection'):.0f}", True, (211, 91, 126)
            )
            screen.blit(
                affection,
                affection.get_rect(
                    right=self.card_rect.right - 9,
                    centery=self.card_rect.top + 13,
                ),
            )

        for index, (name, label, color) in enumerate(self.BAR_ITEMS):
            column = index % 3
            row = index // 3
            item_width = 51
            left = self.card_rect.left + 8 + column * 55
            top = self.card_rect.top + 26 + row * 20
            value = growth.value(name)
            self._text(
                screen,
                self.small_font,
                f"{label}{value:.0f}",
                (77, 65, 70),
                left=left,
                centery=top + 4,
            )
            bar = pygame.Rect(left, top + 10, item_width - 5, 4)
            pygame.draw.rect(screen, (231, 225, 222), bar, border_radius=2)
            fill = bar.copy()
            fill.width = max(1, round(bar.width * value / 100))
            pygame.draw.rect(screen, color, fill, border_radius=2)

        xp_surface = self.small_font.render(
            f"EXP {int(growth.state['xp'])}", True, (119, 104, 110)
        )
        screen.blit(
            xp_surface,
            xp_surface.get_rect(right=self.card_rect.right - 9, bottom=self.card_rect.bottom - 5),
        )

    def _draw_buttons(self, screen: pygame.Surface, growth: PetGrowth) -> None:
        for action, label, color in self._active_buttons():
            rect = self.button_rects[action]
            if action == "sleep" and growth.sleeping:
                label = "叫醒"
            hovered = action == self.hovered_action
            fill = tuple(min(255, channel + 13) for channel in color) if hovered else color
            shadow = rect.move(1, 2)
            pygame.draw.rect(screen, (206, 194, 198), shadow, border_radius=8)
            pygame.draw.rect(screen, fill, rect, border_radius=8)
            pygame.draw.rect(
                screen,
                (105, 88, 94) if hovered else (150, 132, 138),
                rect,
                1,
                border_radius=8,
            )
            text_surface = self.font.render(label, True, (63, 52, 57))
            screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    def draw(
        self,
        screen: pygame.Surface,
        growth: PetGrowth,
        *,
        show_card: bool = True,
        activity_text: str | None = None,
    ) -> None:
        if not self.visible:
            return
        if show_card:
            self._draw_card(screen, growth, activity_text)
        self._draw_buttons(screen, growth)
