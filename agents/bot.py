import asyncio
import base64
import discord
import io
import os
import shutil
import sys
import json
import tempfile
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime
from discord import app_commands
from dotenv import load_dotenv
from anthropic import Anthropic
from elevenlabs import ElevenLabs
import PyPDF2
import docx
from pdf2image import convert_from_bytes
from PIL import Image

# Add project root to path
project_root = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))
sys.path.insert(0, project_root)

from memory.memory_manager import (
    save_strategic_memory,
    save_operational_memory,
    save_analytical_memory,
    save_experience,
    get_relevant_memories,
    format_memory_for_prompt,
    increment_interaction_count,
    get_recent_experiences,
    get_handoff_memories,
    memory_stats,
    get_consolidation_candidates,
    is_task_completion,
    set_pending_reflection,
    get_pending_reflection,
    validate_memory,
    archive_memory,
    check_stale_memories,
    save_conversation_history,
    load_all_conversation_histories,
    MEMORY_ISOLATED_CHANNELS,
    log_conversation_turn,
    search_conversations,
    cleanup_old_conversation_log,
    backfill_conversation_log,
)

from tools.tool_definitions import (
    TOOL_DEFINITIONS,
    execute_tool,
    drain_escalation_queue,
)

from voice_input import transcribe_attachment

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    '.env'
))

client = Anthropic()

MAIN_MODEL = "claude-sonnet-4-6"
BACKGROUND_MODEL = "claude-haiku-4-5-20251001"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"

OWNER_ID = os.getenv("DISCORD_OWNER_ID", "")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")

COMMAND_CHANNEL = "bot-commands"
STATUS_CHANNEL = "bot-status"
LOG_CHANNEL = "bot-logs"

# ── CHANNEL MEMORY ROUTING ───────────────────────────────────
# "ephemeral" = respond but skip memory extraction and reflection
# "global"    = extract memories with no project tag
# "project"   = extract memories tagged to a specific project
# Channels absent from this map default to "ephemeral".
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

# Channels where each new conversation starts in a dedicated Discord thread.
# Bot creates a thread on the first message and responds inside it.
# Subsequent messages in that thread continue the same context.
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

# ── CHANNEL TOOL LOADING ─────────────────────────────────────
# "none"        = no tools sent (sandbox, unknown channels)
# "search_only" = web_search + query_memory only (bot-commands)
# "full"        = all tools (memory-active channels)
# Channels absent from this map default to "none".
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

SEARCH_ONLY_TOOL_NAMES = {"web_search", "query_memory"}

# ── CONSOLIDATION THRESHOLDS ──────────────────────────────────
# Auto-consolidation triggers when a layer's non-health count
# exceeds the layer threshold, or health-tracking memories
# across all layers exceed the health threshold.
CONSOLIDATION_THRESHOLDS = {
    "strategic":      100,
    "operational":     50,
    "analytical":      75,
    "health_tracking": 150,
}

# ── MEMORY ISOLATION ──────────────────────────────────────────
# Channels in MEMORY_ISOLATED_CHANNELS get bidirectional isolation:
# their memories never surface in other channels, and they never
# receive memories from other channels. Defined in memory_manager.py
# and imported here so bot logic can reference the same set.
# Current isolated channels: health-tracking

# ── CHANNEL PURPOSE DESCRIPTIONS ─────────────────────────────
# Injected into every user message so Claude knows what each
# channel is for and adjusts scope and focus accordingly.
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
        "Professional development, leadership "
        "thinking, contact center insights, "
        "career growth."
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

# Maximum tool calls per response to prevent runaway loops
MAX_TOOL_CALLS = 5

conversation_history = {}
attached_files: defaultdict = defaultdict(list)
BOT_START_TIME = None
_last_token_usage = {"input": 0, "output": 0}
stale_warned_this_session = False

CONFABULATION_TRIGGERS = (
    "you said", "you told me", "you mentioned", "did you say",
    "show me where", "you recommended", "you suggested",
    "you told", "you wrote", "you claimed",
)


def _is_confabulation_check(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in CONFABULATION_TRIGGERS)


# Goal mode state — keyed by user_id, cleared on restart
pending_goals: dict = {}
execution_context: dict = {}
gate_pending: dict = {}

# Gate frequency: "smart" | "always" | "minimal"
# smart   = gate when results are surprising, low quality, or last search before synthesis
# always  = gate after every web_search step and always before draft
# minimal = only gate before draft steps
GOAL_GATE_MODE = "smart"

# ── AGENT DEFINITIONS ──────────────────────────────────────────
# Agent .md files are loaded at startup from AGENTS_DIR.
# Keyword extraction uses the background model once, then caches to disk.
AGENTS_DIR = r"C:\Users\Jerm\.claude\agents"
AGENT_KEYWORDS_CACHE_PATH = os.path.join(
    project_root, "memory", "agent_keywords_cache.json"
)
AGENT_DEFINITIONS: dict = {}

# Channel → preferred agent slug(s).
# health-tracking is a hard rule (enforced in select_agent, not overridable by keywords).
# Lists are resolved by keyword matching; first valid entry is fallback.
CHANNEL_AGENT_HINTS: dict = {
    "health-tracking":        "health-researcher",
    "gamification-dashboard": ["engineering-ai-engineer", "engineering-data-engineer"],
    "director-workspace":     "director-advisor",
    "chief-of-staff":         ["personal-productivity", "director-advisor"],
    "slack-intelligence":     "support-analytics-reporter",
    "contact-center":         "support-analytics-reporter",
}

SUPPORTED_DOC_EXTENSIONS   = {".pdf", ".txt", ".md", ".csv", ".docx"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_EXTENSIONS = SUPPORTED_DOC_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS
IMAGE_MEDIA_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
FILE_CONTENT_CHAR_LIMIT = 50_000
POPPLER_PATH = r"C:\poppler\poppler-25.12.0\Library\bin"
PDF_VISION_THRESHOLD = 50   # chars — below this triggers vision fallback
PDF_VISION_MAX_PAGES = 3

with open(
    os.path.join(project_root, "SOUL.md"), "r", encoding="utf-8"
) as _f:
    SYSTEM_PROMPT = _f.read()

REFLECTION_PROMPT = """Review these completed task experiences and extract structured analytical insights.

Completed task experiences:
{experiences}

For each meaningful pattern you identify respond with this exact JSON format and no other text:
{{
    "insights": [
        {{
            "observation": "what factually happened",
            "reasoning": "why that approach was taken",
            "outcome": "whether it worked and how",
            "pattern": "the generalisable insight",
            "confidence": 0.7,
            "trigger_conditions": "when to apply this insight in future"
        }}
    ],
    "strategic_insights": [
        "any long term strategic observations worth storing"
    ],
    "summary": "one sentence summary of what was learned"
}}

Only include insights with genuine signal. Return empty arrays if nothing meaningful emerged.
Confidence should be between 0.0 and 1.0 based on how many times this pattern was observed."""

GOAL_PLANNER_SYSTEM_PROMPT = """You are a planning agent. Break down the following goal into 3-8 specific executable steps. Each step should be one of these types:
- web_search: search for specific information
- query_memory: check existing memory for context
- analyze: synthesize information gathered so far
- draft: write a structured output or report

For each step specify:
- step_number
- type (from list above)
- description (what to do)
- query (the specific search query or memory query if applicable)

Return ONLY a JSON array of steps, no other text."""

HANDOFF_SYSTEM_PROMPT = """You are generating a dense, structured handoff document from live memory snapshots.
Your output will be pasted directly into a new AI session as context. Write for an AI reader, not a human one.
Be maximally information-dense. No filler, no headers beyond what is specified, no pleasantries.

Structure your output exactly as follows:

## WHO I AM
Key facts about the user: role, working style, communication preferences, goals, constraints.

## WHAT IS ACTIVE
Current projects and tasks with status. What is in progress, what is blocked, what is next.

## WHAT I KNOW
Analytical patterns and crystallised skills worth carrying forward. Confidence-weighted.

## WHAT TO WATCH
Open review flags, unresolved uncertainties, things that need follow-up.

## RECENT CONTEXT
Brief summary of the last few completed tasks and what was learned from them.

Be specific. Use actual names, numbers, and project details from the memory data provided.
If a section has nothing meaningful to report, write one sentence saying so — do not omit the section."""

HELP_TEXT = """**PerMyLastBot — Commands**

`!help` — Show this message. Works in any channel.

`!memory` — Show what's stored in memory for the current channel context. Respects isolation — `#health-tracking` shows health memories only.

`!clear` — Wipe your conversation history for this session. Fixes context confusion without touching long-term memory. Works in any channel.

`!status` — System report: Ollama, FFmpeg, memory counts, uptime, last token usage. Works in any channel.

`!retry` — Regenerate a response to your last message through the full pipeline. Works in any channel.

`!remember <text>` — Save something directly to long-term memory. `#bot-commands` only.

`!handoff` — Generate a dense memory snapshot document for pasting into a new AI session. Works in any channel.

`!consolidate` — Manually trigger memory consolidation for the current channel scope. Groups similar memories, merges them via AI, archives originals. Respects isolation — `#health-tracking` only consolidates health memories.

`!goal [description]` — Decompose a goal into an approved step plan, then execute it. Also `!plan` and `!research`. Reply `!approve` to run, `!cancel` to abort, `!modify [changes]` to revise the plan before running. During execution: `!continue` resumes a paused gate, `!adjust [changes]` replans remaining steps, `!retry` retries a failed step, `!skip` skips it.

`!agent [slug] [message]` — Activate a specific specialist agent for one response. Example: `!agent health-researcher what peptides help with EBV reactivation`. Reverts to default after the response.

`!agents` — List all available specialist agents with their slugs and descriptions.

`!search [query]` — Full-text search of your past conversations. Scans the permanent archive and summarises matching exchanges. Respects channel isolation — `#health-tracking` searches only health conversations."""


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.voice_states = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def tag_owner() -> str:
    """Returns a Discord mention string for the owner, or empty string if unset."""
    return f"<@{OWNER_ID}> " if OWNER_ID else ""


def _saveable_history(history: list) -> list:
    """Returns the last 50 plain-string messages after bidirectional tool-block
    validation. Strips orphaned tool_use/tool_result blocks before filtering
    so corrupted exchanges are never written to SQLite."""
    validated, _ = strip_orphaned_tool_results(history)
    return [
        m for m in validated
        if isinstance(m.get("content"), str)
    ][-50:]


def check_ollama_health() -> None:
    """Pings Ollama's base URL to confirm it's running at startup."""
    target = "http://localhost:11434"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(target), timeout=3
        ):
            pass
        print(f"[Ollama] {OLLAMA_MODEL} reachable at {target}")
    except Exception:
        print(
            f"[Ollama] WARNING: not reachable at {target} — "
            f"background tasks will fall back to {BACKGROUND_MODEL}"
        )


def check_ffmpeg() -> None:
    """Checks whether FFmpeg is on the system PATH at startup."""
    path = shutil.which("ffmpeg")
    if path:
        print(f"[FFmpeg] Found at {path}")
    else:
        print(
            "[FFmpeg] WARNING: ffmpeg not found on PATH — "
            "TTS voice output will silently fail until FFmpeg "
            "is installed and added to PATH"
        )


