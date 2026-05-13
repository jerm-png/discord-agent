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
                user_id TEXT NOT NULL DEFAULT 'drift-owner',
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_message_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                message_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Migration: older databases were created before user-scoping.
        # Idempotent — second run raises OperationalError ("duplicate
        # column name"), which we swallow.
        try:
            conn.execute(
                "ALTER TABLE threads ADD COLUMN user_id TEXT "
                "NOT NULL DEFAULT 'drift-owner'"
            )
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_workspace_user "
            "ON threads(workspace, user_id, status)"
        )


def create_thread(workspace: str, title: str, user_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    thread_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO threads
                (id, workspace, user_id, title, created_at,
                 updated_at, status, message_count)
            VALUES (?, ?, ?, ?, ?, ?, 'active', 0)
            """,
            (thread_id, workspace, user_id, title, now, now),
        )
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return _row_to_dict(row)


def get_thread(thread_id: str, user_id: str | None = None) -> dict | None:
    """
    Fetch a thread by id. When user_id is provided, returns None unless the
    thread belongs to that user — used by endpoints to enforce ownership
    without a separate query.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    if not row:
        return None
    result = _row_to_dict(row)
    if user_id is not None and result.get("user_id") != user_id:
        return None
    return result


def list_threads(
    workspace: str, user_id: str, status: str = "active"
) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM threads
            WHERE workspace = ? AND user_id = ? AND status = ?
            ORDER BY last_message_at DESC, updated_at DESC
            """,
            (workspace, user_id, status),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def rename_thread(thread_id: str, title: str, user_id: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE threads SET title = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (title, now, thread_id, user_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def archive_thread(thread_id: str, user_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE threads SET status = 'archived', updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (now, thread_id, user_id),
        )
    return cur.rowcount > 0


def update_thread_activity(thread_id: str) -> None:
    """
    Bump last_message_at / message_count. Callers (chat WS handler)
    already verified ownership via get_thread(thread_id, user_id) before
    invoking, so no per-user gate is needed here.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """
            UPDATE threads
            SET last_message_at = ?, updated_at = ?,
                message_count = message_count + 1
            WHERE id = ?
            """,
            (now, now, thread_id),
        )


init_threads_table()
