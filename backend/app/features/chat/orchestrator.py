# ============================================================
# orchestrator.py — Core message processing and goal execution
# Ported from agents/orchestrator.py for FastAPI + WebSocket.
# Discord dependencies replaced with ws_manager and logger.
# See ORCHESTRATOR_PORT_PLAN.md for full mapping.
# ============================================================

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.request
import datetime
from datetime import datetime
from collections import defaultdict

from anthropic import APIStatusError

from app.core.config import (
    MAIN_MODEL,
    BACKGROUND_MODEL,
    DB_PATH,
    MAX_TOOL_CALLS,
    MAX_REASONING_ITERATIONS,
    AGENT_INJECT_CHAR_LIMIT,
    GOAL_GATE_MODE,
    HISTORY_RAW_WINDOW,
    HISTORY_SUMMARY_ROLE,
    CONSOLIDATION_THRESHOLDS,
    WORKSPACES,
    ISOLATED_WORKSPACES,
    FILE_CONTENT_CHAR_LIMIT,
    POPPLER_PATH,
    PDF_VISION_THRESHOLD,
    PDF_VISION_MAX_PAGES,
)
from app.core.model import (
    client,
    call_background_model,
    call_background_model_json,
)
from app.core.ws_manager import ws_manager
from app.core.state import (
    conversation_history,
    attached_files,
    pending_goals,
    execution_context,
    gate_pending,
    thread_agent_pins,
    _consolidation_cooldown,
    _last_token_usage,
    BOT_START_TIME,
    AGENT_DEFINITIONS,
    SYSTEM_PROMPT,
)
import app.core.state as state
from app.db.memory_manager import (
    get_relevant_memories,
    format_memory_for_prompt,
    save_strategic_memory,
    save_operational_memory,
    save_analytical_memory,
    save_experience,
    save_content_flag,
    memory_stats,
    get_consolidation_candidates,
    archive_memory,
    log_conversation_turn,
    get_entity_by_id,
    get_entity_tags,
    get_entity_timeline,
    save_entity_fact,
    search_conversations,
    log_reasoning_trace,
    check_stale_memories,
    auto_archive_stale_operational,
    list_entities,
    format_entity_profile_for_prompt,
    upsert_entity,
    add_entity_fact,
    drain_rubric_rejection_log,
    is_task_completion,
    get_recent_experiences,
    extract_and_save_health_protocols,
    _health_protocol_log,
    save_conversation_history,
    evaluate_memory_rubric,
    get_unresolved_high_priority_flags,
    get_top_similar_memories,
    record_rubric_rejection,
    check_operational_duplicate,
    set_pending_reflection,
    medbay_add_protocol,
    medbay_update_protocol_dose,
    medbay_stop_protocol,
    medbay_add_lab_result,
    medbay_add_followup,
    medbay_list_protocol,
)
from app.features.tools.tool_definitions import (
    TOOL_DEFINITIONS,
    execute_tool,
    drain_escalation_queue,
)
from app.features.session.session import (
    load_session_state,
    update_session_state,
    append_recent_action,
    clear_session_state,
    format_session_context,
)
try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

logger = logging.getLogger(__name__)


CONFABULATION_TRIGGERS = (
    "you said", "you told me", "you mentioned", "did you say",
    "show me where", "you recommended", "you suggested",
    "you told", "you wrote", "you claimed",
)


def _is_confabulation_check(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in CONFABULATION_TRIGGERS)


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


def _saveable_history(history: list) -> list:
    """Returns the last 50 plain-string messages after bidirectional tool-block
    validation. Strips orphaned tool_use/tool_result blocks before filtering
    so corrupted exchanges are never written to SQLite."""
    validated, _ = strip_orphaned_tool_results(history)
    return [
        m for m in validated
        if isinstance(m.get("content"), str)
    ][-50:]


def _now_iso() -> str:
    """UTC ISO 8601 timestamp with offset, e.g. 2026-05-13T14:23:45+00:00.
    Used as the canonical timestamp on every conversation_history entry
    so the /messages endpoint can return real times to the frontend."""
    from datetime import timezone as _tz
    return datetime.now(_tz.utc).isoformat()


# Goal-mode persistence is retired. The functions below are kept as dead
# code for reference; these stubs let the dead paths still resolve at
# import time without touching the database.
def save_goal_state(*_args, **_kwargs) -> None:
    return None


def delete_goal_state(*_args, **_kwargs) -> None:
    return None


def _persist_goal_state(user_id: str) -> None:
    """
    Snapshot the in-memory pending_goals / execution_context /
    gate_pending entries for this user_id and write them to SQLite.
    Empty / popped entries are deleted from the table by save_goal_state.

    Called after every mutation of those dicts in the goal-mode flow so
    a server restart can rehydrate exactly where it left off. Cheap —
    each call is at most three SQLite UPSERTs against indexed rows.
    Wrapped in try/except so a transient DB failure can never block
    goal execution.
    """
    try:
        save_goal_state(user_id, "pending_goal", pending_goals.get(user_id))
        save_goal_state(
            user_id, "execution_context", execution_context.get(user_id)
        )
        save_goal_state(user_id, "gate_pending", gate_pending.get(user_id))
    except Exception as e:
        logger.warning(f"[goal state persist] {user_id}: {e}")


def append_history_turn(
    user_id: str, context_id: str, role: str, content: str,
    timestamp: str | None = None,
) -> None:
    """Append a single turn to the in-memory conversation_history for
    (user_id, context_id). Used by goal-mode paths that bypass
    process_user_message — !goal trigger, run_goal_planning's plan emission,
    execute_goal's final draft, and the cancel action confirmation.
    Each entry now carries an ISO timestamp so reloaded threads can
    render proper times instead of empty strings."""
    hist_key = (user_id, context_id)
    if hist_key not in conversation_history:
        conversation_history[hist_key] = []
    conversation_history[hist_key].append({
        "role": role,
        "content": content,
        "timestamp": timestamp or _now_iso(),
    })


_FLAG_CATEGORIES = {
    "stranger", "social_pressure", "money_scam", "body_sleep",
    "violence", "distress", "family", "personal_info",
    "sexual_curiosity", "adult_topics", "trust_isolation", "other",
}


def _clean_generated_title(raw: str) -> str:
    """Strip the most common framing the model wraps around a title:
    quotes, leading 'Title:' label, asterisks, surrounding whitespace.
    Returns the cleaned single-line title capped at 100 chars."""
    t = (raw or "").strip()
    if not t:
        return ""
    t = t.splitlines()[0].strip()
    for prefix in ("Title:", "title:", "Thread title:", "**"):
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix):].strip()
    t = t.strip('"\'`*').strip()
    return t[:100].strip()


async def _run_entity_thread_rename(
    thread_id: str,
    user_id: str,
    user_message: str,
    entity_name: str,
    current_title: str,
) -> None:
    """
    Background task: ask Haiku for a short topic-shaped title for an
    entity-linked thread on its first user message, then update the
    thread row via rename_thread. Never raises — a failure leaves the
    placeholder "Coaching: Name" title in place.
    """
    try:
        prompt = (
            "Generate a short, specific title (5-7 words MAX) for a "
            f"coaching conversation about {entity_name}. The opening "
            "message is below. Prefer the format "
            f"'{entity_name.split()[0]} — <Topic>' when natural, "
            "otherwise just the topic.\n\n"
            "Examples of the style:\n"
            "  Jay — AD Promotion Path\n"
            "  Sarah — Q4 Goal Recalibration\n"
            "  Delegation 90-Day Plan\n\n"
            "Return ONLY the title text. No quotes, no explanation, no "
            "label.\n\n"
            f"Opening message:\n{user_message[:600]}"
        )
        raw = await call_background_model(prompt)
        new_title = _clean_generated_title(raw)
        if not new_title or new_title == current_title:
            return
        from app.db.threads import rename_thread
        loop = asyncio.get_running_loop()
        updated = await loop.run_in_executor(
            None, rename_thread, thread_id, new_title, user_id,
        )
        if updated:
            logger.info(
                f"[entity rename] thread={thread_id} -> {new_title!r}"
            )
        else:
            logger.warning(
                f"[entity rename] rename returned None for "
                f"thread={thread_id} (ownership mismatch?)"
            )
    except Exception as e:
        logger.warning(f"[entity rename] failed: {e}")


_COACHING_CATEGORIES = {"note", "decision", "goal", "milestone"}

# Admin Prime → Institute Prime one-way bridge: when a message in the
# admin workspace contains any of these phrases, we cross-pull entity
# profiles from Institute Prime as ephemeral prompt context. Match is
# substring on the lowercased message — kept narrow so casual mentions
# of "team" in other contexts (e.g. "the Engineering team's bug") don't
# trigger an unnecessary roster pull.
_ADMIN_TEAM_QUERY_PHRASES = (
    "my team",
    "the team",
    "pull up team",
    "team patterns",
    "team dynamic",
    "what do you know about",
    "tell me about ",
    "remind me about ",
    "my directs",
    "my reports",
    "direct reports",
)


# ── Drop-and-File mode (Institute Prime, entity-linked threads) ──
# A "transcript dump" is detected by length, an attached document, or
# dialogue-style formatting. When detected, the orchestrator routes
# the message to Haiku for structured extraction instead of the normal
# conversation loop, then parks the items in state.pending_filings
# awaiting user confirmation.

_TRANSCRIPT_MIN_CHARS = 500

# A line like "Jerm: ...", "Alex Smith: ...", or "Q: ..." counts as a
# dialogue marker. Two or more such lines tip the message into
# transcript mode. The name pattern caps at three capitalised tokens
# so a random capitalised sentence doesn't false-positive.
_DIALOGUE_LINE_RE = re.compile(
    r"^\s*(?:[QA]|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}):\s+\S",
    re.MULTILINE,
)

# Confirmation/abandon intent regexes for the pending-filing reply.
# Anything else is interpreted as an edit instruction — i.e. the user
# rephrasing or adjusting, which triggers a re-extraction.
_FILING_CONFIRM_RE = re.compile(
    r"\b("
    r"save|file|ship|confirm|"
    r"looks?\s+good|good\s+to\s+go|go\s+ahead|do\s+it|"
    r"yes\s+please|yes\s+save|file\s+it|save\s+it|"
    r"file\s+this|save\s+this|file\s+them"
    r")\b",
    re.IGNORECASE,
)
_FILING_ABANDON_RE = re.compile(
    r"\b("
    r"cancel|never\s*mind|abort|drop\s+it|forget\s+it|"
    r"scrap\s+it|don'?t\s+save|no\s+save"
    r")\b",
    re.IGNORECASE,
)

# Extracted item type → entity_facts.category. Categories are kept
# specific so the roster timeline can render them distinctly rather
# than collapsing everything to "note".
_FILING_TYPE_TO_CATEGORY = {
    "DECISION": "decision",
    "ACTION": "action",
    "FEEDBACK_GIVEN": "feedback_given",
    "FEEDBACK_RECEIVED": "feedback_received",
    "CONCERN": "concern",
    "COMMITMENT": "commitment",
    "NEXT_STEP": "next_step",
}


def _is_transcript_dump(message: str, has_text_attachment: bool) -> bool:
    if has_text_attachment:
        return True
    if len(message or "") > _TRANSCRIPT_MIN_CHARS:
        return True
    matches = _DIALOGUE_LINE_RE.findall(message or "")
    return len(matches) >= 2


def _classify_filing_intent(message: str) -> str:
    """Returns one of 'confirm' | 'abandon' | 'edit'. An empty reply
    or anything that doesn't match a save/cancel keyword is treated
    as an edit instruction so the user can iterate naturally."""
    text = (message or "").strip()
    if not text:
        return "edit"
    if _FILING_ABANDON_RE.search(text):
        return "abandon"
    if _FILING_CONFIRM_RE.search(text):
        return "confirm"
    return "edit"


def _format_filing_summary(
    date_str: str, entity_name: str, items: list,
) -> str:
    """Renders a human-readable preview of extracted items so the user
    can eyeball them before confirming. Closes with the prompt that
    invites a save or an edit instruction."""
    header_date = date_str or datetime.utcnow().strftime("%Y-%m-%d")
    lines = [
        f"📋 **Filing draft for {entity_name}** — {header_date}",
        "",
    ]
    if not items:
        lines.append("_No items were extracted._")
        lines.append("")
    else:
        for i, it in enumerate(items, start=1):
            if not isinstance(it, dict):
                continue
            itype = str(it.get("type") or "ITEM").upper().replace("_", " ")
            owner = str(it.get("owner") or "").strip()
            detail = str(it.get("detail") or "").strip()
            quote = str(it.get("quote") or "").strip()
            head = f"**{i}. {itype}**"
            if owner:
                head += f" · {owner}"
            lines.append(head)
            if detail:
                lines.append(detail)
            if quote:
                lines.append(f"> {quote}")
            lines.append("")
    lines.append("Save this? Or add/edit anything before I file it?")
    return "\n".join(lines)