def strip_orphaned_tool_results(history: list) -> tuple:
    """
    Removes orphaned tool blocks from conversation history in both directions.

    Pass 1 — tool_result without matching tool_use: strips tool_result blocks
    from a user message when the preceding assistant message has no tool_use
    block with the same tool_use_id.

    Pass 2 — tool_use without matching tool_result: strips tool_use blocks
    from an assistant message when the immediately following user message has
    no tool_result block with the matching tool_use_id. If an assistant message
    loses all its content blocks it is removed entirely.

    Handles both SDK objects (.type / .id attributes) and plain dicts.
    Returns (cleaned_history, count_stripped).
    """
    stripped = 0

    def _block_type(block):
        if isinstance(block, dict):
            return block.get("type")
        return getattr(block, "type", None)

    def _block_id(block):
        if isinstance(block, dict):
            return block.get("id")
        return getattr(block, "id", None)

    def _tool_use_id(block):
        if isinstance(block, dict):
            return block.get("tool_use_id")
        return getattr(block, "tool_use_id", None)

    # ── Pass 1: strip orphaned tool_results (user message direction) ──────────
    pass1 = []
    for msg in history:
        content = msg.get("content")
        role = msg.get("role")

        if role == "user" and isinstance(content, list):
            valid_ids = set()
            if pass1:
                prev = pass1[-1]
                if prev.get("role") == "assistant":
                    prev_content = prev.get("content", [])
                    if isinstance(prev_content, list):
                        for block in prev_content:
                            if _block_type(block) == "tool_use":
                                valid_ids.add(_block_id(block))

            surviving = []
            for block in content:
                if _block_type(block) == "tool_result":
                    if _tool_use_id(block) in valid_ids:
                        surviving.append(block)
                    else:
                        stripped += 1
                else:
                    surviving.append(block)

            if surviving:
                pass1.append({**msg, "content": surviving})
            # else: entire message was orphaned tool_results — drop it
        else:
            pass1.append(msg)

    # ── Pass 2: strip orphaned tool_use blocks (assistant message direction) ───
    pass2 = []
    for i, msg in enumerate(pass1):
        content = msg.get("content")
        role = msg.get("role")

        if role == "assistant" and isinstance(content, list):
            # Collect tool_result IDs from the immediately following user message
            valid_result_ids = set()
            if i + 1 < len(pass1):
                next_msg = pass1[i + 1]
                if next_msg.get("role") == "user":
                    next_content = next_msg.get("content", [])
                    if isinstance(next_content, list):
                        for block in next_content:
                            if _block_type(block) == "tool_result":
                                valid_result_ids.add(_tool_use_id(block))

            surviving = []
            for block in content:
                if _block_type(block) == "tool_use":
                    if _block_id(block) in valid_result_ids:
                        surviving.append(block)
                    else:
                        stripped += 1
                else:
                    surviving.append(block)

            if surviving:
                pass2.append({**msg, "content": surviving})
            # else: all blocks stripped — drop the assistant message entirely
        else:
            pass2.append(msg)

    return pass2, stripped


def _extract_original_message(full_content: str) -> str:
    """Extracts the user's original message from the context-prefixed stored string."""
    if "Current message: " in full_content:
        return full_content.split("Current message: ", 1)[1].strip()
    if "[Channel:" in full_content:
        after = full_content.split("[Channel:", 1)[1]
        lines = after.split("\n", 1)
        return lines[1].strip() if len(lines) > 1 else ""
    return full_content


def _process_attachment(filename: str, file_bytes: bytes) -> dict:
    """
    Extracts content from a file attachment in memory.
    Documents return text_content. Images return base64_data + media_type.
    Raises on parse failure so the caller can post a user-facing error.
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        return {
            "filename": filename,
            "content_type": "image",
            "media_type": IMAGE_MEDIA_TYPES[ext],
            "base64_data": base64.standard_b64encode(file_bytes).decode("utf-8"),
        }

    if ext == ".pdf":
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        text_content = "\n\n".join(p for p in pages if p.strip())

        if len(text_content.strip()) < PDF_VISION_THRESHOLD:
            # Image-based PDF — fall back to vision
            pil_pages = convert_from_bytes(
                file_bytes,
                poppler_path=POPPLER_PATH,
            )[:PDF_VISION_MAX_PAGES]
            vision_pages = []
            for pil_page in pil_pages:
                buf = io.BytesIO()
                pil_page.save(buf, format="PNG")
                vision_pages.append({
                    "media_type": "image/png",
                    "base64_data": base64.standard_b64encode(
                        buf.getvalue()
                    ).decode("utf-8"),
                })
            return {
                "filename": filename,
                "content_type": "pdf_vision",
                "pages": vision_pages,
            }
    elif ext == ".docx":
        doc = docx.Document(io.BytesIO(file_bytes))
        text_content = "\n".join(
            p.text for p in doc.paragraphs if p.text.strip()
        )
    else:  # .txt, .md, .csv
        text_content = file_bytes.decode("utf-8")

    return {
        "filename": filename,
        "content_type": "document",
        "text_content": text_content,
    }


def _check_ollama_status() -> tuple:
    """Returns (is_reachable, model_name) for use in !status."""
    try:
        urllib.request.urlopen(
            "http://localhost:11434", timeout=3
        )
        return True, OLLAMA_MODEL
    except Exception:
        return False, OLLAMA_MODEL


async def call_background_model(prompt: str) -> str:
    """Tries Ollama first, falls back to Anthropic Haiku if unavailable."""
    def _call_ollama():
        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["response"]

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _call_ollama)
    except Exception:
        response = client.messages.create(
            model=BACKGROUND_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()


async def generate_thread_name(message_text: str, channel_name: str) -> str:
    """Generates a 4-6 word thread title via the background model (5 s timeout)."""
    preview = message_text[:30].strip()
    fallback = f"{preview}..." if preview else channel_name
    prompt = (
        "Create a short 4-6 word thread title that captures the topic of this message. "
        "Be specific about the actual subject matter. "
        "Return only the title, no punctuation, no quotes, no explanation.\n\n"
        f"Message: {message_text[:200]}"
    )
    try:
        name = await asyncio.wait_for(call_background_model(prompt), timeout=5.0)
        name = name.strip().strip("\"'").strip()
        if name:
            print(f"[Thread] name='{name[:100]}' source=ai")
            return name[:100]
        print(f"[Thread] name='{fallback}' source=fallback")
        return fallback
    except Exception:
        print(f"[Thread] name='{fallback}' source=fallback")
        return fallback


async def _resolve_response_channel(message, channel_name: str, text_hint: str = "") -> tuple:
    """
    Returns (response_channel, context_id) for a message.

    For messages in THREADED_CHANNELS that are NOT already in a thread:
    creates a new Discord thread on the message, posts 'Replied in thread →'
    in the main channel, and returns the thread. Falls back to the main
    channel if thread creation fails.

    For all other cases (already in a thread, or not a THREADED_CHANNEL):
    returns the message's current channel unchanged.
    """
    # Already in a thread — keep going there
    if isinstance(message.channel, discord.Thread):
        return message.channel, message.channel.id

    # Not a channel that uses threads
    if channel_name not in THREADED_CHANNELS:
        return message.channel, message.channel.id

    print(f"[Thread] channel={channel_name} threaded={channel_name in THREADED_CHANNELS}")
    # Create a thread on this message
    content = text_hint or message.content or ""
    thread_name = await generate_thread_name(content, channel_name)
    archive_duration = THREAD_ARCHIVE_DURATION.get(channel_name, 1440)
    try:
        thread = await message.create_thread(
            name=thread_name,
            auto_archive_duration=archive_duration,
        )
        await message.channel.send("Replied in thread →")
        await send_to_channel(
            message.guild, LOG_CHANNEL,
            f"Thread created | #{channel_name} | \"{thread_name}\" | ID: {thread.id}"
        )
        return thread, thread.id
    except Exception as e:
        await send_to_channel(
            message.guild, LOG_CHANNEL,
            f"Thread creation failed | #{channel_name} | {str(e)}"
        )
        await message.channel.send(
            "(Thread creation failed — responding here instead)"
        )
        return message.channel, message.channel.id


async def send_to_channel(guild, channel_name, message):
    """Finds a channel by name and sends a message to it."""
    channel = discord.utils.get(
        guild.channels, name=channel_name
    )
    if channel:
        await channel.send(message)


async def send_long_message(channel, message):
    """Splits messages exceeding Discord's 2000 char limit."""
    if len(message) <= 2000:
        await channel.send(message)
    else:
        for i in range(0, len(message), 2000):
            await channel.send(message[i:i+2000])


async def post_status(guild, message: str, memory_mode: str = "global") -> None:
    """Posts a one-line status to STATUS_CHANNEL. Skips ephemeral channels."""
    if memory_mode == "ephemeral":
        return
    await send_to_channel(guild, STATUS_CHANNEL, message)


async def process_tool_calls(response, guild, tool_call_count, channel_name=None, memory_mode: str = "global"):
    """
    Handles tool calls from Claude.
    Executes the requested tool and returns the result.
    Enforces the maximum tool call limit.
    """
    tool_results = []

    for block in response.content:
        if block.type == "tool_use":

            # Enforce max tool calls limit
            if tool_call_count >= MAX_TOOL_CALLS:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        "Tool call limit reached. "
                        "Please summarise findings so far."
                    )
                })
                continue

            tool_name = block.name
            tool_inputs = block.input

            # Log the tool call
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"Tool called: {tool_name} | "
                f"Inputs: {json.dumps(tool_inputs)[:200]}"
            )

            # Status before execution — web search gets a dedicated message
            if tool_name == "web_search":
                await post_status(guild, "🔍 Searching the web...", memory_mode)
            else:
                await post_status(guild, f"🔧 Using tool: {tool_name}", memory_mode)

            # Execute the tool off the event loop thread — pass channel_name
            # so query_memory respects isolation for health-tracking and similar channels
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, execute_tool, tool_name, tool_inputs, channel_name
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result)
            })

            tool_call_count += 1

    return tool_results, tool_call_count


async def run_reflection_loop(guild, experiences):
    """
    Runs when a task completion is detected.
    Extracts structured six part analytical insights
    from completed task experiences.
    """
    try:
        await send_to_channel(
            guild,
            STATUS_CHANNEL,
            "Running reflection loop..."
        )

        if not experiences:
            await send_to_channel(
                guild,
                STATUS_CHANNEL,
                "Reflection skipped — no completed experiences yet."
            )
            return

        exp_text = "\n\n".join([
            f"Request: {e['request']}\n"
            f"Approach: {e['approach']}\n"
            f"Outcome: {e['outcome']}\n"
            f"Lesson: {e['lesson']}"
            for e in experiences
        ])

        raw = await call_background_model(
            REFLECTION_PROMPT.format(experiences=exp_text)
        )
        clean = raw.replace(
            "```json", ""
        ).replace("```", "").strip()
        reflection = json.loads(clean)

        stored_analytical = 0
        stored_strategic = 0

        for insight in reflection.get("insights", []):
            if insight.get("pattern"):
                save_analytical_memory(
                    pattern=insight.get("pattern", ""),
                    observation=insight.get("observation", ""),
                    reasoning=insight.get("reasoning", ""),
                    outcome=insight.get("outcome", ""),
                    confidence=float(
                        insight.get("confidence", 0.5)
                    ),
                    trigger_conditions=insight.get(
                        "trigger_conditions", ""
                    ),
                    pattern_type="task_reflection"
                )
                stored_analytical += 1

        for insight in reflection.get("strategic_insights", []):
            if insight:
                save_strategic_memory(
                    content=insight,
                    category="reflection",
                    confidence=0.7,
                    source="reflection_loop"
                )
                stored_strategic += 1

        set_pending_reflection(False)

        if stored_analytical or stored_strategic:
            await send_to_channel(
                guild,
                STATUS_CHANNEL,
                f"{tag_owner()}Reflection complete — "
                f"{stored_analytical} analytical and "
                f"{stored_strategic} strategic insights stored."
            )
        else:
            await send_to_channel(
                guild,
                STATUS_CHANNEL,
                "Reflection complete — no new insights stored."
            )

        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"Reflection loop | "
            f"Summary: {reflection.get('summary', 'None')}"
        )

    except Exception as e:
        set_pending_reflection(False)
        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"Reflection loop error: {str(e)}"
        )


