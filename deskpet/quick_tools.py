"""M3 快捷工具箱；只以参数列表启动已确认的本地程序或安全网页。"""

from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse


BUILTIN_TOOLS = {
    "calculator": ("计算器", "calc.exe"),
    "notepad": ("记事本", "notepad.exe"),
    "screenshot": ("截图工具", "snippingtool.exe"),
    "explorer": ("资源管理器", "explorer.exe"),
}


def launch_builtin(tool_id: str) -> tuple[bool, str]:
    definition = BUILTIN_TOOLS.get(tool_id)
    if not definition:
        return False, "未知快捷工具"
    label, executable = definition
    try:
        subprocess.Popen([executable], close_fds=True)
    except OSError:
        return False, f"无法打开{label}"
    return True, f"已打开{label}"


def validate_custom_target(target: str) -> tuple[bool, str]:
    parsed = urlparse(target.strip())
    if parsed.scheme:
        if parsed.scheme.lower() not in ("http", "https"):
            return False, "网页只允许 http 或 https"
        return True, target.strip()
    path = Path(os.path.expandvars(target.strip()))
    if not path.is_absolute():
        return False, "程序路径必须是绝对路径"
    if not path.is_file():
        return False, "程序文件不存在"
    return True, str(path)


def launch_custom(target: str) -> tuple[bool, str]:
    valid, normalized = validate_custom_target(target)
    if not valid:
        return False, normalized
    parsed = urlparse(normalized)
    try:
        if parsed.scheme in ("http", "https"):
            webbrowser.open(normalized)
        else:
            subprocess.Popen([normalized], close_fds=True)
    except OSError:
        return False, "快捷工具启动失败"
    return True, "快捷工具已打开"
