# ============================================================
# state.py — Shared runtime state
# Owns all mutable state dicts so orchestrator.py and other
# modules can import them without circular dependencies.
# ============================================================

from collections import defaultdict
from app.core.config import SOUL_PATH

# ── Conversation state ───────────────────────────────────────
conversation_history: dict = {}
attached_files: defaultdict = defaultdict(list)

# ── Upload registry ──────────────────────────────────────────
# Maps file_id → metadata produced by POST /api/v1/upload. The chat
# WS handler reads from here to translate a file_id reference on an
# inbound message into an attached_files entry the orchestrator can
# consume. Entries persist in-process only; the on-disk file path
# survives restarts so refs can be re-resolved if we ever decide to
# rehydrate this map at startup.
uploaded_files: dict = {}

# ── Goal execution state ─────────────────────────────────────
pending_goals: dict = {}
execution_context: dict = {}
gate_pending: dict = {}

# ── Agent routing state ──────────────────────────────────────
thread_agent_pins: dict = {}

# ── Memory and consolidation state ──────────────────────────
_consolidation_cooldown: set = set()
stale_warned_this_session: bool = False

# ── Token tracking ───────────────────────────────────────────
_last_token_usage: dict = {"input": 0, "output": 0}

# ── Bot startup time ─────────────────────────────────────────
BOT_START_TIME = None

# ── Agent definitions ────────────────────────────────────────
# Populated at startup by the app lifespan handler
AGENT_DEFINITIONS: dict = {}

# ── System prompt ────────────────────────────────────────────
try:
    with open(SOUL_PATH, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT: str = f.read()
except Exception:
    SYSTEM_PROMPT: str = ""

# ── Langfuse observability client ───────────────────────────
# Set at startup if keys are present
_langfuse = None
