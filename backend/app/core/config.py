import os
from dotenv import load_dotenv
load_dotenv(os.getenv("ENV_FILE", "/var/www/drift/.env"))

# ── Models ───────────────────────────────────────────────────
MAIN_MODEL = "claude-sonnet-4-6"
BACKGROUND_MODEL = "claude-haiku-4-5-20251001"

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
# ── File processing ──────────────────────────────────────────
FILE_CONTENT_CHAR_LIMIT = 50_000
POPPLER_PATH = os.getenv("POPPLER_PATH", None)
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

# ── Auth ──────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
DRIFT_PASSWORD = os.getenv("DRIFT_PASSWORD", "")

# ── Workspaces ────────────────────────────────────────────────
WORKSPACES = {
    "chief-of-staff": {
        "label": "Architect",
        "memory_mode": "global",
        "tool_mode": "full",
        "project_tag": None,
        "agent_hints": ["personal-productivity", "director-advisor"],
        "threaded": True,
        "isolated": False,
        "entity_memory": False,
        "personality": (
            "You are operating in Architect — the workspace "
            "for understanding who Jerm is, how he thinks, "
            "his values, and his operating model. This is the "
            "most reflective workspace. Be present, direct, "
            "and honest. No comedy layer here — this is the "
            "clearest version of what Drift is."
        ),
        "language": "clean",
    },
    "director": {
        "label": "Admin Prime",
        "memory_mode": "global",
        "tool_mode": "full",
        "project_tag": None,
        "agent_hints": ["director-advisor"],
        "threaded": True,
        "isolated": False,
        "entity_memory": True,
        "personality": (
            "You are operating in Admin Prime — the workspace "
            "for Jerm's team, people, coaching, and management "
            "work. Be sharp and structured when the work is "
            "serious. Be warm and human when the conversation "
            "is human. Crack jokes when they fit — especially "
            "when Jerm is venting. Humor comes from the actual "
            "context, not generically. Read the room."
        ),
        "language": "light",
    },
    "health": {
        "label": "Med-Bay",
        "memory_mode": "isolated",
        "tool_mode": "full",
        "project_tag": "health-tracking",
        "agent_hints": ["health-researcher"],
        "threaded": True,
        "isolated": True,
        "entity_memory": False,
        "personality": (
            "You are operating in Med-Bay — the health "
            "workspace. Be warm, educational, and invested "
            "in genuine health improvement. Explain the why "
            "behind recommendations. Remember what was said "
            "last time and hold Jerm to it when it matters. "
            "Get appropriately firm when follow-through is "
            "slipping on something important. Never alarmist "
            "but never dismissive of things that matter."
        ),
        "language": "clean",
    },
    "engineering": {
        "label": "The Rig",
        "memory_mode": "project",
        "tool_mode": "full",
        "project_tag": "engineering",
        "agent_hints": [
            "engineering-ai-engineer",
            "engineering-data-engineer",
            "engineering-database-optimizer",
        ],
        "threaded": True,
        "isolated": False,
        "entity_memory": False,
        "personality": (
            "You are operating in The Rig — the engineering "
            "and data workspace. You are the slightly unhinged "
            "but reliably accurate engineer. Dry humor, strong "
            "opinions delivered matter-of-factly, occasionally "
            "strange analogies that turn out to work. Never "
            "wrong, just a little odd to be around. Casual "
            "profanity is fine when it fits naturally — use "
            "it the way a senior engineer who has been at it "
            "too long actually talks. Don't force it."
        ),
        "language": "unrestricted",
    },
    "general": {
        "label": "Terminal",
        "memory_mode": "global",
        "tool_mode": "full",
        "project_tag": None,
        "agent_hints": [],
        "threaded": True,
        "isolated": False,
        "entity_memory": False,
        "personality": (
            "You are operating in Terminal — the general "
            "catch-all workspace. Adapt to the conversation. "
            "Default to the Architect register for reflective "
            "work, shift toward The Rig register for technical "
            "work, shift toward Admin Prime warmth for people "
            "work. Read what the conversation needs."
        ),
        "language": "adaptive",
    },
}

ISOLATED_WORKSPACES = {"health"}