async def extract_and_store_memories(
    user_message, bot_reply, guild, task_completed,
    project_tag=None, channel_name="unknown", memory_mode="global"
):
    """
    Extracts anything worth storing in long term memory
    after each interaction.
    """
    try:
        if channel_name in MEMORY_ISOLATED_CHANNELS:
            scope_instruction = (
                "\nSCOPE RESTRICTION: This exchange is from the "
                "private health tracking channel. Only extract "
                "health-related insights — biomarker trends, "
                "protocol effects, supplement or peptide patterns, "
                "and health research findings. Never extract work, "
                "business, career, or personal non-health context. "
                "If nothing health-specific is worth storing, "
                "return empty arrays."
            )
        else:
            scope_instruction = ""

        extraction_prompt = f"""Review this exchange and identify anything worth storing in long term memory.

User said: {user_message}
Assistant replied: {bot_reply[:500]}
Task completed: {task_completed}{scope_instruction}

Respond in this exact JSON format with no other text:
{{
    "strategic": ["item worth storing long term"],
    "operational": ["active task or project to track"],
    "experience": {{
        "request_summary": "brief summary of what was asked",
        "approach_used": "how it was handled",
        "outcome": "positive/neutral/negative",
        "lesson": "what to remember for next time"
    }}
}}

Only include items genuinely worth remembering long term.
Return empty arrays if nothing meaningful to store."""

        raw = await call_background_model(extraction_prompt)
        clean = raw.replace(
            "```json", ""
        ).replace("```", "").strip()
        extracted = json.loads(clean)

        strategic_count = 0
        operational_count = 0

        for item in extracted.get("strategic", []):
            if item:
                save_strategic_memory(
                    content=item,
                    category="conversation",
                    source="auto_extraction",
                    project_tag=project_tag
                )
                strategic_count += 1

        for item in extracted.get("operational", []):
            if item:
                save_operational_memory(
                    content=item,
                    project_name="general",
                    project_tag=project_tag
                )
                operational_count += 1

        exp = extracted.get("experience", {})
        if exp:
            save_experience(
                request_summary=exp.get(
                    "request_summary", ""
                ),
                approach_used=exp.get("approach_used", ""),
                outcome=exp.get("outcome", "neutral"),
                lesson=exp.get("lesson", ""),
                layers_used=list(extracted.keys()),
                task_completed=task_completed,
                project_tag=project_tag
            )

        tag_str = f" | Project: {project_tag}" if project_tag else ""
        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"Memory extraction complete | "
            f"Channel: #{channel_name} | "
            f"Mode: {memory_mode}{tag_str} | "
            f"Strategic: {strategic_count} | "
            f"Operational: {operational_count} | "
            f"Experience: {'yes' if exp else 'no'}"
        )

    except Exception as e:
        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"Memory extraction error | "
            f"Channel: #{channel_name} | "
            f"Mode: {memory_mode} | "
            f"{str(e)}"
        )


_CONSOLIDATION_PROMPT = (
    "You are consolidating these related memories into a single dense "
    "entry. Preserve all specific facts, dates, numbers, and named "
    "entities. Remove redundancy. Output a single memory entry that "
    "contains everything important from all inputs. Be specific and "
    "dense — no filler. Output only the consolidated memory text, "
    "nothing else.\n\n{cluster_text}"
)


def _should_consolidate(stats: dict, channel_name: str) -> bool:
    """Returns True if any layer exceeds its consolidation threshold."""
    is_isolated = channel_name in MEMORY_ISOLATED_CHANNELS
    for layer in ("strategic", "operational", "analytical"):
        layer_stats = stats.get(layer, {})
        if is_isolated:
            count = layer_stats.get("by_tag", {}).get(channel_name, 0)
            if count > CONSOLIDATION_THRESHOLDS["health_tracking"]:
                return True
        else:
            total = layer_stats.get("total", 0)
            health_count = sum(
                v for k, v in layer_stats.get("by_tag", {}).items()
                if k in MEMORY_ISOLATED_CHANNELS
            )
            if total - health_count > CONSOLIDATION_THRESHOLDS[layer]:
                return True
    return False


async def _consolidate_layer(
    guild, layer: str, channel_name: str, trigger: str
) -> dict:
    """
    Fetches consolidation candidates for one layer, merges each cluster
    via the background model, saves the consolidated entry, and archives
    the originals. Returns {"merged": N, "archived": X, "skipped": Y}.
    """
    loop = asyncio.get_running_loop()
    is_isolated = channel_name in MEMORY_ISOLATED_CHANNELS

    before_stats = memory_stats()
    before_count = (
        before_stats.get(layer, {}).get("by_tag", {}).get(channel_name, 0)
        if is_isolated
        else before_stats.get(layer, {}).get("total", 0)
    )

    candidates = await loop.run_in_executor(
        None, get_consolidation_candidates, layer, channel_name
    )

    merged = archived = skipped = 0

    for cluster in candidates:
        cluster_text = "\n\n".join(f"- {m['content']}" for m in cluster)
        prompt = _CONSOLIDATION_PROMPT.format(cluster_text=cluster_text)

        try:
            consolidated_text = (
                await call_background_model(prompt)
            ).strip()
        except Exception as e:
            skipped += 1
            await send_to_channel(
                guild, LOG_CHANNEL,
                f"Memory consolidation | Cluster skipped — model error "
                f"| Layer: {layer} | {str(e)}"
            )
            continue

        if not consolidated_text:
            skipped += 1
            await send_to_channel(
                guild, LOG_CHANNEL,
                f"Memory consolidation | Cluster skipped — empty output "
                f"| Layer: {layer}"
            )
            continue

        tags = {m["project_tag"] for m in cluster}
        consolidated_tag = next(iter(tags)) if len(tags) == 1 else None
        avg_conf = sum(m["confidence"] for m in cluster) / len(cluster)

        try:
            if layer == "strategic":
                save_strategic_memory(
                    content=consolidated_text,
                    category="consolidation",
                    confidence=avg_conf,
                    source="consolidation",
                    project_tag=consolidated_tag,
                )
            elif layer == "operational":
                save_operational_memory(
                    content=consolidated_text,
                    project_name="consolidation",
                    project_tag=consolidated_tag,
                )
            elif layer == "analytical":
                save_analytical_memory(
                    pattern=consolidated_text,
                    confidence=avg_conf,
                    pattern_type="consolidation",
                    project_tag=consolidated_tag,
                )
        except Exception as e:
            skipped += 1
            await send_to_channel(
                guild, LOG_CHANNEL,
                f"Memory consolidation | Save failed | "
                f"Layer: {layer} | {str(e)}"
            )
            continue

        archived_count = sum(
            1 for m in cluster
            if archive_memory(layer, m["id"], "consolidated")
        )
        merged += 1
        archived += archived_count

    after_count = before_count - archived + merged
    await send_to_channel(
        guild, LOG_CHANNEL,
        f"Memory consolidation | Layer: {layer} | "
        f"Before: {before_count} | After: {after_count} | "
        f"Archived: {archived} | Trigger: {trigger}"
    )

    return {"merged": merged, "archived": archived, "skipped": skipped}


async def consolidate_all_layers(
    guild, channel_name: str = None, trigger: str = "auto"
) -> dict:
    """
    Consolidates all three memory layers. Used by auto-trigger and
    exposed publicly so tests and future callers have a single entry point.
    Returns {"merged": N, "archived": X, "skipped": Y}.
    """
    totals = {"merged": 0, "archived": 0, "skipped": 0}
    for layer in ("strategic", "operational", "analytical"):
        result = await _consolidate_layer(guild, layer, channel_name, trigger)
        for k in totals:
            totals[k] += result[k]
    return totals


async def run_consolidate_command(channel, guild, channel_name):
    """Handles the !consolidate command — posts per-layer progress."""
    totals = {"merged": 0, "archived": 0, "skipped": 0}
    for layer in ("strategic", "operational", "analytical"):
        await channel.send(f"🧠 Consolidating {layer} layer...")
        result = await _consolidate_layer(guild, layer, channel_name, "manual")
        for k in totals:
            totals[k] += result[k]

    await channel.send(
        f"✅ Consolidation complete — "
        f"{totals['merged']} memories merged into entries, "
        f"{totals['archived']} archived"
        + (
            f", {totals['skipped']} cluster(s) skipped"
            if totals["skipped"] else ""
        )
    )


def _parse_goal_trigger(user_message: str):
    """
    Returns (trigger_word, goal_text) if the message starts with a goal
    trigger phrase (goal/plan/research), otherwise None.
    Called after the leading '!' has already been stripped.
    """
    lower = user_message.lower()
    for trigger in ("goal ", "plan ", "research "):
        if lower.startswith(trigger):
            goal_text = user_message[len(trigger):].strip()
            if goal_text:
                return (trigger.strip(), goal_text)
    return None


def _format_plan(goal: str, steps: list) -> str:
    lines = [f"📋 Here's my plan for: **{goal}**\n"]
    for step in steps:
        num = step.get("step_number", "?")
        stype = step.get("type", "unknown")
        desc = step.get("description", "")
        lines.append(f"Step {num} ({stype}): {desc}")
    lines.append(
        "\nReply `!approve` to execute, `!cancel` to abort, "
        "or `!modify [changes]` to adjust the plan."
    )
    return "\n".join(lines)


def _format_execution_context(findings: list) -> str:
    if not findings:
        return "No information gathered yet."
    parts = [
        f"[Step {f['step']} — {f['type']}]\n{f['content']}"
        for f in findings
    ]
    return "\n\n---\n\n".join(parts)


def _is_last_search_before_synthesis(steps: list, current_idx: int) -> bool:
    """True if there are no further web_search steps before the next analyze/draft."""
    for step in steps[current_idx + 1:]:
        t = step.get("type")
        if t == "web_search":
            return False
        if t in ("analyze", "draft"):
            return True
    return False


def _is_low_quality_result(result_str: str) -> bool:
    """True if the search result is empty, very short, or flagged as unavailable."""
    if not result_str or len(result_str.strip()) < 100:
        return True
    lower = result_str.lower()
    return "no results found" in lower or "web search unavailable" in lower


async def _search_changes_direction(goal: str, result_str: str) -> bool:
    """
    Asks the background model whether search results significantly change the
    research direction. Returns True if the answer is yes.
    """
    prompt = (
        f"Goal: {goal}\n\n"
        f"Search results:\n{result_str[:800]}\n\n"
        "Do these results significantly change the direction of this research, "
        "revealing that the original assumption was wrong or that a fundamentally "
        "different approach is needed? Answer with a single word: yes or no."
    )
    try:
        answer = await call_background_model(prompt)
        return answer.strip().lower().startswith("yes")
    except Exception:
        return False


async def _summarize_search_results(goal: str, result_str: str) -> str:
    """Returns a 2-3 sentence summary of search results for a gate message."""
    prompt = (
        f"Goal: {goal}\n\n"
        f"Search results:\n{result_str[:1200]}\n\n"
        "Summarize the key findings in 2-3 sentences. Be specific and direct."
    )
    try:
        return (await call_background_model(prompt)).strip()
    except Exception:
        return result_str[:300]


async def run_goal_planning(
    goal_text: str, user_id: str, author_display_name: str,
    guild, channel, memory_mode: str, project_tag
):
    """
    Calls the planner model to decompose a goal into steps, validates
    the plan, stores it in pending_goals, and posts it for approval.
    """
    try:
        response = client.messages.create(
            model=MAIN_MODEL,
            max_tokens=1024,
            system=GOAL_PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": goal_text}]
        )
        raw = response.content[0].text.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        steps = json.loads(clean)
    except Exception as e:
        await channel.send(
            f"Failed to generate a plan: {str(e)[:200]}\n"
            "Try rephrasing your goal."
        )
        return

    if not isinstance(steps, list) or not steps:
        await channel.send(
            "I couldn't generate a valid plan for that goal. "
            "Please try again with more detail."
        )
        return

    if len(steps) > 8:
        steps = steps[:8]
        await channel.send("⚠️ Plan trimmed to 8 steps (maximum allowed).")

    web_search_steps = sum(
        1 for s in steps if s.get("type") == "web_search"
    )
    if web_search_steps > 5:
        await channel.send(
            f"⚠️ Plan has {web_search_steps} web search steps — "
            "excess searches will be skipped during execution (max 5)."
        )

    pending_goals[user_id] = {
        "goal": goal_text,
        "steps": steps,
        "channel": channel,
        "guild": guild,
        "channel_name": channel.name,
        "memory_mode": memory_mode,
        "project_tag": project_tag,
        "status": "awaiting_approval",
        "current_step": 0,
        "web_search_count": 0,
    }
    execution_context.pop(user_id, None)

    await send_long_message(channel, _format_plan(goal_text, steps))
    await send_to_channel(
        guild, LOG_CHANNEL,
        f"Goal plan generated | User: {author_display_name} | "
        f"Steps: {len(steps)} | Goal: {goal_text[:100]}"
    )


