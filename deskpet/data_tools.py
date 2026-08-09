"""Safe local backup and restore helpers."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def create_backup(destination: Path, files: dict[str, Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            if path.exists():
                archive.write(path, name)


def restore_backup(source: Path, files: dict[str, Path]) -> None:
    with zipfile.ZipFile(source) as archive:
        allowed = set(files)
        if not set(archive.namelist()).issubset(allowed):
            raise ValueError("备份文件包含不支持的内容")
        for name, target in files.items():
            if name in archive.namelist():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".restore")
                with archive.open(name) as incoming, temporary.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                temporary.replace(target)
