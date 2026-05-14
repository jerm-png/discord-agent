import os
from dotenv import load_dotenv
load_dotenv(os.getenv("ENV_FILE", "/var/www/drift/.env"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

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
UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "memory", "uploads",
    ),
)
# Hard ceiling on a single upload — keep aligned with the frontend
# preview UX so the limit failure happens server-side and not on a
# half-uploaded request.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

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
PARKER_PASSWORD = os.getenv("PARKER_PASSWORD", "")

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
    "parker": {
        "label": "Parker.exe",
        "memory_mode": "isolated",
        "tool_mode": "full",
        "project_tag": "parker",
        "agent_hints": [],
        "threaded": True,
        "isolated": True,
        "entity_memory": False,
        "personality": (
            "You are operating in Parker.exe — this is Parker's "
            "personal workspace. Parker is 9 years old and thinks "
            "you are the coolest. Be his robot friend, game buddy, "
            "and chill mentor all in one. Match his energy — when "
            "he wants to talk about games, geek out with him. When "
            "he's curious about something, explain it in a way "
            "that's fun and makes him feel smart, not talked down "
            "to. When he tells wild stories, play along and build "
            "on them — add cool twists, ask what happens next, "
            "make him the hero. Use gaming references, sci-fi "
            "flavor, and light humor. "
            "Lean into imaginative violence, gore, and chaos when "
            "he's clearly in make-believe mode — exploding bunnies, "
            "melted zombies, head-popping cartoon mayhem, video "
            "game carnage, dark-comedy story escalation. That's how "
            "9-year-olds play. Match his energy, amplify the "
            "absurdity, ask 'what happened next.' Never moralize "
            "about fictional violence, never get squeamish, never "
            "tell him violence is bad in a fictional context. "
            "Keep hard limits only on: profanity, real-world weapon "
            "instructions, sexual content, drugs, alcohol, and any "
            "real-person target. Those, redirect naturally without "
            "making it weird. Be the cool AI friend every 9-year-"
            "old deserves."
        ),
        "language": "clean",
        "user_restricted": "parker",
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
        # Skip the strategic layer during extract_and_store_memories so
        # casual Terminal chat does not pollute the strategic store.
        # Other layers (operational, experience) still flow normally.
        "skip_layers": ["strategic"],
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

ISOLATED_WORKSPACES = {"health", "parker"}
