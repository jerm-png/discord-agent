import sqlite3
import json
import os
import chromadb
from datetime import datetime
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
            source TEXT
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
            dependencies TEXT
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
            status TEXT DEFAULT 'active'
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
                          confidence=0.8, source="conversation"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        INSERT INTO strategic_memory
        (content, category, confidence, created,
         last_confirmed, flag_after_days, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (content, category, confidence, now, now,
          DECAY_RATES["strategic"], source))

    memory_id = str(c.lastrowid)
    conn.commit()
    conn.close()

    embedding = embedding_model.encode(content).tolist()
    strategic_collection.add(
        documents=[content],
        embeddings=[embedding],
        ids=[f"strategic_{memory_id}"],
        metadatas=[{
            "category": category,
            "confidence": confidence
        }]
    )

    return memory_id


def save_operational_memory(content, project_name="general",
                            priority="medium", blockers=None,
                            dependencies=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        INSERT INTO operational_memory
        (project_name, content, priority, created,
         last_updated, flag_after_days, blockers, dependencies)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (project_name, content, priority, now, now,
          DECAY_RATES["operational"],
          blockers or "", dependencies or ""))

    memory_id = str(c.lastrowid)
    conn.commit()
    conn.close()

    embedding = embedding_model.encode(content).tolist()
    operational_collection.add(
        documents=[content],
        embeddings=[embedding],
        ids=[f"operational_{memory_id}"],
        metadatas=[{
            "project": project_name,
            "priority": priority
        }]
    )

    return memory_id


def save_analytical_memory(pattern, observation="",
                           reasoning="", outcome="",
                           confidence=0.5,
                           trigger_conditions="",
                           pattern_type="general"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        INSERT INTO analytical_memory
        (pattern_type, observation, reasoning, outcome,
         pattern, confidence, trigger_conditions,
         created, last_observed, flag_after_days)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pattern_type, observation, reasoning, outcome,
          pattern, confidence, trigger_conditions,
          now, now, DECAY_RATES["analytical"]))

    memory_id = str(c.lastrowid)
    conn.commit()
    conn.close()

    full_text = f"{pattern} {trigger_conditions}".strip()
    embedding = embedding_model.encode(full_text).tolist()
    analytical_collection.add(
        documents=[full_text],
        embeddings=[embedding],
        ids=[f"analytical_{memory_id}"],
        metadatas=[{
            "pattern_type": pattern_type,
            "confidence": confidence,
            "trigger_conditions": trigger_conditions
        }]
    )

    return memory_id


def save_experience(request_summary, approach_used,
                    outcome, lesson, layers_used=None,
                    quality_score=0.5, task_completed=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        INSERT INTO experiences
        (request_summary, approach_used, outcome, lesson,
         layers_used, timestamp, quality_score, task_completed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (request_summary, approach_used, outcome, lesson,
          json.dumps(layers_used or []),
          datetime.now().isoformat(), quality_score,
          1 if task_completed else 0))

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

def get_relevant_memories(query, max_results=TOP_N_MEMORIES):
    query_embedding = embedding_model.encode(query).tolist()
    results = {}

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

            search_results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(max_results, count)
            )

            if search_results["documents"][0]:
                results[layer_name] = \
                    search_results["documents"][0]
            else:
                results[layer_name] = []

        except Exception:
            results[layer_name] = []

    results["stale_flags"] = check_stale_memories()
    return results


def check_stale_memories():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now()
    flags = []

    c.execute("""
        SELECT id, content, last_confirmed, flag_after_days
        FROM strategic_memory
        WHERE status = 'active'
    """)
    for mem_id, content, last_confirmed, flag_days in \
            c.fetchall():
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
                    "message": (
                        f"Strategic memory "
                        f"({days_old} days old) "
                        f"— still valid? "
                        f"'{content[:80]}...'"
                    )
                })

    c.execute("""
        SELECT id, content, last_updated, flag_after_days
        FROM operational_memory
        WHERE status = 'active'
    """)
    for mem_id, content, last_updated, flag_days in \
            c.fetchall():
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


# ============================================================
# INITIALISE ON IMPORT
# ============================================================

init_db()