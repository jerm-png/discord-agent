import sqlite3
import uuid
from datetime import datetime, timezone

from app.core.config import DB_PATH


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_threads_table() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_message_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                message_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_workspace "
            "ON threads(workspace, status)"
        )


def create_thread(workspace: str, title: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    thread_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO threads
                (id, workspace, title, created_at, updated_at, status, message_count)
            VALUES (?, ?, ?, ?, ?, 'active', 0)
            """,
            (thread_id, workspace, title, now, now),
        )
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return _row_to_dict(row)


def get_thread(thread_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_threads(workspace: str, status: str = "active") -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM threads
            WHERE workspace = ? AND status = ?
            ORDER BY last_message_at DESC, updated_at DESC
            """,
            (workspace, status),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def rename_thread(thread_id: str, title: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, thread_id),
        )
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def archive_thread(thread_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE threads SET status = 'archived', updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
    return cur.rowcount > 0


def update_thread_activity(thread_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """
            UPDATE threads
            SET last_message_at = ?, updated_at = ?, message_count = message_count + 1
            WHERE id = ?
            """,
            (now, now, thread_id),
        )


init_threads_table()