async def run_goal_modification(
    changes: str, user_id: str, author_display_name: str,
    guild, channel, memory_mode: str, project_tag
):
    """Replans a pending goal based on the user's modification request."""
    pg = pending_goals.get(user_id)
    if not pg:
        await channel.send("No pending goal to modify.")
        return

    current_plan = json.dumps(pg["steps"], indent=2)
    mod_prompt = (
        f"Current plan:\n{current_plan}\n\n"
        f"Modification request: {changes}\n\n"
        "Update the plan accordingly. Return ONLY the updated "
        "JSON array of steps, no other text."
    )

    try:
        response = client.messages.create(
            model=MAIN_MODEL,
            max_tokens=1024,
            system=GOAL_PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mod_prompt}]
        )
        raw = response.content[0].text.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        steps = json.loads(clean)
    except Exception as e:
        await channel.send(f"Failed to modify the plan: {str(e)[:200]}")
        return

    if not isinstance(steps, list) or not steps:
        await channel.send(
            "I couldn't generate a valid revised plan. "
            "Try a different modification request."
        )
        return

    if len(steps) > 8:
        steps = steps[:8]

    pg["steps"] = steps
    pg["status"] = "awaiting_approval"
    pg["current_step"] = 0

    await send_long_message(channel, _format_plan(pg["goal"], steps))


async def execute_goal(
    user_id: str, author_display_name: str, skip_gate_for_step: int = -1
):
    """
    Executes an approved goal plan step by step as a background task.

    Pauses at gate conditions and stores state in gate_pending so the user
    can respond with !continue, !adjust, !retry, or !skip. Gates:
      - DRAFT GATE: always pause before any draft step (unless resuming)
      - RESEARCH GATE: pause after web_search when mode requires it
      - STEP FAILURE GATE: pause on any step exception with retry option

    skip_gate_for_step: when resuming after a draft gate, pass the step
    index so the draft gate is not re-triggered for that step.
    """
    pg = pending_goals.get(user_id)
    if not pg:
        return

    channel = pg["channel"]
    guild = pg["guild"]
    steps = pg["steps"]
    goal = pg["goal"]
    channel_name = pg["channel_name"]
    memory_mode = pg["memory_mode"]
    project_tag = pg["project_tag"]
    start_step = pg.get("current_step", 0)
    total = len(steps)

    if user_id not in execution_context:
        execution_context[user_id] = []

    loop = asyncio.get_running_loop()
    final_output = ""

    try:
        async with channel.typing():
            for i in range(start_step, total):
                # Cancellation / external-status check between steps
                if user_id not in pending_goals:
                    return
                pg = pending_goals[user_id]
                if pg.get("status") != "executing":
                    return

                step = steps[i]
                step_num = step.get("step_number", i + 1)
                step_type = step.get("type", "analyze")
                step_desc = step.get("description", "")
                step_query = step.get("query", step_desc)

                # ── DRAFT GATE: always pause before draft steps ──────────────
                if step_type == "draft" and i != skip_gate_for_step:
                    findings = execution_context.get(user_id, [])
                    bullets = "\n".join(
                        f"• Step {f['step']} ({f['type']}): "
                        f"{f['content'][:120].rstrip()}..."
                        for f in findings
                    ) or "No findings gathered yet."

                    pg["status"] = "gated"
                    pg["current_step"] = i
                    gate_pending[user_id] = {
                        "type": "draft_gate",
                        "step_index": i,
                        "step_num": step_num,
                        "author_display_name": author_display_name,
                    }
                    await send_long_message(channel, (
                        f"📝 Ready to draft the final output based on:\n"
                        f"{bullets}\n\n"
                        "Reply `!continue` to generate the draft "
                        "or `!cancel` to abort."
                    ))
                    return

                await post_status(
                    guild,
                    f"⚙️ Step {step_num}/{total}: {step_desc}...",
                    memory_mode
                )

                try:
                    if step_type == "web_search":
                        search_count = pg.get("web_search_count", 0)
                        if search_count >= 5:
                            execution_context[user_id].append({
                                "step": step_num, "type": step_type,
                                "content": "[Skipped — web search limit of 5 reached]"
                            })
                            continue

                        result = await loop.run_in_executor(
                            None, execute_tool,
                            "web_search",
                            {"query": step_query, "max_results": 3},
                            channel_name
                        )
                        result_str = str(result)
                        execution_context[user_id].append({
                            "step": step_num, "type": "web_search",
                            "content": result_str
                        })
                        pg["web_search_count"] = search_count + 1

                        # ── RESEARCH GATE ────────────────────────────────────
                        should_gate = False
                        if GOAL_GATE_MODE == "always":
                            should_gate = True
                        elif GOAL_GATE_MODE == "smart":
                            low_quality = _is_low_quality_result(result_str)
                            last_search = _is_last_search_before_synthesis(
                                steps, i
                            )
                            direction_change = (
                                await _search_changes_direction(goal, result_str)
                                if not low_quality else False
                            )
                            should_gate = low_quality or last_search or direction_change
                        # "minimal": no research gate

                        if should_gate:
                            summary = await _summarize_search_results(
                                goal, result_str
                            )
                            remaining_lines = "\n".join(
                                f"• Step {s.get('step_number', '?')} "
                                f"({s.get('type', '?')}): "
                                f"{s.get('description', '')}"
                                for s in steps[i + 1:]
                            ) or "No remaining steps."

                            pg["status"] = "gated"
                            pg["current_step"] = i + 1
                            gate_pending[user_id] = {
                                "type": "research_gate",
                                "step_index": i + 1,
                                "step_num": step_num,
                                "author_display_name": author_display_name,
                            }
                            await send_long_message(channel, (
                                f"🔍 Step {step_num} complete — "
                                f"here's what I found:\n{summary}\n\n"
                                f"Remaining steps:\n{remaining_lines}\n\n"
                                "Does this look right? Reply:\n"
                                "`!continue` — proceed with remaining steps\n"
                                "`!adjust [changes]` — modify the remaining plan\n"
                                "`!cancel` — abort the goal"
                            ))
                            return

                    elif step_type == "query_memory":
                        memories = await loop.run_in_executor(
                            None,
                            lambda q=step_query: get_relevant_memories(
                                q, channel_name=channel_name
                            )
                        )
                        mem_text = format_memory_for_prompt(memories)
                        execution_context[user_id].append({
                            "step": step_num, "type": "query_memory",
                            "content": mem_text or "No relevant memories found."
                        })

                    elif step_type == "analyze":
                        ctx = _format_execution_context(
                            execution_context[user_id]
                        )
                        r = client.messages.create(
                            model=MAIN_MODEL,
                            max_tokens=2048,
                            messages=[{"role": "user", "content": (
                                f"Goal: {goal}\n\n"
                                f"Information gathered:\n{ctx}\n\n"
                                f"Task: {step_desc}\n\n"
                                "Synthesize the above into a concise analysis."
                            )}]
                        )
                        execution_context[user_id].append({
                            "step": step_num, "type": "analyze",
                            "content": r.content[0].text.strip()
                        })

                    elif step_type == "draft":
                        ctx = _format_execution_context(
                            execution_context[user_id]
                        )
                        r = client.messages.create(
                            model=MAIN_MODEL,
                            max_tokens=4096,
                            messages=[{"role": "user", "content": (
                                f"Goal: {goal}\n\n"
                                f"Research and analysis:\n{ctx}\n\n"
                                f"Task: {step_desc}\n\n"
                                "Produce the final output as requested."
                            )}]
                        )
                        final_output = r.content[0].text.strip()
                        execution_context[user_id].append({
                            "step": step_num, "type": "draft",
                            "content": final_output
                        })

                except Exception as e:
                    # ── STEP FAILURE GATE ────────────────────────────────────
                    remaining_descs = "\n".join(
                        f"• Step {s.get('step_number', '?')} "
                        f"({s.get('type', '?')}): {s.get('description', '')}"
                        for s in steps[i + 1:]
                    )
                    pg["status"] = "gated"
                    pg["current_step"] = i
                    gate_pending[user_id] = {
                        "type": "step_failure",
                        "step_index": i,
                        "step_num": step_num,
                        "author_display_name": author_display_name,
                    }
                    await channel.send(
                        f"⚠️ Step {step_num} failed: {str(e)[:200]}"
                        + (f"\n\nRemaining steps:\n{remaining_descs}" if remaining_descs else "")
                        + "\n\nReply:\n"
                        "`!skip` — skip this step and continue\n"
                        "`!retry` — try this step again\n"
                        "`!cancel` — abort the goal"
                    )
                    return

    except Exception as e:
        await send_to_channel(
            guild, LOG_CHANNEL,
            f"Goal execution error | User: {author_display_name} | {str(e)}"
        )
        pending_goals.pop(user_id, None)
        execution_context.pop(user_id, None)
        gate_pending.pop(user_id, None)
        return

    # ── Deliver output ───────────────────────────────────────────────────────
    if final_output:
        await send_long_message(channel, final_output)
    else:
        findings = execution_context.get(user_id, [])
        if findings:
            parts = [f"**Goal complete: {goal}**\n"]
            for f in findings:
                parts.append(
                    f"**Step {f['step']} ({f['type']}):**\n"
                    f"{f['content'][:600]}"
                )
            await send_long_message(channel, "\n\n".join(parts))
        else:
            await channel.send(f"Goal complete: {goal}")

    await post_status(
        guild,
        f"✅ Goal complete — {total} steps executed",
        memory_mode
    )

    web_searches = pg.get("web_search_count", 0)
    mem_queries = sum(
        1 for f in execution_context.get(user_id, [])
        if f["type"] == "query_memory"
    )
    await send_to_channel(
        guild, LOG_CHANNEL,
        f"Goal completed | Steps: {total} | "
        f"Web searches: {web_searches} | "
        f"Memory queries: {mem_queries} | "
        f"Channel: #{channel_name}"
    )

    output_for_memory = final_output or goal
    if memory_mode != "ephemeral":
        await extract_and_store_memories(
            goal, output_for_memory, guild, True,
            project_tag=project_tag,
            channel_name=channel_name,
            memory_mode=memory_mode
        )

    pending_goals.pop(user_id, None)
    execution_context.pop(user_id, None)
    gate_pending.pop(user_id, None)


