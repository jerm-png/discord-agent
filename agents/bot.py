import os
from dotenv import load_dotenv

# Load environment variables FIRST before any other
# imports that may call os.getenv at module level
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Now import everything else
import asyncio
import base64
import contextlib
import io
import json
import shutil
import sqlite3
import sys
import urllib.request
from datetime import datetime

import discord
from discord import app_commands
from anthropic import APIStatusError
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
    get_handoff_memories,
    memory_stats,
    MEMORY_ISOLATED_CHANNELS,
    log_conversation_turn,
    search_conversations,
    load_all_conversation_histories,
    cleanup_old_conversation_log,
    backfill_conversation_log,
    get_reasoning_trace,
    pin_memory,
    unpin_memory,
    get_entity_profile,
    list_entities,
)

from session import init_session_table

from voice_input import (
    transcribe_attachment,
    check_ffmpeg,
)

from config import (
    MAIN_MODEL,
    BACKGROUND_MODEL,
    OLLAMA_MODEL,
    LOG_CHANNEL,
    STATUS_CHANNEL,
    FILE_CONTENT_CHAR_LIMIT,
    POPPLER_PATH,
    PDF_VISION_THRESHOLD,
    PDF_VISION_MAX_PAGES,
    THREADED_CHANNELS,
    THREAD_ARCHIVE_DURATION,
    CHANNEL_MEMORY_MODE,
    CHANNEL_PROJECT_TAG,
    CHANNEL_IGNORED,
    CHANNEL_AGENT_HINTS,
)
from model import (
    client,
    call_background_model,
)
from services import (
    send_to_channel,
    send_long_message,
    post_status,
)
from state import (
    conversation_history,
    attached_files,
    pending_goals,
    execution_context,
    gate_pending,
    thread_agent_pins,
    _last_token_usage,
    BOT_START_TIME,
    AGENT_DEFINITIONS,
)
from orchestrator import (
    process_user_message,
    execute_goal,
    run_goal_planning,
    run_goal_modification,
    resume_goal_from_gate,
    run_consolidate_command,
    consolidate_all_layers,
    run_scheduled_consolidation,
    run_proactive_flag_surfacing,
    extract_and_store_memories,
    run_reflection_loop,
    _parse_goal_trigger,
    process_tool_calls,
    _is_confabulation_check,
    strip_orphaned_tool_results,
    _saveable_history,
    tag_owner,
    CREW_GOAL_PLANNER_SYSTEM_PROMPT,
)

# ============================================================
# CONFIGURATION
# ============================================================

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")

# ── Langfuse observability ───────────────────────────
import state as _state_module
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_HOST = os.getenv(
    "LANGFUSE_HOST", "https://us.cloud.langfuse.com"
)
try:
    if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
        from langfuse import Langfuse
        _state_module._langfuse = Langfuse(
            secret_key=LANGFUSE_SECRET_KEY,
            public_key=LANGFUSE_PUBLIC_KEY,
            host=LANGFUSE_HOST,
        )
        print("[Langfuse] Observability active")
    else:
        print("[Langfuse] No keys found — tracing disabled")
except Exception as _lf_err:
    print(f"[Langfuse] Init failed — tracing disabled: {_lf_err}")

# ── Agent definitions ────────────────────────────────────────
AGENTS_DIR = r"C:\Users\Jerm\.claude\agents"
AGENT_KEYWORDS_CACHE_PATH = os.path.join(
    project_root, "memory", "agent_keywords_cache.json"
)

