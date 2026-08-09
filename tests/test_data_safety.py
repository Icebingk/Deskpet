from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from deskpet.data_tools import create_backup, create_restore_point, restore_backup
from deskpet.persistence import DeskPetDatabase
from deskpet.settings import DEFAULT_SETTINGS, SettingsStore


class SettingsRecoveryTests(unittest.TestCase):
    def test_invalid_settings_are_quarantined_before_defaults_are_used(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            settings_path = Path(root) / "settings.json"
            settings_path.write_text("{invalid json", encoding="utf-8")
            with patch.dict(os.environ, {"DESKPET_SETTINGS_PATH": str(settings_path)}):
                settings = SettingsStore().load()
            self.assertEqual(settings["scale"], DEFAULT_SETTINGS["scale"])
            backups = list(Path(root).glob("settings.broken-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{invalid json")


class BackupSafetyTests(unittest.TestCase):
    def test_backup_round_trip_and_restore_point(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            files = {
                "settings.json": directory / "settings.json",
                "pet_state.json": directory / "pet_state.json",
                "deskpet.db": directory / "deskpet.db",
            }
            original = {
                "settings.json": b'{"scale": 1.0}',
                "pet_state.json": b'{"energy": 80}',
                "deskpet.db": b"sqlite-data",
            }
            for name, content in original.items():
                files[name].write_bytes(content)
            backup = directory / "backup.zip"
            create_backup(backup, files)
            restore_point = create_restore_point(directory / "backups", files)
            second_restore_point = create_restore_point(directory / "backups", files)
            self.assertTrue(restore_point.is_file())
            self.assertTrue(second_restore_point.is_file())
            self.assertNotEqual(restore_point, second_restore_point)

            for path in files.values():
                path.write_bytes(b"changed")
            restore_backup(backup, files)
            self.assertEqual({name: path.read_bytes() for name, path in files.items()}, original)

    def test_restore_rejects_unknown_zip_member_without_changing_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            files = {
                "settings.json": directory / "settings.json",
                "pet_state.json": directory / "pet_state.json",
                "deskpet.db": directory / "deskpet.db",
            }
            for path in files.values():
                path.write_bytes(b"safe")
            invalid = directory / "invalid.zip"
            with zipfile.ZipFile(invalid, "w") as archive:
                archive.writestr("../outside.txt", "blocked")
            with self.assertRaises(ValueError):
                restore_backup(invalid, files)
            self.assertTrue(all(path.read_bytes() == b"safe" for path in files.values()))


class DatabaseMigrationTests(unittest.TestCase):
    def test_legacy_notes_table_receives_missing_notified_column(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            database_path = Path(root) / "deskpet.db"
            connection = sqlite3.connect(database_path)
            connection.execute(
                """
                CREATE TABLE notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    due_at REAL,
                    priority INTEGER NOT NULL DEFAULT 1,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted_at REAL
                )
                """
            )
            connection.commit()
            connection.close()
            with patch.dict(os.environ, {"DESKPET_DB_PATH": str(database_path)}):
                database = DeskPetDatabase()
                columns = {
                    str(row[1])
                    for row in database.connection.execute("PRAGMA table_info(notes)")
                }
                database.close()
            self.assertIn("notified_at", columns)


if __name__ == "__main__":
    unittest.main()