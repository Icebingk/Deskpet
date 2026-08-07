"""线条小狗桌宠启动入口。"""

from __future__ import annotations

import os

from deskpet.app import DeskPetApp
from deskpet.window_win32 import SingleInstance


def main() -> None:
    instance = SingleInstance()
    if instance.already_running:
        instance.activate_existing()
        instance.close()
        return
    try:
        test_seconds = float(os.environ.get("DESKPET_TEST_SECONDS", "0")) or None
        DeskPetApp().run(test_seconds)
    finally:
        instance.close()


if __name__ == "__main__":
    main()
