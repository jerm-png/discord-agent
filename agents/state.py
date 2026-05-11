# ============================================================
# state.py — Shared runtime state
# Owns all mutable state dicts so both bot.py and
# orchestrator.py can import them without circular deps.
# ============================================================

from collections import defaultdict
import os

# ── Conversation state ───────────────────────────────────────
conversation_history: dict = {}
attached_files: defaultdict = defaultdict(list)

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
# Populated at startup by _load_agent_definitions()
AGENT_DEFINITIONS: dict = {}

# ── System prompt ────────────────────────────────────────────
# Loaded from SOUL.md at module import time so both
# bot.py and orchestrator.py see the real content immediately.
_soul_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "SOUL.md",
)
try:
    with open(_soul_path, "r", encoding="utf-8") as _f:
        SYSTEM_PROMPT: str = _f.read()
except Exception:
    SYSTEM_PROMPT: str = ""

# ── Discord bot client ───────────────────────────────────────
# Set in on_ready() after bot connects
bot = None

# ── Langfuse observability client ───────────────────────────
# Set at startup if keys are present
_langfuse = None
