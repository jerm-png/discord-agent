import sqlite3
import json
import re
import difflib
import numpy as np
import chromadb
from datetime import datetime, timedelta
from sentence_transformers import SentenceTransformer
from app.core.config import DB_PATH, CHROMA_PATH

# ============================================================
# CONFIGURATION
# ============================================================

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

# ── Rubric rejection queue ────────────────────────────────────
_rubric_rejection_log: list = []

# ── Health protocol notification queue ──────────────────────────
_health_protocol_log: list = []


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
            confidence REAL NOT NULL DEFAULT 0.7,
            pinned INTEGER DEFAULT 0
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

    try:
        c.execute(
            "ALTER TABLE operational_memory ADD COLUMN pinned INTEGER DEFAULT 0"
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS session_state (
            session_key TEXT PRIMARY KEY,
            active_task TEXT,
            build_list TEXT,
            decisions TEXT,
            recent_actions TEXT,
            updated TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_updated
        ON session_state(updated)
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL DEFAULT 'person',
            role TEXT,
            context TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL REFERENCES entities(id),
            category TEXT NOT NULL,
            fact TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            superseded_by INTEGER REFERENCES entity_facts(id),
            recorded_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_channel TEXT,
            confidence REAL DEFAULT 0.8
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_entity_facts_entity_id
        ON entity_facts(entity_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_entity_facts_status
        ON entity_facts(status, entity_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_entity_facts_category
        ON entity_facts(category, entity_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_entities_name
        ON entities(name)
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reasoning_trace (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_id TEXT,
            channel_name TEXT,
            tool_name TEXT NOT NULL,
            tool_inputs TEXT,
            result_summary TEXT,
            iteration INTEGER
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialised.")


def log_reasoning_trace(
    user_id: str,
    channel_name: str,
    tool_name: str,
    tool_inputs: dict,
    result_summary: str,
    iteration: int
):
    """Logs a single tool call trace entry to the reasoning_trace table."""
    import json as _json
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO reasoning_trace
            (timestamp, user_id, channel_name, tool_name,
             tool_inputs, result_summary, iteration)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                user_id,
                channel_name,
                tool_name,
                _json.dumps(tool_inputs)[:500],
                result_summary[:1000],
                iteration,
            )
        )
        conn.commit()
    finally:
        conn.close()


def get_reasoning_trace(
    user_id: str, channel_name: str, limit: int = 10
) -> list[dict]:
    """Returns the most recent reasoning trace entries for a user/channel pair."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            """
            SELECT timestamp, tool_name, tool_inputs, result_summary, iteration
            FROM reasoning_trace
            WHERE user_id = ? AND channel_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (user_id, channel_name, limit)
        )
        rows = cursor.fetchall()
        return [
            {
                "timestamp": row[0],
                "tool_name": row[1],
                "tool_inputs": row[2],
                "result_summary": row[3],
                "iteration": row[4],
            }
            for row in rows
        ]
    finally:
        conn.close()


def pin_memory(memory_id: int) -> bool:
    """Sets pinned=1 on the given operational_memory row. Returns True if a row was updated."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "UPDATE operational_memory SET pinned = 1 WHERE id = ?",
            (memory_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def unpin_memory(memory_id: int) -> bool:
    """Sets pinned=0 on the given operational_memory row. Returns True if a row was updated."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "UPDATE operational_memory SET pinned = 0 WHERE id = ?",
            (memory_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def drain_rubric_rejection_log() -> list:
    """
    Returns all pending rubric rejections and clears the queue.
    Called from bot.py after extract_and_store_memories() returns.
    Each item: {"score": int, "layer": str, "content": str, "reason": str}
    """
    global _rubric_rejection_log
    items = list(_rubric_rejection_log)
    _rubric_rejection_log.clear()
    return items


def record_rubric_rejection(score: int, layer: str,
                             content: str, reason: str) -> None:
    """Appends a rejection entry to the module-level queue."""
    _rubric_rejection_log.append({
        "score": score,
        "layer": layer,
        "content": content,
        "reason": reason,
    })


async def evaluate_memory_rubric(
    content: str,
    similar_memories: list,
    background_model_fn
) -> dict:
    """
    Score proposed memory content using a 4-criterion rubric via Haiku.
    (Criterion 5 — save type appropriateness — is NOT scored here.)
    Returns {"score": int, "pass": bool, "reason": str}.
    Fails open on any error — never blocks a save.
    """
    similar_block = (
        "\n".join(f"- {m[:150]}" for m in similar_memories[:3])
        if similar_memories else "None"
    )

    prompt = (
        f"Score this memory (1-3 each, max 12 for criteria 1-4,"
        f" skip criterion 5):\n"
        f"Specificity: concrete/actionable vs vague paraphrase\n"
        f"Non-redundancy: adds new info vs restates existing\n"
        f"Durability: true in 2+ weeks vs session-specific noise\n"
        f"Attribution: clear project/context vs orphaned\n"
        f"Proposed: {content[:300]}\n\n"
        f"Most similar existing memories:\n{similar_block}\n\n"
        f"Reply with exactly: SCORE:<n>/12 REASON:<one sentence>"
    )

    try:
        response = await background_model_fn(prompt)
        # Strip markdown fences Ollama sometimes wraps around responses
        raw = response.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        response = raw.strip()
        match = re.search(r'SCORE:(\d+)/12', response)
        if not match:
            return {
                "score": 12,
                "pass": True,
                "reason": "parse_failed_fail_open",
            }
        score = int(match.group(1))
        reason_match = re.search(r'REASON:(.+)', response)
        reason = (
            reason_match.group(1).strip()
            if reason_match else "no reason returned"
        )
        # Threshold 8/12 — proportionally equivalent to 10/15 with
        # 4 active criteria (criterion 5 excluded, max is 12).
        return {"score": score, "pass": score >= 8, "reason": reason}
    except Exception as e:
        return {
            "score": 12,
            "pass": True,
            "reason": f"rubric_unavailable: {e}",
        }


def get_top_similar_memories(content: str, layer: str,
                              n: int = 3) -> tuple:
    """
    Returns (max_cosine_similarity, [top_n_texts]) for content against
    the given ChromaDB layer collection.
    For unit-normalized embeddings: cosine_sim = 1 - (L2^2 / 2).
    Returns (0.0, []) on empty collection or error.
    """
    collection_map = {
        "strategic":   strategic_collection,
        "operational": operational_collection,
        "analytical":  analytical_collection,
    }
    collection = collection_map.get(layer)
    if not collection:
        return (0.0, [])
    try:
        count = collection.count()
        if count == 0:
            return (0.0, [])
        embedding = embedding_model.encode(content).tolist()
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(n, count),
            include=["documents", "distances"]
        )
        distances = results.get("distances", [[]])[0]
        documents = results.get("documents", [[]])[0]
        if not distances:
            return (0.0, documents)
        similarities = [
            max(0.0, 1.0 - (d * d) / 2.0) for d in distances
        ]
        return (max(similarities), documents)
    except Exception:
        return (0.0, [])


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

    # Sync ChromaDB — remove vector entry so archived records
    # never surface in semantic retrieval
    collection_map = {
        "strategic": strategic_collection,
        "operational": operational_collection,
        "analytical": analytical_collection,
    }
    chroma_collection = collection_map.get(layer)
    if chroma_collection:
        chroma_id = f"{layer}_{memory_id}"
        try:
            chroma_collection.delete(ids=[chroma_id])
        except Exception as e:
            print(f"[archive_memory] ChromaDB delete skipped for {chroma_id}: {e}")

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


def auto_archive_stale_operational() -> int:
    """
    Archives active operational memories that are open clarification
    questions (contain 'clarify', 'determine', 'confirm', or '?') and
    have not been updated in more than 30 days.

    Health-tracking memories are never touched under any circumstances.
    Returns count of memories archived.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now()

    c.execute("""
        SELECT id, content, last_updated, project_tag
        FROM operational_memory
        WHERE status = 'active'
          AND (pinned IS NULL OR pinned = 0)
          AND (project_tag IS NULL OR project_tag != 'health-tracking')
          AND (
              content LIKE '%clarify%'
           OR content LIKE '%determine%'
           OR content LIKE '%confirm%'
           OR content LIKE '%?%'
          )
    """)
    rows = c.fetchall()
    conn.close()

    archived = 0
    for mem_id, content, last_updated, project_tag in rows:
        if not last_updated:
            continue
        try:
            updated_date = datetime.fromisoformat(last_updated)
        except (ValueError, TypeError):
            continue
        if (today - updated_date).days <= 30:
            continue
        if archive_memory("operational", mem_id,
                          "auto-archived: exceeded decay threshold"):
            print(
                f"[Decay] Auto-archived operational memory "
                f"id={mem_id}: {content[:80]}"
            )
            archived += 1

    return archived


def check_operational_duplicate(content: str,
                                 project_tag=None) -> tuple:
    """
    Returns (is_duplicate, ratio, existing_id).
    is_duplicate is True when any active operational memory with the
    same project_tag has a SequenceMatcher ratio > 0.90 against content.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if project_tag is None:
        c.execute("""
            SELECT id, content FROM operational_memory
            WHERE status = 'active' AND project_tag IS NULL
        """)
    else:
        c.execute("""
            SELECT id, content FROM operational_memory
            WHERE status = 'active' AND project_tag = ?
        """, (project_tag,))
    rows = c.fetchall()
    conn.close()

    for existing_id, existing_content in rows:
        ratio = difflib.SequenceMatcher(
            None, existing_content, content
        ).ratio()
        if ratio > 0.90:
            return (True, ratio, existing_id)
    return (False, 0.0, None)


def audit_stale_operational() -> None:
    """
    Prints all operational memories grouped by status with days since
    last_updated. Call manually for decay diagnostics — not scheduled.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, status, content, last_updated, project_tag
        FROM operational_memory
        ORDER BY status, last_updated ASC
    """)
    rows = c.fetchall()
    conn.close()

    today = datetime.now()
    by_status: dict = {}
    for mem_id, status, content, last_updated, project_tag in rows:
        by_status.setdefault(status, []).append(
            (mem_id, content, last_updated, project_tag)
        )

    for status, entries in sorted(by_status.items()):
        print(f"\n{'=' * 60}")
        print(f"STATUS: {status.upper()} ({len(entries)} entries)")
        print(f"{'=' * 60}")
        print(f"{'ID':<6} {'Days':<6} {'Tag':<20} Content")
        print(f"{'-' * 6} {'-' * 6} {'-' * 20} {'-' * 40}")
        for mem_id, content, last_updated, project_tag in entries:
            if last_updated:
                try:
                    days: object = (
                        today - datetime.fromisoformat(last_updated)
                    ).days
                except (ValueError, TypeError):
                    days = "?"
            else:
                days = "?"
            tag = project_tag or "global"
            print(
                f"{mem_id:<6} {str(days):<6} {tag:<20} {content[:60]}"
            )


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

    # Top 3 analytical by confidence then times observed
    c.execute("""
        SELECT id, pattern, confidence,
               trigger_conditions, pattern_type
        FROM analytical_memory
        WHERE status = 'active'
        ORDER BY confidence DESC, times_observed DESC
        LIMIT 3
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


def get_unresolved_high_priority_flags() -> list:
    """
    Returns all active HIGH priority review flags for the scheduled
    proactive surfacing job. Queries operational_memory directly.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT id, content, priority, created, channel_name
            FROM operational_memory
            WHERE project_name = 'review_flags'
              AND status = 'active'
              AND priority = 'high'
            ORDER BY created ASC
            """
        )
        rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "content": row[1],
            "priority": row[2],
            "created": row[3],
            "channel_name": row[4],
        }
        for row in rows
    ]


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


def get_active_health_protocol(protocol_name: str) -> dict | None:
    """Returns the active (no end_date) health_protocols row for protocol_name, or None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, protocol_name, dose, frequency, start_date, notes
        FROM health_protocols
        WHERE protocol_name = ? AND end_date IS NULL
        LIMIT 1
    """, (protocol_name,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "protocol_name": row[1], "dose": row[2],
        "frequency": row[3], "start_date": row[4], "notes": row[5]
    }


def health_protocol_log_notification(msg: str) -> None:
    """Appends a notification message to the health protocol log queue."""
    _health_protocol_log.append(msg)


async def extract_health_protocols(
    bot_reply: str, call_background_model_fn
) -> list:
    """
    Calls the background model to extract supplement/peptide/medication
    protocols from bot_reply. Returns a list of dicts with keys:
    protocol_name, dose, frequency, start_date, notes.
    Returns [] on parse failure or if no protocols found.
    """
    prompt = (
        "You are a clinical data extractor. Read the following text and identify "
        "any supplement, peptide, or medication protocols that include a specific "
        "name, dosage, and frequency.\n\n"
        "Return ONLY a valid JSON array. Each item must have exactly these fields:\n"
        "\"protocol_name\": string — name of the supplement, peptide, or medication\n"
        "\"dose\": string — dosage amount and unit (e.g. \"500mg\", \"250mcg\", \"5mg/kg\")\n"
        "\"frequency\": string — how often taken (e.g. \"daily\", \"twice weekly\", \"as needed\")\n"
        "\"start_date\": string — use today's date in YYYY-MM-DD format if not explicitly stated\n"
        "\"notes\": string or null — relevant context such as whether this is a confirmed "
        "current protocol or a recommendation\n\n"
        "Rules:\n"
        "If no protocols with all three of name + dose + frequency are present, return []\n"
        "Do not hallucinate. Only extract what is explicitly stated in the text.\n"
        "Return [] for general health discussion with no specific protocols.\n"
        "Return ONLY the JSON array with no explanation, no markdown, no code fences.\n\n"
        f"Text to analyze:\n{bot_reply}"
    )
    try:
        raw = await call_background_model_fn(prompt, max_tokens=600)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        return []


async def extract_and_save_health_protocols(
    bot_reply: str, call_background_model_fn
) -> int:
    """
    Extracts clinical protocols from bot_reply, applies dose-aware dedup,
    writes new/updated records to health_protocols, and queues log messages.
    Returns the count of records written (new + updated, skips excluded).
    """
    protocols = await extract_health_protocols(bot_reply, call_background_model_fn)
    today = datetime.now().strftime("%Y-%m-%d")
    written = 0

    for protocol in protocols:
        name = protocol.get("protocol_name", "").strip()
        dose = protocol.get("dose", "").strip()
        frequency = protocol.get("frequency", "").strip()
        start_date = protocol.get("start_date") or today
        notes = protocol.get("notes") or None

        if not name or not dose or not frequency:
            continue

        existing = get_active_health_protocol(name)

        if existing is None:
            log_health_protocol(name, dose, frequency, start_date, notes)
            health_protocol_log_notification(
                f"💊 Protocol captured: {name} | {dose} | {frequency}"
            )
            written += 1
        elif existing["dose"] == dose:
            continue  # true duplicate — skip
        else:
            old_dose = existing["dose"]
            update_health_protocol_end(name, today)
            log_health_protocol(name, dose, frequency, start_date, notes)
            health_protocol_log_notification(
                f"💊 Protocol updated: {name} | {old_dose} → {dose}"
            )
            written += 1

    return written


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


def _cluster_by_similarity(memories: list, threshold: float = 0.72) -> list:
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
    pinned_clause = (
        "AND (pinned IS NULL OR pinned = 0)"
        if layer == "operational" else ""
    )

    conf_expr = "confidence"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if is_isolated:
        c.execute(f"""
            SELECT id, {content_col}, {conf_expr}, project_tag, created
            FROM {table}
            WHERE {status_clause}
              {pinned_clause}
              AND project_tag = ?
              AND created < ?
        """, (channel_name, cutoff))
    else:
        placeholders = ",".join("?" * len(excluded_tags))
        c.execute(f"""
            SELECT id, {content_col}, {conf_expr}, project_tag, created
            FROM {table}
            WHERE {status_clause}
              {pinned_clause}
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

    large_layer = len(memories) > 400

    all_clusters = []
    for tag_group in by_tag.values():
        if len(tag_group) >= 3:
            all_clusters.extend(_cluster_by_similarity(tag_group))
            if large_layer:
                all_clusters.extend(
                    _cluster_by_similarity(tag_group, threshold=0.65)
                )

    return all_clusters


# ============================================================
# ============================================================
# ENTITY MEMORY — person-keyed longitudinal tracking
# ============================================================

def upsert_entity(
    name: str,
    entity_type: str = "person",
    role: str = None,
    context: str = None,
) -> int:
    """
    Creates or updates an entity. Returns the entity's id.
    Name is the unique key — case-insensitive match.
    """
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(?)",
            (name,)
        )
        row = cursor.fetchone()
        if row:
            entity_id = row[0]
            conn.execute(
                """UPDATE entities SET role = COALESCE(?, role),
                   context = COALESCE(?, context),
                   updated_at = ?
                   WHERE id = ?""",
                (role, context, now, entity_id)
            )
        else:
            cursor = conn.execute(
                """INSERT INTO entities
                   (name, entity_type, role, context,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, entity_type, role, context, now, now)
            )
            entity_id = cursor.lastrowid
        conn.commit()
        return entity_id
    finally:
        conn.close()


def add_entity_fact(
    entity_id: int,
    category: str,
    fact: str,
    source_channel: str = "director-workspace",
    confidence: float = 0.8,
    supersede_category: bool = False,
) -> int:
    """
    Adds a new fact for an entity. If supersede_category=True,
    marks all previous active facts in this category as superseded
    by the new one. Returns the new fact's id.
    """
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            """INSERT INTO entity_facts
               (entity_id, category, fact, status,
                recorded_at, updated_at, source_channel, confidence)
               VALUES (?, ?, ?, 'active', ?, ?, ?, ?)""",
            (entity_id, category, fact, now, now,
             source_channel, confidence)
        )
        new_id = cursor.lastrowid

        if supersede_category:
            conn.execute(
                """DELETE FROM entity_facts
                   WHERE entity_id = ?
                     AND category = ?
                     AND status = 'active'
                     AND id != ?""",
                (entity_id, category, new_id)
            )
        conn.commit()
        return new_id
    finally:
        conn.close()


def get_entity_profile(name: str) -> dict:
    """
    Returns a full profile for an entity by name.
    Includes all active facts grouped by category,
    plus superseded facts for timeline view.
    Returns empty dict if entity not found.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "SELECT id, name, entity_type, role, context, "
            "created_at, updated_at "
            "FROM entities WHERE LOWER(name) = LOWER(?)",
            (name,)
        )
        row = cursor.fetchone()
        if not row:
            return {}

        entity_id = row[0]
        profile = {
            "id": entity_id,
            "name": row[1],
            "entity_type": row[2],
            "role": row[3],
            "context": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "facts": {},
            "history": [],
        }

        # Active facts grouped by category
        facts_cursor = conn.execute(
            """SELECT id, category, fact, recorded_at, confidence
               FROM entity_facts
               WHERE entity_id = ? AND status = 'active'
               ORDER BY category, recorded_at DESC""",
            (entity_id,)
        )
        for fid, cat, fact, recorded_at, confidence in facts_cursor:
            if cat not in profile["facts"]:
                profile["facts"][cat] = []
            profile["facts"][cat].append({
                "id": fid,
                "fact": fact,
                "recorded_at": recorded_at,
                "confidence": confidence,
            })

        # Timeline — all facts including superseded
        history_cursor = conn.execute(
            """SELECT category, fact, status, recorded_at
               FROM entity_facts
               WHERE entity_id = ?
               ORDER BY recorded_at ASC""",
            (entity_id,)
        )
        profile["history"] = [
            {
                "category": r[0],
                "fact": r[1],
                "status": r[2],
                "recorded_at": r[3],
            }
            for r in history_cursor
        ]

        return profile
    finally:
        conn.close()


def list_entities(entity_type: str = "person") -> list:
    """
    Returns all entities of a given type with their
    active fact counts. Used for !roster or similar commands.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            """SELECT e.id, e.name, e.role,
                      COUNT(f.id) as fact_count,
                      e.updated_at
               FROM entities e
               LEFT JOIN entity_facts f
                 ON f.entity_id = e.id AND f.status = 'active'
               WHERE e.entity_type = ?
               GROUP BY e.id
               ORDER BY e.name""",
            (entity_type,)
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "role": row[2],
                "fact_count": row[3],
                "updated_at": row[4],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def format_entity_profile_for_prompt(name: str) -> str:
    """
    Returns a compact string representation of an entity profile
    suitable for injection into a system prompt or message context.
    Returns empty string if entity not found.
    """
    profile = get_entity_profile(name)
    if not profile:
        return ""

    lines = [
        f"[PERSON: {profile['name']}"
        + (f" | {profile['role']}" if profile['role'] else "")
        + "]"
    ]

    if profile["context"]:
        lines.append(f"Context: {profile['context']}")

    for category, facts in profile["facts"].items():
        lines.append(f"{category.title()}:")
        for f in facts[:3]:  # cap at 3 per category
            date = f["recorded_at"][:10]
            lines.append(f"  • [{date}] {f['fact']}")

    return "\n".join(lines)


# INITIALISE ON IMPORT
# ============================================================

init_db()
auto_archive_stale_operational()