# ORCHESTRATOR_PORT_PLAN.md
# agents/orchestrator.py — Function-by-Function Port Mapping

Every function in `agents/orchestrator.py` mapped to one of four categories for the PerMyLastBot → Drift (FastAPI + WebSocket) migration.

**Categories**
1. **Portable as-is** — no Discord dependencies, copy directly
2. **Minor edits** — Discord calls replaceable with a logger call or a single WebSocket emit
3. **Major refactor** — deeply coupled to Discord, needs architectural redesign
4. **Drop** — Discord-specific, no equivalent needed in web UI

---

## Top-level imports to drop (line 19–57)

| Import | Action | Reason |
|--------|--------|--------|
| `import discord` (line 19) | **Drop** | No Discord in Drift |
| `from services import send_to_channel, send_long_message, post_status` (lines 53–57) | **Drop** | `services.py` is Discord-only; usages replaced by `logger.*` and `ws.send_json(...)` |
| `from voice_input import speak_response` (line 117) | **Drop** | TTS/voice not in initial Drift scope |

---

## Module-level string constants (lines 255–325)

| Constant | Category | Notes |
|----------|----------|-------|
| `REFLECTION_PROMPT` (255) | **1 — Portable** | Pure string template |
| `GOAL_PLANNER_SYSTEM_PROMPT` (282) | **1 — Portable** | Pure string template |
| `CREW_GOAL_PLANNER_SYSTEM_PROMPT` (300) | **1 — Portable** | Pure string template |
| `_CONSOLIDATION_PROMPT` (318) | **1 — Portable** | Pure string template |

---

## Pure / model-only functions

### `_is_confabulation_check(text)` — line 131
**Category: 1 — Portable as-is**
Pure string check against `CONFABULATION_TRIGGERS` tuple. No I/O.

---

### `strip_orphaned_tool_results(history)` — line 136
**Category: 1 — Portable as-is**
Pure list manipulation of the conversation history structure. No I/O.

---

### `_saveable_history(history)` — line 239
**Category: 1 — Portable as-is**
Filters conversation history list to only saveable entries. No I/O.

---

### `_should_consolidate(stats, channel_name)` — line 328
**Category: 1 — Portable as-is**
Pure dict/config logic comparing memory layer counts against `CONSOLIDATION_THRESHOLDS`. No I/O.

---

### `_parse_goal_trigger(user_message)` — line 348
**Category: 1 — Portable as-is**
Pure string parsing — detects `!goal` prefix. No I/O.

---

### `_format_plan(goal, steps)` — line 363
**Category: 1 — Portable as-is**
Pure string formatter — builds the numbered step display text. No I/O.

---

### `_format_execution_context(...)` — line 377
**Category: 1 — Portable as-is**
Pure string formatter — builds the execution context summary for display. No I/O.

---

### `_is_last_search_before_synthesis(steps, current_idx)` — line 412
**Category: 1 — Portable as-is**
Pure list inspection of step types. No I/O.

---

### `_is_low_quality_result(result_str)` — line 423
**Category: 1 — Portable as-is**
Pure string check for low-quality search results. No I/O.

---

### `_search_changes_direction(goal, result_str)` — line 431
**Category: 1 — Portable as-is**
Async background model call. Returns bool. No Discord calls.

---

### `_summarize_search_results(goal, result_str)` — line 450
**Category: 1 — Portable as-is**
Async background model call. Returns summary string. No Discord calls.

---

### `_save_session_state_async(...)` — line 463
**Category: 1 — Portable as-is**
Async SQLite write via `update_session_state` and `append_recent_action`. No Discord calls.

---

### `_summarize_history_tail(messages, context_hint)` — line 544
**Category: 1 — Portable as-is**
Async background model call. Compresses conversation history. No Discord calls.

---

## Minor-edit functions

### `tag_owner()` — line 250
**Category: 2 — Minor edits**

Discord dependency:
- Returns `f"<@{OWNER_ID}> "` — a Discord user mention string injected into messages posted to Discord channels.

FastAPI replacement:
- In Drift there is no channel to ping; caller is the authenticated web user. Return `""` unconditionally, or replace with the owner's display name if needed for log clarity.
- Change: `return f"<@{OWNER_ID}> " if OWNER_ID else ""` → `return ""`

---

### `run_reflection_loop(guild, experiences)` — line 595
**Category: 2 — Minor edits**

