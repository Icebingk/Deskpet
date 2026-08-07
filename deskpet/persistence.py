"""M3 SQLite 数据层：计时、闹钟、番茄钟、便签和最近删除。"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


class DeskPetDatabase:
    def __init__(self) -> None:
        override = os.environ.get("DESKPET_DB_PATH")
        if override:
            self.path = Path(override)
        else:
            local_data = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            self.path = local_data / "LineDogDeskPet" / "deskpet.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=3.0)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                ends_at REAL NOT NULL,
                duration_seconds INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                notified_at REAL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_timers_due
                ON timers(status, ends_at);

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                due_at REAL,
                priority INTEGER NOT NULL DEFAULT 1,
                completed INTEGER NOT NULL DEFAULT 0,
                notified_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                deleted_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_notes_due
                ON notes(completed, deleted_at, due_at);
            """
        )
        note_columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(notes)")
        }
        if "notified_at" not in note_columns:
            self.connection.execute("ALTER TABLE notes ADD COLUMN notified_at REAL")
        self.connection.commit()

    @staticmethod
    def _timer_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        try:
            result["metadata"] = json.loads(result.get("metadata") or "{}")
        except (TypeError, ValueError):
            result["metadata"] = {}
        return result

    def add_timer(
        self,
        kind: str,
        title: str,
        ends_at: float,
        duration_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO timers(kind, title, ends_at, duration_seconds, status, created_at, metadata)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                kind,
                title.strip()[:80] or "未命名计时",
                float(ends_at),
                max(1, int(duration_seconds)),
                time.time(),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def due_timers(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.time()
        rows = self.connection.execute(
            "SELECT * FROM timers WHERE status='active' AND ends_at<=? ORDER BY ends_at",
            (now,),
        ).fetchall()
        if rows:
            ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in ids)
            self.connection.execute(
                f"UPDATE timers SET status='completed', notified_at=? WHERE id IN ({placeholders})",
                (now, *ids),
            )
            self.connection.commit()
        return [self._timer_dict(row) for row in rows]

    def active_timers(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM timers WHERE status='active' ORDER BY ends_at LIMIT 20"
        ).fetchall()
        return [self._timer_dict(row) for row in rows]

    def cancel_timer(self, timer_id: int) -> bool:
        cursor = self.connection.execute(
            "UPDATE timers SET status='cancelled' WHERE id=? AND status='active'",
            (int(timer_id),),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def cancel_kind(self, kind_prefix: str) -> int:
        cursor = self.connection.execute(
            "UPDATE timers SET status='cancelled' WHERE status='active' AND kind LIKE ?",
            (f"{kind_prefix}%",),
        )
        self.connection.commit()
        return cursor.rowcount

    def add_note(
        self,
        title: str,
        content: str = "",
        due_at: float | None = None,
        priority: int = 1,
    ) -> int:
        now = time.time()
        cursor = self.connection.execute(
            """
            INSERT INTO notes(title, content, due_at, priority, completed, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                title.strip()[:120] or "未命名便签",
                content.strip()[:10000],
                float(due_at) if due_at else None,
                max(0, min(2, int(priority))),
                now,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_notes(
        self, search: str = "", *, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        deleted_clause = "deleted_at IS NOT NULL" if include_deleted else "deleted_at IS NULL"
        query = f"SELECT * FROM notes WHERE {deleted_clause}"
        values: list[object] = []
        if search.strip():
            query += " AND (title LIKE ? OR content LIKE ?)"
            pattern = f"%{search.strip()}%"
            values.extend((pattern, pattern))
        query += " ORDER BY completed, priority DESC, COALESCE(due_at, 9e18), updated_at DESC LIMIT 200"
        rows = self.connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def toggle_note(self, note_id: int) -> bool:
        cursor = self.connection.execute(
            """
            UPDATE notes SET completed=CASE completed WHEN 0 THEN 1 ELSE 0 END, updated_at=?
            WHERE id=? AND deleted_at IS NULL
            """,
            (time.time(), int(note_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def postpone_note(self, note_id: int, days: int = 1) -> bool:
        target = time.time() + max(1, int(days)) * 86400
        cursor = self.connection.execute(
            "UPDATE notes SET due_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (target, time.time(), int(note_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def delete_note(self, note_id: int) -> bool:
        cursor = self.connection.execute(
            "UPDATE notes SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (time.time(), time.time(), int(note_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def restore_note(self, note_id: int) -> bool:
        cursor = self.connection.execute(
            "UPDATE notes SET deleted_at=NULL, updated_at=? WHERE id=? AND deleted_at IS NOT NULL",
            (time.time(), int(note_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def due_notes(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.time()
        rows = self.connection.execute(
            """
            SELECT * FROM notes
            WHERE deleted_at IS NULL AND completed=0 AND due_at IS NOT NULL
              AND due_at<=? AND (notified_at IS NULL OR notified_at<due_at)
            ORDER BY priority DESC, due_at
            """,
            (now,),
        ).fetchall()
        if rows:
            self.connection.executemany(
                "UPDATE notes SET notified_at=? WHERE id=?",
                [(now, int(row["id"])) for row in rows],
            )
            self.connection.commit()
        return [dict(row) for row in rows]

    def purge_deleted(self, now: float | None = None) -> int:
        cutoff = (now if now is not None else time.time()) - 7 * 86400
        cursor = self.connection.execute(
            "DELETE FROM notes WHERE deleted_at IS NOT NULL AND deleted_at<?",
            (cutoff,),
        )
        self.connection.commit()
        return cursor.rowcount

    def export_notes(self, destination: Path) -> int:
        notes = self.list_notes()
        lines: list[str] = []
        for note in notes:
            marker = "[x]" if note["completed"] else "[ ]"
            lines.append(f"{marker} {note['title']}\n{note['content']}\n")
        destination.write_text("\n".join(lines), encoding="utf-8")
        return len(notes)

    def close(self) -> None:
        self.connection.close()
