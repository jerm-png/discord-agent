# ============================================================
# config.py — Shared constants for bot.py and orchestrator.py
# ============================================================

import os

# ── Owner ─────────────────────────────────────────────────────
OWNER_ID = os.getenv("DISCORD_OWNER_ID", "")

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

# ── Channel configuration ────────────────────────────────────
CHANNEL_MEMORY_MODE = {
    "bot-commands":           "ephemeral",
    "sandbox":                "ephemeral",
    "chief-of-staff":         "global",
    "director-workspace":     "global",
    "planning":               "global",
    "contact-center":         "project",
    "gamification-dashboard": "project",
    "slack-intelligence":     "project",
    "health-tracking":        "project",
}

CHANNEL_PROJECT_TAG = {
    "contact-center":         "contact-center",
    "gamification-dashboard": "gamification-dashboard",
    "slack-intelligence":     "slack-intelligence",
    "health-tracking":        "health-tracking",
}

CHANNEL_IGNORED = {
    "rules-and-info",
    "bot-status",
    "bot-logs",
    "research-reports",
    "general-output",
}

THREADED_CHANNELS = {
    "chief-of-staff",
    "director-workspace",
    "planning",
    "contact-center",
    "gamification-dashboard",
    "health-tracking",
}

THREAD_ARCHIVE_DURATION = {
    "health-tracking":        1440,
    "chief-of-staff":         1440,
    "director-workspace":     1440,
    "planning":               1440,
    "contact-center":         4320,
    "gamification-dashboard": 4320,
    "slack-intelligence":     4320,
}

CHANNEL_TOOL_MODE = {
    "bot-commands":           "search_only",
    "sandbox":                "none",
    "chief-of-staff":         "full",
    "director-workspace":     "full",
    "planning":               "full",
    "contact-center":         "full",
    "gamification-dashboard": "full",
    "slack-intelligence":     "full",
    "health-tracking":        "full",
}

SEARCH_ONLY_TOOL_NAMES = {
    "web_search", "web_fetch", "query_memory", "search_codebase"
}

CODEBASE_SEARCH_EXCLUDED_CHANNELS = {
    "health-tracking",
    "chief-of-staff",
    "director-workspace",
}

CHANNEL_PURPOSE = {
    "bot-commands": (
        "General assistance channel. Open scope. "
        "All topics welcome including personal, "
        "workplace, and day-to-day situations."
    ),
    "chief-of-staff": (
        "Strategic layer. Long-term decisions, "
        "values, constraints, who the user is."
    ),
    "director-workspace": (
        "Private leadership workspace for a Director "
        "of Customer/Client Experience. Used for "
        "coaching and development tracking of four "
        "direct reports, sounding board conversations, "
        "team trend analysis, difficult people decisions, "
        "and leadership mentoring. Entity memory tracks "
        "individuals longitudinally across sessions. "
        "High-stakes decisions always gate before drafting."
    ),
    "planning": (
        "Strategic planning sessions and "
        "long-form thinking."
    ),
    "contact-center": (
        "Active project: 60-day contact center "
        "intelligence validation. Balto audit, "
        "Five9 pipeline, briefing format."
    ),
    "gamification-dashboard": (
        "Active project: frontline agent "
        "performance gamification dashboard build."
    ),
    "slack-intelligence": (
        "Future project: Slack channel analysis, "
        "common questions and obstacle surfacing."
    ),
    "sandbox": (
        "Testing only. Treat all messages as "
        "experiments, no real context assumed."
    ),
    "health-tracking": (
        "Fully private health tracking channel. "
        "Biomarker panel logging and trend analysis, "
        "peptide protocol tracking, direct-to-consumer "
        "panel recommendations, and health research. "
        "Context is completely isolated from all other channels. "
        "Treat all health information with discretion. "
        "Always recommend consulting a doctor for clinical "
        "decisions while providing thorough research-based guidance."
    ),
}

CHANNEL_AGENT_HINTS: dict = {
    "health-tracking":        "health-researcher",
    "gamification-dashboard": ["engineering-ai-engineer", "engineering-data-engineer"],
    "director-workspace":     "director-advisor",
    "chief-of-staff":         ["personal-productivity", "director-advisor"],
    "slack-intelligence":     "support-analytics-reporter",
    "contact-center":         "support-analytics-reporter",
}

# ── File processing ──────────────────────────────────────────
FILE_CONTENT_CHAR_LIMIT = 50_000
POPPLER_PATH = r"C:\poppler\poppler-25.12.0\Library\bin"
PDF_VISION_THRESHOLD = 50
PDF_VISION_MAX_PAGES = 3