Discord dependencies:
- `send_to_channel(guild, STATUS_CHANNEL, "Running reflection loop...")` (line 602) — progress notification
- `send_to_channel(guild, STATUS_CHANNEL, "Reflection skipped...")` (line 609) — skip notification
- `send_to_channel(guild, STATUS_CHANNEL, f"...Reflection complete — {N} insights stored.")` (line 665) — completion notice (includes `tag_owner()`)
- `send_to_channel(guild, STATUS_CHANNEL, "Reflection complete — no new insights stored.")` (line 673)
- `send_to_channel(guild, LOG_CHANNEL, f"Reflection loop | Summary: ...")` (line 679) — audit log
- `send_to_channel(guild, LOG_CHANNEL, f"Reflection loop error: ...")` (line 688) — error log

FastAPI replacement:
- Drop `guild` parameter entirely.
- Replace all `send_to_channel(guild, STATUS_CHANNEL, ...)` with `logger.info(...)`.
- Replace all `send_to_channel(guild, LOG_CHANNEL, ...)` with `logger.info(...)`.
- No WebSocket emit needed — reflection runs in the background after task completion; the result is stored in memory, not delivered as a response.

---

### `extract_and_store_memories(...)` — line 695
**Category: 2 — Minor edits**

Discord dependencies:
- `send_to_channel(guild, LOG_CHANNEL, f"Memory extraction complete | ...")` (line 877) — audit log
- `send_to_channel(guild, LOG_CHANNEL, f"Memory extraction error | ...")` (line 889) — error log

FastAPI replacement:
- Drop `guild` parameter.
- Replace both `send_to_channel(...)` calls with `logger.info(...)`.
- Everything else (background model calls, rubric evaluation, save_strategic_memory, check_operational_duplicate, etc.) is already Discord-free.

---

### `_consolidate_layer(guild, layer, channel_name, trigger)` — line 899
**Category: 2 — Minor edits**

Discord dependencies:
- `send_to_channel(guild, LOG_CHANNEL, f"Memory consolidation | Cluster skipped — model error...")` (line 933)
- `send_to_channel(guild, LOG_CHANNEL, f"Memory consolidation | Cluster skipped — empty output...")` (line 942)
- `send_to_channel(guild, LOG_CHANNEL, f"Memory consolidation | Save failed | ...")` (line 987)
- `send_to_channel(guild, LOG_CHANNEL, f"Memory consolidation | Layer: {layer} | Before: ... | After: ...")` (line 1007) — summary log

FastAPI replacement:
- Drop `guild` parameter from signature.
- Replace all four `send_to_channel(guild, LOG_CHANNEL, ...)` with `logger.info(...)` / `logger.error(...)`.
- All memory operations (ChromaDB, SQLite) are Discord-free — no other changes.

---

### `consolidate_all_layers(guild, channel_name, trigger)` — line 1017
**Category: 2 — Minor edits**

Discord dependency:
- Passes `guild` through to `_consolidate_layer(guild, ...)` in a loop (line 1027).

FastAPI replacement:
- Drop `guild` parameter from signature.
- Pass without `guild` once `_consolidate_layer` is updated.
- One-line change to the `await _consolidate_layer(...)` call.

---

### `run_consolidate_command(channel, guild, channel_name)` — line 1033
**Category: 2 — Minor edits**

Discord dependencies:
- `await channel.send(f"🧠 Consolidating {layer}...")` (line 1037) — progress per layer
- `await channel.send(f"✅ Consolidation complete — ...")` (line 1042) — final summary