SUPPORTED_DOC_EXTENSIONS   = {".pdf", ".txt", ".md", ".csv", ".docx"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_EXTENSIONS = SUPPORTED_DOC_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS
IMAGE_MEDIA_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

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

`!crew [description]` — Like `!goal`, but every step is assigned to a specialist agent. The planner selects the best agent per step based on available agents. Same approval and gate flow as `!goal`.

`!agent [slug] [message]` — Activate a specific specialist agent for one response. Example: `!agent health-researcher what peptides help with EBV reactivation`. Reverts to default after the response.

`!agents` — List all available specialist agents with their slugs and descriptions.

`!search [query]` — Full-text search of your past conversations. Scans the permanent archive and summarises matching exchanges. Respects channel isolation — `#health-tracking` searches only health conversations.

`!trace [N]` — Show last N reasoning steps (tool calls, inputs, results) for this channel. Default 10, max 25.

`!pin <id>` — Pin a memory by ID so it is never auto-archived or consolidated.

`!unpin <id>` — Remove pin from a memory.

`!save-verbatim [layer] <content>` — Write content directly to memory, bypassing AI extraction. Layer is `strategic` (default), `operational`, or `analytical`. Replies with the assigned memory ID.

`!roster` — List all people tracked in entity memory
`!profile [name]` — View full profile and fact history for a person
`!profile-delete <id>` — Delete a wrong fact by ID. Find IDs with `!profile [name]`
`!save-thread` — Summarize and save the current thread to strategic memory. Run inside any thread."""


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
    cache_write_tokens = getattr(response.usage, 'cache_creation_input_tokens', 0)
    cache_read_tokens = getattr(response.usage, 'cache_read_input_tokens', 0)
    est_cost = (
        (in_tokens / 1_000_000 * 3.00) +
        (out_tokens / 1_000_000 * 15.00) +
        (cache_write_tokens / 1_000_000 * 3.75) +
        (cache_read_tokens / 1_000_000 * 0.30)
    )
    cache_note = (
        f" | cache_write: {cache_write_tokens:,} | cache_read: {cache_read_tokens:,}"
        if cache_write_tokens or cache_read_tokens else ""
    )
    await send_to_channel(
        guild, LOG_CHANNEL,
        f"Handoff generated | Channel: #{channel_name} | "
        f"Tokens — in: {in_tokens:,} | out: {out_tokens:,}"
        + cache_note
        + f" | est. cost: ${est_cost:.4f}"
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


def select_agent(message_text: str, channel_name: str,
                 context_id: int = 0) -> tuple:
    """
    Returns (agent_slug, trigger_type) for auto-detection.
    trigger_type: "channel" | "keyword" | "explicit" | "pinned" | "none"

    Priority order:
    0. Thread pin — if context_id is in thread_agent_pins, return that slug.
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

    if context_id and context_id in thread_agent_pins:
        return thread_agent_pins[context_id], "pinned"

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
    import state as _st
    _st.BOT_START_TIME = datetime.now()
    _st.bot = bot
    init_session_table()

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
        asyncio.create_task(run_proactive_flag_surfacing(guild))
        asyncio.create_task(run_scheduled_consolidation(guild))


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
        _va_slug, _va_trigger = select_agent(transcription, channel_name, context_id)
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
            attached_files[(uid, context_id)].append(file_data)

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
            _fa_slug, _fa_trigger = select_agent(raw_text, channel_name, context_id)
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

    # !crew — crew mode: every step assigned to a specialist agent by the planner
    if is_prefix and user_message.lower().startswith("crew "):
        _crew_goal_text = user_message[5:].strip()
        if _crew_goal_text:
            _agent_slugs = ", ".join(sorted(AGENT_DEFINITIONS.keys())) or "none loaded"
            _crew_planner_prompt = CREW_GOAL_PLANNER_SYSTEM_PROMPT
            _crew_user_content = (
                f"Available agent slugs: {_agent_slugs}\n\n"
                f"Goal: {_crew_goal_text}"
            )
            asyncio.create_task(
                run_goal_planning(
                    _crew_user_content, uid, message.author.display_name,
                    message.guild, message.channel, memory_mode, project_tag,
                    planner_prompt=_crew_planner_prompt, crew_mode=True
                )
            )
        else:
            await message.channel.send(
                "Usage: `!crew [goal description]`"
            )
        return

    # Gate commands — mid-execution pauses awaiting !continue/!adjust/!retry/!skip
    if uid in gate_pending:
        gate = gate_pending[uid]
        gate_type = gate["type"]
        if is_prefix:
            lm = user_message.lower()

            def _capture_gate_decision(action: str, changes: str = ""):
                _pg = pending_goals.get(uid, {})
                _goal_desc = _pg.get("goal", "unknown goal")
                _step = gate.get("step_num", gate.get("step_index", 0) + 1)
                _pt = _pg.get("project_tag") or project_tag
                save_experience(
                    request_summary=f"Gate decision on: {_goal_desc[:100]}",
                    approach_used=f"!{action} at step {_step}" + (f" — changes: {changes[:80]}" if changes else ""),
                    outcome="in_progress",
                    lesson=f"User chose '!{action}' at execution gate (step {_step}).",
                    task_completed=False,
                    project_tag=_pt
                )

            if lm == "continue":
                _capture_gate_decision("continue")
                asyncio.create_task(
                    resume_goal_from_gate(
                        uid, message.author.display_name, "continue"
                    )
                )
                return
            if lm.startswith("adjust "):
                changes = user_message[7:].strip()
                if changes:
                    _capture_gate_decision("adjust", changes)
                    asyncio.create_task(
                        resume_goal_from_gate(
                            uid, message.author.display_name, "adjust", changes
                        )
                    )
                return
            if lm == "skip" and gate_type == "step_failure":
                _capture_gate_decision("skip")
                asyncio.create_task(
                    resume_goal_from_gate(
                        uid, message.author.display_name, "skip"
                    )
                )
                return
            if lm == "retry" and gate_type == "step_failure":
                _capture_gate_decision("retry")
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
                    execution_context.pop(uid, None)
                    # Decision-as-memory capture
                    _goal_desc = pg.get("goal", "unknown goal")
                    _step_count = len(pg.get("steps", []))
                    _pt = pg.get("project_tag") or project_tag
                    save_experience(
                        request_summary=f"Goal approved: {_goal_desc[:120]}",
                        approach_used=f"!approve — {_step_count}-step plan queued for execution",
                        outcome="pending",
                        lesson="User approved goal execution. Outcome to be captured on completion.",
                        task_completed=False,
                        project_tag=_pt
                    )
                    await message.channel.send("✅ Executing plan...")
                    asyncio.create_task(
                        execute_goal(uid, message.author.display_name)
                    )
                return
            if lm == "cancel":
                # Decision-as-memory capture
                _goal_desc = pg.get("goal", "unknown goal")
                _steps_done = pg.get("current_step", 0)
                _total_steps = len(pg.get("steps", []))
                _pt = pg.get("project_tag") or project_tag
                save_experience(
                    request_summary=f"Goal cancelled: {_goal_desc[:120]}",
                    approach_used=f"!cancel at step {_steps_done}/{_total_steps}",
                    outcome="cancelled",
                    lesson=f"Goal was cancelled after {_steps_done} of {_total_steps} steps.",
                    task_completed=False,
                    project_tag=_pt
                )
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
        _current_pin = thread_agent_pins.get(context_id)
        lines = ["**Available Specialist Agents**\n"]
        for _slug in sorted(AGENT_DEFINITIONS.keys()):
            _ag = AGENT_DEFINITIONS[_slug]
            _desc = _ag["description"][:120] if _ag["description"] else "No description."
            _pin_marker = " 📌" if _current_pin == _slug else ""
            lines.append(f"`{_slug}`{_pin_marker} — **{_ag['name']}**: {_desc}")
        if _current_pin and _current_pin in AGENT_DEFINITIONS:
            lines.append(
                f"\n📌 **{AGENT_DEFINITIONS[_current_pin]['name']}** is pinned "
                f"for this thread. Use `!use default` to clear."
            )
        await send_long_message(message.channel, "\n".join(lines))
        return

    # !use [slug] or !use default: pin an agent for this thread (or clear the pin)
    if is_prefix and user_message.lower().startswith("use "):
        _use_arg = user_message[4:].strip().lower()
        if _use_arg == "default":
            thread_agent_pins.pop(context_id, None)
            await message.channel.send(
                "📌 Agent pin cleared — auto-selection resumed"
            )
            return
        _use_slug = None
        if _use_arg in AGENT_DEFINITIONS:
            _use_slug = _use_arg
        else:
            for _s, _a in AGENT_DEFINITIONS.items():
                if _use_arg == _a["name"].lower() or _use_arg in _s:
                    _use_slug = _s
                    break
        if not _use_slug:
            _available = ", ".join(f"`{s}`" for s in sorted(AGENT_DEFINITIONS.keys()))
            await message.channel.send(
                f"Unknown agent `{_use_arg}`. Available: {_available}"
            )
            return
        thread_agent_pins[context_id] = _use_slug
        await message.channel.send(
            f"📌 **{AGENT_DEFINITIONS[_use_slug]['name']}** pinned for this thread"
        )
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

        _ag_channel, context_id = await _resolve_response_channel(
            message, channel_name, _rest
        )
        if isinstance(message.channel, discord.Thread):
            thread_agent_pins[context_id] = _found_slug
            await message.channel.send(
                f"🤖 Using **{AGENT_DEFINITIONS[_found_slug]['name']}** "
                f"— 📌 pinned for this thread"
            )
        else:
            await message.channel.send(
                f"🤖 Using **{AGENT_DEFINITIONS[_found_slug]['name']}**"
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

    # !trace [N]: display recent reasoning trace entries for this channel
    if is_prefix and (
        user_message.lower() == "trace"
        or user_message.lower().startswith("trace ")
    ):
        _trace_arg = user_message[6:].strip() if " " in user_message else ""
        _trace_limit = 10
        if _trace_arg:
            try:
                _trace_limit = min(int(_trace_arg), 25)
            except ValueError:
                _trace_limit = 10
        _traces = get_reasoning_trace(uid, channel_name, _trace_limit)
        if not _traces:
            await message.channel.send(
                "No reasoning trace found for this channel in the current session."
            )
            return
        _trace_lines = []
        for _t in _traces:
            _ts = _t["timestamp"][:19].replace("T", " ") if _t["timestamp"] else "?"
            _summary = _t["result_summary"] or ""
            if len(_summary) > 120:
                _summary = _summary[:120] + "…"
            _trace_lines.append(
                f"[{_ts} UTC] iter={_t['iteration']} tool={_t['tool_name']}\n"
                f"→ {_summary}"
            )
        # Split into ≤1900-char chunks so each fits in one code block message
        _chunks = []
        _cur: list = []
        _cur_len = 0
        for _entry in _trace_lines:
            _entry_len = len(_entry) + 2  # +2 for the "\n\n" separator
            if _cur and _cur_len + _entry_len > 1900:
                _chunks.append("\n\n".join(_cur))
                _cur = [_entry]
                _cur_len = len(_entry)
            else:
                _cur.append(_entry)
                _cur_len += _entry_len
        if _cur:
            _chunks.append("\n\n".join(_cur))
        for _chunk in _chunks:
            await message.channel.send(f"```\n{_chunk}\n```")
        return

    # ── !roster ──────────────────────────────────────────────
    if is_prefix and user_message.lower() == "roster":
        people = list_entities(entity_type="person")
        if not people:
            await message.channel.send(
                "No people tracked yet. Mention someone by name "
                "in director-workspace and use !profile to start "
                "building their record."
            )
            return
        lines = ["**People tracked in entity memory:**\n"]
        for p in people:
            updated = p["updated_at"][:10] if p["updated_at"] else "—"
            role_str = f" — {p['role']}" if p["role"] else ""
            lines.append(
                f"• **{p['name']}**{role_str} "
                f"| {p['fact_count']} fact(s) "
                f"| last updated {updated}"
            )
        await send_long_message(message.channel, "\n".join(lines))
        return

    # ── !profile [name] ──────────────────────────────────────
    if is_prefix and user_message.lower().startswith("profile"):
        parts = user_message.split(None, 1)
        if len(parts) < 2:
            await message.channel.send(
                "Usage: `!profile [name]` — e.g. `!profile Marcus`"
            )
            return
        _pname = parts[1].strip()
        _prof = get_entity_profile(_pname)
        if not _prof:
            await message.channel.send(
                f"No profile found for **{_pname}**. "
                f"They will be added automatically when you "
                f"discuss them in director-workspace."
            )
            return
        lines = [f"**Profile: {_prof['name']}**"]
        if _prof["role"]:
            lines.append(f"Role: {_prof['role']}")
        if _prof["context"]:
            lines.append(f"Context: {_prof['context']}")
        lines.append("")
        if _prof["facts"]:
            for cat, facts in _prof["facts"].items():
                lines.append(f"**{cat.title()}**")
                for f in facts:
                    date = f["recorded_at"][:10]
                    lines.append(
                        f"  • ID:{f['id']} [{date}] {f['fact']}"
                    )
                lines.append("")
        else:
            lines.append("No facts recorded yet.")
        await send_long_message(message.channel, "\n".join(lines))
        return

    # ── !profile-delete <id> ────────────────────────────
    if is_prefix and user_message.lower().startswith(
            "profile-delete"):
        parts = user_message.split(None, 1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.channel.send(
                "Usage: `!profile-delete <id>` — "
                "find IDs with `!profile [name]`"
            )
            return
        _fact_id = int(parts[1].strip())
        try:
            conn = sqlite3.connect(
                os.path.join(
                    os.path.dirname(__file__),
                    "..", "memory", "database.db"
                )
            )
            cursor = conn.execute(
                "SELECT f.category, f.fact, e.name "
                "FROM entity_facts f "
                "JOIN entities e ON e.id = f.entity_id "
                "WHERE f.id = ?",
                (_fact_id,)
            )
            row = cursor.fetchone()
            if not row:
                await message.channel.send(
                    f"No fact found with ID {_fact_id}."
                )
                conn.close()
                return
            _cat, _fact_text, _person = row
            conn.execute(
                "DELETE FROM entity_facts WHERE id = ?",
                (_fact_id,)
            )
            conn.commit()
            conn.close()
            await message.channel.send(
                f"Deleted [{_cat}] fact (ID:{_fact_id}) "
                f"for {_person}."
            )
        except Exception as e:
            await message.channel.send(
                f"Error deleting fact: {e}"
            )
        return

    # ── !save-thread ─────────────────────────────────────
    if is_prefix and user_message.lower() == "save-thread":
        _st_channel = message.channel
        _is_thread = isinstance(
            _st_channel, discord.Thread
        )
        if not _is_thread:
            await message.channel.send(
                "Use `!save-thread` inside a thread — "
                "it saves the current thread's conversation "
                "to memory."
            )
            return

        # Fetch thread messages
        _st_messages = []
        async for _msg in _st_channel.history(
            limit=200, oldest_first=True
        ):
            if _msg.author.bot and not _msg.author == client.user:
                continue
            role = (
                "assistant" if _msg.author == client.user
                else "user"
            )
            if _msg.content and _msg.content.strip():
                _st_messages.append({
                    "role": role,
                    "content": _msg.content.strip(),
                    "timestamp": _msg.created_at.isoformat(),
                })

        if not _st_messages:
            await message.channel.send(
                "No messages found in this thread to save."
            )
            return

        # Build transcript for summarization
        _transcript = "\n\n".join(
            f"{m['role'].title()}: {m['content'][:400]}"
            for m in _st_messages
        )

        # Summarize via background model
        _summary_prompt = (
            "Summarize this conversation thread into a "
            "structured memory record. Include: what was "
            "worked on, decisions made, outcomes, and any "
            "unresolved items. Be specific and factual. "
            "Maximum 400 words.\n\n"
            f"Thread: #{_st_channel.name}\n\n"
            f"{_transcript[:3000]}"
        )

        await message.channel.send(
            "Summarizing thread and saving to memory..."
        )

        try:
            _summary = await call_background_model(
                _summary_prompt
            )
            _summary = _summary.strip()
        except Exception as _e:
            await message.channel.send(
                f"Summarization failed: {_e}"
            )
            return

        # Determine channel context
        _parent_name = (
            _st_channel.parent.name
            if hasattr(_st_channel, "parent")
            and _st_channel.parent
            else channel_name
        )
        _is_isolated = (
            _parent_name in MEMORY_ISOLATED_CHANNELS
        )

        # Save summary as strategic memory
        loop = asyncio.get_running_loop()
        try:
            _mem_id = await loop.run_in_executor(
                None,
                lambda: save_strategic_memory(
                    content=(
                        f"[THREAD SUMMARY: {_st_channel.name}]\n"
                        + _summary
                    ),
                    category="thread_summary",
                    confidence=0.85,
                    source="save-thread",
                    project_tag=_parent_name,
                    channel_name=_parent_name,
                )
            )
        except Exception as _e:
            await message.channel.send(
                f"Failed to save to memory: {_e}"
            )
            return

        # Log raw turns to conversation_log if not isolated
        if not _is_isolated:
            _thread_context_id = _st_channel.id
            for _tm in _st_messages:
                await loop.run_in_executor(
                    None,
                    lambda m=_tm: log_conversation_turn(
                        user_id=str(uid),
                        context_id=_thread_context_id,
                        channel_name=_parent_name,
                        role=m["role"],
                        content=m["content"],
                        project_tag=_parent_name,
                    )
                )

        await message.channel.send(
            f"Thread saved to strategic memory "
            f"(ID: {_mem_id}).\n"
            f"Summary:\n> {_summary[:300]}"
            + ("..." if len(_summary) > 300 else "")
        )
        return

    # !pin <id>: pin an operational memory so it is never auto-archived or consolidated
    if is_prefix and user_message.lower().startswith("pin "):
        _pin_arg = user_message[4:].strip()
        try:
            _pin_id = int(_pin_arg)
        except ValueError:
            await message.channel.send("Usage: `!pin <memory_id>`")
            return
        if pin_memory(_pin_id):
            await message.channel.send(
                f"📌 Memory {_pin_id} pinned — it will not be archived or consolidated."
            )
        else:
            await message.channel.send(f"Memory {_pin_id} not found.")
        return

    # !unpin <id>: remove pin from an operational memory
    if is_prefix and user_message.lower().startswith("unpin "):
        _unpin_arg = user_message[6:].strip()
        try:
            _unpin_id = int(_unpin_arg)
        except ValueError:
            await message.channel.send("Usage: `!unpin <memory_id>`")
            return
        if unpin_memory(_unpin_id):
            await message.channel.send(f"Memory {_unpin_id} unpinned.")
        else:
            await message.channel.send(f"Memory {_unpin_id} not found.")
        return

    # !save-verbatim [layer] <content>: write directly to memory, bypassing AI extraction
    if is_prefix and user_message.lower().startswith("save-verbatim"):
        _sv_body = user_message[len("save-verbatim"):].strip()
        _sv_valid_layers = ("strategic", "operational", "analytical")
        _sv_parts = _sv_body.split(None, 1)
        if _sv_parts and _sv_parts[0].lower() in _sv_valid_layers:
            _sv_layer = _sv_parts[0].lower()
            _sv_content = _sv_parts[1].strip() if len(_sv_parts) > 1 else ""
        else:
            _sv_layer = "strategic"
            _sv_content = _sv_body
        if not _sv_content:
            await message.channel.send("Usage: `!save-verbatim [strategic|operational|analytical] <content>`")
            return
        if _sv_layer == "strategic":
            _sv_id = save_strategic_memory(
                content=_sv_content,
                category="manual",
                source="!save-verbatim",
                channel_name=channel_name,
                project_tag=project_tag,
            )
        elif _sv_layer == "operational":
            _sv_id = save_operational_memory(
                content=_sv_content,
                project_name="manual",
                channel_name=channel_name,
                project_tag=project_tag,
            )
        else:
            _sv_id = save_analytical_memory(
                pattern=_sv_content,
                pattern_type="manual",
                channel_name=channel_name,
                project_tag=project_tag,
            )
        if _sv_id:
            await message.channel.send(f"Saved to {_sv_layer} memory (ID: {_sv_id}).")
        else:
            await message.channel.send(f"Saved to {_sv_layer} memory.")
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
        cleared_files = len(attached_files.pop((uid, context_id), []))
        cleared_pin = thread_agent_pins.pop(context_id, None)
        note_parts = []
        if stripped:
            note_parts.append(f"{stripped} orphaned tool block(s) cleaned")
        if cleared_files:
            note_parts.append(f"{cleared_files} attached file(s) removed")
        if cleared_pin and cleared_pin in AGENT_DEFINITIONS:
            note_parts.append(
                f"{AGENT_DEFINITIONS[cleared_pin]['name']} pin cleared"
            )
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
        _retry_slug, _retry_trigger = select_agent(original_message, channel_name, context_id)
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

    _auto_slug, _auto_trigger = select_agent(user_message, channel_name, context_id)
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
