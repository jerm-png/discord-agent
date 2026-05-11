# ============================================================
# config.py — Shared constants for bot.py and orchestrator.py
# ============================================================

# ── Models ───────────────────────────────────────────────────
MAIN_MODEL = "claude-sonnet-4-6"
BACKGROUND_MODEL = "claude-haiku-4-5-20251001"

# ── Ollama ───────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:8b"

# ── Discord channels ─────────────────────────────────────────
LOG_CHANNEL = "bot-logs"
STATUS_CHANNEL = "bot-status"
COMMAND_CHANNEL = "bot-commands"

# ── Agentic loop limits ──────────────────────────────────────
MAX_TOOL_CALLS = 10
MAX_REASONING_ITERATIONS = 10
AGENT_INJECT_CHAR_LIMIT = 1500
GOAL_GATE_MODE = "smart"

# ── History summarization ────────────────────────────────────
HISTORY_RAW_WINDOW = 6
HISTORY_SUMMARY_ROLE = "user"

# ── Memory consolidation ─────────────────────────────────────
CONSOLIDATION_THRESHOLDS = {
    "strategic":       100,
    "operational":      50,
    "analytical":       75,
    "health_tracking": 150,
}