async def _replan_remaining_steps(
    user_id: str, author_display_name: str,
    from_step_index: int, changes: str, channel, pg: dict
):
    """
    Replans steps from from_step_index onwards based on the user's adjustment
    request. Splices the revised steps into pg["steps"] and resumes execution.
    Called by resume_goal_from_gate when action is "adjust".
    """
    steps = pg["steps"]
    remaining = steps[from_step_index:]

    if not remaining:
        await channel.send("No remaining steps to adjust — goal is already complete.")
        pg["status"] = "executing"
        asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    ctx_summary = _format_execution_context(execution_context.get(user_id, []))
    mod_prompt = (
        f"Goal: {pg['goal']}\n\n"
        f"Context gathered so far:\n{ctx_summary[:800]}\n\n"
        f"Remaining plan:\n{json.dumps(remaining, indent=2)}\n\n"
        f"Adjustment request: {changes}\n\n"
        "Revise the remaining steps accordingly. "
        "Return ONLY a JSON array of steps, no other text."
    )

    try:
        response = client.messages.create(
            model=MAIN_MODEL,
            max_tokens=1024,
            system=GOAL_PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mod_prompt}]
        )
        raw = response.content[0].text.strip()
        new_steps = json.loads(
            raw.replace("```json", "").replace("```", "").strip()
        )
        if not isinstance(new_steps, list) or not new_steps:
            raise ValueError("empty plan returned")
    except Exception as e:
        await channel.send(
            f"Failed to adjust the plan: {str(e)[:200]}\n"
            "Continuing with the original remaining steps."
        )
        new_steps = remaining

    pg["steps"] = steps[:from_step_index] + new_steps
    pg["current_step"] = from_step_index
    pg["status"] = "executing"

    step_lines = "\n".join(
        f"• Step {s.get('step_number', '?')} ({s.get('type', '?')}): "
        f"{s.get('description', '')}"
        for s in new_steps
    )
    await channel.send(f"📋 Adjusted plan:\n{step_lines}\n\nContinuing...")
    asyncio.create_task(execute_goal(user_id, author_display_name))


async def resume_goal_from_gate(
    user_id: str, author_display_name: str, action: str, changes: str = ""
):
    """
    Resumes goal execution after a gate pause.
    action: "continue" | "adjust" | "retry" | "skip"
    Reads gate_pending[user_id] for context, then dispatches accordingly.
    """
    gate = gate_pending.get(user_id)
    pg = pending_goals.get(user_id)
    if not gate or not pg:
        return

    gate_type = gate["type"]
    step_index = gate["step_index"]
    channel = pg["channel"]

    gate_pending.pop(user_id, None)

    if action == "skip" and gate_type == "step_failure":
        pg["current_step"] = step_index + 1
        pg["status"] = "executing"
        remaining_count = len(pg["steps"]) - (step_index + 1)
        await channel.send(
            f"⏭️ Step skipped — continuing with "
            f"{remaining_count} remaining step(s)..."
        )
        asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    if action == "retry" and gate_type == "step_failure":
        pg["current_step"] = step_index
        pg["status"] = "executing"
        await channel.send("🔄 Retrying step...")
        asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    if action == "continue":
        pg["status"] = "executing"
        if gate_type == "draft_gate":
            pg["current_step"] = step_index
            await channel.send("✍️ Generating draft...")
            asyncio.create_task(
                execute_goal(
                    user_id, author_display_name,
                    skip_gate_for_step=step_index
                )
            )
        else:
            # research_gate: step_index already points to the next step
            pg["current_step"] = step_index
            await channel.send("▶️ Continuing execution...")
            asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    if action == "adjust":
        await _replan_remaining_steps(
            user_id, author_display_name, step_index, changes, channel, pg
        )
        return


async def run_handoff_command(channel, guild, channel_name):
    """
    Generates a dense handoff document from live memory for pasting
    into a new AI session. Read-only — does not write to memory.
    """
    await send_to_channel(
        guild, STATUS_CHANNEL, "Generating handoff document..."
    )

    loop = asyncio.get_running_loop()
    snapshot = await loop.run_in_executor(None, get_handoff_memories)

    def _fmt_list(items):
        return "\n".join(f"- {i}" for i in items) if items else "None."

    def _fmt_experiences(exps):
        if not exps:
            return "None."
        lines = []
        for e in exps:
            lines.append(
                f"- {e.get('request', '')} → {e.get('outcome', '')} | "
                f"Lesson: {e.get('lesson', '')}"
            )
        return "\n".join(lines)

    memory_text = f"""STRATEGIC MEMORIES (top by confidence):
{_fmt_list(snapshot.get('strategic', []))}

OPERATIONAL / ACTIVE TASKS:
{_fmt_list(snapshot.get('operational', []))}

ANALYTICAL PATTERNS:
{_fmt_list(snapshot.get('analytical', []))}

RECENT EXPERIENCES:
{_fmt_experiences(snapshot.get('experiences', []))}

OPEN REVIEW FLAGS:
{_fmt_list(snapshot.get('review_flags', []))}"""

    try:
        response = client.messages.create(
            model=MAIN_MODEL,
            max_tokens=2048,
            system=HANDOFF_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": memory_text}]
        )
    except Exception as e:
        await channel.send(
            "Handoff generation failed — please try again."
        )
        await send_to_channel(
            guild, LOG_CHANNEL,
            f"Handoff error in #{channel_name}: {str(e)}"
        )
        return

    handoff_doc = response.content[0].text.strip()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"**HANDOFF DOCUMENT — {timestamp}**\n"

    await send_long_message(channel, header + handoff_doc)

    in_tokens = response.usage.input_tokens
    out_tokens = response.usage.output_tokens
    est_cost = (in_tokens / 1_000_000 * 3.00) + (out_tokens / 1_000_000 * 15.00)
    await send_to_channel(
        guild, LOG_CHANNEL,
        f"Handoff generated | Channel: #{channel_name} | "
        f"Tokens — in: {in_tokens:,} | out: {out_tokens:,} | "
        f"est. cost: ${est_cost:.4f}"
    )


async def run_memory_command(channel, guild, channel_name):
    """Displays what the bot knows in memory for the current channel context."""
    memory_mode = CHANNEL_MEMORY_MODE.get(channel_name, "ephemeral")
    is_isolated = channel_name in MEMORY_ISOLATED_CHANNELS

    if memory_mode == "ephemeral":
        await channel.send(
            "This channel uses ephemeral mode — no memories are stored here."
        )
        return

    if is_isolated:
        query = "health biomarkers protocols supplements peptides"
    elif memory_mode == "project":
        query = f"{channel_name} project tasks status progress"
    else:
        query = "user background goals preferences working style projects"

    loop = asyncio.get_running_loop()
    memories = await loop.run_in_executor(
        None,
        lambda: get_relevant_memories(
            query, max_results=5, channel_name=channel_name
        )
    )

    lines = [f"**Memory snapshot — #{channel_name}**\n"]
    strategic = memories.get("strategic", [])
    operational = memories.get("operational", [])
    analytical = memories.get("analytical", [])

    if strategic:
        lines.append("**Strategic:**")
        for m in strategic[:5]:
            lines.append(f"• {m}")
        lines.append("")

    if operational:
        lines.append("**Operational:**")
        for m in operational[:3]:
            lines.append(f"• {m}")
        lines.append("")

    if analytical:
        lines.append("**Patterns:**")
        for m in analytical[:3]:
            lines.append(f"• {m}")
        lines.append("")

    if not strategic and not operational and not analytical:
        lines.append("No memories found for this channel context.")

    await send_long_message(channel, "\n".join(lines))


async def run_status_command(channel, guild):
    """Posts a formatted system status report to the current channel."""
    loop = asyncio.get_running_loop()

    ollama_up, ollama_model = await loop.run_in_executor(
        None, _check_ollama_status
    )
    ffmpeg_path = shutil.which("ffmpeg")
    stats = await loop.run_in_executor(None, memory_stats)

    uptime_str = "unknown"
    if BOT_START_TIME:
        delta = datetime.now() - BOT_START_TIME
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        minutes = rem // 60
        uptime_str = f"{hours}h {minutes}m"

    ollama_status = (
        f"reachable ({ollama_model})" if ollama_up
        else f"unreachable ({ollama_model})"
    )
    ffmpeg_status = (
        f"found ({ffmpeg_path})" if ffmpeg_path else "not found"
    )
    last_in = _last_token_usage["input"]
    last_out = _last_token_usage["output"]
    last_tokens = (
        f"in: {last_in:,} | out: {last_out:,}"
        if last_in or last_out else "no responses yet"
    )

    def _layer_line(layer: str) -> str:
        ls = stats.get(layer, {})
        total = ls.get("total", 0)
        by_tag = ls.get("by_tag", {})
        parts = []
        global_count = by_tag.get(None, 0)
        if global_count:
            parts.append(f"global: {global_count}")
        for tag, count in sorted(
            (k, v) for k, v in by_tag.items() if k is not None
        ):
            parts.append(f"{tag}: {count}")
        breakdown = " | ".join(parts) if parts else "none"
        return f"{layer}: {total} ({breakdown})"

    mem_lines = "\n  ".join(
        _layer_line(l) for l in ("strategic", "operational", "analytical")
    )

    report = (
        "**System Status**\n"
        f"Ollama: {ollama_status}\n"
        f"FFmpeg: {ffmpeg_status}\n"
        f"Memory —\n  {mem_lines}\n"
        f"Conversation contexts: {len(conversation_history)} active "
        f"({len({k[0] for k in conversation_history})} user(s))\n"
        f"Uptime: {uptime_str}\n"
        f"Last tokens: {last_tokens}"
    )

    await channel.send(report)


async def speak_response(text: str, guild, channel=None) -> None:
    """
    Converts text to speech via ElevenLabs and plays it in the General
    voice channel. Disconnects when done. On failure, notifies the user
    in the originating channel and logs the raw error to bot-logs.
    """
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return

    voice_channel = discord.utils.get(guild.voice_channels, name="General")
    if not voice_channel:
        return

    tmp_path = None
    voice_client = None
    try:
        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio_iter = el_client.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            text=text,
            model_id="eleven_monolingual_v1",
        )

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            for chunk in audio_iter:
                tmp.write(chunk)
            tmp_path = tmp.name

        voice_client = discord.utils.get(bot.voice_clients, guild=guild)
        if voice_client is None:
            voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

        source = discord.FFmpegPCMAudio(tmp_path)
        done = asyncio.Event()
        voice_client.play(source, after=lambda _: done.set())
        await done.wait()

    except Exception as e:
        if channel:
            await channel.send(
                "Voice response failed — text response above is complete."
            )
        await send_to_channel(
            guild, LOG_CHANNEL,
            f"TTS error: {str(e)}"
        )
    finally:
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


