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
    OWNER_ID,
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


def tag_owner() -> str:
    """Returns a Discord mention for the owner, or empty string."""
    return f"<@{OWNER_ID}> " if OWNER_ID else ""


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
    project_tag=None, channel_name="unknown", memory_mode="global",
    background_model_fn=None
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
            await send_to_channel(
                guild, LOG_CHANNEL,
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


async def run_proactive_flag_surfacing(guild):
    """
    Scheduled background task. Fires once on startup after a 60-second
    delay, then repeats every 24 hours. Pulls active HIGH priority review
    flags from operational_memory and posts a digest to #chief-of-staff.
    Skips silently if no flags exist or channel is unavailable.
    """
    await asyncio.sleep(60)  # allow bot to fully connect before first run
    while True:
        try:
            loop = asyncio.get_running_loop()
            flags = await loop.run_in_executor(
                None, get_unresolved_high_priority_flags
            )
            if flags:
                cos_channel = discord.utils.get(
                    guild.channels, name="chief-of-staff"
                )
                if cos_channel:
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
                    await send_long_message(cos_channel, "\n\n".join(lines))
                    await send_to_channel(
                        guild, LOG_CHANNEL,
                        f"Proactive flag surfacing | "
                        f"{len(flags)} HIGH flag(s) posted to #chief-of-staff"
                    )
        except Exception as e:
            await send_to_channel(
                guild, LOG_CHANNEL,
                f"Proactive flag surfacing error: {str(e)}"
            )
        await asyncio.sleep(86400)  # 24 hours


async def run_scheduled_consolidation(guild):
    """
    Scheduled background task. Fires once on startup after a 90-second
    delay, then repeats every 72 hours. Calls consolidate_all_layers()
    with trigger="scheduled". Posts a one-line summary to #chief-of-staff
    if any merges occurred. Skips silently if consolidation returns zeros
    or channel is unavailable.
    """
    await asyncio.sleep(90)  # stagger startup relative to flag surfacing (60s)
    while True:
        try:
            totals = await consolidate_all_layers(
                guild, channel_name=None, trigger="scheduled"
            )
            if totals and totals.get("merged", 0) > 0:
                cos_channel = discord.utils.get(
                    guild.channels, name="chief-of-staff"
                )
                if cos_channel:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    skipped_str = (
                        f", {totals['skipped']} cluster(s) skipped"
                        if totals.get("skipped") else ""
                    )
                    await cos_channel.send(
                        f"🧠 Scheduled consolidation [{timestamp}] — "
                        f"{totals['merged']} memories merged, "
                        f"{totals['archived']} archived"
                        + skipped_str
                    )
        except Exception as e:
            print(f"[ScheduledConsolidation] Error: {e}")
        await asyncio.sleep(72 * 3600)  # 72 hours


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
