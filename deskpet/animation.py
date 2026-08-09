"""GIF 解码、逐帧播放和有上限的懒加载缓存。"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pygame
from PIL import Image

from .resources import resource_path


class GifClip:
    """把一个透明 GIF 解码为可由 Pygame 播放的帧序列。"""

    MAX_DECODED_SIZE = 240

    def __init__(self, path: Path, looping: bool, loop_start: int = 0) -> None:
        self.path = path
        self.looping = looping
        self.loop_start = max(0, int(loop_start))
        self.frames: list[pygame.Surface] = []
        self.durations: list[float] = []
        self.frame_index = 0
        self.frame_elapsed = 0.0
        self.finished = False
        self.loop_completed = False
        self.frame_changed = True
        self.scaled_cache: dict[tuple[int, int], pygame.Surface] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"缺少动画素材：{self.path}")

        rgba_frames: list[Image.Image] = []
        boxes: list[tuple[int, int, int, int]] = []
        with Image.open(self.path) as source:
            for index in range(source.n_frames):
                source.seek(index)
                frame = source.convert("RGBA").copy()
                rgba_frames.append(frame)
                alpha_box = frame.getchannel("A").getbbox()
                if alpha_box:
                    boxes.append(alpha_box)
                duration_ms = int(source.info.get("duration", 100))
                self.durations.append(max(0.045, min(0.25, duration_ms / 1000)))

        if not boxes:
            raise ValueError(f"动画没有可见内容：{self.path}")
        self.loop_start = min(self.loop_start, len(rgba_frames) - 1)
        left = max(0, min(box[0] for box in boxes) - 4)
        top = max(0, min(box[1] for box in boxes) - 4)
        right = min(rgba_frames[0].width, max(box[2] for box in boxes) + 4)
        bottom = min(rgba_frames[0].height, max(box[3] for box in boxes) + 4)
        crop_box = (left, top, right, bottom)
        crop_width = right - left
        crop_height = bottom - top
        resize_ratio = self.MAX_DECODED_SIZE / max(crop_width, crop_height)
        decoded_size = (
            max(1, round(crop_width * resize_ratio)),
            max(1, round(crop_height * resize_ratio)),
        )

        for frame in rgba_frames:
            prepared = frame.crop(crop_box).resize(decoded_size, Image.Resampling.LANCZOS)
            alpha = prepared.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
            prepared.putalpha(alpha)
            surface = pygame.image.frombytes(
                prepared.tobytes(), prepared.size, "RGBA"
            ).convert_alpha()
            self.frames.append(surface)

    def reset(self) -> None:
        self.frame_index = 0
        self.frame_elapsed = 0.0
        self.finished = False
        self.loop_completed = False
        self.frame_changed = True

    def update(self, elapsed: float, *, force_loop: bool = False) -> bool:
        """推进动画；定时活动可临时强制循环，不改变素材原始循环设置。"""
        self.loop_completed = False
        self.frame_changed = False
        if self.finished:
            return True
        self.frame_elapsed += elapsed
        while self.frame_elapsed >= self.durations[self.frame_index]:
            self.frame_elapsed -= self.durations[self.frame_index]
            self.frame_changed = True
            if self.frame_index == len(self.frames) - 1:
                if self.looping or force_loop:
                    self.frame_index = self.loop_start
                    self.loop_completed = True
                else:
                    self.finished = True
                    return True
            else:
                self.frame_index += 1
        return False

    def surface(self, target_size: int) -> pygame.Surface:
        key = (self.frame_index, target_size)
        cached = self.scaled_cache.get(key)
        if cached is not None:
            return cached
        frame = self.frames[self.frame_index]
        ratio = target_size / max(frame.get_width(), frame.get_height())
        size = (
            max(1, round(frame.get_width() * ratio)),
            max(1, round(frame.get_height() * ratio)),
        )
        scaled = pygame.transform.scale(frame, size)
        self.scaled_cache[key] = scaled
        return scaled

    def clear_scale_cache(self) -> None:
        self.scaled_cache.clear()


class GifLibrary:
    """按需解码 GIF，并限制同时驻留的动画数量。"""

    def __init__(self, action_definitions: dict[str, dict[str, object]], max_loaded: int = 8) -> None:
        self.action_definitions = action_definitions
        self.max_loaded = max(2, max_loaded)
        self.loaded: OrderedDict[str, GifClip] = OrderedDict()

    def get(self, action: str) -> GifClip:
        cached = self.loaded.pop(action, None)
        if cached is not None:
            self.loaded[action] = cached
            return cached
        definition = self.action_definitions.get(action)
        if not definition:
            raise KeyError(f"动作 Manifest 中不存在：{action}")
        clip = GifClip(
            resource_path(str(definition["file"])),
            bool(definition.get("loop", False)),
            int(definition.get("loop_start", 0)),
        )
        self.loaded[action] = clip
        while len(self.loaded) > self.max_loaded:
            self.loaded.popitem(last=False)
        return clip

    def clear_scale_caches(self) -> None:
        for clip in self.loaded.values():
            clip.clear_scale_cache()

    @property
    def loaded_count(self) -> int:
        return len(self.loaded)