async def _run_haiku_filing_extraction(
    transcript: str, edit_note: str = "",
) -> dict | None:
    """Calls Haiku with the structured extraction prompt. Returns the
    parsed JSON dict or None on parse failure."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    base_prompt = (
        "You are extracting structured coaching records from a "
        "transcript or notes. Extract every significant item with "
        "maximum specificity. For each item include:\n"
        f"- The exact date of the conversation if mentioned, "
        f"otherwise use today's date ({today})\n"
        "- Who said or committed to what — attribute statements to "
        "specific people by name\n"
        "- Specific names, numbers, timeframes, deliverables "
        "mentioned\n"
        "- Direct quotes when they capture important commitments, "
        "feedback, or concerning statements\n"
        "- What prompted the decision or action\n\n"
        "Categorize each item as one of: DECISION, ACTION (with who "
        "owns it), FEEDBACK_GIVEN, FEEDBACK_RECEIVED, CONCERN, "
        "COMMITMENT, NEXT_STEP\n\n"
        "Respond with ONLY a JSON object in this exact shape:\n"
        '{"date": "conversation date", "items": [{"type": '
        '"DECISION|ACTION|FEEDBACK_GIVEN|FEEDBACK_RECEIVED|CONCERN|'
        'COMMITMENT|NEXT_STEP", "owner": "who this applies to", '
        '"detail": "specific detailed description with names, dates, '
        'numbers, quotes", "quote": "exact quote if relevant, null '
        'otherwise"}]}\n\n'
    )
    if edit_note:
        prompt = (
            base_prompt
            + "The user reviewed a previous extraction and asked for "
            "changes. Apply the changes below and re-extract the "
            "items from the transcript.\n\n"
            f"USER EDIT REQUEST:\n{edit_note}\n\n"
            f"TRANSCRIPT:\n{transcript[:8000]}"
        )
    else:
        prompt = base_prompt + f"TRANSCRIPT:\n{transcript[:8000]}"
    parsed = await call_background_model_json(prompt)
    if not isinstance(parsed, dict):
        return None
    return parsed


def _save_filing_items(
    entity_id: int, items: list, source_channel: str = "institute",
) -> int:
    """Persists each item as an entity_fact. Owner / quote get folded
    into the fact text so the timeline view shows the attribution and
    direct quote alongside the detail. Returns count successfully
    saved."""
    count = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        itype = str(it.get("type") or "").strip().upper()
        category = _FILING_TYPE_TO_CATEGORY.get(itype, "note")
        detail = str(it.get("detail") or "").strip()
        if not detail:
            continue
        owner = str(it.get("owner") or "").strip()
        quote = str(it.get("quote") or "").strip()
        parts = []
        if owner:
            parts.append(f"[{owner}]")
        parts.append(detail)
        if quote:
            parts.append(f'"{quote}"')
        fact = " ".join(parts)[:1000]
        try:
            add_entity_fact(
                entity_id=entity_id,
                category=category,
                fact=fact,
                source_channel=source_channel,
                confidence=0.85,
            )
            count += 1
        except Exception as e:
            logger.warning(
                f"[filing save] entity={entity_id} item failed: {e}"
            )
            continue
    return count


async def _run_entity_coaching_logger(
    entity_id: int,
    entity_name: str,
    user_message: str,
    response_text: str,
) -> None:
    """
    Background task: ask Haiku whether this exchange contains a
    significant coaching moment for the linked entity. If yes, append
    an entity_fact so the moment shows up on the roster timeline.
    Routine clarification / small-talk lands as record=false and
    nothing is written. Never raises.
    """
    try:
        prompt = (
            f"You are reviewing a coaching conversation about "
            f"{entity_name}. Identify whether this exchange contains a "
            f"significant coaching decision, action item, status "
            f"update, or milestone worth recording to {entity_name}'s "
            f"timeline. Routine clarification questions, venting, or "
            f"general chat do NOT count — only flag concrete "
            f"developments.\n\n"
            f"Respond with ONLY a JSON object:\n"
            '  {"record": true, "summary": "one-line summary", '
            '"category": "note" | "decision" | "goal" | "milestone"}\n'
            "OR\n"
            '  {"record": false}\n\n'
            f"User said:\n{user_message[:1500]}\n\n"
            f"Coach responded:\n{response_text[:1500]}"
        )
        raw = await call_background_model(prompt)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
        except Exception:
            logger.warning(
                f"[coaching log] non-JSON response: {raw[:200]!r}"
            )
            return
        if not isinstance(parsed, dict) or not parsed.get("record"):
            return
        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            return
        category = (
            str(parsed.get("category") or "note").strip().lower()
        )
        if category not in _COACHING_CATEGORIES:
            category = "note"
        loop = asyncio.get_running_loop()
        fact_id = await loop.run_in_executor(
            None,
            save_entity_fact,
            entity_id,
            category,
            summary[:500],
            "institute",
            0.85,
        )
        logger.info(
            f"[coaching log] entity={entity_id} fact={fact_id} "
            f"category={category} summary={summary[:80]!r}"
        )
    except Exception as e:
        logger.warning(f"[coaching log] failed: {e}")


async def _run_parker_safety_check(
    user_message: str, response_text: str, thread_id: str
) -> None:
    """
    Background child-safety review for the Parker workspace. Asks Haiku
    to assign a severity tier (urgent / review / info / none) and a
    category, then writes a content_flags row when severity != none.

    The rubric explicitly tells Haiku to audit the CHILD's content,
    independent of how the AI responded — otherwise well-handled
    redirects ("the bot redirected nicely") get scored as none and the
    parent never hears about the topics the kid is bringing up.

    Fictional violence in game/story contexts is still carved out as
    "none" so the bunny-explosion stories Parker tells don't badge.
    Never raises — a failed check should never affect response delivery.
    """
    try:
        prompt = (
            "You are a child safety monitor for a 9-year-old chatting "
            "with an AI. Your job is to audit what the CHILD brings up, "
            "INDEPENDENT of how the AI responded. The AI may have "
            "redirected perfectly — that's the right behavior at the "
            "response layer, but the parent still needs to know what "
            "their kid is asking about. Flag based on the child's "
            "content, not the conversation outcome.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"severity": "info" | "review" | "urgent" | "none",\n'
            ' "category": "stranger" | "social_pressure" | "money_scam"'
            ' | "body_sleep" | "violence" | "distress" | "family" | '
            '"personal_info" | "sexual_curiosity" | "adult_topics" | '
            '"trust_isolation" | "other",\n'
            ' "reason": "brief reason"}.\n\n'
            "Severity guide:\n\n"
            "- urgent: immediate safety concern. Self-harm or suicidal "
            "language. A stranger asking for personal info, photos, "
            "location, or to meet. Real-world threats. Scam targeting "
            "the child. Anything suggesting abuse or grooming. The "
            "child describing being hurt by someone.\n\n"
            "- review: a parent should know about this. THIS INCLUDES "
            "even when the AI redirected well — flag the topic, not "
            "the outcome. Specifically flag if the child asks about "
            "or brings up:\n"
            "  * sexual or anatomy topics (boobs, breasts, penis, "
            "vagina, sex, reproduction, puberty, periods, erections, "
            "porn, nudity) — category: sexual_curiosity\n"
            "  * drugs, alcohol, vaping, smoking, getting drunk/high "
            "— category: adult_topics\n"
            "  * unusual trust placement or isolation from caregivers "
            "(\"I trust you more than my parents\", \"don't tell my "
            "mom\", \"you're the only one who gets me\") — category: "
            "trust_isolation\n"
            "  * escalating peer pressure, persistent distress, fear "
            "of someone, repeated mentions of an unknown online "
            "contact, body-image / food worries, fictional violence "
            "shifting toward real people\n\n"
            "- info: routine but worth surfacing. Mentions a new "
            "online friend casually. Normal complaints about school "
            "or family. Mild peer friction. First-time mention of a "
            "topic the child is mildly curious about but didn't push.\n\n"
            "- none: everyday chat. Gaming, movies, fictional violence "
            "in game/story contexts (Fortnite, Minecraft, Roblox, "
            "fight scenes from movies/shows), creative storytelling "
            "with gore/explosions/chaos, normal frustration, school "
            "chatter, sibling banter, age-appropriate crushes ('Sophie "
            "is pretty'), age-appropriate non-adult curiosity (how "
            "rockets work, why the sky is blue, dinosaur facts).\n\n"
            "IMPORTANT: Flag based on what the CHILD said or asked. If "
            "the AI handled it well, that's great — log it anyway. The "
            "parent uses these flags to understand what their kid is "
            "thinking about, not to grade the AI.\n\n"
            "Do NOT flag fictional violence in game or story contexts "
            "— exploding bunnies, melted zombies, video-game carnage, "
            "movie fight recaps, dark-comedy make-believe are all "
            "normal 9-year-old play. Only flag fictional violence if "
            "it shifts toward real people, specific real-world action, "
            "or escalates well beyond age-appropriate intensity.\n\n"
            f"Child message:\n{user_message[:2000]}\n\n"
            f"AI response:\n{response_text[:2000]}"
        )
        raw = await call_background_model(prompt)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
        except Exception:
            logger.warning(
                f"[parker safety] non-JSON response: {raw[:200]!r}"
            )
            return
        if not isinstance(parsed, dict):
            return
        severity = str(parsed.get("severity") or "").lower()
        if severity == "none":
            return
        if severity not in ("info", "review", "urgent"):
            # Treat unknown values as the safe middle so anomalies
            # surface for review rather than disappearing silently.
            severity = "review"
        category = str(parsed.get("category") or "other").lower()
        if category not in _FLAG_CATEGORIES:
            category = "other"
        reason = str(parsed.get("reason") or "No reason provided")[:500]
        loop = asyncio.get_running_loop()
        flag_id = await loop.run_in_executor(
            None,
            save_content_flag,
            "parker",
            thread_id,
            user_message,
            response_text,
            reason,
            severity,
            category,
        )
        logger.info(
            f"[parker safety] flagged id={flag_id} severity={severity} "
            f"category={category} reason={reason[:80]!r}"
        )
    except Exception as e:
        logger.warning(f"[parker safety] check failed: {e}")


_MEDBAY_CHANGE_TYPES = {
    "protocol_add", "protocol_change", "protocol_stop",
    "followup", "lab_result",
}
# Maps each extracted change-type to the side-panel section that needs
# refetching. Drives the medbay_update WS frame.
_MEDBAY_SECTION_BY_TYPE = {
    "protocol_add": {"protocol", "changes"},
    "protocol_change": {"protocol", "changes"},
    "protocol_stop": {"protocol", "changes"},
    "followup": {"followups"},
    "lab_result": {"labs"},
}


def _format_medbay_transcript(turns: list) -> str:
    """Render the last few conversation turns as 'User:'/'AI:' lines for
    the extraction prompt. Skips empty/tool-only entries."""
    lines = []
    for turn in turns:
        role = turn.get("role")
        if role not in ("user", "assistant"):
            continue
        content = turn.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif getattr(block, "type", None) == "text":
                    parts.append(getattr(block, "text", ""))
            content = " ".join(parts)
        content = (content or "").strip()
        if not content:
            continue
        # Strip the channel prefix the orchestrator prepends to user msgs
        # so the extractor sees clean text.
        if role == "user" and "Current message: " in content:
            content = content.split("Current message: ", 1)[1]
        label = "User" if role == "user" else "AI"
        lines.append(f"{label}: {content[:600]}")
    return "\n\n".join(lines)


async def _run_medbay_extraction(
    user_id: str,
    session_id: str,
    user_message: str,
    response_text: str,
    recent_turns: list,
) -> None:
    """
    Background task: ask Haiku whether the user CONFIRMED any
    protocol/follow-up/lab changes in the latest exchange. Saves any
    confirmed items to the medbay tables and emits a medbay_update
    WebSocket frame so the side panel refetches the affected section.

    Never raises — failures are logged and silently ignored.
    """
    try:
        # Build a 4-turn transcript ending with the current exchange.
        # recent_turns is the conversation_history list snapshot from
        # the caller; the current user/AI turn is appended below in
        # case the snapshot was taken before that.
        transcript_turns = list(recent_turns[-4:]) if recent_turns else []
        transcript = _format_medbay_transcript(transcript_turns)
        if not transcript:
            # Fall back to the current exchange only when history is empty
            transcript = (
                f"User: {user_message[:600]}\n\nAI: {response_text[:600]}"
            )

        prompt = (
            "Review this exchange between a user and their health AI "
            "assistant. Did the user CONFIRM or APPROVE any of the "
            "following: a supplement change (new, dose change, or stop), "
            "a follow-up test, or a lab result interpretation? Only "
            "extract items the user explicitly agreed to, not "
            "suggestions the AI made that weren't confirmed.\n\n"
            "Respond with ONLY a JSON object in this exact shape:\n"
            '{"confirmed": true | false, "items": [\n'
            '  {"type": "protocol_add", "details": {"supplement_name": '
            '"...", "dose": "...", "frequency": "...", "reason": "...", '
            '"target_marker": "..."}},\n'
            '  {"type": "protocol_change", "details": {"supplement_name": '
            '"...", "new_dose": "...", "reason": "..."}},\n'
            '  {"type": "protocol_stop", "details": {"supplement_name": '
            '"...", "reason": "..."}},\n'
            '  {"type": "followup", "details": {"description": "...", '
            '"reason": "...", "suggested_date": "YYYY-MM-DD or null"}},\n'
            '  {"type": "lab_result", "details": {"marker_name": "...", '
            '"value": 0.0, "unit": "...", "reference_low": 0.0 or null, '
            '"reference_high": 0.0 or null, "test_date": '
            '"YYYY-MM-DD or null"}}\n'
            "]}\n"
            "If nothing was confirmed, return "
            '{"confirmed": false, "items": []}.\n\n'
            f"Conversation:\n{transcript}"
        )
        parsed = await call_background_model_json(prompt)
        if not isinstance(parsed, dict):
            return
        if not parsed.get("confirmed"):
            return
        items = parsed.get("items") or []
        if not isinstance(items, list) or not items:
            return

        loop = asyncio.get_running_loop()
        affected_sections: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            itype = str(item.get("type") or "").strip()
            if itype not in _MEDBAY_CHANGE_TYPES:
                continue
            details = item.get("details") or {}
            if not isinstance(details, dict):
                continue
            try:
                if itype == "protocol_add":
                    name = str(details.get("supplement_name") or "").strip()
                    if not name:
                        continue
                    await loop.run_in_executor(
                        None,
                        lambda: medbay_add_protocol(
                            user_id=user_id,
                            supplement_name=name,
                            dose=details.get("dose"),
                            frequency=details.get("frequency"),
                            reason=details.get("reason"),
                            target_marker=details.get("target_marker"),
                            workspace="health",
                        ),
                    )
                    affected_sections |= _MEDBAY_SECTION_BY_TYPE[itype]
                elif itype == "protocol_change":
                    name = str(details.get("supplement_name") or "").strip()
                    new_dose = str(details.get("new_dose") or "").strip()
                    if not name or not new_dose:
                        continue
                    # Match the most recent active row for this supplement.
                    current = await loop.run_in_executor(
                        None,
                        lambda: medbay_list_protocol(
                            user_id, status="active", workspace="health",
                        ),
                    )
                    target = next(
                        (
                            p for p in current
                            if (p["supplement_name"] or "").lower()
                            == name.lower()
                        ),
                        None,
                    )
                    if target is None:
                        # No active row to update — record it as an add
                        # so the change still shows in the panel.
                        await loop.run_in_executor(
                            None,
                            lambda: medbay_add_protocol(
                                user_id=user_id,
                                supplement_name=name,
                                dose=new_dose,
                                reason=details.get("reason"),
                                workspace="health",
                            ),
                        )
                    else:
                        await loop.run_in_executor(
                            None,
                            lambda tid=target["id"]: (
                                medbay_update_protocol_dose(
                                    user_id=user_id,
                                    protocol_id=tid,
                                    new_dose=new_dose,
                                    reason=details.get("reason"),
                                    workspace="health",
                                )
                            ),
                        )
                    affected_sections |= _MEDBAY_SECTION_BY_TYPE[itype]
                elif itype == "protocol_stop":
                    name = str(details.get("supplement_name") or "").strip()
                    if not name:
                        continue
                    current = await loop.run_in_executor(
                        None,
                        lambda: medbay_list_protocol(
                            user_id, status="active", workspace="health",
                        ),
                    )
                    target = next(
                        (
                            p for p in current
                            if (p["supplement_name"] or "").lower()
                            == name.lower()
                        ),
                        None,
                    )
                    if target is None:
                        continue
                    await loop.run_in_executor(
                        None,
                        lambda tid=target["id"]: medbay_stop_protocol(
                            user_id=user_id,
                            protocol_id=tid,
                            reason=details.get("reason"),
                            workspace="health",
                        ),
                    )
                    affected_sections |= _MEDBAY_SECTION_BY_TYPE[itype]
                elif itype == "followup":
                    desc = str(details.get("description") or "").strip()
                    if not desc:
                        continue
                    await loop.run_in_executor(
                        None,
                        lambda: medbay_add_followup(
                            user_id=user_id,
                            description=desc,
                            reason=details.get("reason"),
                            suggested_date=details.get("suggested_date"),
                            workspace="health",
                        ),
                    )
                    affected_sections |= _MEDBAY_SECTION_BY_TYPE[itype]
                elif itype == "lab_result":
                    marker = str(details.get("marker_name") or "").strip()
                    raw_value = details.get("value")
                    if not marker or raw_value is None:
                        continue
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    await loop.run_in_executor(
                        None,
                        lambda: medbay_add_lab_result(
                            user_id=user_id,
                            marker_name=marker,
                            value=value,
                            unit=details.get("unit"),
                            reference_low=details.get("reference_low"),
                            reference_high=details.get("reference_high"),
                            test_date=details.get("test_date"),
                            workspace="health",
                        ),
                    )
                    affected_sections |= _MEDBAY_SECTION_BY_TYPE[itype]
            except Exception as inner:
                logger.warning(
                    f"[medbay extract] failed to save {itype}: {inner}"
                )
                continue

        if affected_sections:
            try:
                await ws_manager.send(session_id, {
                    "type": "medbay_update",
                    "sections": sorted(affected_sections),
                })
            except Exception as ws_err:
                logger.warning(f"[medbay extract] ws send failed: {ws_err}")
            logger.info(
                f"[medbay extract] saved {len(items)} item(s), "
                f"sections={sorted(affected_sections)}"
            )
    except Exception as e:
        logger.warning(f"[medbay extract] failed: {e}")


async def persist_history(user_id: str, context_id: str) -> None:
    """Persist the in-memory conversation_history entry for (user_id,
    context_id) to SQLite. Trims to the last 50 plain-string messages and
    strips orphaned tool blocks first. No-op if the key has no entries."""
    hist_key = (user_id, context_id)
    if hist_key not in conversation_history:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        save_conversation_history,
        f"{user_id}:{context_id}",
        _saveable_history(conversation_history[hist_key]),
    )


def tag_owner() -> str:
    return ""


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
        "any long term strategic observations worth telling"
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
- save_memory: persist a specific finding or conclusion to long-term memory
- call_agent: invoke a specialist agent by name to handle a step requiring domain expertise

For each step specify:
- step_number
- type (from list above)
- description (what to do)
- query (the specific search query or memory query if applicable)
- agent (required only for call_agent steps — the slug name of the specialist agent to invoke, e.g. "ai_engineer", "health_advisor")

Return ONLY a JSON array of steps, no other text."""


