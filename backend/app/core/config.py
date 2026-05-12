import os
from dotenv import load_dotenv
load_dotenv()

# ── Owner ─────────────────────────────────────────────────────
OWNER_ID = os.getenv("OWNER_ID", "")

# ── Models ───────────────────────────────────────────────────
MAIN_MODEL = "claude-sonnet-4-6"
BACKGROUND_MODEL = "claude-haiku-4-5-20251001"

# ── Ollama ───────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:8b"

# ── Database ─────────────────────────────────────────────────
DB_PATH = os.getenv(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "memory", "database.db")
)

CHROMA_PATH = os.getenv(
    "CHROMA_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "memory", "chroma_db")
)

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

# ── Channel / context configuration ─────────────────────────
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

CHANNEL_IGNORED: set = {
    "rules-and-info",
    "bot-status",
    "bot-logs",
    "research-reports",
    "general-output",
}

THREADED_CHANNELS: set = {
    "chief-of-staff",
    "director-workspace",
    "planning",
    "contact-center",
    "gamification-dashboard",
    "health-tracking",
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

SEARCH_ONLY_TOOL_NAMES: set = {
    "web_search", "web_fetch", "query_memory", "search_codebase"
}

CODEBASE_SEARCH_EXCLUDED_CHANNELS: set = {
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

# ── File processing ──────────────────────────────────────────
FILE_CONTENT_CHAR_LIMIT = 50_000
POPPLER_PATH = r"C:\poppler\poppler-25.12.0\Library\bin"
PDF_VISION_THRESHOLD = 50
PDF_VISION_MAX_PAGES = 3

# ── Paths ─────────────────────────────────────────────────────
SOUL_PATH = os.getenv(
    "SOUL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "SOUL.md")
)

AGENTS_PATH = os.getenv(
    "AGENTS_PATH",
    r"C:\Users\Jerm\.claude\agents"
)

AGENT_KEYWORDS_CACHE_PATH = os.getenv(
    "AGENT_KEYWORDS_CACHE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "memory", "agent_keywords_cache.json")
)
