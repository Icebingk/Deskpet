"""Safe local backup and restore helpers."""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path


MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024


def _validate_archive(source: Path, allowed_names: set[str]) -> set[str]:
    if not source.is_file() or not zipfile.is_zipfile(source):
        raise ValueError("备份文件不是有效的 ZIP 文件")
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("备份文件包含重复条目")
        if not set(names).issubset(allowed_names):
            raise ValueError("备份文件包含不支持的内容")
        if any(info.is_dir() for info in infos):
            raise ValueError("备份文件不能包含目录")
        if any(info.file_size > MAX_ARCHIVE_MEMBER_BYTES for info in infos):
            raise ValueError("备份文件中有文件过大")
        if sum(info.file_size for info in infos) > MAX_ARCHIVE_TOTAL_BYTES:
            raise ValueError("备份文件总大小超过限制")
        broken_name = archive.testzip()
        if broken_name:
            raise ValueError(f"备份文件损坏：{broken_name}")
        return set(names)


def create_backup(destination: Path, files: dict[str, Path]) -> None:
    """Atomically write a ZIP containing the known local data files only."""
    if destination.suffix.lower() != ".zip":
        raise ValueError("备份文件必须使用 .zip 后缀")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, path in files.items():
                if path.is_file():
                    archive.write(path, name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def create_restore_point(directory: Path, files: dict[str, Path]) -> Path:
    """Save current data before a restore, so the operation is reversible."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    destination = directory / f"restore-before-{timestamp}.zip"
    sequence = 1
    while destination.exists():
        destination = directory / f"restore-before-{timestamp}-{sequence}.zip"
        sequence += 1
    create_backup(destination, files)
    return destination


def restore_backup(source: Path, files: dict[str, Path]) -> None:
    """Validate and stage every member before replacing any local data file."""
    member_names = _validate_archive(source, set(files))
    temporary_files: dict[str, Path] = {}
    try:
        with zipfile.ZipFile(source) as archive:
            for name in member_names:
                target = files[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".restore")
                with archive.open(name) as incoming, temporary.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                temporary_files[name] = temporary
        for name, temporary in temporary_files.items():
            temporary.replace(files[name])
    finally:
        for temporary in temporary_files.values():
            temporary.unlink(missing_ok=True)