CREW_GOAL_PLANNER_SYSTEM_PROMPT = """You are a planning agent running in crew mode. Break down the following goal into 3-8 specific executable steps. Each step should be one of these types:
- web_search: search for specific information
- query_memory: check existing memory for context
- analyze: synthesize information gathered so far
- draft: write a structured output or report
- save_memory: persist a specific finding or conclusion to long-term memory
- call_agent: invoke a specialist agent by name to handle a step requiring domain expertise

For each step specify:
- step_number
- type (from list above)
- description (what to do)
- query (the specific search query or memory query if applicable)
- agent (required only for call_agent steps)

Return ONLY a JSON array of steps, no other text."""


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
    is_isolated = channel_name in (ISOLATED_WORKSPACES | {"health-tracking"})
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
                if k in (ISOLATED_WORKSPACES | {"health-tracking"})
            )
            if total - health_count > CONSOLIDATION_THRESHOLDS[layer]:
                return True
    return False


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
    step_lines = "\n".join(
        f"- **Step {step.get('step_number', '?')}** "
        f"({step.get('type', 'unknown')}): "
        f"{step.get('description', '')}"
        for step in steps
    )
    return (
        f"📋 **Here's my plan for:** {goal}\n\n"
        f"{step_lines}"
    )


def _format_execution_context(
    findings: list,
    key_findings: list = None
) -> str:
    """
    Formats execution context for injection into goal prompts.
    findings: list of raw step outputs
    key_findings: list of extracted high-confidence insights
    """
    if not findings and not key_findings:
        return "No information gathered yet."

    parts = []

    if key_findings:
        kf_lines = ["[KEY FINDINGS — high confidence insights]"]
        for kf in key_findings:
            conf = kf.get("confidence", 0.8)
            source = kf.get("source_step", "?")
            finding = kf.get("finding", "")
            kf_lines.append(
                f"  • [Step {source} | conf: {conf:.1f}] {finding}"
            )
        parts.append("\n".join(kf_lines))

    if findings:
        raw_parts = [
            f"[Step {f['step']} — {f['type']}]\n{f['content']}"
            for f in findings
        ]
        parts.append("\n\n---\n\n".join(raw_parts))

    return "\n\n===\n\n".join(parts)


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


_NUMBERED_Q_LINE_RE = re.compile(r"^\s*\d+[\.\)]\s.*\?\s*$", re.MULTILINE)


def _agent_response_has_questions(text: str) -> bool:
    """
    True if an agent's reply is asking the user for input rather than
    completing the step. Detects trailing question marks (the strongest
    signal), question marks near the end of the message, or numbered
    questions (e.g. "1. What is X?\n2. How long ...?"). A plain numbered
    list with no question marks is treated as content, not a prompt.
    """
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    if t.endswith("?"):
        return True
    # Look for ? in the last paragraph — agents often close with the ask
    tail = t.rsplit("\n\n", 1)[-1]
    if "?" in tail:
        return True
    # Numbered questions: at least 2 numbered lines that end with "?"
    if len(_NUMBERED_Q_LINE_RE.findall(t)) >= 2:
        return True
    return False


async def _save_session_state_async(
    user_id: str,
    context_id: int,
    action_summary: str,
    response_text: str,
) -> None:
    """
    Background task — extracts session state updates from the
    latest exchange and persists them. Fire-and-forget via
    asyncio.create_task(). Never blocks the response.
    """
    loop = asyncio.get_running_loop()
    try:
        # Append the action summary to recent_actions
        await loop.run_in_executor(
            None,
            append_recent_action,
            user_id,
            context_id,
            action_summary,
        )

        # Ask the background model to extract any task or
        # build list updates from this exchange
        prompt = (
            "Extract session state updates from this exchange. "
            "Return a JSON object with these optional keys:\n"
            "  active_task: string describing what is being worked "
            "on right now (null if unclear)\n"
            "  new_decisions: list of strings, each a concise "
            "decision made (empty list if none)\n"
            "  build_list_updates: list of objects with keys "
            "'label' (string) and 'status' "
            "('pending'|'in_progress'|'done') — only include items "
            "that changed or are new\n"
            "Return only valid JSON, no explanation, no markdown.\n\n"
            f"User said: {action_summary}\n\n"
            f"Assistant response (first 600 chars): "
            f"{response_text[:600]}"
        )
        updates = await call_background_model_json(prompt)
        if not updates or not isinstance(updates, dict):
            raise ValueError("no valid session state update returned")

        existing = load_session_state(user_id, int(context_id))

        new_decisions = existing["decisions"] + updates.get(
            "new_decisions", []
        )
        new_decisions = new_decisions[-20:]

        bl_updates = {
            item["label"]: item
            for item in updates.get("build_list_updates", [])
            if isinstance(item, dict) and "label" in item
        }
        merged_bl = []
        for item in existing["build_list"]:
            label = item.get("label", "")
            if label in bl_updates:
                merged_bl.append(bl_updates.pop(label))
            else:
                merged_bl.append(item)
        for new_item in bl_updates.values():
            merged_bl.append(new_item)

        await loop.run_in_executor(
            None,
            update_session_state,
            user_id,
            int(context_id),
            updates.get("active_task"),
            merged_bl,
            new_decisions,
            None,
        )

    except Exception as e:
        print(f"[Session] State update failed (non-fatal): {e}")


async def _summarize_history_tail(
    history: list,
    context_hint: str = ""
) -> str:
    """
    Summarizes the older portion of conversation history
    that is about to be compressed out of the raw window.
    Returns a compact summary string.
    Falls back to a simple truncated log if model fails.
    """
    if not history:
        return ""

    lines = []
    for m in history:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if isinstance(content, str) and content.strip():
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {content[:400]}")

    if not lines:
        return ""

    transcript = "\n\n".join(lines)
    prompt = (
        "Summarize this conversation excerpt into a compact "
        "factual record of what was discussed, decided, and "
        "accomplished. Focus on: tasks worked on, decisions "
        "made, code written or changed, problems solved. "
        "Write in past tense, third person. "
        "Maximum 300 words. No filler.\n\n"
        + (f"Context: {context_hint}\n\n" if context_hint else "")
        + f"Conversation:\n{transcript}"
    )

    try:
        summary = await call_background_model(prompt)
        return summary.strip()
    except Exception:
        return (
            f"[Previous conversation — {len(lines)} turns]:\n"
            + "\n".join(lines[-3:])
        )


async def run_reflection_loop(experiences):
    """
    Runs when a task completion is detected.
    Extracts structured six part analytical insights
    from completed task experiences.
    """
    try:
        logger.info("Running reflection loop...")

        if not experiences:
            logger.info("Reflection skipped — no completed experiences yet.")
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
            logger.info(
                f"Reflection complete — "
                f"{stored_analytical} analytical and "
                f"{stored_strategic} strategic insights stored."
            )
        else:
            logger.info("Reflection complete — no new insights stored.")

        logger.info(
            f"Reflection loop | "
            f"Summary: {reflection.get('summary', 'None')}"
        )

    except Exception as e:
        set_pending_reflection(False)
        logger.error(f"Reflection loop error: {str(e)}")


