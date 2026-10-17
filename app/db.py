from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    album_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'jm',
                    source_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    zip_path TEXT,
                    zip_size INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "source" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'jm'")
            if "source_url" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "UPDATE tasks SET status='failed', message='任务因服务中断而停止，请检查原因后手动重试' "
                "WHERE status='running'"
            )

    def create_task(self, album_id: str, source: str = "jm", source_url: str = "") -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        task_id = uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM tasks WHERE source=? AND album_id=? AND source_url=? "
                "AND status IN ('queued', 'running') LIMIT 1",
                (source, album_id, source_url),
            ).fetchone()
            if existing:
                return dict(existing)
            conn.execute(
                "INSERT INTO tasks(id, album_id, source, source_url, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                (task_id, album_id, source, source_url, now, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_next(self) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                "UPDATE tasks SET status='running', message='正在下载', updated_at=? "
                "WHERE id=?",
                (now, row["id"]),
            )
            conn.commit()
        return self.get_task(row["id"])

    def update_task(self, task_id: str, **fields: Any) -> None:
        allowed = {"status", "message", "zip_path", "zip_size"}
        values = {key: value for key, value in fields.items() if key in allowed}
        values["updated_at"] = datetime.now(UTC).isoformat()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id=?",
                (*values.values(), task_id),
            )

    def retry_task(self, task_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status='queued', message='已重新排队', updated_at=? "
                "WHERE id=? AND status='failed'",
                (datetime.now(UTC).isoformat(), task_id),
            )
        return cursor.rowcount == 1

    def delete_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.get_task(task_id)
        if not task or task["status"] == "running":
            return None
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        return task