FastAPI replacement:
- Replace `channel` parameter with `ws: WebSocket` (the caller's active WebSocket connection).
- Replace each `channel.send(...)` with `await ws.send_json({"type": "progress", "text": ...})`.
- Drop `guild` parameter (no longer needed once `consolidate_all_layers` is updated).
- This function is the handler for the `!consolidate` command — becomes a POST `/api/consolidate` endpoint or a WS message handler.

---

### `process_tool_calls(response, guild, tool_call_count, channel_name, memory_mode)` — line 1915
**Category: 2 — Minor edits**

Discord dependencies:
- `send_to_channel(guild, LOG_CHANNEL, f"Tool called: {tool_name} | Inputs: ...")` (line 1942) — tool audit log
- `post_status(guild, "🔍 Searching the web...", memory_mode)` (line 1951) — web_search status
- `post_status(guild, f"🌐 Reading {domain}...", memory_mode)` (line 1958) — web_fetch status
- `post_status(guild, "🔎 Searching codebase...", memory_mode)` (line 1960) — search_codebase status
- `post_status(guild, f"🔧 Using tool: {tool_name}", memory_mode)` (line 1962) — default tool status
- `send_to_channel(guild, LOG_CHANNEL, f"Web fetch | URL: ... | Content: ...")` (line 1987) — web_fetch result log
- `send_to_channel(guild, LOG_CHANNEL, f"Web fetch large | ~{N} tokens ...")` (line 1995) — large fetch warning
- `send_to_channel(guild, LOG_CHANNEL, f"Codebase search | Query: ...")` (line 2003) — codebase result log

FastAPI replacement:
- Drop `guild` parameter.
- Replace all `send_to_channel(guild, LOG_CHANNEL, ...)` with `logger.info(...)`.
- Replace all `post_status(guild, ..., memory_mode)` with `await ws.send_json({"type": "status", "text": ...})` — requires adding `ws: WebSocket` parameter or passing a callback.
- The core logic (tool dispatch via `execute_tool`, tool result assembly) is Discord-free.

---

## Major-refactor functions

### `run_proactive_flag_surfacing(guild)` — line 1053
**Category: 3 — Major refactor**

Discord dependencies:
- `discord.utils.get(guild.channels, name="chief-of-staff")` (line 1068) — channel lookup by name
- `await send_long_message(cos_channel, "\n\n".join(lines))` (line 1090) — posts flag digest to that channel
- `await send_to_channel(guild, LOG_CHANNEL, f"Proactive flag surfacing | ...")` (line 1091) — audit log
- `await send_to_channel(guild, LOG_CHANNEL, f"Proactive flag surfacing error: ...")` (line 1097) — error log

Why this needs redesign:
- The function is a Discord-specific background `asyncio` loop that pushes notifications to a named channel. There is no "chief-of-staff channel" in Drift.
- The delivery mechanism (Discord channel post) needs a completely different target.

FastAPI replacement:
- Drop `guild` parameter and the `discord.utils.get(...)` lookup entirely.
- Instead of posting to a Discord channel, write each flag digest to a `notifications` table (SQLite: `notification_id, created_at, type, content, read`).
- Keep the `asyncio` loop and timing (60s startup delay, 24h repeat) in a background task registered at app startup via `asyncio.create_task(run_proactive_flag_surfacing())`.
- The frontend polls `/api/notifications` or receives a push via WebSocket broadcast to the authenticated user on next connection.
- Replace LOG_CHANNEL sends with `logger.info(...)`.

---

### `run_scheduled_consolidation(guild)` — line 1104
**Category: 3 — Major refactor**

Discord dependencies:
- `await consolidate_all_layers(guild, ...)` (line 1115) — passes Discord guild through
- `discord.utils.get(guild.channels, name="chief-of-staff")` (line 1119) — channel lookup
- `await cos_channel.send(f"🧠 Scheduled consolidation ...")` (line 1128) — posts result to channel
- `print(f"[ScheduledConsolidation] Error: {e}")` (line 1135) — already a print, not Discord

Why this needs redesign:
- Notification delivery target (named Discord channel) does not exist in Drift.

FastAPI replacement:
- Drop `guild` from signature and the `discord.utils.get(...)` call.
- After `consolidate_all_layers(channel_name=None, trigger="scheduled")` completes, if `totals["merged"] > 0`, insert a row into the `notifications` table with the consolidation summary.
- Keep the `asyncio` loop timing (90s startup delay, 72h repeat) as a background task.
- Replace `print(...)` with `logger.error(...)`.

---

### `run_goal_modification(changes, user_id, author_display_name, guild, channel, memory_mode, project_tag)` — line 1139
**Category: 3 — Major refactor**

Discord dependencies:
- `await channel.send("No pending goal to modify.")` (line 1146) — error response
- `await channel.send(f"Failed to modify the plan: {str(e)[:200]}")` (line 1168) — error response
- `await channel.send("I couldn't generate a valid revised plan. ...")` (line 1172) — validation error
- `await send_long_message(channel, _format_plan(pg["goal"], steps))` (line 1185) — delivers updated plan

Why this needs redesign:
- `channel` is a Discord channel object used as the response target. In Drift, the caller has an active WebSocket connection.

FastAPI replacement:
- Replace `channel` and `guild` parameters with `ws: WebSocket`.
- Replace each `channel.send(...)` with `await ws.send_json({"type": "error", "text": ...})`.
- Replace `send_long_message(channel, ...)` with `await ws.send_json({"type": "plan", "text": ...})`.
- The Anthropic API call and plan JSON parsing are Discord-free — no other changes.

---

### `_replan_remaining_steps(user_id, author_display_name, from_step_index, changes, channel, pg)` — line 1188
**Category: 3 — Major refactor**

Discord dependencies:
- `await channel.send("No remaining steps to adjust — goal is already complete.")` (line 1201)
- `await channel.send(f"Failed to adjust the plan: {str(e)[:200]}\n...")` (line 1233)
- `await channel.send(f"📋 Adjusted plan:\n{step_lines}\n\nContinuing...")` (line 1248)

Why this needs redesign:
- `channel` is a Discord channel object. All three sends go to the user as live feedback.
- Additionally, `asyncio.create_task(execute_goal(...))` at lines 1203 and 1249 must call an already-refactored `execute_goal`.

FastAPI replacement:
- Replace `channel` parameter with `ws: WebSocket`.
- Replace all three `channel.send(...)` with `await ws.send_json({"type": ..., "text": ...})`.
- `asyncio.create_task(execute_goal(...))` survives unchanged in form — `execute_goal` itself must be refactored first.

---

### `run_goal_planning(goal_text, user_id, author_display_name, guild, channel, memory_mode, project_tag, planner_prompt, crew_mode)` — line 1252
**Category: 3 — Major refactor**

Discord dependencies:
- `await channel.send(f"Failed to generate a plan: {str(e)[:200]}\n...")` (line 1272) — error
- `await channel.send("I couldn't generate a valid plan ...")` (line 1279) — validation error
- `await channel.send("⚠️ Plan trimmed to 8 steps ...")` (line 1287) — trim warning
- `await channel.send(f"⚠️ Plan has {N} web search steps ...")` (line 1293) — search warning
- `await send_long_message(channel, _format_plan(goal_text, steps))` (line 1313) — plan display
- `await send_to_channel(guild, LOG_CHANNEL, f"Goal plan generated | ...")` (line 1314) — audit log

Critical structural issue:
- Stores Discord objects directly in `pending_goals` state dict at lines 1298–1310:
  ```python
  pending_goals[user_id] = {
      ...
      "channel": channel,   # Discord channel object
      "guild": guild,        # Discord guild object
      ...
  }
  ```
  `execute_goal`, `resume_goal_from_gate`, `run_goal_modification`, and `_replan_remaining_steps` all read `pg["channel"]` and `pg["guild"]` from this dict. This is the root of the Discord coupling in the entire goal state machine.

FastAPI replacement:
- Replace `channel` and `guild` parameters with `ws: WebSocket` + `session_id: str`.
- Store `"session_id": session_id` in `pending_goals` instead of `"channel": channel, "guild": guild`.
- Add a `WebSocketManager` (or equivalent) that maps `session_id → WebSocket` so any function that needs to send to the user can look up the live connection.
- Replace all `channel.send(...)` / `send_long_message(channel, ...)` with `await ws.send_json(...)`.
- Replace `send_to_channel(guild, LOG_CHANNEL, ...)` with `logger.info(...)`.
- This change cascades to `execute_goal`, `resume_goal_from_gate`, `run_goal_modification`, and `_replan_remaining_steps` — they must all swap `pg["channel"]` lookups for a WS manager lookup by session_id.

---

### `execute_goal(user_id, author_display_name, skip_gate_for_step)` — line 1321
**Category: 3 — Major refactor**

Discord dependencies:
- `channel = pg["channel"]` (line 1340) — retrieves Discord channel stored by `run_goal_planning`
- `guild = pg["guild"]` (line 1341) — retrieves Discord guild stored by `run_goal_planning`
- `async with channel.typing():` (line 1360) — Discord typing indicator wrapping the entire step loop
- `await send_long_message(channel, f"📝 Ready to draft ... Reply \`!continue\` ...")` (line 1408) — draft gate message
- `await post_status(guild, f"⚙️ Step {step_num}/{total}: {step_desc}...", memory_mode)` (line 1416) — step progress status
- `channel.send(...)` — numerous gate/error messages throughout the step loop (step failure gate, research gate, etc.)
- `send_long_message(channel, ...)` — final output delivery after goal completes
- `send_to_channel(guild, LOG_CHANNEL, ...)` — logging throughout

Why this needs redesign:
- `channel.typing()` is a Discord context manager with no web equivalent. It wraps the entire execution loop.
- `pg["channel"]` retrieval couples this function to state written by `run_goal_planning`. Once `run_goal_planning` is refactored to store session_id instead, this function must look up the WebSocket via the session_id.
- Response delivery (draft gate messages, final output) all go through `channel.send` / `send_long_message`.

FastAPI replacement:
- Remove `channel = pg["channel"]` and `guild = pg["guild"]` lines; instead resolve `ws = ws_manager.get(pg["session_id"])`.
- Remove `async with channel.typing():` entirely; optionally emit a `{"type": "status", "text": "working..."}` WS event at the start of execution and each step.
- Replace all `send_long_message(channel, ...)` with `await ws.send_json({"type": "message", "text": ...})`.
- Replace all `channel.send(...)` with `await ws.send_json({"type": "gate" | "error" | "message", "text": ...})`.
- Replace all `post_status(guild, ...)` with `await ws.send_json({"type": "status", "text": ...})`.
- Replace all `send_to_channel(guild, LOG_CHANNEL, ...)` with `logger.info(...)`.
- `asyncio.create_task(execute_goal(...))` in gate paths is preserved.

---

### `resume_goal_from_gate(user_id, author_display_name, action, changes)` — line 1853
**Category: 3 — Major refactor**

Discord dependencies:
- `channel = pg["channel"]` (line 1868) — retrieves Discord channel from pending_goals
- `await channel.send(f"⏭️ Step skipped — ...")` (line 1876) — skip confirmation
- `await channel.send("🔄 Retrying step...")` (line 1886) — retry confirmation
- `await channel.send("✍️ Generating draft...")` (line 1894) — continue on draft gate
- `await channel.send("▶️ Continuing execution...")` (line 1904) — continue on research gate

FastAPI replacement:
- Remove `channel = pg["channel"]`; resolve `ws = ws_manager.get(pg["session_id"])`.
- Replace all four `channel.send(...)` with `await ws.send_json({"type": "status", "text": ...})`.
- `asyncio.create_task(execute_goal(...))` at lines 1880, 1887, 1895, 1905 is preserved.
- In Drift, this function is triggered by a WebSocket message from the frontend when the user clicks "Continue", "Retry", "Skip", or "Adjust" — not by a `!continue` Discord command.

---

### `process_user_message(...)` — line 2027
**Category: 3 — Major refactor**

This is the most Discord-coupled function in the file. It is the entry point for every user interaction.

Discord dependencies:
- `async with contextlib.AsyncExitStack() as _typing_stack:` + `await _typing_stack.enter_async_context(channel.typing())` (lines 2267–2269) — typing indicator for duration of Claude API call
- `except discord.errors.HTTPException as _e: if _e.status != 429: raise` (lines 2270–2272) — suppresses Discord rate-limit errors on the typing call
- `await channel.send("Anthropic's API is currently overloaded. ...")` (line 2426) — overload error
- `await channel.send("Rate limit hit — ...")` (line 2432) — rate limit error
- `discord.utils.get(guild.channels, name="chief-of-staff")` (line 2492) — escalation routing lookup
- `await send_to_channel(guild, cos_channel.name, f"🚨 ...")` (line 2496) — escalation post
- `await send_long_message(channel, final_response_text)` (line 2581) — primary response delivery
- `await speak_response(final_response_text, guild, channel, bot=state.bot)` (line 2583) — TTS (marked for drop)
- `await channel.send("I processed your request but had trouble ...")` (line 2585) — empty response fallback
- `await send_to_channel(guild, LOG_CHANNEL, ...)` — x7+ across the function: response summary, token/cost breakdown (lines 2662, 2692), health protocol count (lines 2600, 2604), rubric rejections (lines 2619, 2624), agent activation (line 2711)
- `await post_status(guild, ...)` — x5: memory searched (line 2116), file reading (line 2184), processing request (line 2254), agent activated (line 2261), response delivered (line 2717)

Signature: `(user_message, user_id, author_display_name, guild, channel, speak, memory_mode, project_tag, active_agent_slug, agent_trigger, context_id, channel_name)`

Why this needs redesign:
- `channel` is used as both the typing indicator context and the response delivery target.
- `guild` is used for status/log routing and escalation channel lookup.
- `discord.errors.HTTPException` has no equivalent in a WS context.
- `speak_response` uses Discord voice — dropped.
- The function is called from `bot.py`'s `on_message` handler. In Drift it becomes either a FastAPI WebSocket message handler or a REST endpoint that streams via SSE/WebSocket.

FastAPI replacement:
- New signature: `(user_message, user_id, author_display_name, ws: WebSocket, memory_mode, project_tag, active_agent_slug, agent_trigger, context_id, channel_name)`; drop `guild`, `channel`, `speak`.
- Remove `async with channel.typing()` and the `discord.errors.HTTPException` suppression block.
- Replace `send_long_message(channel, final_response_text)` with `await ws.send_json({"type": "response", "text": final_response_text})` or stream token-by-token via Anthropic streaming API.
- Replace `channel.send(...)` error messages with `await ws.send_json({"type": "error", "text": ...})`.
- Replace `discord.utils.get(guild.channels, name="chief-of-staff")` + escalation send with a `notifications` table insert.
- Replace all `send_to_channel(guild, LOG_CHANNEL, ...)` with `logger.info(...)`.
- Replace all `post_status(guild, ...)` with `await ws.send_json({"type": "status", "text": ...})`.
- Remove `speak_response(...)` call entirely.
- `context_id` remains — it becomes the WebSocket session or thread ID, already a plain int.
- Everything inside the reasoning loop (Claude API call, tool routing, history management, session state, memory extraction) is Discord-free and survives unchanged.

---

## Summary table

| Function | Line | Category | Discord calls to replace |
|----------|------|----------|--------------------------|
| `_is_confabulation_check` | 131 | 1 — Portable | — |
| `strip_orphaned_tool_results` | 136 | 1 — Portable | — |
| `_saveable_history` | 239 | 1 — Portable | — |
| `tag_owner` | 250 | 2 — Minor | Return `""` instead of `<@OWNER_ID>` |
| `_should_consolidate` | 328 | 1 — Portable | — |
| `_parse_goal_trigger` | 348 | 1 — Portable | — |
| `_format_plan` | 363 | 1 — Portable | — |
| `_format_execution_context` | 377 | 1 — Portable | — |
| `_is_last_search_before_synthesis` | 412 | 1 — Portable | — |
| `_is_low_quality_result` | 423 | 1 — Portable | — |
| `_search_changes_direction` | 431 | 1 — Portable | — |
| `_summarize_search_results` | 450 | 1 — Portable | — |
| `_save_session_state_async` | 463 | 1 — Portable | — |
| `_summarize_history_tail` | 544 | 1 — Portable | — |
| `run_reflection_loop` | 595 | 2 — Minor | 5× `send_to_channel` → `logger.info` |
| `extract_and_store_memories` | 695 | 2 — Minor | 2× `send_to_channel` → `logger.info` |
| `_consolidate_layer` | 899 | 2 — Minor | 4× `send_to_channel` → `logger.info`/`error` |
| `consolidate_all_layers` | 1017 | 2 — Minor | Remove `guild` pass-through |
| `run_consolidate_command` | 1033 | 2 — Minor | 2× `channel.send` → `ws.send_json` |
| `run_proactive_flag_surfacing` | 1053 | 3 — Major | `discord.utils.get` + `send_long_message` → `notifications` table insert |
| `run_scheduled_consolidation` | 1104 | 3 — Major | `discord.utils.get` + `cos_channel.send` → `notifications` table insert |
| `run_goal_modification` | 1139 | 3 — Major | 4× `channel.send`/`send_long_message` → `ws.send_json` |
| `_replan_remaining_steps` | 1188 | 3 — Major | 3× `channel.send` → `ws.send_json` |
| `run_goal_planning` | 1252 | 3 — Major | Stores Discord objects in state → store `session_id`; 6× sends → `ws.send_json` / `logger.info` |
| `execute_goal` | 1321 | 3 — Major | `pg["channel"]`/`pg["guild"]` lookup + `channel.typing()` + 10+ sends → WS manager lookup + `ws.send_json` |
| `resume_goal_from_gate` | 1853 | 3 — Major | `pg["channel"]` lookup + 4× `channel.send` → WS manager lookup + `ws.send_json` |
| `process_tool_calls` | 1915 | 2 — Minor | 4× `send_to_channel` → `logger.info`; 4× `post_status` → `ws.send_json` |
| `process_user_message` | 2027 | 3 — Major | `channel.typing()` + `discord.errors.HTTPException` + 15+ sends/statuses → WS; `speak_response` → drop |

---

## Key architectural decision unlocked by this port

`run_goal_planning` storing `"channel": channel` and `"guild": guild` in `pending_goals` is the single change that cascades to `execute_goal`, `resume_goal_from_gate`, `run_goal_modification`, and `_replan_remaining_steps`. Fixing this one storage choice — replacing with `"session_id": session_id` and adding a `WebSocketManager` that maps session_id → WebSocket — unblocks all four downstream functions simultaneously. Do this first.
