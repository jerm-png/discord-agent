# ============================================================
# orchestrator.py — Core message processing and goal execution
# Extracted from bot.py. Imports from config, model, services,
# state, and memory_manager — no imports from bot.py.
# ============================================================

import asyncio
import json
import os
import re
import datetime
from datetime import datetime
from collections import defaultdict

import discord

from config import (
    MAIN_MODEL,
    BACKGROUND_MODEL,
    LOG_CHANNEL,
    STATUS_CHANNEL,
    MAX_TOOL_CALLS,
    MAX_REASONING_ITERATIONS,
    AGENT_INJECT_CHAR_LIMIT,
    GOAL_GATE_MODE,
    HISTORY_RAW_WINDOW,
    HISTORY_SUMMARY_ROLE,
    CONSOLIDATION_THRESHOLDS,
)
from model import (
    client,
    call_background_model,
    call_background_model_json,
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
    _consolidation_cooldown,
    _last_token_usage,
    stale_warned_this_session,
    BOT_START_TIME,
)
from memory.memory_manager import (
    get_relevant_memories,
    format_memory_for_prompt,
    save_strategic_memory,
    save_operational_memory,
    save_analytical_memory,
    save_experience,
    memory_stats,
    get_consolidation_candidates,
    archive_memory,
    log_conversation_turn,
    search_conversations,
    log_reasoning_trace,
    check_stale_memories,
    auto_archive_stale_operational,
    list_entities,
    format_entity_profile_for_prompt,
    upsert_entity,
    add_entity_fact,
    MEMORY_ISOLATED_CHANNELS,
)
from tools.tool_definitions import (
    TOOL_DEFINITIONS,
    execute_tool,
    drain_escalation_queue,
)
from session import (
    load_session_state,
    update_session_state,
    append_recent_action,
    clear_session_state,
    format_session_context,
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
