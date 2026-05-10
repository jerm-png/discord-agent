# ============================================================
# SESSION STATE MANAGER
# agents/session.py
#
# Provides per-(user_id, context_id) working state that persists
# within and across coding sessions. Injected into the system
# prompt so the bot never loses track of active tasks, build
# list progress, or decisions made this session.
# ============================================================

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "database.db")

# Max chars injected into system prompt — keeps it cheap
SESSION_INJECT_CHAR_LIMIT = 1200

# How many recent actions to keep in the scratchpad
MAX_RECENT_ACTIONS = 8


def init_session_table() -> None:
    """
    Additive migration — adds session_state table to the existing
    database.db. Safe to call multiple times (IF NOT EXISTS).
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_state (
                session_key TEXT PRIMARY KEY,
                active_task TEXT,
                build_list TEXT,
                decisions TEXT,
                recent_actions TEXT,
                updated TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_updated
            ON session_state(updated)
        """)
        conn.commit()
    finally:
        conn.close()


def load_session_state(
    user_id: str,
    context_id: int,
    channel_name: str = None
) -> dict:
    """
    Loads session state for a (user_id, context_id) pair.
    Falls back to most recent state for this user if no
    exact match exists — handles cross-thread continuity.
    Returns a default empty state if nothing exists.
    """
    key = f"{user_id}:{context_id}"
    conn = sqlite3.connect(DB_PATH)
    try:
        # Try exact match first
        cursor = conn.execute(
            "SELECT active_task, build_list, decisions, "
            "recent_actions "
            "FROM session_state WHERE session_key = ?",
            (key,)
        )
        row = cursor.fetchone()

        # Fall back to most recent state for this user
        if not row:
            cursor = conn.execute(
                "SELECT active_task, build_list, decisions, "
                "recent_actions "
                "FROM session_state "
                "WHERE session_key LIKE ? "
                "ORDER BY updated DESC LIMIT 1",
                (f"{user_id}:%",)
            )
            row = cursor.fetchone()

        if not row:
            return {
                "active_task": None,
                "build_list": [],
                "decisions": [],
                "recent_actions": [],
            }
        return {
            "active_task": row[0],
            "build_list": json.loads(row[1]) if row[1] else [],
            "decisions": json.loads(row[2]) if row[2] else [],
            "recent_actions": json.loads(row[3]) if row[3] else [],
        }
    finally:
        conn.close()


def update_session_state(
    user_id: str,
    context_id: int,
    active_task: str = None,
    build_list: list = None,
    decisions: list = None,
    recent_actions: list = None,
) -> None:
    """
    Upserts session state. Only updates fields that are passed in —
    existing values are preserved for fields left as None.
    """
    key = f"{user_id}:{context_id}"
    existing = load_session_state(user_id, context_id)

    merged = {
        "active_task": active_task if active_task is not None
                       else existing["active_task"],
        "build_list": build_list if build_list is not None
                      else existing["build_list"],
        "decisions": decisions if decisions is not None
                     else existing["decisions"],
        "recent_actions": (recent_actions if recent_actions is not None
                           else existing["recent_actions"])[-MAX_RECENT_ACTIONS:],
    }

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT INTO session_state
                (session_key, active_task, build_list,
                 decisions, recent_actions, updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                active_task    = excluded.active_task,
                build_list     = excluded.build_list,
                decisions      = excluded.decisions,
                recent_actions = excluded.recent_actions,
                updated        = excluded.updated
        """, (
            key,
            merged["active_task"],
            json.dumps(merged["build_list"]),
            json.dumps(merged["decisions"]),
            json.dumps(merged["recent_actions"]),
            datetime.utcnow().isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()


def append_recent_action(
    user_id: str,
    context_id: int,
    action: str,
) -> None:
    """
    Convenience function — appends a single action summary to
    recent_actions without touching other fields.
    """
    existing = load_session_state(user_id, context_id)
    actions = existing["recent_actions"] + [action]
    update_session_state(
        user_id, context_id,
        recent_actions=actions
    )


def clear_session_state(user_id: str, context_id: int) -> None:
    """
    Clears session state for a context — called when a session
    ends or a new goal is started from scratch.
    """
    key = f"{user_id}:{context_id}"
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "DELETE FROM session_state WHERE session_key = ?",
            (key,)
        )
        conn.commit()
    finally:
        conn.close()


def format_session_context(
    user_id: str,
    context_id: int,
    channel_name: str = None
) -> str:
    """
    Returns a compact string for injection into the system prompt.
    Returns empty string if no meaningful state exists.
    Capped at SESSION_INJECT_CHAR_LIMIT characters.
    """
    state = load_session_state(user_id, context_id)

    # Nothing worth injecting
    if (not state["active_task"]
            and not state["build_list"]
            and not state["decisions"]
            and not state["recent_actions"]):
        return ""

    lines = ["[SESSION STATE — your working context for this conversation]"]

    if state["active_task"]:
        lines.append(f"Active task: {state['active_task']}")

    if state["build_list"]:
        lines.append("Build list:")
        for item in state["build_list"]:
            status = item.get("status", "pending")
            icon = "✅" if status == "done" else "🔄" if status == "in_progress" else "⬜"
            lines.append(f"  {icon} {item.get('label', str(item))}")

    if state["decisions"]:
        lines.append("Decisions this session:")
        for d in state["decisions"][-5:]:
            lines.append(f"  • {d}")

    if state["recent_actions"]:
        lines.append("Recent actions:")
        for a in state["recent_actions"][-4:]:
            lines.append(f"  → {a}")

    result = "\n".join(lines)
    if len(result) > SESSION_INJECT_CHAR_LIMIT:
        result = result[:SESSION_INJECT_CHAR_LIMIT] + "\n[Session context truncated]"

    return result