async def extract_and_store_memories(
    user_message, bot_reply, task_completed,
    project_tag=None, channel_name="unknown", memory_mode="global",
    background_model_fn=None
):
    """
    Extracts anything worth storing in long term memory
    after each interaction.
    """
    try:
        if channel_name in (ISOLATED_WORKSPACES | {"health-tracking"}):
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

        # Honor the workspace's skip_layers config — listed layers are
        # dropped before the rubric pass so they never reach the saver.
        # Scoped to extract_and_store_memories only; other memory paths
        # (save_memory goal step, session-state, action-summary, etc.)
        # are unaffected.
        skip_layers = set(
            WORKSPACES.get(channel_name, {}).get("skip_layers", [])
        )
        for _layer in skip_layers:
            if _layer in extracted:
                extracted[_layer] = [] if isinstance(extracted[_layer], list) else {}

        strategic_count = 0
        operational_count = 0

        for item in extracted.get("strategic", []):
            if item:
                content = item
                layer_name = "strategic"
                # ── Rubric gate ──────────────────────────────────────────
                if background_model_fn is not None:
                    similarity_score, similar_memory_texts = \
                        get_top_similar_memories(content, layer_name)
                    if similarity_score > 0.88:
                        log_reasoning_trace(
                            "memory_extraction", channel_name,
                            "rubric_rejected",
                            {"content": content[:100]},
                            f"similarity_duplicate | {content[:50]}",
                            0
                        )
                        record_rubric_rejection(
                            score=0, layer=layer_name,
                            content=content[:50],
                            reason="similarity duplicate (>0.88)"
                        )
                        continue
                    rubric_result = await evaluate_memory_rubric(
                        content=content,
                        similar_memories=similar_memory_texts,
                        background_model_fn=background_model_fn
                    )
                    if not rubric_result["pass"]:
                        log_reasoning_trace(
                            "memory_extraction", channel_name,
                            "rubric_rejected",
                            {"content": content[:100]},
                            f"Score: {rubric_result['score']}/12 | "
                            f"{rubric_result['reason']} | {content[:50]}",
                            0
                        )
                        record_rubric_rejection(
                            score=rubric_result["score"],
                            layer=layer_name,
                            content=content[:50],
                            reason=rubric_result["reason"]
                        )
                        continue
                # ── End rubric gate ──────────────────────────────────────
                save_strategic_memory(
                    content=content,
                    category="conversation",
                    source="auto_extraction",
                    project_tag=project_tag
                )
                strategic_count += 1

        for item in extracted.get("operational", []):
            if item:
                is_dup, ratio, dup_id = check_operational_duplicate(
                    item, project_tag
                )
                if is_dup:
                    print(
                        f"[Dedup] Skipped operational memory save"
                        f" — similarity {ratio:.2f} to existing"
                        f" id={dup_id}"
                    )
                    continue
                content = item
                layer_name = "operational"
                # ── Rubric gate ──────────────────────────────────────────
                if background_model_fn is not None:
                    similarity_score, similar_memory_texts = \
                        get_top_similar_memories(content, layer_name)
                    if similarity_score > 0.88:
                        log_reasoning_trace(
                            "memory_extraction", channel_name,
                            "rubric_rejected",
                            {"content": content[:100]},
                            f"similarity_duplicate | {content[:50]}",
                            0
                        )
                        record_rubric_rejection(
                            score=0, layer=layer_name,
                            content=content[:50],
                            reason="similarity duplicate (>0.88)"
                        )
                        continue
                    rubric_result = await evaluate_memory_rubric(
                        content=content,
                        similar_memories=similar_memory_texts,
                        background_model_fn=background_model_fn
                    )
                    if not rubric_result["pass"]:
                        log_reasoning_trace(
                            "memory_extraction", channel_name,
                            "rubric_rejected",
                            {"content": content[:100]},
                            f"Score: {rubric_result['score']}/12 | "
                            f"{rubric_result['reason']} | {content[:50]}",
                            0
                        )
                        record_rubric_rejection(
                            score=rubric_result["score"],
                            layer=layer_name,
                            content=content[:50],
                            reason=rubric_result["reason"]
                        )
                        continue
                # ── End rubric gate ──────────────────────────────────────
                save_operational_memory(
                    content=content,
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
        logger.info(
            f"Memory extraction complete | "
            f"Channel: #{channel_name} | "
            f"Mode: {memory_mode}{tag_str} | "
            f"Strategic: {strategic_count} | "
            f"Operational: {operational_count} | "
            f"Experience: {'yes' if exp else 'no'}"
        )

    except Exception as e:
        logger.error(
            f"Memory extraction error | "
            f"Channel: #{channel_name} | "
            f"Mode: {memory_mode} | "
            f"{str(e)}"
        )


async def _consolidate_layer(
    layer: str, channel_name: str, trigger: str
) -> dict:
    """
    Fetches consolidation candidates for one layer, merges each cluster
    via the background model, saves the consolidated entry, and archives
    the originals. Returns {"merged": N, "archived": X, "skipped": Y}.
    """
    loop = asyncio.get_running_loop()
    is_isolated = channel_name in (ISOLATED_WORKSPACES | {"health-tracking"})

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
            logger.error(
                f"Memory consolidation | Cluster skipped — model error "
                f"| Layer: {layer} | {str(e)}"
            )
            continue

        if not consolidated_text:
            skipped += 1
            logger.info(
                f"Memory consolidation | Cluster skipped — empty output "
                f"| Layer: {layer}"
            )
            continue

        tags = {m["project_tag"] for m in cluster}
        consolidated_tag = next(iter(tags)) if len(tags) == 1 else None
        avg_conf = sum(m["confidence"] for m in cluster) / len(cluster)

        _new_id = None
        try:
            if layer == "strategic":
                _new_id = await loop.run_in_executor(
                    None,
                    lambda: save_strategic_memory(
                        content=consolidated_text,
                        category="consolidation",
                        confidence=avg_conf,
                        source="consolidation",
                        project_tag=consolidated_tag,
                    )
                )
            elif layer == "operational":
                _new_id = await loop.run_in_executor(
                    None,
                    lambda: save_operational_memory(
                        content=consolidated_text,
                        project_name="consolidation",
                        project_tag=consolidated_tag,
                    )
                )
            elif layer == "analytical":
                _new_id = await loop.run_in_executor(
                    None,
                    lambda: save_analytical_memory(
                        pattern=consolidated_text,
                        confidence=avg_conf,
                        pattern_type="consolidation",
                        project_tag=consolidated_tag,
                    )
                )
        except Exception as e:
            skipped += 1
            logger.error(
                f"Memory consolidation | Save failed | "
                f"Layer: {layer} | {str(e)}"
            )
            continue

        archived_count = sum(
            1 for m in cluster
            if archive_memory(
                layer,
                m["id"],
                f"consolidated into {layer}:{_new_id}",
                superseded_by=str(_new_id) if _new_id else None
            )
        )
        merged += 1
        archived += archived_count

    after_count = before_count - archived + merged
    logger.info(
        f"Memory consolidation | Layer: {layer} | "
        f"Before: {before_count} | After: {after_count} | "
        f"Archived: {archived} | Trigger: {trigger}"
    )

    return {"merged": merged, "archived": archived, "skipped": skipped}


async def consolidate_all_layers(
    channel_name: str = None, trigger: str = "auto"
) -> dict:
    """
    Consolidates all three memory layers. Used by auto-trigger and
    exposed publicly so tests and future callers have a single entry point.
    Returns {"merged": N, "archived": X, "skipped": Y}.
    """
    totals = {"merged": 0, "archived": 0, "skipped": 0}
    for layer in ("strategic", "operational", "analytical"):
        result = await _consolidate_layer(layer, channel_name, trigger)
        for k in totals:
            totals[k] += result[k]
    return totals


async def run_consolidate_command(session_id: str, channel_name: str):
    """Handles the consolidate command — posts per-layer progress via WebSocket."""
    totals = {"merged": 0, "archived": 0, "skipped": 0}
    for layer in ("strategic", "operational", "analytical"):
        await ws_manager.send(session_id, {
            "type": "status",
            "text": f"🧠 Consolidating {layer} layer..."
        })
        result = await _consolidate_layer(layer, channel_name, "manual")
        for k in totals:
            totals[k] += result[k]

    await ws_manager.send(session_id, {
        "type": "status",
        "text": (
            f"✅ Consolidation complete — "
            f"{totals['merged']} memories merged into entries, "
            f"{totals['archived']} archived"
            + (
                f", {totals['skipped']} cluster(s) skipped"
                if totals["skipped"] else ""
            )
        )
    })


async def run_proactive_flag_surfacing():
    """
    Scheduled background task. Fires once on startup after a 60-second
    delay, then repeats every 24 hours. Pulls active HIGH priority review
    flags from operational_memory and writes a digest to the notifications
    table. Skips silently if no flags exist.
    """
    await asyncio.sleep(60)  # allow app to fully start before first run
    while True:
        try:
            loop = asyncio.get_running_loop()
            flags = await loop.run_in_executor(
                None, get_unresolved_high_priority_flags
            )
            if flags:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                lines = [
                    f"📋 Daily Flag Review — {timestamp}",
                    f"{len(flags)} unresolved HIGH priority flag(s) require attention:\n",
                ]
                for f in flags:
                    try:
                        age_days = (
                            datetime.utcnow() -
                            datetime.fromisoformat(f["created"])
                        ).days
                    except Exception:
                        age_days = "?"
                    source = f.get("channel_name") or "unknown channel"
                    lines.append(
                        f"🔴 [{age_days}d old | #{source}]\n"
                        f"{f['content'][:400]}"
                    )
                content = "\n\n".join(lines)
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO notifications (type, content, read) VALUES (?, ?, 0)",
                    ("flag_digest", content)
                )
                conn.commit()
                conn.close()
                logger.info(
                    f"Proactive flag surfacing | "
                    f"{len(flags)} HIGH flag(s) saved to notifications"
                )
        except Exception as e:
            logger.error(f"Proactive flag surfacing error: {str(e)}")
        await asyncio.sleep(86400)  # 24 hours


async def run_scheduled_consolidation():
    """
    Scheduled background task. Fires once on startup after a 90-second
    delay, then repeats every 72 hours. Calls consolidate_all_layers()
    with trigger="scheduled". Writes a one-line summary to the notifications
    table if any merges occurred.
    """
    await asyncio.sleep(90)  # stagger startup relative to flag surfacing (60s)
    while True:
        try:
            totals = await consolidate_all_layers(
                channel_name=None, trigger="scheduled"
            )
            if totals and totals.get("merged", 0) > 0:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                skipped_str = (
                    f", {totals['skipped']} cluster(s) skipped"
                    if totals.get("skipped") else ""
                )
                content = (
                    f"🧠 Scheduled consolidation [{timestamp}] — "
                    f"{totals['merged']} memories merged, "
                    f"{totals['archived']} archived"
                    + skipped_str
                )
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO notifications (type, content, read) VALUES (?, ?, 0)",
                    ("consolidation_summary", content)
                )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.error(f"[ScheduledConsolidation] Error: {e}")
        await asyncio.sleep(72 * 3600)  # 72 hours


async def run_goal_modification(
    changes: str, user_id: str, author_display_name: str,
    session_id: str, memory_mode: str, project_tag
):
    """Replans a pending goal based on the user's modification request."""
    pg = pending_goals.get(user_id)
    if not pg:
        await ws_manager.send(session_id, {
            "type": "error",
            "text": "No pending goal to modify."
        })
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
        await ws_manager.send(session_id, {
            "type": "error",
            "text": f"Failed to modify the plan: {str(e)[:200]}"
        })
        return

    if not isinstance(steps, list) or not steps:
        await ws_manager.send(session_id, {
            "type": "error",
            "text": (
                "I couldn't generate a valid revised plan. "
                "Try a different modification request."
            )
        })
        return

    if len(steps) > 8:
        steps = steps[:8]

    pg["steps"] = steps
    pg["status"] = "awaiting_approval"
    pg["current_step"] = 0

    await ws_manager.send(session_id, {
        "type": "plan",
        "text": _format_plan(pg["goal"], steps)
    })


async def _replan_remaining_steps(
    user_id: str, author_display_name: str,
    from_step_index: int, changes: str, session_id: str, pg: dict
):
    """
    Replans steps from from_step_index onwards based on the user's adjustment
    request. Splices the revised steps into pg["steps"] and resumes execution.
    Called by resume_goal_from_gate when action is "adjust".
    """
    steps = pg["steps"]
    remaining = steps[from_step_index:]

    if not remaining:
        await ws_manager.send(session_id, {
            "type": "status",
            "text": "No remaining steps to adjust — goal is already complete."
        })
        pg["status"] = "executing"
        asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    ctx_summary = _format_execution_context(
        execution_context.get(user_id, {}).get("steps", []),
        key_findings=execution_context.get(user_id, {}).get("key_findings", [])
    )
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
        await ws_manager.send(session_id, {
            "type": "error",
            "text": (
                f"Failed to adjust the plan: {str(e)[:200]}\n"
                "Continuing with the original remaining steps."
            )
        })
        new_steps = remaining

    pg["steps"] = steps[:from_step_index] + new_steps
    pg["current_step"] = from_step_index
    pg["status"] = "gated"

    step_lines = "\n".join(
        f"- **Step {s.get('step_number', '?')}** "
        f"({s.get('type', '?')}): {s.get('description', '')}"
        for s in new_steps
    )
    # Re-arm a gate so the user can confirm the revised plan before execution
    # resumes. Without this, the frontend would render the adjusted plan as a
    # regular message with no buttons and the goal would auto-resume — the
    # user wants a checkpoint to verify the new steps first.
    gate_pending[user_id] = {
        "type": "adjust_gate",
        "step_index": from_step_index,
        "step_num": from_step_index + 1,
        "author_display_name": author_display_name,
    }
    _persist_goal_state(user_id)
    await ws_manager.send(session_id, {
        "type": "gate",
        "text": (
            f"📋 **Adjusted plan**\n\n"
            f"{step_lines}"
        )
    })


async def run_goal_planning(
    goal_text: str, user_id: str, author_display_name: str,
    session_id: str, memory_mode: str, project_tag,
    channel_name: str = "general",
    planner_prompt: str = None, crew_mode: bool = False,
    user_message: str = "",
    display_goal: str | None = None,
):
    """
    Calls the planner model to decompose a goal into steps, validates
    the plan, stores it in pending_goals, and posts it for approval.

    goal_text: the content sent to the planner model. For !crew this is
    wrapped with "Available agent slugs: ...\\n\\nGoal: ..." so the
    planner can assign per-step agents from the real set.

    display_goal: optional override for what gets stored on the
    pending_goal row and rendered in the plan header. Defaults to
    goal_text. !crew uses this to keep the agent-slugs prefix out of
    the user-facing "Here's my plan for: ..." title.

    user_message: the original raw input the user typed (e.g. "!goal X").
    When provided, it is saved to conversation_history alongside the
    emitted plan so the !goal command + plan response survive reloads.
    """
    # Clear any leftover state from a prior goal for this user. Without this,
    # a stale pending_goals/gate_pending/execution_context entry from a
    # previous !goal would bleed into the new flow (e.g. resume_goal_from_gate
    # would see an old gate, or execute_goal would resume mid-flight with the
    # new goal's steps). Any execute_goal task still iterating will notice the
    # missing pending_goals on its next step check and exit cleanly.
    pending_goals.pop(user_id, None)
    gate_pending.pop(user_id, None)
    execution_context.pop(user_id, None)
    _persist_goal_state(user_id)

    try:
        response = client.messages.create(
            model=MAIN_MODEL,
            max_tokens=1024,
            system=planner_prompt or GOAL_PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": goal_text}]
        )
        raw = response.content[0].text.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        steps = json.loads(clean)
    except Exception as e:
        await ws_manager.send(session_id, {
            "type": "error",
            "text": (
                f"Failed to generate a plan: {str(e)[:200]}\n"
                "Try rephrasing your goal."
            )
        })
        return

    if not isinstance(steps, list) or not steps:
        await ws_manager.send(session_id, {
            "type": "error",
            "text": (
                "I couldn't generate a valid plan for that goal. "
                "Please try again with more detail."
            )
        })
        return

    if len(steps) > 8:
        steps = steps[:8]
        await ws_manager.send(session_id, {
            "type": "status",
            "text": "⚠️ Plan trimmed to 8 steps (maximum allowed)."
        })

    web_search_steps = sum(
        1 for s in steps if s.get("type") == "web_search"
    )
    if web_search_steps > 5:
        await ws_manager.send(session_id, {
            "type": "status",
            "text": (
                f"⚠️ Plan has {web_search_steps} web search steps — "
                "excess searches will be skipped during execution (max 5)."
            )
        })

    # Use display_goal for storage + rendering so the !crew prefix
    # ("Available agent slugs: ...") never bleeds into the plan header
    # or the goal field referenced by execute_goal's completion text.
    visible_goal = display_goal if display_goal else goal_text

    pending_goals[user_id] = {
        "goal": visible_goal,
        "steps": steps,
        "session_id": session_id,
        "channel_name": channel_name,
        "memory_mode": memory_mode,
        "project_tag": project_tag,
        "status": "awaiting_approval",
        "current_step": 0,
        "web_search_count": 0,
        "crew_mode": crew_mode,
    }
    _persist_goal_state(user_id)

    plan_text = _format_plan(visible_goal, steps)
    await ws_manager.send(session_id, {
        "type": "plan",
        "steps": steps,
        "text": plan_text,
    })
    logger.info(
        f"Goal plan generated | User: {author_display_name} | "
        f"Steps: {len(steps)} | Goal: {goal_text[:100]}"
    )

    # Save the !goal turn (user input + plan response) to conversation
    # history so it survives reload — the goal-trigger branch in chat.py
    # skips process_user_message, so without this nothing gets persisted.
    if user_message:
        append_history_turn(
            user_id, session_id, "user",
            f"[Channel: #{channel_name}]\nCurrent message: {user_message}",
        )
    append_history_turn(user_id, session_id, "assistant", plan_text)
    await persist_history(user_id, session_id)