async def process_user_message(
    user_message, user_id, author_display_name, guild, channel,
    speak: bool = False, memory_mode: str = "global",
    project_tag: str = None, active_agent_slug: str = None,
    agent_trigger: str = "none", context_id: int = 0,
    channel_name: str = None,
):
    """
    Shared Claude processing pipeline used by on_message and /listen.
    Handles memory retrieval, the agentic tool loop, memory storage,
    reflection, and logging.

    context_id: thread.id if responding inside a Discord thread, channel.id
        otherwise. Used to key conversation_history so each thread gets its
        own independent history.
    channel_name: the parent channel name (for routing / memory lookups).
        Defaults to channel.name if not supplied. Must be the parent channel
        name when channel is a discord.Thread so that CHANNEL_TOOL_MODE and
        similar dicts resolve correctly.
    """
    global stale_warned_this_session
    effective_channel_name = channel_name or channel.name
    _hist_key = (user_id, context_id)
    if _hist_key not in conversation_history:
        conversation_history[_hist_key] = []

    log_conversation_turn(
        str(user_id), context_id, effective_channel_name,
        "user", user_message, project_tag=project_tag
    )

    task_completed = is_task_completion(user_message)

    memories = get_relevant_memories(
        user_message, channel_name=effective_channel_name
    )
    memory_context = format_memory_for_prompt(memories)
    _mem_count = sum(
        len(memories.get(k, [])) for k in ("strategic", "operational", "analytical")
    )
    if _mem_count > 0:
        await post_status(guild, "🧠 Memory searched — context loaded", memory_mode)

    channel_purpose = CHANNEL_PURPOSE.get(
        effective_channel_name, "General"
    )
    _agent_label = (
        f" | Agent: {AGENT_DEFINITIONS[active_agent_slug]['name']}"
        if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS else ""
    )
    channel_ctx = (
        f"[Channel: #{effective_channel_name} | Purpose: {channel_purpose}{_agent_label}]"
    )

    _search_context = ""
    if _is_confabulation_check(user_message):
        _conv_hits = search_conversations(
            user_message, effective_channel_name, str(user_id)
        )
        if _conv_hits:
            _lines = []
            for _h in _conv_hits:
                _ts = _h["timestamp"][:19].replace("T", " ")
                _snippet = _h["content"][:300].replace("\n", " ")
                _lines.append(
                    f"[{_ts}] #{_h['channel_name']} [{_h['role']}]: {_snippet}"
                )
            _search_context = (
                "[SESSION ARCHIVE — past exchanges matching this query:]\n"
                + "\n".join(_lines)
                + "\n[Use these records to verify claims about what you previously said.]\n\n"
            )

    full_message = user_message
    if memory_context:
        full_message = (
            f"{memory_context}\n\n"
            f"Current message: {user_message}"
        )

    full_message = f"{channel_ctx}\n{_search_context}{full_message}"

    # ── FILE INJECTION ────────────────────────────────────────
    file_injection_chars = 0
    all_user_files = list(attached_files.get(user_id, []))
    is_isolated_channel = effective_channel_name in MEMORY_ISOLATED_CHANNELS

    if all_user_files:
        if is_isolated_channel:
            user_files = [
                f for f in all_user_files
                if f.get("channel_name") == effective_channel_name
            ]
        else:
            user_files = [
                f for f in all_user_files
                if f.get("channel_name") not in MEMORY_ISOLATED_CHANNELS
            ]

        doc_files       = [f for f in user_files if f["content_type"] == "document"]
        img_files       = [f for f in user_files if f["content_type"] == "image"]
        pdf_vision_files = [f for f in user_files if f["content_type"] == "pdf_vision"]

        if user_files:
            await post_status(guild, "📎 Reading attached file(s)...", memory_mode)

        # Cap total document text — drop oldest files first to stay under limit
        docs_to_inject = []
        chars_used = 0
        omitted = 0
        for f in reversed(doc_files):
            flen = len(f["text_content"])
            if chars_used + flen <= FILE_CONTENT_CHAR_LIMIT:
                docs_to_inject.insert(0, f)
                chars_used += flen
            else:
                omitted += 1
        file_injection_chars = chars_used

        if docs_to_inject:
            file_parts = [
                f"[Attached file: {f['filename']}]\nContent: {f['text_content']}"
                for f in docs_to_inject
            ]
            truncation_note = (
                f"\n[{omitted} older file(s) omitted — "
                f"50,000 character limit reached]"
                if omitted else ""
            )
            full_message = (
                f"ATTACHED FILES:\n"
                + "\n\n".join(file_parts)
                + truncation_note
                + f"\n\n{full_message}"
            )

        has_visual = img_files or pdf_vision_files
        if has_visual:
            content_blocks = []
            for img in img_files:
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img["base64_data"],
                    },
                })
            for pdf_file in pdf_vision_files:
                for page in pdf_file["pages"]:
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": page["media_type"],
                            "data": page["base64_data"],
                        },
                    })
            content_blocks.append({"type": "text", "text": full_message})
            conversation_history[_hist_key].append({
                "role": "user",
                "content": content_blocks,
            })
        else:
            conversation_history[_hist_key].append({
                "role": "user",
                "content": full_message,
            })
    else:
        conversation_history[_hist_key].append({
            "role": "user",
            "content": full_message,
        })

    await post_status(
        guild,
        f"Processing request from {author_display_name}...",
        memory_mode
    )

    if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS:
        await post_status(
            guild,
            f"🤖 {AGENT_DEFINITIONS[active_agent_slug]['name']} activated",
            memory_mode
        )

    async with channel.typing():
        try:
            tool_call_count = 0
            final_response_text = ""
            tool_mode = CHANNEL_TOOL_MODE.get(effective_channel_name, "none")
            if tool_mode == "full":
                active_tools = TOOL_DEFINITIONS
            elif tool_mode == "search_only":
                active_tools = [
                    t for t in TOOL_DEFINITIONS
                    if t["name"] in SEARCH_ONLY_TOOL_NAMES
                ]
            else:
                active_tools = []

            if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS:
                _adef = AGENT_DEFINITIONS[active_agent_slug]
                effective_system = (
                    SYSTEM_PROMPT
                    + f"\n\n---\nACTIVE SPECIALIST AGENT: {_adef['name']}\n"
                    + _adef["content"]
                )
            else:
                effective_system = SYSTEM_PROMPT

            while True:
                _cleaned, _n_stripped = strip_orphaned_tool_results(
                    conversation_history[_hist_key]
                )
                if _n_stripped:
                    conversation_history[_hist_key] = _cleaned
                    print(
                        f"[Safety] Stripped {_n_stripped} orphaned blocks "
                        f"before API call in thread {context_id}"
                    )

                api_params = {
                    "model": MAIN_MODEL,
                    "max_tokens": 1024,
                    "system": effective_system,
                    "messages": conversation_history[_hist_key],
                }
                if active_tools:
                    api_params["tools"] = active_tools

                response = client.messages.create(**api_params)

                if response.stop_reason == "tool_use":
                    conversation_history[_hist_key].append({
                        "role": "assistant",
                        "content": response.content
                    })
                    tool_results, tool_call_count = \
                        await process_tool_calls(
                            response, guild, tool_call_count,
                            channel_name=effective_channel_name,
                            memory_mode=memory_mode,
                        )
                    conversation_history[_hist_key].append({
                        "role": "user",
                        "content": tool_results
                    })
                    continue

                for block in response.content:
                    if hasattr(block, "text"):
                        final_response_text += block.text

                conversation_history[_hist_key].append({
                    "role": "assistant",
                    "content": final_response_text
                })
                break

            # Drain escalation queue and post high-priority flags to #chief-of-staff
            pending_escalations = drain_escalation_queue()
            for item in pending_escalations:
                cos_channel = discord.utils.get(
                    guild.channels, name="chief-of-staff"
                )
                if cos_channel:
                    await send_to_channel(
                        guild,
                        cos_channel.name,
                        f"🚨 High-priority flag escalated from #{item['source_channel']}\n"
                        f"Topic: {item['topic']}\n"
                        f"Reason: {item['reason']}"
                    )

            if final_response_text:
                log_conversation_turn(
                    str(user_id), context_id, effective_channel_name,
                    "assistant", final_response_text, project_tag=project_tag
                )

            conversation_history[_hist_key] = \
                conversation_history[_hist_key][-20:]

            if final_response_text:
                await send_long_message(channel, final_response_text)
                if speak:
                    await speak_response(final_response_text, guild, channel)
            else:
                await channel.send(
                    "I processed your request but had "
                    "trouble forming a response. "
                    "Check bot-logs for details."
                )

            if memory_mode != "ephemeral":
                await extract_and_store_memories(
                    user_message,
                    final_response_text,
                    guild,
                    task_completed,
                    project_tag=project_tag,
                    channel_name=effective_channel_name,
                    memory_mode=memory_mode
                )

                if task_completed:
                    experiences = get_recent_experiences(
                        limit=5,
                        task_completed_only=True
                    )
                    await run_reflection_loop(guild, experiences)

                # Fire auto-consolidation in background if thresholds exceeded
                current_stats = memory_stats()
                if _should_consolidate(current_stats, effective_channel_name):
                    asyncio.create_task(
                        consolidate_all_layers(
                            guild,
                            channel_name=effective_channel_name,
                            trigger="auto"
                        )
                    )

            stale_count = len(memories.get("stale_flags", []))
            in_tokens = response.usage.input_tokens
            out_tokens = response.usage.output_tokens
            est_cost = (in_tokens / 1_000_000 * 3.00) + \
                       (out_tokens / 1_000_000 * 15.00)
            _last_token_usage["input"] = in_tokens
            _last_token_usage["output"] = out_tokens
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"Responded to {author_display_name} | "
                f"Model: {response.model} | "
                f"Tools loaded: {', '.join(t['name'] for t in active_tools) or 'none'} | "
                f"Tools used: {tool_call_count} | "
                f"Task complete: {task_completed} | "
                f"Stale flags: {stale_count}"
            )
            file_token_note = (
                f" | File injection: ~{file_injection_chars // 4:,} tokens"
                if file_injection_chars else ""
            )
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"Tokens — in: {in_tokens:,} | "
                f"out: {out_tokens:,} | "
                f"est. cost: ${est_cost:.4f}{file_token_note}"
            )

            if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS:
                _agent_tokens = len(AGENT_DEFINITIONS[active_agent_slug]["content"]) // 4
                await send_to_channel(
                    guild, LOG_CHANNEL,
                    f"Agent activated | {AGENT_DEFINITIONS[active_agent_slug]['name']} | "
                    f"+~{_agent_tokens:,} tokens | trigger: {agent_trigger}"
                )

            await post_status(
                guild,
                f"Response delivered to {author_display_name}. Ready.",
                memory_mode
            )

            if stale_count and not stale_warned_this_session:
                stale_warned_this_session = True
                await send_to_channel(
                    guild,
                    STATUS_CHANNEL,
                    f"{tag_owner()}{stale_count} stale memory "
                    f"flag(s) detected — review may be needed."
                )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                save_conversation_history,
                f"{user_id}:{context_id}",
                _saveable_history(conversation_history[_hist_key])
            )

        except Exception as e:
            await channel.send("Something went wrong — please try again.")
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"{tag_owner()}Error for {author_display_name}: {str(e)}"
            )


# ============================================================
# AGENT LOADING & SELECTION
# ============================================================

