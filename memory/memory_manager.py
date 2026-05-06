import sqlite3
import json
import os
import re
import numpy as np
import chromadb
from datetime import datetime, timedelta
from sentence_transformers import SentenceTransformer

# ============================================================
# CONFIGURATION
# ============================================================

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")

MEMORY_TOKEN_BUDGET = {
    "strategic": 150,
    "operational": 100,
    "analytical": 100,
    "stale_flags": 50
}

DECAY_RATES = {
    "strategic": 60,
    "operational": 7,
    "analytical": 21
}

TOP_N_MEMORIES = 3

COMPLETION_SIGNALS = [
    "done", "that works", "perfect", "let's move on",
    "good", "got it", "makes sense", "that's good",
    "move on", "next", "correct", "exactly", "yes",
    "that's right", "confirmed", "approved", "finished",
    "complete", "sorted", "great", "excellent", "thanks"
]

# Channels whose memories are fully isolated — never bleed
# into other channels and never receive memories from them.
MEMORY_ISOLATED_CHANNELS = {"health-tracking"}

# Channels that receive no global-memory fallback during retrieval.
# Memories saved in these channels only surface in those channels.
RESTRICTED_CHANNELS = {"health-tracking"}

# ============================================================
# INITIALISATION
# ============================================================

print("Loading memory model...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
print("Memory model loaded.")

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

strategic_collection = chroma_client.get_or_create_collection(
    "strategic"
)
operational_collection = chroma_client.get_or_create_collection(
    "operational"
)
analytical_collection = chroma_client.get_or_create_collection(
    "analytical"
)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS strategic_memory (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            category TEXT,
            confidence REAL DEFAULT 0.8,
            created TEXT,
            last_confirmed TEXT,
            times_referenced INTEGER DEFAULT 0,
            flag_after_days INTEGER DEFAULT 60,
            status TEXT DEFAULT 'active',
            source TEXT,
            channel_name TEXT NOT NULL DEFAULT 'global'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS operational_memory (
            id INTEGER PRIMARY KEY,
            project_name TEXT,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            priority TEXT DEFAULT 'medium',
            created TEXT,
            last_updated TEXT,
            flag_after_days INTEGER DEFAULT 7,
            blockers TEXT,
            dependencies TEXT,
            channel_name TEXT NOT NULL DEFAULT 'global',
            confidence REAL NOT NULL DEFAULT 0.7
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS analytical_memory (
            id INTEGER PRIMARY KEY,
            pattern_type TEXT,
            observation TEXT,
            reasoning TEXT,
            outcome TEXT,
            pattern TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            trigger_conditions TEXT,
            times_observed INTEGER DEFAULT 1,
            created TEXT,
            last_observed TEXT,
            flag_after_days INTEGER DEFAULT 21,
            status TEXT DEFAULT 'active',
            channel_name TEXT NOT NULL DEFAULT 'global'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY,
            request_summary TEXT,
            approach_used TEXT,
            outcome TEXT,
            lesson TEXT,
            layers_used TEXT,
            timestamp TEXT,
            quality_score REAL DEFAULT 0.5,
            task_completed INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS memory_archive (
            id INTEGER PRIMARY KEY,
            original_layer TEXT,
            original_id INTEGER,
            content TEXT,
            reason_archived TEXT,
            superseded_by TEXT,
            archived_date TEXT,
            original_created TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("""
        INSERT OR IGNORE INTO meta (key, value)
        VALUES ('interaction_count', '0')
    """)

    c.execute("""
        INSERT OR IGNORE INTO meta (key, value)
        VALUES ('pending_reflection', 'false')
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            user_id TEXT PRIMARY KEY,
            history TEXT NOT NULL,
            updated TEXT NOT NULL
        )
    """)

    for _table in ("strategic_memory", "operational_memory",
                   "analytical_memory", "experiences"):
        try:
            c.execute(
                f"ALTER TABLE {_table} ADD COLUMN project_tag TEXT"
            )
        except sqlite3.OperationalError:
            pass

    for _table in ("strategic_memory", "operational_memory",
                   "analytical_memory"):
        try:
            c.execute(
                f"ALTER TABLE {_table} ADD COLUMN"
                f" channel_name TEXT NOT NULL DEFAULT 'global'"
            )
        except sqlite3.OperationalError:
            pass

    try:
        c.execute(
            "ALTER TABLE operational_memory ADD COLUMN"
            " confidence REAL NOT NULL DEFAULT 0.7"
        )
    except sqlite3.OperationalError:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS health_panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_date TEXT NOT NULL,
            marker TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            reference_range TEXT,
            personal_baseline REAL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS health_protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocol_name TEXT NOT NULL,
            dose TEXT NOT NULL,
            frequency TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS conversation_log USING fts5(
            user_id UNINDEXED,
            context_id UNINDEXED,
            channel_name UNINDEXED,
            role UNINDEXED,
            content,
            project_tag UNINDEXED,
            timestamp UNINDEXED
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialised.")


# ============================================================
# COMPLETION SIGNAL DETECTION
# ============================================================

def is_task_completion(message):
    message_lower = message.lower().strip()
    for signal in COMPLETION_SIGNALS:
        if signal in message_lower:
            return True
    return False


# ============================================================
# CONVERSATION LOG — FTS5 SESSION SEARCH
# ============================================================

def _sanitize_fts_query(query: str) -> str:
    """Strips characters that cause FTS5 MATCH syntax errors."""
    sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
    sanitized = ' '.join(sanitized.split())
    return sanitized if sanitized else "conversation"


def log_conversation_turn(user_id: str, context_id: int, channel_name: str,
                          role: str, content: str,
                          project_tag: str = None) -> None:
    """Appends a single conversation turn to the permanent FTS5 archive."""
    if not isinstance(content, str) or not content.strip():
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO conversation_log
            (user_id, context_id, channel_name, role, content, project_tag, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        str(user_id),
        str(context_id),
        channel_name,
        role,
        content,
        project_tag,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def search_conversations(query: str, channel_name: str, user_id: str,
                         limit: int = 5) -> list:
    """
    Full-text search over the conversation_log archive.
    Returns list of dicts: timestamp, channel_name, role, content, context_id.
    Health-tracking isolation enforced at SQL level.
    """
    safe_query = _sanitize_fts_query(query)
    is_isolated = channel_name in MEMORY_ISOLATED_CHANNELS
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        if is_isolated:
            c.execute("""
                SELECT timestamp, channel_name, role, content, context_id
                FROM conversation_log
                WHERE conversation_log MATCH ?
                  AND user_id = ?
                  AND project_tag = ?
                ORDER BY rank, timestamp DESC
                LIMIT ?
            """, (safe_query, str(user_id), channel_name, limit))
        else:
            excluded = list(MEMORY_ISOLATED_CHANNELS)
            placeholders = ",".join("?" * len(excluded))
            c.execute(f"""
                SELECT timestamp, channel_name, role, content, context_id
                FROM conversation_log
                WHERE conversation_log MATCH ?
                  AND user_id = ?
                  AND (project_tag IS NULL OR project_tag NOT IN ({placeholders}))
                ORDER BY rank, timestamp DESC
                LIMIT ?
            """, [safe_query, str(user_id)] + excluded + [limit])
        rows = c.fetchall()
    except Exception:
        rows = []
    conn.close()
    return [
        {
            "timestamp": row[0],
            "channel_name": row[1],
            "role": row[2],
            "content": row[3],
            "context_id": row[4],
        }
        for row in rows
    ]


def cleanup_old_conversation_log() -> int:
    """Deletes conversation_log entries older than 90 days. Returns count deleted."""
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM conversation_log WHERE timestamp < ?", (cutoff,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def backfill_conversation_log() -> int:
    """
    One-time migration: copies existing conversation_history rows into
    conversation_log so !search and confabulation checks have historical data.

    Guarded by the meta key 'conversation_log_backfilled' — skips entirely
    if that key already exists, so this is safe to call on every startup.

    channel_name is set to 'unknown' for all backfilled rows because the
    channel name cannot be recovered from a Discord channel/thread ID alone.
    project_tag is set to None (global) for the same reason.

    Returns count of turns inserted.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Guard: run only once
    c.execute(
        "SELECT value FROM meta WHERE key = 'conversation_log_backfilled'"
    )
    if c.fetchone():
        conn.close()
        return 0

    # Snapshot existing entries to avoid duplicates
    # (user_id, role, first-100-chars-of-content) as the dedup key
    existing: set = set()
    try:
        c.execute("SELECT user_id, role, content FROM conversation_log")
        for _uid, _role, _content in c.fetchall():
            existing.add((_uid, _role, (_content or "")[:100]))
    except Exception:
        pass

    c.execute("SELECT user_id, history, updated FROM conversation_history")
    rows = c.fetchall()

    inserted = 0
    for key, history_json, updated_ts in rows:
        # Only handle "uid:context_id" format — skip pre-thread legacy keys
        if ":" not in key:
            continue
        uid_str, cid_str = key.split(":", 1)

        try:
            history = json.loads(history_json)
        except (json.JSONDecodeError, TypeError):
            continue

        ts = updated_ts or datetime.now().isoformat()

        for msg in history:
            role = msg.get("role")
            content = msg.get("content")

            # Skip tool use blocks and non-string content
            if not isinstance(content, str) or not content.strip():
                continue
            if role not in ("user", "assistant"):
                continue

            dedup_key = (uid_str, role, content[:100])
            if dedup_key in existing:
                continue

            c.execute("""
                INSERT INTO conversation_log
                    (user_id, context_id, channel_name, role,
                     content, project_tag, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid_str, cid_str, "unknown", role, content, None, ts))
            existing.add(dedup_key)
            inserted += 1

    c.execute("""
        INSERT OR REPLACE INTO meta (key, value)
        VALUES ('conversation_log_backfilled', 'true')
    """)
    conn.commit()
    conn.close()
    return inserted


def set_pending_reflection(value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE meta SET value = ?
        WHERE key = 'pending_reflection'
    """, ("true" if value else "false",))
    conn.commit()
    conn.close()


def get_pending_reflection():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT value FROM meta
        WHERE key = 'pending_reflection'
    """)
    result = c.fetchone()
    conn.close()
    return result and result[0] == "true"


# ============================================================
# SAVE FUNCTIONS
# ============================================================

def save_strategic_memory(content, category="general",
                          confidence=0.8, source="conversation",
                          project_tag=None, channel_name="global"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        INSERT INTO strategic_memory
        (content, category, confidence, created,
         last_confirmed, flag_after_days, source, project_tag,
         channel_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (content, category, confidence, now, now,
          DECAY_RATES["strategic"], source, project_tag,
          channel_name))

    memory_id = str(c.lastrowid)
    conn.commit()
    conn.close()

    embedding = embedding_model.encode(content).tolist()
    meta = {
        "category": category,
        "confidence": confidence,
        "created_at": now,
        "channel_name": channel_name,
    }
    if project_tag:
        meta["project_tag"] = project_tag
    strategic_collection.add(
        documents=[content],
        embeddings=[embedding],
        ids=[f"strategic_{memory_id}"],
        metadatas=[meta]
    )

    return memory_id


def save_operational_memory(content, project_name="general",
                            priority="medium", blockers=None,
                            dependencies=None, project_tag=None,
                            channel_name="global"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        INSERT INTO operational_memory
        (project_name, content, priority, created,
         last_updated, flag_after_days, blockers,
         dependencies, project_tag, channel_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (project_name, content, priority, now, now,
          DECAY_RATES["operational"],
          blockers or "", dependencies or "", project_tag,
          channel_name))

    memory_id = str(c.lastrowid)
    conn.commit()
    conn.close()

    embedding = embedding_model.encode(content).tolist()
    meta = {
        "project": project_name,
        "priority": priority,
        "confidence": 0.7,
        "created_at": now,
        "channel_name": channel_name,
    }
    if project_tag:
        meta["project_tag"] = project_tag
    operational_collection.add(
        documents=[content],
        embeddings=[embedding],
        ids=[f"operational_{memory_id}"],
        metadatas=[meta]
    )

    return memory_id


def save_analytical_memory(pattern, observation="",
                           reasoning="", outcome="",
                           confidence=0.5,
                           trigger_conditions="",
                           pattern_type="general",
                           project_tag=None,
                           channel_name="global"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        INSERT INTO analytical_memory
        (pattern_type, observation, reasoning, outcome,
         pattern, confidence, trigger_conditions,
         created, last_observed, flag_after_days, project_tag,
         channel_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pattern_type, observation, reasoning, outcome,
          pattern, confidence, trigger_conditions,
          now, now, DECAY_RATES["analytical"], project_tag,
          channel_name))

    memory_id = str(c.lastrowid)
    conn.commit()
    conn.close()

    full_text = f"{pattern} {trigger_conditions}".strip()
    embedding = embedding_model.encode(full_text).tolist()
    meta = {
        "pattern_type": pattern_type,
        "confidence": confidence,
        "trigger_conditions": trigger_conditions,
        "created_at": now,
        "channel_name": channel_name,
    }
    if project_tag:
        meta["project_tag"] = project_tag
    analytical_collection.add(
        documents=[full_text],
        embeddings=[embedding],
        ids=[f"analytical_{memory_id}"],
        metadatas=[meta]
    )

    return memory_id


def save_experience(request_summary, approach_used,
                    outcome, lesson, layers_used=None,
                    quality_score=0.5, task_completed=False,
                    project_tag=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        INSERT INTO experiences
        (request_summary, approach_used, outcome, lesson,
         layers_used, timestamp, quality_score,
         task_completed, project_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (request_summary, approach_used, outcome, lesson,
          json.dumps(layers_used or []),
          datetime.now().isoformat(), quality_score,
          1 if task_completed else 0, project_tag))

    conn.commit()
    conn.close()


# ============================================================
# ARCHIVE FUNCTIONS
# ============================================================

def archive_memory(layer, memory_id, reason,
                   superseded_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    table_map = {
        "strategic": "strategic_memory",
        "operational": "operational_memory",
        "analytical": "analytical_memory"
    }
    table = table_map.get(layer)

    if not table:
        conn.close()
        return False

    if layer == "analytical":
        c.execute(f"""
            SELECT pattern, created FROM {table}
            WHERE id = ?
        """, (memory_id,))
    else:
        c.execute(f"""
            SELECT content, created FROM {table}
            WHERE id = ?
        """, (memory_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        return False

    content, original_created = row

    c.execute("""
        INSERT INTO memory_archive
        (original_layer, original_id, content,
         reason_archived, superseded_by,
         archived_date, original_created)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (layer, memory_id, content, reason,
          superseded_by or "", now, original_created))

    c.execute(f"""
        UPDATE {table} SET status = 'archived'
        WHERE id = ?
    """, (memory_id,))

    conn.commit()
    conn.close()
    return True


# ============================================================
# RETRIEVE FUNCTIONS
# ============================================================

def get_relevant_memories(query, max_results=TOP_N_MEMORIES,
                          channel_name=None):
    """
    Retrieves semantically relevant memories with bidirectional
    isolation for channels in MEMORY_ISOLATED_CHANNELS.

    Isolated channel strategy: the ChromaDB where clause enforces
    isolation at query time — only documents whose metadata contains
    project_tag == channel_name are fetched. Global memories (stored
    without project_tag) cannot be returned because they have no
    project_tag key, so they will never match $eq. Post-retrieval
    filtering is not used for this path because it cannot prevent
    global memories from being fetched and potentially returned via
    the query_memory tool path where channel_name is not passed.

    Non-isolated channel strategy: no where clause (avoids $ne
    unreliable behaviour for missing-field documents in ChromaDB).
    Candidates are fetched and filtered post-retrieval: any doc
    whose project_tag is in MEMORY_ISOLATED_CHANNELS is excluded.
    Global memories (project_tag absent → None) correctly pass.
    """
    query_embedding = embedding_model.encode(query).tolist()
    results = {}
    is_isolated = channel_name in MEMORY_ISOLATED_CHANNELS
    is_restricted = channel_name in RESTRICTED_CHANNELS

    for layer_name, collection in [
        ("strategic", strategic_collection),
        ("operational", operational_collection),
        ("analytical", analytical_collection)
    ]:
        try:
            count = collection.count()
            if count == 0:
                results[layer_name] = []
                continue

            if is_isolated:
                # Isolation enforced at query level — only documents
                # tagged for this channel are fetched. Post-filter
                # enforces channel_name match with no global fallback
                # for restricted channels.
                search_results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(max_results, count),
                    where={"project_tag": {"$eq": channel_name}},
                    include=["documents", "metadatas"]
                )
                docs = search_results["documents"][0]
                metas = search_results["metadatas"][0]
                pairs = sorted(
                    zip(docs, metas),
                    key=lambda p: (
                        float((p[1] or {}).get("confidence", 0.0)),
                        (p[1] or {}).get("created_at", "")
                    ),
                    reverse=True
                )
                filtered = []
                for doc, meta in pairs:
                    doc_channel = (
                        meta.get("channel_name") if meta else None
                    ) or "global"
                    if is_restricted:
                        if doc_channel == channel_name:
                            filtered.append(doc)
                    else:
                        filtered.append(doc)
                    if len(filtered) >= max_results:
                        break
                results[layer_name] = filtered
            else:
                # Fetch extra candidates, then exclude isolated-channel
                # memories in Python. $ne on missing fields is unreliable
                # in ChromaDB, so post-retrieval filter is safer here.
                # Also enforce channel scoping: global memories surface
                # everywhere; channel-scoped memories stay local.
                fetch_n = min(max_results * 5, count, 25)
                search_results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=fetch_n,
                    include=["documents", "metadatas"]
                )
                docs = search_results["documents"][0]
                metas = search_results["metadatas"][0]
                pairs = sorted(
                    zip(docs, metas),
                    key=lambda p: (
                        float((p[1] or {}).get("confidence", 0.0)),
                        (p[1] or {}).get("created_at", "")
                    ),
                    reverse=True
                )
                filtered = []
                for doc, meta in pairs:
                    doc_tag = (
                        meta.get("project_tag") if meta else None
                    )
                    if doc_tag in MEMORY_ISOLATED_CHANNELS:
                        continue
                    if channel_name:
                        doc_channel = (
                            meta.get("channel_name") if meta else None
                        ) or "global"
                        if (doc_channel != "global"
                                and doc_channel != channel_name):
                            continue
                    filtered.append(doc)
                    if len(filtered) >= max_results:
                        break
                results[layer_name] = filtered

        except Exception:
            results[layer_name] = []

    all_stale = check_stale_memories()
    if is_isolated:
        results["stale_flags"] = [
            f for f in all_stale
            if f.get("project_tag") == channel_name
        ]
    else:
        results["stale_flags"] = [
            f for f in all_stale
            if f.get("project_tag") not in MEMORY_ISOLATED_CHANNELS
        ]

    return results


def check_stale_memories():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now()
    flags = []

    c.execute("""
        SELECT id, content, last_confirmed, flag_after_days,
               project_tag
        FROM strategic_memory
        WHERE status = 'active'
    """)
    for mem_id, content, last_confirmed, flag_days, \
            project_tag in c.fetchall():
        if last_confirmed:
            confirmed_date = datetime.fromisoformat(
                last_confirmed
            )
            days_old = (today - confirmed_date).days
            if days_old > flag_days:
                flags.append({
                    "layer": "strategic",
                    "id": mem_id,
                    "content": content[:120],
                    "days_old": days_old,
                    "project_tag": project_tag,
                    "message": (
                        f"Strategic memory "
                        f"({days_old} days old) "
                        f"— still valid? "
                        f"'{content[:80]}...'"
                    )
                })

    c.execute("""
        SELECT id, content, last_updated, flag_after_days,
               project_tag
        FROM operational_memory
        WHERE status = 'active'
    """)
    for mem_id, content, last_updated, flag_days, \
            project_tag in c.fetchall():
        if last_updated:
            updated_date = datetime.fromisoformat(
                last_updated
            )
            days_old = (today - updated_date).days
            if days_old > flag_days:
                flags.append({
                    "layer": "operational",
                    "id": mem_id,
                    "content": content[:120],
                    "days_old": days_old,
                    "project_tag": project_tag,
                    "message": (
                        f"Operational memory "
                        f"({days_old} days old) "
                        f"— still active? "
                        f"'{content[:80]}...'"
                    )
                })

    conn.close()
    return flags


def validate_memory(layer, memory_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    table_map = {
        "strategic": ("strategic_memory", "last_confirmed"),
        "operational": ("operational_memory", "last_updated"),
        "analytical": ("analytical_memory", "last_observed")
    }

    table, date_field = table_map.get(
        layer, ("strategic_memory", "last_confirmed")
    )

    c.execute(f"""
        UPDATE {table}
        SET {date_field} = ?,
            times_referenced = times_referenced + 1
        WHERE id = ?
    """, (now, memory_id))

    conn.commit()
    conn.close()


def update_memory_confidence(layer, memory_id, direction):
    _VALID_TABLES = {
        "strategic": "strategic_memory",
        "operational": "operational_memory",
        "analytical": "analytical_memory",
    }
    table = _VALID_TABLES.get(layer)
    if not table:
        return None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        f"SELECT confidence FROM {table} WHERE id = ?",
        (memory_id,)
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    current = float(row[0])
    updated = (
        min(current + 0.1, 1.0)
        if direction == "increase"
        else max(current - 0.1, 0.1)
    )
    c.execute(
        f"UPDATE {table} SET confidence = ? WHERE id = ?",
        (updated, memory_id)
    )
    conn.commit()
    conn.close()
    return (current, updated)


def format_memory_for_prompt(memories):
    sections = []

    if memories.get("strategic"):
        items = "\n".join(
            f"- {m}" for m in memories["strategic"][:3]
        )
        sections.append(f"STRATEGIC CONTEXT:\n{items}")

    if memories.get("operational"):
        items = "\n".join(
            f"- {m}" for m in memories["operational"][:3]
        )
        sections.append(f"ACTIVE PROJECTS:\n{items}")

    if memories.get("analytical"):
        items = "\n".join(
            f"- {m}" for m in memories["analytical"][:3]
        )
        sections.append(f"PATTERNS AND INSIGHTS:\n{items}")

    if memories.get("stale_flags"):
        flags = "\n".join(
            f"⚠️ {f['message']}"
            for f in memories["stale_flags"][:2]
        )
        sections.append(
            f"MEMORIES NEEDING VALIDATION:\n{flags}\n"
            f"Before using these, ask the user to confirm "
            f"they are still accurate."
        )

    if not sections:
        return ""

    return "MEMORY CONTEXT:\n" + "\n\n".join(sections)


# ============================================================
# CONVERSATION HISTORY PERSISTENCE
# ============================================================

def save_conversation_history(user_id: str, history: list) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO conversation_history (user_id, history, updated)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            history = excluded.history,
            updated = excluded.updated
    """, (user_id, json.dumps(history), now))
    conn.commit()
    conn.close()


def load_all_conversation_histories() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, history FROM conversation_history")
    rows = c.fetchall()
    conn.close()
    return {user_id: json.loads(history) for user_id, history in rows}


# ============================================================
# INTERACTION COUNTER
# ============================================================

def increment_interaction_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        UPDATE meta SET value = CAST(
            (CAST(value AS INTEGER) + 1) AS TEXT
        )
        WHERE key = 'interaction_count'
    """)

    c.execute("""
        SELECT value FROM meta
        WHERE key = 'interaction_count'
    """)
    count = int(c.fetchone()[0])

    conn.commit()
    conn.close()
    return count


def get_recent_experiences(limit=10,
                           task_completed_only=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if task_completed_only:
        c.execute("""
            SELECT request_summary, approach_used,
                   outcome, lesson
            FROM experiences
            WHERE task_completed = 1
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
    else:
        c.execute("""
            SELECT request_summary, approach_used,
                   outcome, lesson
            FROM experiences
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

    rows = c.fetchall()
    conn.close()

    return [
        {
            "request": r[0],
            "approach": r[1],
            "outcome": r[2],
            "lesson": r[3]
        }
        for r in rows
    ]


def get_handoff_memories():
    """
    Pulls a structured snapshot of all memory layers for handoff
    generation. Returns raw rows — no semantic search, ordered
    by confidence and recency so the highest-signal items surface.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now()

    # Top 5 strategic by confidence then recency
    c.execute("""
        SELECT id, content, category, confidence, created
        FROM strategic_memory
        WHERE status = 'active'
        ORDER BY confidence DESC, created DESC
        LIMIT 5
    """)
    strategic = [
        {
            "id": r[0], "content": r[1], "category": r[2],
            "confidence": r[3], "created": r[4]
        }
        for r in c.fetchall()
    ]

    # Active operational memories excluding review flags,
    # filtered to non-stale only
    c.execute("""
        SELECT id, content, project_name, priority,
               last_updated, flag_after_days, blockers
        FROM operational_memory
        WHERE status = 'active'
          AND project_name != 'review_flags'
        ORDER BY
            CASE priority
                WHEN 'high'   THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low'    THEN 3
                ELSE 4
            END,
            last_updated DESC
    """)
    operational = []
    for r in c.fetchall():
        last_updated_str = r[4]
        flag_days = r[5] or 7
        if last_updated_str:
            try:
                updated_date = datetime.fromisoformat(last_updated_str)
                if (today - updated_date).days > flag_days:
                    continue
            except (ValueError, TypeError):
                pass
        operational.append({
            "id": r[0], "content": r[1],
            "project_name": r[2], "priority": r[3],
            "blockers": r[6] or ""
        })

    # Top 5 analytical by confidence then times observed
    c.execute("""
        SELECT id, pattern, confidence,
               trigger_conditions, pattern_type
        FROM analytical_memory
        WHERE status = 'active'
        ORDER BY confidence DESC, times_observed DESC
        LIMIT 5
    """)
    analytical = [
        {
            "id": r[0], "pattern": r[1], "confidence": r[2],
            "trigger_conditions": r[3] or "",
            "pattern_type": r[4] or ""
        }
        for r in c.fetchall()
    ]

    # Review flags stored as operational with project_name='review_flags'
    c.execute("""
        SELECT id, content, priority, created
        FROM operational_memory
        WHERE status = 'active'
          AND project_name = 'review_flags'
        ORDER BY
            CASE priority
                WHEN 'high'   THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low'    THEN 3
                ELSE 4
            END,
            created DESC
    """)
    review_flags = [
        {
            "id": r[0], "content": r[1],
            "priority": r[2] or "medium",
            "created": r[3]
        }
        for r in c.fetchall()
    ]

    conn.close()

    return {
        "strategic": strategic,
        "operational": operational,
        "analytical": analytical,
        "experiences": get_recent_experiences(limit=3),
        "review_flags": review_flags
    }


# ============================================================
# HEALTH TRACKING FUNCTIONS
# ============================================================

def log_health_panel(test_date, marker, value, unit,
                     reference_range, notes=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO health_panels
        (test_date, marker, value, unit, reference_range, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (test_date, marker, float(value), unit,
          reference_range, notes))
    panel_id = c.lastrowid
    conn.commit()
    conn.close()
    return panel_id


def get_health_panels(marker=None, since_date=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    conditions = []
    params = []
    if marker:
        conditions.append("marker = ?")
        params.append(marker)
    if since_date:
        conditions.append("test_date >= ?")
        params.append(since_date)

    where = (
        "WHERE " + " AND ".join(conditions) if conditions else ""
    )
    c.execute(f"""
        SELECT id, test_date, marker, value, unit,
               reference_range, personal_baseline, notes,
               created_at
        FROM health_panels
        {where}
        ORDER BY test_date DESC, marker
    """, params)

    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "test_date": r[1], "marker": r[2],
            "value": r[3], "unit": r[4],
            "reference_range": r[5] or "",
            "personal_baseline": r[6],
            "notes": r[7] or "",
            "created_at": r[8]
        }
        for r in rows
    ]


def log_health_protocol(protocol_name, dose, frequency,
                        start_date, notes=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO health_protocols
        (protocol_name, dose, frequency, start_date, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (protocol_name, dose, frequency, start_date, notes))
    protocol_id = c.lastrowid
    conn.commit()
    conn.close()
    return protocol_id


def update_health_protocol_end(protocol_name, end_date):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE health_protocols
        SET end_date = ?
        WHERE protocol_name = ? AND end_date IS NULL
    """, (end_date, protocol_name))
    updated = c.rowcount
    conn.commit()
    conn.close()
    return updated > 0


def get_active_protocols():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, protocol_name, dose, frequency,
               start_date, notes, created_at
        FROM health_protocols
        WHERE end_date IS NULL
        ORDER BY start_date DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "protocol_name": r[1],
            "dose": r[2], "frequency": r[3],
            "start_date": r[4],
            "notes": r[5] or "",
            "created_at": r[6]
        }
        for r in rows
    ]


def get_memory_counts() -> dict:
    """Returns active record counts for each memory layer."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM strategic_memory WHERE status = 'active'"
    )
    strategic = c.fetchone()[0]
    c.execute(
        "SELECT COUNT(*) FROM operational_memory WHERE status = 'active'"
    )
    operational = c.fetchone()[0]
    c.execute(
        "SELECT COUNT(*) FROM analytical_memory WHERE status = 'active'"
    )
    analytical = c.fetchone()[0]
    conn.close()
    return {
        "strategic": strategic,
        "operational": operational,
        "analytical": analytical
    }


def memory_stats() -> dict:
    """
    Returns active memory counts per layer and per project_tag.
    Structure:
      {
        "strategic":   {"total": N, "by_tag": {None: N, "health-tracking": N, ...}},
        "operational": {"total": N, "by_tag": {...}},
        "analytical":  {"total": N, "by_tag": {...}},
      }
    None key = global (no project tag).
    """
    tables = {
        "strategic":   "strategic_memory",
        "operational": "operational_memory",
        "analytical":  "analytical_memory",
    }
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    result = {}
    for layer, table in tables.items():
        c.execute(f"""
            SELECT project_tag, COUNT(*)
            FROM {table}
            WHERE status = 'active'
            GROUP BY project_tag
        """)
        by_tag = {}
        total = 0
        for tag, count in c.fetchall():
            by_tag[tag] = count
            total += count
        result[layer] = {"total": total, "by_tag": by_tag}
    conn.close()
    return result


def _cluster_by_similarity(memories: list, threshold: float = 0.85) -> list:
    """
    Groups a list of memory dicts into clusters using cosine similarity.
    Each dict must have an "embedding" key (list of floats).
    Uses union-find on the full pairwise similarity graph.
    Returns only clusters with 3+ members.
    """
    n = len(memories)
    if n < 3:
        return []

    arr = np.array([m["embedding"] for m in memories], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = arr / norms
    sim_matrix = normalized @ normalized.T

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    for i in range(n):
        for j in range(i + 1, n):
            if float(sim_matrix[i, j]) >= threshold:
                union(i, j)

    clusters_map = {}
    for i, mem in enumerate(memories):
        root = find(i)
        if root not in clusters_map:
            clusters_map[root] = []
        clusters_map[root].append(mem)

    return [cl for cl in clusters_map.values() if len(cl) >= 3]


def get_consolidation_candidates(layer: str,
                                  channel_name: str = None) -> list:
    """
    Returns clusters of semantically similar memories eligible for
    consolidation. Only clusters of 3+ members are returned.

    Constraints enforced:
      - Age > 24 hours (too-recent memories are skipped)
      - Operational layer: only non-active entries (active ones may
        still be needed verbatim)
      - Strategic / analytical: only active entries
      - Respects bidirectional isolation via channel_name
      - Never mixes memories from different project_tags

    Each memory dict in a cluster contains:
      {id, content, confidence, project_tag, embedding}
    """
    layer_config = {
        "strategic":   ("strategic_memory",   "content",  True),
        "operational": ("operational_memory",  "content",  False),
        "analytical":  ("analytical_memory",   "pattern",  True),
    }
    collection_map = {
        "strategic":   strategic_collection,
        "operational": operational_collection,
        "analytical":  analytical_collection,
    }

    if layer not in layer_config:
        return []

    table, content_col, only_active = layer_config[layer]
    collection = collection_map[layer]
    is_isolated = channel_name in MEMORY_ISOLATED_CHANNELS

    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    excluded_tags = list(MEMORY_ISOLATED_CHANNELS)
    status_clause = (
        "status = 'active'" if only_active else "status != 'active'"
    )

    conf_expr = "confidence"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if is_isolated:
        c.execute(f"""
            SELECT id, {content_col}, {conf_expr}, project_tag, created
            FROM {table}
            WHERE {status_clause}
              AND project_tag = ?
              AND created < ?
        """, (channel_name, cutoff))
    else:
        placeholders = ",".join("?" * len(excluded_tags))
        c.execute(f"""
            SELECT id, {content_col}, {conf_expr}, project_tag, created
            FROM {table}
            WHERE {status_clause}
              AND (project_tag IS NULL
                   OR project_tag NOT IN ({placeholders}))
              AND created < ?
        """, excluded_tags + [cutoff])

    rows = c.fetchall()
    conn.close()

    if len(rows) < 3:
        return []

    # Fetch embeddings from ChromaDB by explicit ID list
    chroma_ids = [f"{layer}_{row[0]}" for row in rows]
    try:
        fetched = collection.get(
            ids=chroma_ids,
            include=["embeddings"]
        )
    except Exception:
        return []

    id_to_embedding = {
        fid: emb
        for fid, emb in zip(
            fetched.get("ids", []),
            fetched.get("embeddings", [])
        )
    }

    memories = []
    for mem_id, content, confidence, project_tag, _created in rows:
        embedding = id_to_embedding.get(f"{layer}_{mem_id}")
        if embedding is not None:
            memories.append({
                "id": mem_id,
                "content": content,
                "confidence": float(confidence or 0.5),
                "project_tag": project_tag,
                "embedding": embedding,
            })

    if len(memories) < 3:
        return []

    # Group by project_tag — never mix tags in a cluster
    by_tag = {}
    for m in memories:
        tag = m["project_tag"]
        if tag not in by_tag:
            by_tag[tag] = []
        by_tag[tag].append(m)

    all_clusters = []
    for tag_group in by_tag.values():
        if len(tag_group) >= 3:
            all_clusters.extend(_cluster_by_similarity(tag_group))

    return all_clusters


# ============================================================
# INITIALISE ON IMPORT
# ============================================================

init_db()