async def execute_goal(
    user_id: str, author_display_name: str, skip_gate_for_step: int = -1
):
    """
    Executes an approved goal plan step by step as a background task.

    Pauses at gate conditions and stores state in gate_pending so the user
    can respond with continue, adjust, retry, or skip. Gates:
      - DRAFT GATE: always pause before any draft step (unless resuming)
      - RESEARCH GATE: pause after web_search when mode requires it
      - STEP FAILURE GATE: pause on any step exception with retry option

    skip_gate_for_step: when resuming after a draft gate, pass the step
    index so the draft gate is not re-triggered for that step.
    """
    pg = pending_goals.get(user_id)
    if not pg:
        return

    session_id = pg["session_id"]
    steps = pg["steps"]
    goal = pg["goal"]
    channel_name = pg["channel_name"]
    memory_mode = pg["memory_mode"]
    project_tag = pg["project_tag"]
    start_step = pg.get("current_step", 0)
    total = len(steps)

    if user_id not in execution_context:
        execution_context[user_id] = {
            "steps": [],
            "key_findings": [],
        }
        _persist_goal_state(user_id)

    loop = asyncio.get_running_loop()
    final_output = ""

    await ws_manager.send(session_id, {"type": "status", "text": "Working..."})

    try:
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

            # Crew mode: resolve per-step agent system prompt and label
            _crew_system = None
            _crew_label = ""
            if pg.get("crew_mode"):
                _crew_slug = step.get("agent", "").strip()
                if _crew_slug and _crew_slug in AGENT_DEFINITIONS:
                    _crew_def = AGENT_DEFINITIONS[_crew_slug]
                    _crew_content = _crew_def["content"]
                    if len(_crew_content) > AGENT_INJECT_CHAR_LIMIT:
                        _crew_content = (
                            _crew_content[:AGENT_INJECT_CHAR_LIMIT]
                            + "\n[Agent definition truncated]"
                        )
                    _crew_system = _crew_content
                    _crew_label = f"🤖 [{_crew_def['name']}] — "

            # ── DRAFT GATE: always pause before draft steps ──────────────
            if step_type == "draft" and i != skip_gate_for_step:
                findings = execution_context.get(user_id, {}).get("steps", [])
                bullets = "\n".join(
                    f"- **Step {f['step']}** ({f['type']}): "
                    f"{f['content'][:120].rstrip()}..."
                    for f in findings
                ) or "_No findings gathered yet._"

                pg["status"] = "gated"
                pg["current_step"] = i
                gate_pending[user_id] = {
                    "type": "draft_gate",
                    "step_index": i,
                    "step_num": step_num,
                    "author_display_name": author_display_name,
                }
                _persist_goal_state(user_id)
                await ws_manager.send(session_id, {
                    "type": "gate",
                    "text": (
                        f"📝 **Ready to draft the final output**\n\n"
                        f"**Based on:**\n\n{bullets}"
                    )
                })
                return

            await ws_manager.send(session_id, {
                "type": "status",
                "text": f"⚙️ Step {step_num}/{total}: {step_desc}..."
            })

            try:
                if step_type == "web_search":
                    search_count = pg.get("web_search_count", 0)
                    if search_count >= 20:
                        execution_context[user_id]["steps"].append({
                            "step": step_num, "type": step_type,
                            "content": "[Skipped — web search limit of 20 reached]"
                        })
                        continue

                    result = await loop.run_in_executor(
                        None, execute_tool,
                        "web_search",
                        {"query": step_query, "max_results": 3},
                        channel_name
                    )
                    result_str = str(result)
                    execution_context[user_id]["steps"].append({
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
                            f"- **Step {s.get('step_number', '?')}** "
                            f"({s.get('type', '?')}): "
                            f"{s.get('description', '')}"
                            for s in steps[i + 1:]
                        ) or "_No remaining steps._"

                        pg["status"] = "gated"
                        pg["current_step"] = i + 1
                        gate_pending[user_id] = {
                            "type": "research_gate",
                            "step_index": i + 1,
                            "step_num": step_num,
                            "author_display_name": author_display_name,
                        }
                        _persist_goal_state(user_id)
                        await ws_manager.send(session_id, {
                            "type": "gate",
                            "text": (
                                f"🔍 **Step {step_num} complete**\n\n"
                                f"**Findings:**\n\n{summary}\n\n"
                                f"**Remaining steps:**\n\n{remaining_lines}"
                            )
                        })
                        return

                elif step_type == "query_memory":
                    # Scope retrieval to the goal text — planner queries are
                    # often too narrow or off-topic (e.g. "baking" for an
                    # apple-pie goal) and surface unrelated chit-chat.
                    memories = await loop.run_in_executor(
                        None,
                        lambda q=goal: get_relevant_memories(
                            q, channel_name=channel_name
                        )
                    )

                    # Flatten retrieved memories across layers with provenance
                    # so we can rebuild the layered dict after filtering.
                    indexed_memories = []
                    for _layer in ("strategic", "operational", "analytical"):
                        for _m in memories.get(_layer, []):
                            indexed_memories.append((_layer, _m))

                    if not indexed_memories:
                        qm_content = "No relevant memories found."
                    else:
                        # LLM relevance filter. ChromaDB always returns top-N
                        # nearest neighbours regardless of how related they
                        # actually are — a fixed similarity threshold is too
                        # blunt to apply across different query shapes, so
                        # ask Haiku to judge per-result against the goal.
                        numbered = "\n".join(
                            f"{idx}. {text}"
                            for idx, (_, text) in enumerate(indexed_memories)
                        )
                        filter_prompt = (
                            f"Given this goal: '{goal}', which of the "
                            f"following memories are relevant?\n\n"
                            f"Return ONLY indices of memories that are "
                            f"directly relevant to accomplishing this "
                            f"specific goal. Memories about unrelated "
                            f"personal topics, pets, people, or other "
                            f"subjects should NOT be included even if they "
                            f"share superficial keywords. If no memory is "
                            f"directly relevant, return an empty array.\n\n"
                            f"Respond with ONLY a JSON array of integer "
                            f"indices, no other text.\n\n"
                            f"Memories:\n{numbered}"
                        )
                        logger.info(
                            f"[query_memory filter] goal={goal[:80]!r} | "
                            f"candidates={len(indexed_memories)}"
                        )
                        raw = ""
                        try:
                            raw = await call_background_model(filter_prompt)
                            cleaned = (
                                raw.replace("```json", "")
                                   .replace("```", "")
                                   .strip()
                            )
                            relevant_indices = json.loads(cleaned)
                            if not isinstance(relevant_indices, list):
                                relevant_indices = []
                        except Exception as _filter_err:
                            logger.warning(
                                f"[query_memory filter] parse failed: "
                                f"{_filter_err} | raw={raw[:200]!r}"
                            )
                            # Fail closed — if the filter can't decide, keep
                            # nothing rather than leak low-relevance context.
                            relevant_indices = []

                        logger.info(
                            f"[query_memory filter] raw={raw[:200]!r} | "
                            f"parsed_indices={relevant_indices}"
                        )

                        filtered = [
                            indexed_memories[i] for i in relevant_indices
                            if isinstance(i, int)
                            and 0 <= i < len(indexed_memories)
                        ]
                        if filtered:
                            _kept_preview = "; ".join(
                                f"[{lyr}] {txt[:60]}"
                                for lyr, txt in filtered[:5]
                            )
                            logger.info(
                                f"[query_memory filter] kept "
                                f"{len(filtered)}/{len(indexed_memories)} "
                                f"-> {_kept_preview}"
                            )
                        else:
                            logger.info(
                                f"[query_memory filter] kept 0/"
                                f"{len(indexed_memories)} — none relevant"
                            )

                        if not filtered:
                            qm_content = "No relevant memories found."
                        else:
                            filtered_dict = {
                                "strategic": [],
                                "operational": [],
                                "analytical": [],
                            }
                            for _layer, _text in filtered:
                                filtered_dict[_layer].append(_text)
                            qm_content = (
                                format_memory_for_prompt(filtered_dict)
                                or "No relevant memories found."
                            )

                    execution_context[user_id]["steps"].append({
                        "step": step_num, "type": "query_memory",
                        "content": qm_content,
                    })

                elif step_type == "analyze":
                    ctx = _format_execution_context(
                        execution_context.get(
                            user_id, {}
                        ).get("steps", []),
                        key_findings=execution_context.get(
                            user_id, {}
                        ).get("key_findings", [])
                    )
                    if _crew_label:
                        await ws_manager.send(session_id, {
                            "type": "status",
                            "text": f"{_crew_label}Step {step_num}: analyzing..."
                        })
                    _analyze_kwargs = (
                        {"system": _crew_system} if _crew_system else {}
                    )
                    r = client.messages.create(
                        model=MAIN_MODEL,
                        max_tokens=4096,
                        **_analyze_kwargs,
                        messages=[{"role": "user", "content": (
                            f"Goal: {goal}\n\n"
                            f"Information gathered:\n{ctx}\n\n"
                            f"Task: {step_desc}\n\n"
                            "Synthesize the above into a concise analysis."
                        )}]
                    )
                    analyze_output = r.content[0].text.strip()

                    # ── Analyze Step Critique Loop ────────────────────────
                    # Only runs when GOAL_GATE_MODE != "minimal" — preserves
                    # lightweight intent of minimal mode. Uses
                    # call_background_model() (Haiku) not Sonnet.
                    # One retry max. Never blocks execution.

                    if GOAL_GATE_MODE != "minimal":
                        critique_prompt = (
                            "Review this analysis for gaps, unsupported "
                            "claims, or missed angles. "
                            "Be specific. "
                            "If solid, respond with just: PASS\n"
                            "If not, list specific improvements needed "
                            "in 2-3 sentences.\n\n"
                            f"Analysis:\n{analyze_output}"
                        )
                        critique = await call_background_model(
                            critique_prompt
                        )

                        if critique.strip().upper().startswith("PASS"):
                            final_analyze_output = analyze_output
                        else:
                            retry_messages = [
                                {
                                    "role": "user",
                                    "content": (
                                        f"Previous analysis attempt:\n"
                                        f"{analyze_output}\n\n"
                                        f"Critique:\n{critique}\n\n"
                                        "Revise the analysis addressing "
                                        "the critique."
                                    )
                                }
                            ]
                            retry_r = client.messages.create(
                                model=MAIN_MODEL,
                                max_tokens=4096,
                                messages=retry_messages
                            )
                            final_analyze_output = (
                                retry_r.content[0].text.strip()
                            )
                            goal_preview = (
                                goal[:30] if len(goal) >= 30 else goal
                            )
                            logger.info(
                                f"🔍 Analyze critique fired | "
                                f"Step {step_num}/{total} | "
                                f"Revised | Goal: {goal_preview}..."
                            )
                    else:
                        final_analyze_output = analyze_output
                    # ── End Analyze Step Critique Loop ───────────────────

                    execution_context[user_id]["steps"].append({
                        "step": step_num, "type": "analyze",
                        "content": final_analyze_output
                    })

                    # Extract key findings from analyze output
                    # via background model
                    try:
                        _kf_prompt = (
                            "Extract 1-3 key findings from this analysis. "
                            "Return a JSON array of objects with keys: "
                            "'finding' (string, one sentence), "
                            "'confidence' (float 0.0-1.0). "
                            "Return only valid JSON, no markdown, "
                            "no explanation.\n\n"
                            f"Analysis:\n{analyze_output[:1000]}"
                        )
                        _kf_list = await call_background_model_json(_kf_prompt)
                        if not _kf_list or not isinstance(_kf_list, list):
                            raise ValueError("no valid key findings returned")
                        for _kf in _kf_list:
                            if isinstance(_kf, dict) and "finding" in _kf:
                                execution_context[user_id][
                                    "key_findings"
                                ].append({
                                    "finding": _kf["finding"],
                                    "confidence": float(
                                        _kf.get("confidence", 0.8)
                                    ),
                                    "source_step": step_num,
                                })
                    except Exception:
                        pass  # non-fatal — key findings are supplementary

                elif step_type == "draft":
                    ctx = _format_execution_context(
                        execution_context.get(
                            user_id, {}
                        ).get("steps", []),
                        key_findings=execution_context.get(
                            user_id, {}
                        ).get("key_findings", [])
                    )
                    if _crew_label:
                        await ws_manager.send(session_id, {
                            "type": "status",
                            "text": f"{_crew_label}Step {step_num}: drafting..."
                        })
                    _draft_kwargs = (
                        {"system": _crew_system} if _crew_system else {}
                    )
                    r = client.messages.create(
                        model=MAIN_MODEL,
                        max_tokens=4096,
                        **_draft_kwargs,
                        messages=[{"role": "user", "content": (
                            f"Goal: {goal}\n\n"
                            f"Research and analysis:\n{ctx}\n\n"
                            f"Task: {step_desc}\n\n"
                            "Produce the final output as requested."
                        )}]
                    )
                    final_output = r.content[0].text.strip()
                    if _crew_label:
                        final_output = _crew_label + final_output
                    execution_context[user_id]["steps"].append({
                        "step": step_num, "type": "draft",
                        "content": final_output
                    })

                elif step_type == "save_memory":
                    content_to_save = (
                        step_query if step_query != step_desc else step_desc
                    )
                    if memory_mode == "ephemeral":
                        execution_context[user_id]["steps"].append({
                            "step": step_num, "type": "save_memory",
                            "content": "[Skipped — ephemeral channel]"
                        })
                        await ws_manager.send(session_id, {
                            "type": "status",
                            "text": "💾 Save skipped — this channel doesn't persist memories."
                        })
                    else:
                        await extract_and_store_memories(
                            user_message=content_to_save,
                            bot_reply="",
                            task_completed=True,
                            project_tag=project_tag,
                            channel_name=channel_name,
                            memory_mode=memory_mode,
                            background_model_fn=call_background_model
                        )
                        execution_context[user_id]["steps"].append({
                            "step": step_num, "type": "save_memory",
                            "content": f"Saved to memory: {content_to_save[:100]}"
                        })
                        await ws_manager.send(session_id, {
                            "type": "status",
                            "text": f"💾 Saved to memory: {content_to_save[:80]}"
                        })

                elif step_type == "call_agent":
                    agent_slug = step.get("agent", "").strip()
                    if not agent_slug or agent_slug not in AGENT_DEFINITIONS:
                        logger.info(
                            f"call_agent step missing valid slug | "
                            f"step={step_num} | got={agent_slug!r} | "
                            f"falling back to analyze"
                        )
                        ctx = _format_execution_context(
                            execution_context.get(
                                user_id, {}
                            ).get("steps", []),
                            key_findings=execution_context.get(
                                user_id, {}
                            ).get("key_findings", [])
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
                        agent_response = r.content[0].text.strip()
                        execution_context[user_id]["steps"].append({
                            "step": step_num, "type": "call_agent",
                            "content": agent_response
                        })
                        await ws_manager.send(session_id, {
                            "type": "message",
                            "text": agent_response
                        })
                    else:
                        agent_name = AGENT_DEFINITIONS[agent_slug]["name"]
                        agent_system = AGENT_DEFINITIONS[agent_slug]["content"]
                        if len(agent_system) > AGENT_INJECT_CHAR_LIMIT:
                            agent_system = (
                                agent_system[:AGENT_INJECT_CHAR_LIMIT]
                                + "\n[Agent definition truncated]"
                            )
                        ctx = _format_execution_context(
                            execution_context.get(
                                user_id, {}
                            ).get("steps", []),
                            key_findings=execution_context.get(
                                user_id, {}
                            ).get("key_findings", [])
                        )
                        r = client.messages.create(
                            model=MAIN_MODEL,
                            max_tokens=2048,
                            system=agent_system,
                            messages=[{"role": "user", "content": (
                                f"Goal context: {goal}\n\n"
                                f"Information gathered:\n{ctx}\n\n"
                                f"Task: {step_desc}"
                            )}]
                        )
                        agent_response = r.content[0].text.strip()
                        execution_context[user_id]["steps"].append({
                            "step": step_num, "type": "call_agent",
                            "content": f"[{agent_name}]: {agent_response}"
                        })
                        await ws_manager.send(session_id, {
                            "type": "message",
                            "text": f"🤖 [{agent_name}]: {agent_response}"
                        })

                    # ── QUESTION GATE ────────────────────────────────────
                    # The agent asked the user for input before it can do
                    # its work. Pause so the user can answer; their reply
                    # is appended to execution_context on resume so the
                    # next step has access to it.
                    if _agent_response_has_questions(agent_response):
                        pg["status"] = "gated"
                        pg["current_step"] = i + 1
                        gate_pending[user_id] = {
                            "type": "question_gate",
                            "step_index": i + 1,
                            "step_num": step_num,
                            "author_display_name": author_display_name,
                        }
                        _persist_goal_state(user_id)
                        await ws_manager.send(session_id, {
                            "type": "gate",
                            "gate_kind": "question",
                            "text": (
                                f"❓ **The agent needs your input before "
                                f"continuing (step {step_num})**\n\n"
                                f"{agent_response}"
                            ),
                        })
                        return

            except Exception as e:
                # ── STEP FAILURE GATE ────────────────────────────────────
                remaining_descs = "\n".join(
                    f"- **Step {s.get('step_number', '?')}** "
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
                _persist_goal_state(user_id)
                await ws_manager.send(session_id, {
                    "type": "gate",
                    "text": (
                        f"⚠️ **Step {step_num} failed**\n\n"
                        f"{str(e)[:200]}"
                        + (
                            f"\n\n**Remaining steps:**\n\n{remaining_descs}"
                            if remaining_descs else ""
                        )
                    )
                })
                return

    except Exception as e:
        logger.error(
            f"Goal execution error | User: {author_display_name} | {str(e)}"
        )
        # Surface the failure to the user — without this the thinking
        # indicator stays on the last status text and the chat appears frozen.
        try:
            await ws_manager.send(session_id, {
                "type": "error",
                "text": f"Goal execution failed: {str(e)[:200]}",
            })
        except Exception:
            pass
        pending_goals.pop(user_id, None)
        execution_context.pop(user_id, None)
        gate_pending.pop(user_id, None)
        delete_goal_state(user_id)
        return

    # ── Deliver output ───────────────────────────────────────────────────────
    if final_output:
        completion_text = final_output
    else:
        findings = execution_context.get(user_id, {}).get("steps", [])
        if findings:
            parts = [f"**Goal complete: {goal}**\n"]
            for f in findings:
                parts.append(
                    f"**Step {f['step']} ({f['type']}):**\n"
                    f"{f['content'][:600]}"
                )
            completion_text = "\n\n".join(parts)
        else:
            completion_text = f"Goal complete: {goal}"

    await ws_manager.send(session_id, {
        "type": "message",
        "text": completion_text,
    })

    # Persist the final draft / completion text so reloading the thread
    # restores the goal output. The !goal trigger and Approve click both
    # bypass process_user_message, so without this the result is lost.
    append_history_turn(user_id, session_id, "assistant", completion_text)
    await persist_history(user_id, session_id)

    await ws_manager.send(session_id, {
        "type": "status",
        "text": f"✅ Goal complete — {total} steps executed"
    })

    web_searches = pg.get("web_search_count", 0)
    mem_queries = sum(
        1 for f in execution_context.get(user_id, {}).get("steps", [])
        if f["type"] == "query_memory"
    )
    logger.info(
        f"Goal completed | Steps: {total} | "
        f"Web searches: {web_searches} | "
        f"Memory queries: {mem_queries} | "
        f"Channel: #{channel_name}"
    )

    output_for_memory = final_output or goal
    if memory_mode != "ephemeral":
        await extract_and_store_memories(
            goal, output_for_memory, True,
            project_tag=project_tag,
            channel_name=channel_name,
            memory_mode=memory_mode,
            background_model_fn=call_background_model
        )
        rejections = drain_rubric_rejection_log()
        for rejection in rejections:
            logger.info(
                f"🚫 Memory rejected by rubric | "
                f"Score: {rejection['score']}/12 | "
                f"Layer: {rejection['layer']} | "
                f"Content: {rejection['content']}..."
            )

    pending_goals.pop(user_id, None)
    execution_context.pop(user_id, None)
    gate_pending.pop(user_id, None)
    delete_goal_state(user_id)


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
    session_id = pg["session_id"]

    gate_pending.pop(user_id, None)
    _persist_goal_state(user_id)

    if action == "skip" and gate_type == "step_failure":
        pg["current_step"] = step_index + 1
        pg["status"] = "executing"
        _persist_goal_state(user_id)
        remaining_count = len(pg["steps"]) - (step_index + 1)
        await ws_manager.send(session_id, {
            "type": "status",
            "text": (
                f"⏭️ Step skipped — continuing with "
                f"{remaining_count} remaining step(s)..."
            )
        })
        asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    if action == "retry" and gate_type == "step_failure":
        pg["current_step"] = step_index
        pg["status"] = "executing"
        _persist_goal_state(user_id)
        await ws_manager.send(session_id, {
            "type": "status",
            "text": "🔄 Retrying step..."
        })
        asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    if action == "continue":
        pg["status"] = "executing"
        if gate_type == "draft_gate":
            pg["current_step"] = step_index
            _persist_goal_state(user_id)
            await ws_manager.send(session_id, {
                "type": "status",
                "text": "✍️ Generating draft..."
            })
            asyncio.create_task(
                execute_goal(
                    user_id, author_display_name,
                    skip_gate_for_step=step_index
                )
            )
        elif gate_type == "question_gate":
            # Append the user's answers to execution_context so subsequent
            # steps see them via _format_execution_context. If the user
            # didn't type anything we still continue — they may have
            # answered the gate without text.
            answer = (changes or "").strip()
            if answer:
                ctx = execution_context.setdefault(
                    user_id, {"steps": [], "key_findings": []}
                )
                ctx["steps"].append({
                    "step": gate.get("step_num", step_index),
                    "type": "user_response",
                    "content": answer,
                })
            pg["current_step"] = step_index
            _persist_goal_state(user_id)
            await ws_manager.send(session_id, {
                "type": "status",
                "text": "▶️ Continuing execution..."
            })
            asyncio.create_task(execute_goal(user_id, author_display_name))
        else:
            # research_gate: step_index already points to the next step
            pg["current_step"] = step_index
            _persist_goal_state(user_id)
            await ws_manager.send(session_id, {
                "type": "status",
                "text": "▶️ Continuing execution..."
            })
            asyncio.create_task(execute_goal(user_id, author_display_name))
        return

    if action == "adjust":
        await _replan_remaining_steps(
            user_id, author_display_name, step_index, changes, session_id, pg
        )
        return


async def process_tool_calls(
    response, session_id: str, tool_call_count, channel_name=None,
    memory_mode: str = "global"
):
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
            logger.info(
                f"Tool called: {tool_name} | "
                f"Inputs: {json.dumps(tool_inputs)[:200]}"
            )

            # Status before execution — dedicated messages for specific tools
            if tool_name == "web_search":
                await ws_manager.send(session_id, {
                    "type": "status", "text": "🔍 Searching the web..."
                })
            elif tool_name == "web_fetch":
                _fetch_domain = (
                    tool_inputs.get("url", "").split("/")[2]
                    if "//" in tool_inputs.get("url", "")
                    else tool_inputs.get("url", "")
                )
                await ws_manager.send(session_id, {
                    "type": "status",
                    "text": f"🌐 Reading {_fetch_domain}..."
                })
            elif tool_name == "search_codebase":
                await ws_manager.send(session_id, {
                    "type": "status", "text": "🔎 Searching codebase..."
                })
            else:
                await ws_manager.send(session_id, {
                    "type": "status",
                    "text": f"🔧 Using tool: {tool_name}"
                })

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

            if tool_name == "web_fetch":
                _fetch_url = tool_inputs.get("url", "")
                _fetch_domain = (
                    _fetch_url.split("/")[2]
                    if "//" in _fetch_url
                    else _fetch_url
                )
                _fetch_chars = len(str(result))
                logger.info(
                    f"Web fetch | URL: {_fetch_url[:60]} | "
                    f"Content: {_fetch_chars} chars | "
                    f"Channel: #{channel_name}"
                )
                _fetch_tokens = _fetch_chars // 4
                if _fetch_tokens > 2000:
                    logger.info(
                        f"Web fetch large | ~{_fetch_tokens} tokens | "
                        f"URL: {_fetch_domain} | "
                        f"Consider reducing max_chars"
                    )

            if tool_name == "search_codebase":
                logger.info(
                    f"Codebase search | "
                    f"Query: {tool_inputs.get('query', '')[:40]} | "
                    f"Results: {len(str(result))} chars | "
                    f"Channel: #{channel_name}"
                )

            # Fire-and-forget reasoning trace — run in executor to avoid blocking
            _trace_loop = asyncio.get_running_loop()
            _trace_loop.run_in_executor(
                None,
                log_reasoning_trace,
                "system",
                channel_name or "unknown",
                tool_name,
                tool_inputs,
                str(result)[:1000],
                tool_call_count,
            )

    return tool_results, tool_call_count


async def process_user_message(
    user_message, user_id, author_display_name,
    session_id: str, memory_mode: str = "global",
    project_tag: str = None, active_agent_slug: str = None,
    agent_trigger: str = "none", context_id: int = 0,
    channel_name: str = None,
):
    """
    Shared Claude processing pipeline for WebSocket message handling.
    Handles memory retrieval, the agentic tool loop, memory storage,
    reflection, and logging.

    context_id: thread or conversation ID used to key conversation_history
        so each thread gets its own independent history.
    channel_name: the context name (for routing / memory lookups).
        Defaults to "general" if not supplied.
    session_id: the active WebSocket session identifier used for all
        response delivery via ws_manager.
    """
    effective_channel_name = channel_name or "general"

    # ── Drop-and-File mode (Institute Prime, entity-linked threads) ──
    # Two intercept paths fire before the normal pipeline:
    #   (a) An open pending filing for (user, thread) means the user's
    #       reply is a confirm / abandon / edit decision, not a fresh
    #       chat message.
    #   (b) On an entity-linked Institute Prime thread, a transcript-
    #       shaped inbound message routes to Haiku extraction instead
    #       of the agentic loop.
    # Both paths persist the exchange to conversation_history so the
    # chat UI renders the back-and-forth, then return early.
    _filing_state_key = (str(user_id), str(context_id))
    _pending_filing = state.pending_filings.get(_filing_state_key)
    _filing_thread_row = None
    _filing_entity_id: int | None = None
    _filing_entity_name = ""
    try:
        from app.db.threads import get_thread as _filing_get_thread
        _filing_thread_row = (
            _filing_get_thread(str(context_id)) if context_id else None
        )
        _ent_raw = (
            _filing_thread_row.get("entity_id")
            if _filing_thread_row else None
        )
        if _ent_raw:
            _ent_obj = get_entity_by_id(int(_ent_raw))
            if _ent_obj:
                _filing_entity_id = int(_ent_raw)
                _filing_entity_name = str(_ent_obj.get("name") or "")
    except Exception as _f_err:
        logger.warning(f"[filing] thread lookup failed: {_f_err}")

    _is_institute_entity_thread = (
        effective_channel_name == "institute"
        and _filing_entity_id is not None
    )

    if _pending_filing and _is_institute_entity_thread:
        intent = _classify_filing_intent(user_message)
        # Persist the user reply regardless of intent.
        log_conversation_turn(
            str(user_id), context_id, effective_channel_name,
            "user", user_message, project_tag=project_tag,
        )
        append_history_turn(
            user_id, context_id, "user", user_message,
        )

        if intent == "abandon":
            state.pending_filings.pop(_filing_state_key, None)
            _abandon_msg = (
                "Got it — nothing filed. The draft is discarded."
            )
            await ws_manager.send(session_id, {
                "type": "response", "text": _abandon_msg,
            })
            append_history_turn(
                user_id, context_id, "assistant", _abandon_msg,
            )
            await persist_history(user_id, context_id)
            return

        if intent == "confirm":
            _loop = asyncio.get_running_loop()
            saved = await _loop.run_in_executor(
                None,
                _save_filing_items,
                _pending_filing["entity_id"],
                _pending_filing.get("items") or [],
            )
            state.pending_filings.pop(_filing_state_key, None)
            _ok_msg = (
                f"✅ Filed {saved} item"
                f"{'' if saved == 1 else 's'} to "
                f"{_pending_filing['entity_name']}'s timeline."
            )
            await ws_manager.send(session_id, {
                "type": "response", "text": _ok_msg,
            })
            append_history_turn(
                user_id, context_id, "assistant", _ok_msg,
            )
            await persist_history(user_id, context_id)
            return

        # intent == "edit" — re-extract with the user's note.
        await ws_manager.send(session_id, {
            "type": "status",
            "text": "📝 Updating the draft...",
        })
        _reparsed = await _run_haiku_filing_extraction(
            _pending_filing.get("transcript") or "",
            edit_note=user_message,
        )
        if _reparsed is None:
            _fail_msg = (
                "I couldn't apply that edit cleanly — the draft "
                "is unchanged. Try rephrasing, or say 'save' to "
                "file the current draft."
            )
            await ws_manager.send(session_id, {
                "type": "response", "text": _fail_msg,
            })
            append_history_turn(
                user_id, context_id, "assistant", _fail_msg,
            )
            await persist_history(user_id, context_id)
            return

        _new_items = (
            _reparsed.get("items")
            if isinstance(_reparsed.get("items"), list) else []
        )
        _new_date = str(
            _reparsed.get("date")
            or _pending_filing.get("date") or ""
        )
        _new_summary = _format_filing_summary(
            _new_date, _filing_entity_name, _new_items,
        )
        state.pending_filings[_filing_state_key] = {
            "entity_id": _filing_entity_id,
            "entity_name": _filing_entity_name,
            "items": _new_items,
            "date": _new_date,
            "transcript": _pending_filing.get("transcript") or "",
            "summary": _new_summary,
        }
        await ws_manager.send(session_id, {
            "type": "response", "text": _new_summary,
        })
        append_history_turn(
            user_id, context_id, "assistant", _new_summary,
        )
        await persist_history(user_id, context_id)
        return

    # Fresh transcript dump? Check before any other processing so
    # the heavy memory + entity-injection setup doesn't run for what
    # turns out to be a filing.
    if _is_institute_entity_thread:
        _early_files = list(
            attached_files.get((user_id, context_id), [])
        )
        _doc_files = [
            f for f in _early_files
            if f.get("content_type") == "document"
            and f.get("text_content")
        ]
        _has_doc_attachment = bool(_doc_files)
        if _is_transcript_dump(user_message, _has_doc_attachment):
            log_conversation_turn(
                str(user_id), context_id, effective_channel_name,
                "user", user_message, project_tag=project_tag,
            )
            append_history_turn(
                user_id, context_id, "user", user_message,
            )
            await ws_manager.send(session_id, {
                "type": "status",
                "text": "📋 Extracting structured items from the transcript...",
            })
            _transcript_parts = []
            if user_message and user_message.strip():
                _transcript_parts.append(user_message.strip())
            for _df in _doc_files:
                _label = _df.get("filename") or "attached file"
                _content = (_df.get("text_content") or "")[:8000]
                _transcript_parts.append(
                    f"--- {_label} ---\n{_content}"
                )
            _transcript = "\n\n".join(_transcript_parts)

            _parsed = await _run_haiku_filing_extraction(_transcript)
            if _parsed is None:
                _parse_fail = (
                    "I couldn't parse that as a clean transcript — "
                    "treating it as a normal message. Paste a more "
                    "structured version or attach a file."
                )
                await ws_manager.send(session_id, {
                    "type": "response", "text": _parse_fail,
                })
                append_history_turn(
                    user_id, context_id, "assistant", _parse_fail,
                )
                await persist_history(user_id, context_id)
                return

            _items = (
                _parsed.get("items")
                if isinstance(_parsed.get("items"), list) else []
            )
            _date_str = str(
                _parsed.get("date")
                or datetime.utcnow().strftime("%Y-%m-%d")
            )
            _summary = _format_filing_summary(
                _date_str, _filing_entity_name, _items,
            )
            state.pending_filings[_filing_state_key] = {
                "entity_id": _filing_entity_id,
                "entity_name": _filing_entity_name,
                "items": _items,
                "date": _date_str,
                "transcript": _transcript,
                "summary": _summary,
            }
            await ws_manager.send(session_id, {
                "type": "response", "text": _summary,
            })
            append_history_turn(
                user_id, context_id, "assistant", _summary,
            )
            await persist_history(user_id, context_id)
            return

    # ── Langfuse trace ───────────────────────────────────
    _lf_trace = None
    if state._langfuse:
        try:
            _lf_trace = state._langfuse.trace(
                name="process_user_message",
                user_id=str(user_id),
                session_id=str(context_id),
                metadata={
                    "channel": effective_channel_name,
                    "agent": active_agent_slug or "none",
                    "memory_mode": memory_mode,
                    "project_tag": project_tag or "none",
                },
                input=user_message[:500],
            )
        except Exception as _lf_e:
            print(f"[Langfuse] Trace creation failed: {_lf_e}")
            _lf_trace = None

    _hist_key = (user_id, context_id)
    system_chars = 0
    memory_context_chars = 0
    history_chars = 0
    tool_schema_chars = 0
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
    memory_context_chars = len(memory_context) if memory_context else 0

    # ── Entity profile injection ──────────────────────────────
    # Institute Prime is the canonical home for the roster — entity
    # profiles are matched against the message by name and injected
    # directly into the prompt as context.
    #
    # Admin Prime gets a *one-way bridge*: when the user explicitly
    # asks about their team, we do a cross-workspace lookup into
    # Institute Prime's entity data and inject it as ephemeral
    # context for this turn only. The injected text never gets
    # written back into Admin Prime's memory — the orchestrator's
    # memory pipeline only persists the AI's response and the user's
    # original message, not synthetic context blocks, so isolation
    # holds without extra plumbing.
    _entity_context = ""
    _do_entity_lookup = effective_channel_name == "institute"
    if effective_channel_name == "admin":
        _msg_lower_check = user_message.lower()
        if any(p in _msg_lower_check for p in _ADMIN_TEAM_QUERY_PHRASES):
            _do_entity_lookup = True

    if _do_entity_lookup:
        _known = list_entities(entity_type="person")
        _known_names = [e["name"].lower() for e in _known]
        _msg_lower = user_message.lower()
        _matched = [
            e["name"] for e in _known
            if e["name"].lower() in _msg_lower
        ]
        # In Admin Prime, the team-query phrases ("my team", "what do
        # you know about", …) imply the user wants a roster view even
        # if no specific name was mentioned. Fall back to the top few
        # entities so the cross-workspace bridge isn't useless on a
        # bare "pull up team patterns".
        if not _matched and effective_channel_name == "admin":
            _matched = [e["name"] for e in _known[:3]]
        if _matched:
            _profile_blocks = []
            for _person_name in _matched[:3]:  # cap at 3 per message
                _block = format_entity_profile_for_prompt(_person_name)
                if _block:
                    _profile_blocks.append(_block)
            if _profile_blocks:
                _header = (
                    "[PEOPLE CONTEXT — cross-pulled from Institute "
                    "Prime, ephemeral, do not store]\n"
                    if effective_channel_name == "admin"
                    else "[PEOPLE CONTEXT — retrieved from entity memory]\n"
                )
                _entity_context = (
                    _header
                    + "\n\n".join(_profile_blocks)
                    + "\n"
                )
    _mem_count = sum(
        len(memories.get(k, [])) for k in ("strategic", "operational", "analytical")
    )
    if _mem_count > 0:
        await ws_manager.send(session_id, {
            "type": "status",
            "text": "🧠 Memory searched — context loaded"
        })

    _ws = WORKSPACES.get(effective_channel_name, {})
    channel_purpose = _ws.get(
        "personality", f"General workspace: {effective_channel_name}"
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

    # ── Thread-linked entity context ──────────────────────────────
    # If this thread was opened from the roster (entity_id set on the
    # row), pull the entity's facts + active tags + timeline tail and
    # inject them so Drift knows who the conversation is about. This
    # is independent of the keyword-detect _entity_context above and
    # is the authoritative source when the link is explicit.
    # Captured for the post-response hooks (rename + coaching logger).
    _entity_thread_entity_id: int | None = None
    _entity_thread_name: str = ""
    _entity_thread_title: str = ""
    _entity_thread_msg_count: int = 0

    _thread_entity_context = ""
    try:
        from app.db.threads import get_thread as _get_thread
        _thread_row = _get_thread(str(context_id)) if context_id else None
        _ent_id = _thread_row.get("entity_id") if _thread_row else None
        if _thread_row:
            _entity_thread_title = str(_thread_row.get("title") or "")
            _entity_thread_msg_count = int(
                _thread_row.get("message_count") or 0
            )
        if _ent_id:
            _ent = get_entity_by_id(int(_ent_id))
            if _ent:
                _entity_thread_entity_id = int(_ent_id)
                _entity_thread_name = str(_ent.get("name") or "")
                _tags = get_entity_tags(int(_ent_id))
                _timeline = get_entity_timeline(int(_ent_id))[-6:]
                _rel = (_ent.get("relationship_type") or "")
                _rel_label = _rel.replace("_", " ").title() if _rel else ""
                _role = _ent.get("role") or ""
                if _role and _rel_label:
                    _ident = f"{_ent['name']} ({_role}, {_rel_label})"
                elif _role:
                    _ident = f"{_ent['name']} ({_role})"
                elif _rel_label:
                    _ident = f"{_ent['name']} ({_rel_label})"
                else:
                    _ident = _ent["name"]
                _lines = [
                    f"[Entity context: This thread is about {_ident}."
                ]
                if _tags:
                    _lines.append(
                        "Active situations: " + ", ".join(_tags) + "."
                    )
                if _timeline:
                    _lines.append("Recent timeline:")
                    for _entry in _timeline:
                        _date = (_entry.get("recorded_at") or "")[:10]
                        _cat = _entry.get("category", "note")
                        _fact = (_entry.get("fact") or "").strip()
                        _status_suffix = (
                            " [superseded]"
                            if _entry.get("status") != "active" else ""
                        )
                        _lines.append(
                            f"  • [{_date}] {_cat}: {_fact}{_status_suffix}"
                        )
                _lines.append(
                    "Use this context to inform your responses — "
                    "this is who Jerm is talking about.]"
                )
                _thread_entity_context = "\n".join(_lines) + "\n\n"
    except Exception as _ee:
        logger.warning(f"[entity_ctx] lookup failed: {_ee}")

    # Always wrap user_message with the "Current message:" marker so the
    # /threads/{id}/messages endpoint can reliably split the channel /
    # entity / memory prefix off when returning stored history. Without
    # this, a turn with no memory_context stored the raw user text right
    # after the channel block and the prefix leaked into the chat bubble
    # on reload.
    full_message = f"Current message: {user_message}"
    if memory_context:
        full_message = (
            f"{memory_context}\n\n"
            f"Current message: {user_message}"
        )

    full_message = (
        f"{channel_ctx}\n"
        f"{_thread_entity_context}"
        f"{_entity_context}"
        f"{_search_context}"
        f"{full_message}"
    )

    # ── FILE INJECTION ────────────────────────────────────────
    file_injection_chars = 0
    all_user_files = list(attached_files.get((user_id, context_id), []))
    is_isolated_channel = effective_channel_name in (ISOLATED_WORKSPACES | {"health-tracking"})

    if all_user_files:
        if is_isolated_channel:
            user_files = [
                f for f in all_user_files
                if f.get("channel_name") == effective_channel_name
            ]
        else:
            user_files = [
                f for f in all_user_files
                if f.get("channel_name") not in (ISOLATED_WORKSPACES | {"health-tracking"})
            ]

        doc_files       = [f for f in user_files if f["content_type"] == "document"]
        img_files       = [f for f in user_files if f["content_type"] == "image"]
        pdf_vision_files = [f for f in user_files if f["content_type"] == "pdf_vision"]

        if user_files:
            await ws_manager.send(session_id, {
                "type": "status",
                "text": "📎 Reading attached file(s)..."
            })

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
                "timestamp": _now_iso(),
            })
        else:
            conversation_history[_hist_key].append({
                "role": "user",
                "content": full_message,
                "timestamp": _now_iso(),
            })
    else:
        conversation_history[_hist_key].append({
            "role": "user",
            "content": full_message,
            "timestamp": _now_iso(),
        })

    await ws_manager.send(session_id, {
        "type": "status",
        "text": f"Processing request from {author_display_name}..."
    })

    if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS:
        await ws_manager.send(session_id, {
            "type": "status",
            "text": f"🤖 {AGENT_DEFINITIONS[active_agent_slug]['name']} activated"
        })

    try:
        tool_call_count = 0
        final_response_text = ""
        _ws_tools = WORKSPACES.get(effective_channel_name, {})
        tool_mode = _ws_tools.get("tool_mode", "none")
        if tool_mode == "full":
            if _ws_tools.get("entity_memory", False):
                # Entity-memory workspaces include save_person_fact
                active_tools = list(TOOL_DEFINITIONS)
            else:
                # All other full workspaces exclude save_person_fact
                active_tools = [
                    t for t in TOOL_DEFINITIONS
                    if t["name"] != "save_person_fact"
                ]
        elif tool_mode == "search_only":
            _search_only = {"web_search", "web_fetch", "query_memory"}
            active_tools = [
                t for t in TOOL_DEFINITIONS
                if t["name"] in _search_only
            ]
        else:
            active_tools = []

        if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS:
            _adef = AGENT_DEFINITIONS[active_agent_slug]
            _agent_content = _adef["content"]
            if len(_agent_content) > AGENT_INJECT_CHAR_LIMIT:
                _agent_content = (
                    _agent_content[:AGENT_INJECT_CHAR_LIMIT]
                    + "\n[Agent definition truncated for token efficiency]"
                )
            effective_system = (
                SYSTEM_PROMPT
                + f"\n\n---\nACTIVE SPECIALIST AGENT: {_adef['name']}\n"
                + _agent_content
            )
        else:
            effective_system = SYSTEM_PROMPT

        system_chars = len(effective_system)
        _session_ctx = format_session_context(str(user_id), context_id)
        if _session_ctx:
            effective_system = (
                effective_system
                + "\n\n---\n"
                + _session_ctx
            )
        _reasoning_iterations = 0
        total_in_tokens = 0
        total_out_tokens = 0
        total_cache_write_tokens = 0
        total_cache_read_tokens = 0
        while True:
            _reasoning_iterations += 1
            if _reasoning_iterations > MAX_REASONING_ITERATIONS:
                logger.info(
                    f"[Safety] Reasoning loop hit MAX_REASONING_ITERATIONS "
                    f"({MAX_REASONING_ITERATIONS}) — forcing break"
                )
                break

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
                "max_tokens": 4096,
                "system": [
                    {
                        "type": "text",
                        "text": effective_system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                # Strip the timestamp field before sending — Anthropic's
                # messages schema rejects extra keys. Timestamps live on
                # the stored history for the /messages endpoint and the
                # frontend; the model itself doesn't need them.
                "messages": [
                    {k: v for k, v in m.items() if k in ("role", "content")}
                    for m in conversation_history[_hist_key]
                ],
            }
            if active_tools:
                api_params["tools"] = active_tools

            if _reasoning_iterations == 1:
                # Measure history excluding current turn to avoid
                # double-counting memory context
                _prior_turns = conversation_history[_hist_key][:-1]
                history_chars = sum(
                    len(str(m.get("content", "")))
                    for m in _prior_turns
                )
                tool_schema_chars = sum(
                    len(json.dumps(t)) for t in active_tools
                )

            _lf_generation = None
            if _lf_trace:
                try:
                    _lf_generation = _lf_trace.generation(
                        name=f"claude_call_{_reasoning_iterations}",
                        model=MAIN_MODEL,
                        input=conversation_history[_hist_key][-3:],
                    )
                except Exception:
                    _lf_generation = None

            _overloaded = False
            _rate_limited = False
            for _attempt_delay in [None, 2, 4, 8]:
                if _attempt_delay is not None:
                    await asyncio.sleep(_attempt_delay)
                try:
                    response = client.messages.create(**api_params)
                    _overloaded = False
                    _rate_limited = False
                    break
                except APIStatusError as e:
                    if e.status_code == 529:
                        _overloaded = True
                    elif e.status_code == 429 and not _rate_limited:
                        _rate_limited = True
                        await asyncio.sleep(60)
                        try:
                            response = client.messages.create(**api_params)
                            _rate_limited = False
                            break
                        except APIStatusError as _e2:
                            if _e2.status_code == 429:
                                pass
                            else:
                                raise
                    else:
                        raise
            if _overloaded:
                await ws_manager.send(session_id, {
                    "type": "error",
                    "text": (
                        "Anthropic's API is currently overloaded. "
                        "Please try again in a moment."
                    )
                })
                return
            if _rate_limited:
                await ws_manager.send(session_id, {
                    "type": "error",
                    "text": (
                        "Rate limit hit — please wait a moment "
                        "before sending another message."
                    )
                })
                return

            if _lf_generation:
                try:
                    _lf_generation.end(
                        output=response.content[0].text
                        if response.content and
                        hasattr(response.content[0], "text")
                        else "",
                        usage={
                            "input": response.usage.input_tokens,
                            "output": response.usage.output_tokens,
                        }
                    )
                except Exception:
                    pass

            total_in_tokens += response.usage.input_tokens
            total_out_tokens += response.usage.output_tokens
            total_cache_write_tokens += getattr(
                response.usage, 'cache_creation_input_tokens', 0
            )
            total_cache_read_tokens += getattr(
                response.usage, 'cache_read_input_tokens', 0
            )

            if response.stop_reason == "tool_use":
                conversation_history[_hist_key].append({
                    "role": "assistant",
                    "content": response.content,
                    "timestamp": _now_iso(),
                })
                tool_results, tool_call_count = \
                    await process_tool_calls(
                        response, session_id, tool_call_count,
                        channel_name=effective_channel_name,
                        memory_mode=memory_mode,
                    )
                conversation_history[_hist_key].append({
                    "role": "user",
                    "content": tool_results,
                    "timestamp": _now_iso(),
                })
                continue

            for block in response.content:
                if hasattr(block, "text"):
                    final_response_text += block.text

            conversation_history[_hist_key].append({
                "role": "assistant",
                "content": final_response_text,
                "timestamp": _now_iso(),
            })
            break

        # Drain escalation queue and write high-priority flags to notifications
        pending_escalations = drain_escalation_queue()
        for item in pending_escalations:
            escalation_content = (
                f"🚨 High-priority flag escalated from #{item['source_channel']}\n"
                f"Topic: {item['topic']}\n"
                f"Reason: {item['reason']}"
            )
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO notifications (type, content, read) VALUES (?, ?, 0)",
                ("escalation", escalation_content)
            )
            conn.commit()
            conn.close()

        if final_response_text:
            log_conversation_turn(
                str(user_id), context_id, effective_channel_name,
                "assistant", final_response_text, project_tag=project_tag
            )

        # ── SLIDING WINDOW HISTORY ───────────────────────────
        _full_history = conversation_history[_hist_key]
        _is_isolated = effective_channel_name in (ISOLATED_WORKSPACES | {"health-tracking"})

        if (len(_full_history) > HISTORY_RAW_WINDOW
                and not _is_isolated
                and memory_mode != "ephemeral"):
            _raw_tail = _full_history[-HISTORY_RAW_WINDOW:]
            _head = _full_history[:-HISTORY_RAW_WINDOW]

            _existing_summary = ""
            _head_to_summarize = _head
            if (_head
                    and _head[0].get("role") == HISTORY_SUMMARY_ROLE
                    and isinstance(_head[0].get("content"), str)
                    and _head[0]["content"].startswith(
                        "[CONVERSATION SUMMARY]"
                    )):
                _existing_summary = _head[0]["content"]
                _head_to_summarize = _head[1:]

            if _head_to_summarize:
                _new_summary_text = await _summarize_history_tail(
                    _head_to_summarize,
                    context_hint=effective_channel_name
                )

                if _existing_summary:
                    _merged = (
                        _existing_summary
                        + "\n\n[More recent — now summarized]:\n"
                        + _new_summary_text
                    )
                else:
                    _merged = (
                        "[CONVERSATION SUMMARY — earlier context]\n"
                        + _new_summary_text
                    )

                if len(_merged) > 800:
                    _merged = _merged[-800:]

                conversation_history[_hist_key] = [
                    {
                        "role": HISTORY_SUMMARY_ROLE,
                        "content": _merged,
                        "timestamp": _now_iso(),
                    }
                ] + _raw_tail
            else:
                conversation_history[_hist_key] = (
                    [_head[0]] + _raw_tail
                    if _head else _raw_tail
                )
        else:
            conversation_history[_hist_key] = _full_history[-20:]

        if final_response_text and memory_mode != "ephemeral":
            _action_summary = (
                f"[{datetime.utcnow().strftime('%H:%M')}] "
                + user_message[:80].replace("\n", " ")
            )
            asyncio.create_task(
                _save_session_state_async(
                    str(user_id),
                    context_id,
                    _action_summary,
                    final_response_text,
                )
            )

        if final_response_text:
            await ws_manager.send(session_id, {
                "type": "response",
                "text": final_response_text
            })
            # Child-safety review for Parker's workspace. Fire-and-forget
            # so it never blocks the response delivery; the flag (if any)
            # lands in the content_flags table for admin to review later.
            if str(user_id) == "parker":
                asyncio.create_task(
                    _run_parker_safety_check(
                        user_message=user_message,
                        response_text=final_response_text,
                        thread_id=str(context_id),
                    )
                )

            # Entity-linked thread hooks. Both are fire-and-forget so
            # they never block the response delivery.
            if _entity_thread_entity_id is not None:
                # Coaching logger fires on EVERY turn in an entity-
                # linked thread; the Haiku check decides whether the
                # exchange is significant enough to record.
                asyncio.create_task(
                    _run_entity_coaching_logger(
                        entity_id=_entity_thread_entity_id,
                        entity_name=_entity_thread_name,
                        user_message=user_message,
                        response_text=final_response_text,
                    )
                )
                # Renamer fires ONCE — on the very first user message
                # (message_count == 1 because chat.py just incremented
                # it) AND only if the title is still the placeholder
                # "Coaching: <name>" shape. Manual renames or repeated
                # messages no longer match either condition.
                if (
                    _entity_thread_msg_count == 1
                    and _entity_thread_title.startswith("Coaching: ")
                ):
                    asyncio.create_task(
                        _run_entity_thread_rename(
                            thread_id=str(context_id),
                            user_id=str(user_id),
                            user_message=user_message,
                            entity_name=_entity_thread_name,
                            current_title=_entity_thread_title,
                        )
                    )
        else:
            await ws_manager.send(session_id, {
                "type": "error",
                "text": (
                    "I processed your request but had "
                    "trouble forming a response."
                )
            })

        # ── Med-Bay auto-extraction (fire-and-forget) ─────────────────────
        # Run a background Haiku pass over the last few turns to detect
        # protocol changes / follow-ups / lab readings the user just
        # confirmed, and push them into the medbay tables. Emits a
        # medbay_update WS frame on success so the side panel refetches
        # the affected section.
        if (
            effective_channel_name == "health"
            and final_response_text
        ):
            try:
                _recent_turns = list(conversation_history[_hist_key])[-8:]
            except Exception:
                _recent_turns = []
            asyncio.create_task(
                _run_medbay_extraction(
                    user_id=str(user_id),
                    session_id=session_id,
                    user_message=user_message,
                    response_text=final_response_text,
                    recent_turns=_recent_turns,
                )
            )

        # ── Auto-detect clinical specifics in health-tracking ─────────────
        if effective_channel_name == "health-tracking" and final_response_text:
            saved_count = await extract_and_save_health_protocols(
                final_response_text, call_background_model
            )
            while _health_protocol_log:
                msg = _health_protocol_log.pop(0)
                logger.info(msg)
            if saved_count > 0:
                logger.info(
                    f"🏥 {saved_count} health protocol(s) "
                    f"auto-captured from response"
                )

        if memory_mode != "ephemeral":
            await extract_and_store_memories(
                user_message,
                final_response_text,
                task_completed,
                project_tag=project_tag,
                channel_name=effective_channel_name,
                memory_mode=memory_mode,
                background_model_fn=call_background_model
            )
            rejections = drain_rubric_rejection_log()
            for rejection in rejections:
                logger.info(
                    f"🚫 Memory rejected by rubric | "
                    f"Score: {rejection['score']}/12 | "
                    f"Layer: {rejection['layer']} | "
                    f"Content: {rejection['content']}..."
                )

            if task_completed:
                experiences = get_recent_experiences(
                    limit=5,
                    task_completed_only=True
                )
                await run_reflection_loop(experiences)

            # Fire auto-consolidation in background if thresholds exceeded
            current_stats = memory_stats()
            _cooldown_key = (effective_channel_name,
                             datetime.utcnow().strftime("%Y-%m-%d-%H"))
            if (_should_consolidate(current_stats, effective_channel_name)
                    and _cooldown_key not in _consolidation_cooldown):
                _consolidation_cooldown.add(_cooldown_key)
                asyncio.create_task(
                    consolidate_all_layers(
                        channel_name=effective_channel_name,
                        trigger="auto"
                    )
                )

        stale_count = len(memories.get("stale_flags", []))
        in_tokens = total_in_tokens
        out_tokens = total_out_tokens
        cache_write_tokens = total_cache_write_tokens
        cache_read_tokens = total_cache_read_tokens
        est_cost = (
            (in_tokens / 1_000_000 * 3.00) +
            (out_tokens / 1_000_000 * 15.00) +
            (cache_write_tokens / 1_000_000 * 3.75) +
            (cache_read_tokens / 1_000_000 * 0.30)
        )
        _last_token_usage["input"] = in_tokens
        _last_token_usage["output"] = out_tokens
        logger.info(
            f"Responded to {author_display_name} | "
            f"Model: {response.model} | "
            f"Tools loaded: {', '.join(t['name'] for t in active_tools) or 'none'} | "
            f"Tools used: {tool_call_count} | "
            f"Task complete: {task_completed} | "
            f"Stale flags: {stale_count}"
        )
        cache_note = (
            f" | cache_write: {cache_write_tokens:,} | cache_read: {cache_read_tokens:,}"
            if cache_write_tokens or cache_read_tokens else ""
        )
        _attr_total = (
            system_chars + memory_context_chars
            + history_chars + tool_schema_chars
            + file_injection_chars
        )
        if _attr_total > 0:
            _scale = in_tokens / (_attr_total / 4)
        else:
            _scale = 1.0

        system_tokens_est = int((system_chars / 4) * _scale)
        memory_tokens_est = int((memory_context_chars / 4) * _scale)
        history_tokens_est = int((history_chars / 4) * _scale)
        tool_tokens_est = int((tool_schema_chars / 4) * _scale)
        file_tokens_est = int((file_injection_chars / 4) * _scale)

        logger.info(
            f"Tokens — in: {in_tokens:,} | out: {out_tokens:,}"
            + cache_note
            + f" | est. cost: ${est_cost:.4f}\n"
            + f"  ↳ system: ~{system_tokens_est:,}"
            + f" | memory: ~{memory_tokens_est:,}"
            + f" | history: ~{history_tokens_est:,}"
            + f" | tools: ~{tool_tokens_est:,}"
            + (f" | files: ~{file_tokens_est:,}" if file_injection_chars else "")
        )

        if active_agent_slug and active_agent_slug in AGENT_DEFINITIONS:
            _injected_len = min(
                len(AGENT_DEFINITIONS[active_agent_slug]["content"]),
                AGENT_INJECT_CHAR_LIMIT
            )
            _agent_tokens = _injected_len // 4
            logger.info(
                f"Agent activated | {AGENT_DEFINITIONS[active_agent_slug]['name']} | "
                f"+~{_agent_tokens:,} tokens | trigger: {agent_trigger}"
            )

        await ws_manager.send(session_id, {
            "type": "status",
            "text": f"Response delivered to {author_display_name}. Ready."
        })

        if _lf_trace:
            try:
                _lf_trace.update(
                    output=final_response_text[:500],
                    metadata={
                        "tools_used": tool_call_count,
                        "in_tokens": total_in_tokens,
                        "out_tokens": total_out_tokens,
                        "est_cost": round(est_cost, 6),
                        "cache_read_tokens": total_cache_read_tokens,
                        "cache_write_tokens": total_cache_write_tokens,
                        "agent": active_agent_slug or "none",
                        "task_complete": task_completed,
                    }
                )
                state._langfuse.flush()
            except Exception:
                pass

        if stale_count and not state.stale_warned_this_session:
            state.stale_warned_this_session = True
            logger.warning(
                f"Stale memory flags detected: {stale_count} flag(s) — review may be needed."
            )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            save_conversation_history,
            f"{user_id}:{context_id}",
            _saveable_history(conversation_history[_hist_key])
        )

    except Exception as e:
        await ws_manager.send(session_id, {
            "type": "error",
            "text": "Something went wrong — please try again."
        })
        logger.error(f"Error for {author_display_name}: {str(e)}")


def _ensure_notifications_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            read INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


_ensure_notifications_table()
