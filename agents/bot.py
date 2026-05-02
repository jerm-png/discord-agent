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
    get_memory_counts,
    is_task_completion,
    set_pending_reflection,
    get_pending_reflection,
    validate_memory,
    archive_memory,
    check_stale_memories,
    save_conversation_history,
    load_all_conversation_histories,
    MEMORY_ISOLATED_CHANNELS,
)

from tools.tool_definitions import (
    TOOL_DEFINITIONS,
    execute_tool
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

`!handoff` — Generate a dense memory snapshot document for pasting into a new AI session. Works in any channel."""


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
    """Returns the last 50 messages whose content is a plain string.
    Filters out intermediate tool_use/tool_result messages (non-serializable
    SDK objects) so the persisted list is clean JSON and safe to restore."""
    return [
        m for m in history
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
    Removes orphaned tool_result blocks from conversation history.
    A tool_result is orphaned when the preceding assistant message lacks
    a matching tool_use block with the same tool_use_id.
    Returns (cleaned_history, count_stripped).
    """
    stripped = 0
    cleaned = []

    for msg in history:
        content = msg.get("content")
        role = msg.get("role")

        if role == "user" and isinstance(content, list):
            valid_ids = set()
            if cleaned:
                prev = cleaned[-1]
                if prev.get("role") == "assistant":
                    prev_content = prev.get("content", [])
                    if isinstance(prev_content, list):
                        for block in prev_content:
                            if (hasattr(block, "type")
                                    and block.type == "tool_use"):
                                valid_ids.add(block.id)
                            elif (isinstance(block, dict)
                                  and block.get("type") == "tool_use"):
                                valid_ids.add(block.get("id"))

            surviving = []
            for block in content:
                is_tr = (
                    (isinstance(block, dict)
                     and block.get("type") == "tool_result")
                    or (hasattr(block, "type")
                        and getattr(block, "type") == "tool_result")
                )
                if is_tr:
                    tid = (
                        block.get("tool_use_id")
                        if isinstance(block, dict)
                        else getattr(block, "tool_use_id", None)
                    )
                    if tid in valid_ids:
                        surviving.append(block)
                    else:
                        stripped += 1
                else:
                    surviving.append(block)

            if surviving:
                cleaned.append({**msg, "content": surviving})
            # else: entire message was orphaned tool_results — drop it
        else:
            cleaned.append(msg)

    return cleaned, stripped


def _extract_original_message(full_content: str) -> str:
    """Extracts the user's original message from the context-prefixed stored string."""
    if "Current message: " in full_content:
        return full_content.split("Current message: ", 1)[1].strip()
    lines = full_content.split("\n", 1)
    if len(lines) > 1 and lines[0].startswith("[Channel:"):
        return lines[1].strip()
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


async def process_tool_calls(response, guild, tool_call_count):
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

            # Execute the tool off the event loop thread
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, execute_tool, tool_name, tool_inputs
            )

            # Show tool activity in status channel
            await send_to_channel(
                guild,
                STATUS_CHANNEL,
                f"Tool used: {tool_name}"
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
    mem_counts = await loop.run_in_executor(None, get_memory_counts)

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

    report = (
        "**System Status**\n"
        f"Ollama: {ollama_status}\n"
        f"FFmpeg: {ffmpeg_status}\n"
        f"Memory — strategic: {mem_counts['strategic']} | "
        f"operational: {mem_counts['operational']} | "
        f"analytical: {mem_counts['analytical']}\n"
        f"Conversation histories: {len(conversation_history)} user(s)\n"
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
    project_tag: str = None
):
    """
    Shared Claude processing pipeline used by on_message and /listen.
    Handles memory retrieval, the agentic tool loop, memory storage,
    reflection, and logging.
    """
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    task_completed = is_task_completion(user_message)

    memories = get_relevant_memories(
        user_message, channel_name=channel.name
    )
    memory_context = format_memory_for_prompt(memories)

    channel_purpose = CHANNEL_PURPOSE.get(
        channel.name, "General"
    )
    channel_ctx = (
        f"[Channel: #{channel.name} | Purpose: {channel_purpose}]"
    )

    full_message = user_message
    if memory_context:
        full_message = (
            f"{memory_context}\n\n"
            f"Current message: {user_message}"
        )

    full_message = f"{channel_ctx}\n{full_message}"

    # ── FILE INJECTION ────────────────────────────────────────
    file_injection_chars = 0
    all_user_files = list(attached_files.get(user_id, []))
    is_isolated_channel = channel.name in MEMORY_ISOLATED_CHANNELS

    if all_user_files:
        if is_isolated_channel:
            user_files = [
                f for f in all_user_files
                if f.get("channel_name") == channel.name
            ]
        else:
            user_files = [
                f for f in all_user_files
                if f.get("channel_name") not in MEMORY_ISOLATED_CHANNELS
            ]

        doc_files = [f for f in user_files if f["content_type"] == "document"]
        img_files = [f for f in user_files if f["content_type"] == "image"]

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

        if img_files:
            content_blocks = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img["base64_data"],
                    },
                }
                for img in img_files
            ]
            content_blocks.append({"type": "text", "text": full_message})
            conversation_history[user_id].append({
                "role": "user",
                "content": content_blocks,
            })
        else:
            conversation_history[user_id].append({
                "role": "user",
                "content": full_message,
            })
    else:
        conversation_history[user_id].append({
            "role": "user",
            "content": full_message,
        })

    await send_to_channel(
        guild,
        STATUS_CHANNEL,
        f"Processing request from {author_display_name}..."
    )

    async with channel.typing():
        try:
            tool_call_count = 0
            final_response_text = ""
            tool_mode = CHANNEL_TOOL_MODE.get(channel.name, "none")
            if tool_mode == "full":
                active_tools = TOOL_DEFINITIONS
            elif tool_mode == "search_only":
                active_tools = [
                    t for t in TOOL_DEFINITIONS
                    if t["name"] in SEARCH_ONLY_TOOL_NAMES
                ]
            else:
                active_tools = []

            while True:
                api_params = {
                    "model": MAIN_MODEL,
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "messages": conversation_history[user_id],
                }
                if active_tools:
                    api_params["tools"] = active_tools

                response = client.messages.create(**api_params)

                if response.stop_reason == "tool_use":
                    conversation_history[user_id].append({
                        "role": "assistant",
                        "content": response.content
                    })
                    tool_results, tool_call_count = \
                        await process_tool_calls(
                            response, guild, tool_call_count
                        )
                    conversation_history[user_id].append({
                        "role": "user",
                        "content": tool_results
                    })
                    continue

                for block in response.content:
                    if hasattr(block, "text"):
                        final_response_text += block.text

                conversation_history[user_id].append({
                    "role": "assistant",
                    "content": final_response_text
                })
                break

            conversation_history[user_id] = \
                conversation_history[user_id][-20:]

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
                    channel_name=channel.name,
                    memory_mode=memory_mode
                )

                if task_completed:
                    experiences = get_recent_experiences(
                        limit=5,
                        task_completed_only=True
                    )
                    await run_reflection_loop(guild, experiences)

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

            await send_to_channel(
                guild,
                STATUS_CHANNEL,
                f"Response delivered to {author_display_name}. Ready."
            )

            if stale_count:
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
                user_id,
                _saveable_history(conversation_history[user_id])
            )

        except Exception as e:
            await channel.send("Something went wrong — please try again.")
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"{tag_owner()}Error for {author_display_name}: {str(e)}"
            )


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
    for user_id, history in raw_histories.items():
        cleaned, count = strip_orphaned_tool_results(history)
        raw_histories[user_id] = cleaned
        total_stripped += count
    conversation_history.update(raw_histories)
    if total_stripped:
        print(
            f"[Startup] Stripped {total_stripped} orphaned "
            f"tool_result block(s) from loaded histories."
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, check_ollama_health)
    await loop.run_in_executor(None, check_ffmpeg)
    print(f"PerMyLastBot is online as {bot.user} "
          f"({len(conversation_history)} histories restored)")
    await tree.sync()

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

    channel_name = message.channel.name

    if channel_name in CHANNEL_IGNORED:
        return

    memory_mode = CHANNEL_MEMORY_MODE.get(channel_name, "ephemeral")
    project_tag = CHANNEL_PROJECT_TAG.get(channel_name)

    # ── VOICE MESSAGE ATTACHMENTS ─────────────────────────
    voice_attachment = next(
        (
            a for a in message.attachments
            if a.content_type and a.content_type.startswith("audio/")
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
        await process_user_message(
            transcription,
            str(message.author.id),
            message.author.display_name,
            message.guild,
            message.channel,
            speak=True,
            memory_mode=memory_mode,
            project_tag=project_tag
        )
        return

    # ── FILE ATTACHMENTS (non-audio) ──────────────────────
    non_audio_attachments = [
        a for a in message.attachments
        if not (a.content_type and a.content_type.startswith("audio/"))
    ]

    if non_audio_attachments:
        uid = str(message.author.id)
        loop = asyncio.get_running_loop()
        for attachment in non_audio_attachments:
            ext = os.path.splitext(attachment.filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
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

            await message.channel.send(
                f"📎 {attachment.filename} received and ready. "
                f"Ask me anything about it or keep uploading."
            )

            char_count = (
                len(file_data.get("text_content", ""))
                if file_data["content_type"] == "document"
                else len(file_data.get("base64_data", ""))
            )
            await send_to_channel(
                message.guild, LOG_CHANNEL,
                f"File received | {attachment.filename} | "
                f"{file_data['content_type']} | "
                f"{char_count:,} chars | Channel: #{channel_name}"
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
            await process_user_message(
                raw_text,
                uid,
                message.author.display_name,
                message.guild,
                message.channel,
                speak=False,
                memory_mode=memory_mode,
                project_tag=project_tag,
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

    # !clear: wipe in-memory conversation history and attached files
    if is_prefix and user_message.lower() == "clear":
        uid = str(message.author.id)
        old_history = conversation_history.get(uid, [])
        _, stripped = strip_orphaned_tool_results(old_history)
        conversation_history[uid] = []
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
        uid = str(message.author.id)
        history = conversation_history.get(uid, [])
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
        await process_user_message(
            original_message,
            str(message.author.id),
            message.author.display_name,
            message.guild,
            message.channel,
            speak=False,
            memory_mode=memory_mode,
            project_tag=project_tag,
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

    await process_user_message(
        user_message,
        str(message.author.id),
        message.author.display_name,
        message.guild,
        message.channel,
        speak=speak,
        memory_mode=memory_mode,
        project_tag=project_tag
    )


# ============================================================
# START THE BOT
# ============================================================

bot.run(os.getenv("DISCORD_TOKEN"))