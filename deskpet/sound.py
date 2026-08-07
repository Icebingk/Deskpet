"""M3 独立提醒声音；使用 Windows 系统音，不附带额外音频资源。"""

from __future__ import annotations

import winsound


def play_alarm(enabled: bool = True) -> None:
    if not enabled:
        return
    try:
        winsound.PlaySound(
            "SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC
        )
    except RuntimeError:
        pass


def play_interaction(enabled: bool = True) -> None:
    if not enabled:
        return
    try:
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except RuntimeError:
        pass