async def _load_agent_definitions():
    """
    Reads all .md files from AGENTS_DIR at startup, parses frontmatter for
    name/description, and extracts keywords via the background model.
    Keywords are cached to AGENT_KEYWORDS_CACHE_PATH so we only call the
    model once per agent (or when new agents are added).
    Skips files that cannot be read — logs to stdout, does not raise.
    """
    import re as _re

    if not os.path.isdir(AGENTS_DIR):
        print(f"[Agents] Directory not found: {AGENTS_DIR} — skipping agent load")
        return

    # Load keyword cache from disk
    cache: dict = {}
    if os.path.exists(AGENT_KEYWORDS_CACHE_PATH):
        try:
            with open(AGENT_KEYWORDS_CACHE_PATH, "r", encoding="utf-8") as _cf:
                cache = json.load(_cf)
        except Exception:
            cache = {}

    cache_updated = False

    for filename in sorted(os.listdir(AGENTS_DIR)):
        if not filename.endswith(".md"):
            continue
        slug = filename[:-3]
        path = os.path.join(AGENTS_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as _f:
                content = _f.read()
        except Exception as e:
            print(f"[Agents] Skipping {filename}: {e}")
            continue

        # Parse frontmatter for name and description
        name = slug
        description = ""
        fm_match = _re.search(r"^---\n(.*?)\n---", content, _re.DOTALL)
        if fm_match:
            fm_body = fm_match.group(1)
            name_m = _re.search(r"^name:\s*(.+)$", fm_body, _re.MULTILINE)
            if name_m:
                name = name_m.group(1).strip()
            desc_m = _re.search(r"^description:\s*(.+)$", fm_body, _re.MULTILINE)
            if desc_m:
                description = desc_m.group(1).strip()

        # Get keywords: use cache if present, otherwise extract via background model
        if slug in cache:
            keywords = cache[slug]
        else:
            try:
                kw_prompt = (
                    "Read this agent definition and return a JSON array of 15 keywords "
                    "that would indicate a user needs this agent. "
                    "Return only the JSON array, no other text.\n\n"
                    + content[:2000]
                )
                raw_kw = await call_background_model(kw_prompt)
                keywords = json.loads(
                    raw_kw.replace("```json", "").replace("```", "").strip()
                )
                if not isinstance(keywords, list):
                    keywords = []
                cache[slug] = keywords
                cache_updated = True
            except Exception as e:
                print(f"[Agents] Keyword extraction failed for {slug}: {e}")
                keywords = []

        AGENT_DEFINITIONS[slug] = {
            "name": name,
            "slug": slug,
            "description": description,
            "content": content,
            "keywords": [str(k).lower() for k in keywords],
        }
        print(f"[Agents] Loaded: {name} ({slug})")

    if cache_updated:
        try:
            with open(AGENT_KEYWORDS_CACHE_PATH, "w", encoding="utf-8") as _cf:
                json.dump(cache, _cf, indent=2)
        except Exception as e:
            print(f"[Agents] Failed to save keyword cache: {e}")

    count = len(AGENT_DEFINITIONS)
    print(f"[Agents] {count} agent definition(s) loaded.")
    if AGENT_DEFINITIONS:
        pairs = ", ".join(
            f"{slug}: {agent['name']}"
            for slug, agent in sorted(AGENT_DEFINITIONS.items())
        )
        print(f"[Agents] Agents loaded: {pairs}")

    # Validate CHANNEL_AGENT_HINTS against loaded slugs — warn on any miss
    for _ch, _hint in CHANNEL_AGENT_HINTS.items():
        slugs_to_check = [_hint] if isinstance(_hint, str) else _hint
        for _s in slugs_to_check:
            if _s not in AGENT_DEFINITIONS:
                print(
                    f"[Agents] WARNING: CHANNEL_AGENT_HINTS['{_ch}'] "
                    f"references unknown slug '{_s}' — hint will be ignored"
                )


def select_agent(message_text: str, channel_name: str) -> tuple:
    """
    Returns (agent_slug, trigger_type) for auto-detection.
    trigger_type: "channel" | "keyword" | "explicit" | "none"

    Priority order:
    1. Health-tracking hard rule — always returns health-researcher (cannot be
       overridden by keywords; use !agent explicitly to bypass).
    2. Sandbox — never activates any agent.
    3. Explicit mention of agent name or slug in the message text.
    4. Channel hints (CHANNEL_AGENT_HINTS): single slug returned directly;
       lists resolved by keyword score among candidates.
    5. Global keyword matching — activate if score >= 3 across all agents.
    6. Default: (None, "none").

    Does NOT handle !agent explicit commands — those bypass this function.
    """
    if not AGENT_DEFINITIONS:
        return None, "none"

    # Hard rule: health-tracking always uses health-researcher
    if channel_name == "health-tracking":
        slug = "health-researcher"
        return (slug, "channel") if slug in AGENT_DEFINITIONS else (None, "none")

    # Sandbox never activates any agent
    if channel_name == "sandbox":
        return None, "none"

    msg_lower = message_text.lower()

    # Priority 3: explicit mention of agent name or slug in the message
    for slug, agent in AGENT_DEFINITIONS.items():
        if slug in msg_lower or agent["name"].lower() in msg_lower:
            return slug, "explicit"

    # Priority 4: channel hints
    hint = CHANNEL_AGENT_HINTS.get(channel_name)
    if hint:
        if isinstance(hint, str):
            if hint in AGENT_DEFINITIONS:
                return hint, "channel"
        elif isinstance(hint, list):
            # Score each candidate; first entry wins ties (including all-zero)
            best_slug = None
            best_score = -1
            for s in hint:
                if s not in AGENT_DEFINITIONS:
                    continue
                score = sum(
                    1 for kw in AGENT_DEFINITIONS[s]["keywords"] if kw in msg_lower
                )
                if score > best_score:
                    best_score = score
                    best_slug = s
            if best_slug:
                return best_slug, "channel"

    # Priority 5: global keyword matching (threshold: 3)
    best_slug = None
    best_score = 0
    for slug, agent in AGENT_DEFINITIONS.items():
        score = sum(1 for kw in agent["keywords"] if kw in msg_lower)
        if score > best_score:
            best_score = score
            best_slug = slug

    if best_score >= 3:
        return best_slug, "keyword"

    return None, "none"


# ============================================================
# BOT EVENTS
# ============================================================

@bot.event
async def on_ready():
    """Runs once when the bot connects to Discord."""
    global BOT_START_TIME
    BOT_START_TIME = datetime.now()

    raw_histories = load_all_conversation_histories()
    total_stripped = 0
    for key, history in raw_histories.items():
        cleaned, count = strip_orphaned_tool_results(history)
        total_stripped += count
        if ":" in key:
            uid_str, cid_str = key.split(":", 1)
            try:
                tuple_key = (uid_str, int(cid_str))
            except ValueError:
                continue
        else:
            # Legacy key (user_id only, pre-thread keying) — skip; stale context
            continue
        conversation_history[tuple_key] = cleaned
    if total_stripped:
        print(
            f"[Startup] Stripped {total_stripped} orphaned "
            f"tool_result block(s) from loaded histories."
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, check_ollama_health)
    await loop.run_in_executor(None, check_ffmpeg)
    _deleted = await loop.run_in_executor(None, cleanup_old_conversation_log)
    if _deleted:
        print(f"[Startup] Pruned {_deleted} conversation_log entries older than 90 days.")
    _backfilled = await loop.run_in_executor(None, backfill_conversation_log)
    if _backfilled > 0:
        print(f"[Search] Backfilled {_backfilled} conversation turns into search index")
    print(f"PerMyLastBot is online as {bot.user} "
          f"({len(conversation_history)} conversation context(s) restored)")
    await tree.sync()
    await _load_agent_definitions()
    if AGENT_DEFINITIONS:
        _agent_summary = " | ".join(
            f"{slug}: {a['name']}"
            for slug, a in sorted(AGENT_DEFINITIONS.items())
        )
        print(f"[Startup] Agents loaded: {_agent_summary}")

    for guild in bot.guilds:
        await send_to_channel(
            guild,
            STATUS_CHANNEL,
            "PerMyLastBot is online — "
            "memory system and tools active."
        )


@bot.event
async def on_message(message):
    """Handles all incoming messages, including Discord voice message attachments."""

    if message.author == bot.user:
        return

    # Resolve effective channel name: threads inherit their parent's settings
    if isinstance(message.channel, discord.Thread):
        channel_name = (
            message.channel.parent.name
            if message.channel.parent else message.channel.name
        )
        context_id = message.channel.id
    else:
        channel_name = message.channel.name
        context_id = message.channel.id

    if channel_name in CHANNEL_IGNORED:
        return

    memory_mode = CHANNEL_MEMORY_MODE.get(channel_name, "ephemeral")
    project_tag = CHANNEL_PROJECT_TAG.get(channel_name)

    # ── VOICE MESSAGE ATTACHMENTS ─────────────────────────
    voice_attachment = next(
        (
            a for a in message.attachments
            if a.content_type
            and a.content_type.startswith("audio/")
            and not a.filename.lower().endswith(".txt")
        ),
        None
    )

    if voice_attachment:
        suffix = (
            os.path.splitext(voice_attachment.filename)[1]
            if "." in voice_attachment.filename
            else "." + voice_attachment.content_type.split("/")[-1].split(";")[0]
        )
        audio_bytes = await voice_attachment.read()
        loop = asyncio.get_running_loop()
        try:
            transcription = await loop.run_in_executor(
                None, transcribe_attachment, audio_bytes, suffix
            )
        except Exception as e:
            await message.channel.send(
                "Voice transcription failed — please try again "
                "or type your message instead."
            )
            await send_to_channel(
                message.guild, LOG_CHANNEL,
                f"Transcription error in #{channel_name}: {str(e)}"
            )
            return

        if not transcription:
            return

        await message.channel.send(f"Heard: {transcription}")
        _va_slug, _va_trigger = select_agent(transcription, channel_name)
        _va_channel, context_id = await _resolve_response_channel(
            message, channel_name, transcription
        )
        await process_user_message(
            transcription,
            str(message.author.id),
            message.author.display_name,
            message.guild,
            _va_channel,
            speak=True,
            memory_mode=memory_mode,
            project_tag=project_tag,
            active_agent_slug=_va_slug,
            agent_trigger=_va_trigger,
            context_id=context_id,
            channel_name=channel_name,
        )
        return

    # ── FILE ATTACHMENTS (non-audio) ──────────────────────
    non_audio_attachments = [
        a for a in message.attachments
        if not (
            a.content_type
            and a.content_type.startswith("audio/")
            and not a.filename.lower().endswith(".txt")
        )
    ]

    if non_audio_attachments:
        uid = str(message.author.id)
        loop = asyncio.get_running_loop()
        for attachment in non_audio_attachments:
            ext = os.path.splitext(attachment.filename)[1].lower()
            _is_txt = (
                attachment.filename.lower().endswith(".txt")
                or "text/plain" in (attachment.content_type or "")
            )
            if ext not in SUPPORTED_EXTENSIONS and not _is_txt:
                await message.channel.send(
                    f"⚠️ {attachment.filename} — file type not supported. "
                    f"Supported: PDF, DOCX, TXT, MD, CSV, PNG, JPG, WEBP"
                )
                continue

            file_bytes = await attachment.read()
            try:
                file_data = await loop.run_in_executor(
                    None, _process_attachment, attachment.filename, file_bytes
                )
            except Exception as e:
                await message.channel.send(
                    f"⚠️ {attachment.filename} — could not read this file. "
                    f"It may be corrupted or password protected."
                )
                await send_to_channel(
                    message.guild, LOG_CHANNEL,
                    f"File processing error | {attachment.filename} | "
                    f"Channel: #{channel_name} | {str(e)}"
                )
                continue

            file_data["channel_name"] = channel_name
            attached_files[uid].append(file_data)

            ct = file_data["content_type"]
            if ct == "document":
                char_count = len(file_data.get("text_content", ""))
                await message.channel.send(
                    f"📎 {attachment.filename} received — "
                    f"{char_count:,} chars extracted. "
                    f"Ask me anything about it or keep uploading."
                )
                log_detail = f"text | {char_count:,} chars"
            elif ct == "pdf_vision":
                page_count = len(file_data.get("pages", []))
                await message.channel.send(
                    f"📎 {attachment.filename} received as image-based PDF — "
                    f"{page_count} page(s) will be read visually by Claude."
                )
                log_detail = f"vision | {page_count} page(s)"
            else:
                b64_len = len(file_data.get("base64_data", ""))
                await message.channel.send(
                    f"📎 {attachment.filename} received and ready. "
                    f"Ask me anything about it or keep uploading."
                )
                log_detail = f"image | {b64_len:,} chars (base64)"

            await send_to_channel(
                message.guild, LOG_CHANNEL,
                f"File received | {attachment.filename} | "
                f"{log_detail} | Channel: #{channel_name}"
            )

        # Check if there's a question alongside the files
        raw_text = message.content.strip()
        if bot.user in message.mentions:
            raw_text = raw_text.replace(
                f"<@{bot.user.id}>", ""
            ).strip()

        if not raw_text:
            return  # files only — waiting for a question

        if not raw_text.startswith("!"):
            # Plain-text question with files — run pipeline directly
            _fa_slug, _fa_trigger = select_agent(raw_text, channel_name)
            _fa_channel, context_id = await _resolve_response_channel(
                message, channel_name, raw_text
            )
            await process_user_message(
                raw_text,
                uid,
                message.author.display_name,
                message.guild,
                _fa_channel,
                speak=False,
                memory_mode=memory_mode,
                project_tag=project_tag,
                active_agent_slug=_fa_slug,
                agent_trigger=_fa_trigger,
                context_id=context_id,
                channel_name=channel_name,
            )
            return
        # Starts with "!" — fall through to command handling below

    # ── TEXT COMMANDS ─────────────────────────────────────
    is_mention = bot.user in message.mentions
    is_prefix = message.content.startswith("!")

    if not is_mention and not is_prefix:
        return

    if is_prefix:
        user_message = message.content[1:].strip()
    else:
        user_message = message.content.replace(
            f"<@{bot.user.id}>", ""
        ).strip()

    uid = str(message.author.id)

    # Goal triggers: !goal, !plan, !research
    if is_prefix:
        goal_trigger = _parse_goal_trigger(user_message)
        if goal_trigger:
            _, goal_text = goal_trigger
            asyncio.create_task(
                run_goal_planning(
                    goal_text, uid, message.author.display_name,
                    message.guild, message.channel, memory_mode, project_tag
                )
            )
            return

    # Gate commands — mid-execution pauses awaiting !continue/!adjust/!retry/!skip
    if uid in gate_pending:
        gate = gate_pending[uid]
        gate_type = gate["type"]
        if is_prefix:
            lm = user_message.lower()
            if lm == "continue":
                asyncio.create_task(
                    resume_goal_from_gate(
                        uid, message.author.display_name, "continue"
                    )
                )
                return
            if lm.startswith("adjust "):
                changes = user_message[7:].strip()
                if changes:
                    asyncio.create_task(
                        resume_goal_from_gate(
                            uid, message.author.display_name, "adjust", changes
                        )
                    )
                return
            if lm == "skip" and gate_type == "step_failure":
                asyncio.create_task(
                    resume_goal_from_gate(
                        uid, message.author.display_name, "skip"
                    )
                )
                return
            if lm == "retry" and gate_type == "step_failure":
                asyncio.create_task(
                    resume_goal_from_gate(
                        uid, message.author.display_name, "retry"
                    )
                )
                return
            if lm == "cancel":
                pending_goals.pop(uid, None)
                gate_pending.pop(uid, None)
                execution_context.pop(uid, None)
                await message.channel.send("❌ Goal cancelled.")
                return
        if not is_prefix:
            step_num = gate.get("step_num", gate.get("step_index", 0) + 1)
            if gate_type == "step_failure":
                await message.channel.send(
                    f"⚠️ Execution paused — step {step_num} failed. "
                    "Reply `!retry`, `!skip`, or `!cancel`."
                )
            else:
                await message.channel.send(
                    f"⏸️ Execution paused at step {step_num}. "
                    "Reply `!continue`, `!adjust [changes]`, or `!cancel`."
                )
            return

    # Goal approval/modification commands — pre-execution only
    if uid in pending_goals:
        pg = pending_goals[uid]
        pg_status = pg["status"]
        if is_prefix:
            lm = user_message.lower()
            if lm == "approve":
                if pg_status == "awaiting_approval":
                    pg["status"] = "executing"
                    pg["current_step"] = 0
                    execution_context[uid] = []
                    await message.channel.send("✅ Executing plan...")
                    asyncio.create_task(
                        execute_goal(uid, message.author.display_name)
                    )
                return
            if lm == "cancel":
                pending_goals.pop(uid, None)
                execution_context.pop(uid, None)
                await message.channel.send("❌ Goal cancelled.")
                return
            if lm.startswith("modify "):
                if pg_status == "awaiting_approval":
                    changes = user_message[7:].strip()
                    if changes:
                        asyncio.create_task(run_goal_modification(
                            changes, uid, message.author.display_name,
                            message.guild, message.channel, memory_mode, project_tag
                        ))
                return
        if not is_prefix and pg_status == "awaiting_approval":
            await message.channel.send(
                "You have a pending goal plan. Reply `!approve`, `!cancel`, "
                "or `!modify [changes]` — I will not process other messages "
                "until the plan is resolved."
            )
            return
        if not is_prefix and pg_status == "gated":
            # gate_pending block should have caught this — defensive fallback
            await message.channel.send(
                "⏸️ Execution is paused. "
                "Reply `!continue`, `!adjust [changes]`, or `!cancel`."
            )
            return

    # !agents: list all available specialist agents
    if is_prefix and user_message.lower() == "agents":
        if not AGENT_DEFINITIONS:
            await message.channel.send(
                "No agent definitions loaded — check startup logs."
            )
            return
        lines = ["**Available Specialist Agents**\n"]
        for _slug in sorted(AGENT_DEFINITIONS.keys()):
            _ag = AGENT_DEFINITIONS[_slug]
            _desc = _ag["description"][:120] if _ag["description"] else "No description."
            lines.append(f"`{_slug}` — **{_ag['name']}**: {_desc}")
        await send_long_message(message.channel, "\n".join(lines))
        return

    # !agent [slug-or-name] [message]: manually activate one agent for one response
    if is_prefix and user_message.lower().startswith("agent "):
        _parts = user_message[6:].strip().split(None, 1)
        if not _parts:
            await message.channel.send(
                "Usage: `!agent [slug-or-name] [your message]`\n"
                "Run `!agents` to see available agents."
            )
            return
        _query = _parts[0].lower()
        _rest = _parts[1].strip() if len(_parts) > 1 else ""

        # Match by exact slug, then by name, then by slug substring
        _found_slug = None
        if _query in AGENT_DEFINITIONS:
            _found_slug = _query
        else:
            for _s, _a in AGENT_DEFINITIONS.items():
                if _query == _a["name"].lower() or _query in _s:
                    _found_slug = _s
                    break

        if not _found_slug:
            _available = ", ".join(f"`{s}`" for s in sorted(AGENT_DEFINITIONS.keys()))
            await message.channel.send(
                f"Unknown agent `{_query}`. Available: {_available}"
            )
            return

        if not _rest:
            await message.channel.send(
                f"Usage: `!agent {_found_slug} [your message]`"
            )
            return

        await message.channel.send(
            f"🤖 Using **{AGENT_DEFINITIONS[_found_slug]['name']}**"
        )
        _ag_channel, context_id = await _resolve_response_channel(
            message, channel_name, _rest
        )
        await process_user_message(
            _rest, uid, message.author.display_name,
            message.guild, _ag_channel,
            speak=False, memory_mode=memory_mode,
            project_tag=project_tag,
            active_agent_slug=_found_slug,
            agent_trigger="explicit",
            context_id=context_id,
            channel_name=channel_name,
        )
        return

    # !remember in bot-commands: save directly to global memory and confirm
    if (channel_name == "bot-commands" and is_prefix
            and user_message.lower().startswith("remember ")):
        content = user_message[9:].strip()
        if content:
            save_strategic_memory(
                content=content,
                category="manual",
                source="!remember"
            )
            await message.channel.send(
                f"Saved to global memory: \"{content}\""
            )
        else:
            await message.channel.send(
                "Nothing to remember — please include "
                "content after !remember."
            )
        return

    # !handoff: generate dense memory snapshot for new AI session
    if is_prefix and user_message.lower() == "handoff":
        await run_handoff_command(
            message.channel, message.guild, channel_name
        )
        return

    # !search [query]: full-text search of permanent conversation archive
    if is_prefix and user_message.lower().startswith("search "):
        _sq = user_message[7:].strip()
        if not _sq:
            await message.channel.send("Usage: `!search [query]`")
            return
        _hits = search_conversations(_sq, channel_name, uid)
        await send_to_channel(
            message.guild, LOG_CHANNEL,
            f"!search | {message.author.display_name} | \"{_sq}\" | {len(_hits)} result(s)"
        )
        if not _hits:
            await message.channel.send("No past conversations found.")
            return
        _excerpt_lines = []
        for _r in _hits:
            _ts = _r["timestamp"][:19].replace("T", " ")
            _snip = _r["content"][:400].replace("\n", " ")
            _excerpt_lines.append(
                f"**[{_ts}] #{_r['channel_name']} [{_r['role']}]:**\n{_snip}"
            )
        _excerpts = "\n\n".join(_excerpt_lines)
        _summary_prompt = (
            f"The user searched for: \"{_sq}\"\n\n"
            f"Matching conversation excerpts from the archive:\n\n{_excerpts}\n\n"
            f"Briefly summarise what these records show. Be direct and specific."
        )
        _summary = await call_background_model(_summary_prompt)
        await send_long_message(
            message.channel,
            f"{_summary}\n\n---\n*Found {len(_hits)} relevant exchange(s).*"
        )
        return

    # !consolidate: manually trigger memory consolidation for this channel scope
    if is_prefix and user_message.lower() == "consolidate":
        await run_consolidate_command(
            message.channel, message.guild, channel_name
        )
        return

    # !help: list all commands
    if is_prefix and user_message.lower() == "help":
        await message.channel.send(HELP_TEXT)
        return

    # !memory: show memory snapshot for this channel context
    if is_prefix and user_message.lower() == "memory":
        await run_memory_command(
            message.channel, message.guild, channel_name
        )
        return

    # !clear: wipe in-memory conversation history for this (user, context) pair
    if is_prefix and user_message.lower() == "clear":
        _clear_key = (uid, context_id)
        old_history = conversation_history.get(_clear_key, [])
        _, stripped = strip_orphaned_tool_results(old_history)
        conversation_history[_clear_key] = []
        cleared_files = len(attached_files.pop(uid, []))
        note_parts = []
        if stripped:
            note_parts.append(f"{stripped} orphaned tool block(s) cleaned")
        if cleared_files:
            note_parts.append(f"{cleared_files} attached file(s) removed")
        note = f" ({', '.join(note_parts)})" if note_parts else ""
        await message.channel.send(
            f"Conversation history cleared for this channel. "
            f"Starting fresh.{note}"
        )
        return

    # !status: system health report
    if is_prefix and user_message.lower() == "status":
        await run_status_command(message.channel, message.guild)
        return

    # !retry: resend last user message through the full pipeline
    if is_prefix and user_message.lower() == "retry":
        history = conversation_history.get((uid, context_id), [])
        last_user_content = None
        for msg in reversed(history):
            if (msg.get("role") == "user"
                    and isinstance(msg.get("content"), str)):
                last_user_content = msg["content"]
                break
        if not last_user_content:
            await message.channel.send("No previous message to retry.")
            return
        original_message = _extract_original_message(last_user_content)
        if not original_message:
            await message.channel.send("No previous message to retry.")
            return
        _retry_slug, _retry_trigger = select_agent(original_message, channel_name)
        await process_user_message(
            original_message,
            uid,
            message.author.display_name,
            message.guild,
            message.channel,
            speak=False,
            memory_mode=memory_mode,
            project_tag=project_tag,
            active_agent_slug=_retry_slug,
            agent_trigger=_retry_trigger,
            context_id=context_id,
            channel_name=channel_name,
        )
        return

    speak = user_message.lower().endswith(" speak")
    if speak:
        user_message = user_message[:-6].rstrip()

    if not user_message:
        await message.channel.send(
            "I got your message but there was nothing in it. "
            "What do you need?"
        )
        return

    if uid in gate_pending:
        gate = gate_pending[uid]
        step_num = gate.get("step_num", gate.get("step_index", 0) + 1)
        if gate["type"] == "step_failure":
            await message.channel.send(
                f"⚠️ Execution paused — step {step_num} failed. "
                "Reply `!retry`, `!skip`, or `!cancel`."
            )
        else:
            await message.channel.send(
                f"⏸️ Execution paused at step {step_num}. "
                "Reply `!continue`, `!adjust [changes]`, or `!cancel`."
            )
        return

    if uid in pending_goals and pending_goals[uid].get("status") == "awaiting_approval":
        await message.channel.send(
            "You have a pending goal plan. Reply `!approve`, `!cancel`, "
            "or `!modify [changes]` — I will not process other messages "
            "until the plan is resolved."
        )
        return

    _auto_slug, _auto_trigger = select_agent(user_message, channel_name)
    _auto_channel, context_id = await _resolve_response_channel(
        message, channel_name, user_message
    )
    await process_user_message(
        user_message,
        uid,
        message.author.display_name,
        message.guild,
        _auto_channel,
        speak=speak,
        memory_mode=memory_mode,
        project_tag=project_tag,
        active_agent_slug=_auto_slug,
        agent_trigger=_auto_trigger,
        context_id=context_id,
        channel_name=channel_name,
    )


# ============================================================
# START THE BOT
# ============================================================

bot.run(os.getenv("DISCORD_TOKEN"))