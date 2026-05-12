# Drift Port Specification
## PerMyLastBot → Drift Web UI

Generated from codebase on 2026-05-11

---

## Section 1 — Current Codebase Inventory

### 1.1 File Structure

| File | Description |
|------|-------------|
| `agents/bot.py` | Main Discord bot entry point: handles `on_message`, all `!` commands, voice/file attachment processing, agent selection, and startup lifecycle. |
| `agents/config.py` | Shared constants: model names (`claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, `qwen3:8b`), channel configurations, memory modes, tool modes, agent hints, file limits. |
| `agents/model.py` | Anthropic client singleton and background model functions (`call_background_model`, `call_background_model_json`); tries Ollama first, falls back to Haiku. |
| `agents/orchestrator.py` | Core pipeline: `process_user_message`, `execute_goal`, `run_goal_planning`, memory consolidation (`consolidate_all_layers`), reflection loop, and the two scheduled background tasks. |
| `agents/services.py` | Discord messaging utilities: `send_to_channel`, `send_long_message`, `post_status`. |
| `agents/session.py` | Per-`(user_id, context_id)` session state manager stored in `session_state` SQLite table; injected into system prompt for working context continuity. |
| `agents/state.py` | Shared mutable runtime state dicts (`conversation_history`, `pending_goals`, `execution_context`, `gate_pending`, `AGENT_DEFINITIONS`); loads `SYSTEM_PROMPT` from `SOUL.md` at import. |
| `agents/voice_input.py` | Voice transcription via faster-whisper (`small` model, CPU) and TTS playback via ElevenLabs + FFmpeg into Discord voice channel. |
| `memory/memory_manager.py` | Three-layer memory system (SQLite + ChromaDB): save/retrieve/consolidate strategic, operational, and analytical memories; health panel/protocol tables; entity profiles; FTS5 conversation log; rubric-gated extraction. |
| `tools/tool_definitions.py` | Claude tool definitions (JSON schemas) and handlers: `query_memory`, `save_skill`, `update_user_model`, `flag_for_review`, `web_search`, `web_fetch`, `search_codebase`, `calculate_confidence`, `save_person_fact`. Also contains the tool router `execute_tool`. |

---

### 1.2 Bot Commands

| Command | What It Does | Channel Restriction | Approx. Line |
|---------|-------------|---------------------|--------------|
| `!help` | Displays `HELP_TEXT` listing all commands. | Any channel | ~1798 |
| `!memory` | Shows memory snapshot (strategic/operational/analytical) for current channel context, respecting isolation. | Any channel | ~1803 |
| `!clear` | Wipes in-memory conversation history for the current `(uid, context_id)` pair; clears attached files and agent pin. | Any channel | ~1810 |
| `!status` | Posts system health report: Ollama status/model, FFmpeg path, memory counts per layer and per project_tag, active conversation contexts, uptime, last token usage. | Any channel | ~1834 |
| `!retry` | Re-sends last user message through the full pipeline; if in a `step_failure` gate, retries the failed step instead. | Any channel | ~1839 |
| `!remember <text>` | Saves `text` directly to strategic memory (category: `manual`, source: `!remember`). | `bot-commands` only | ~1375 |
| `!handoff` | Generates a dense multi-section memory snapshot document (WHO I AM / WHAT IS ACTIVE / etc.) via `MAIN_MODEL` for pasting into a new AI session. | Any channel | ~1395 |
| `!consolidate` | Manually triggers `run_consolidate_command` — consolidates all three memory layers for the current channel scope. | Any channel | ~1791 |
| `!goal <text>` / `!plan <text>` / `!research <text>` | Decomposes goal into 3–8 steps via `GOAL_PLANNER_SYSTEM_PROMPT`, stores in `pending_goals`, posts plan for approval. | Any channel | ~1083 |
| `!crew <text>` | Like `!goal` but uses `CREW_GOAL_PLANNER_SYSTEM_PROMPT` — every step is assigned a specialist agent slug by the planner. | Any channel | ~1096 |
| `!approve` | Approves a pending goal plan (`status: awaiting_approval → executing`) and kicks off `execute_goal` as an asyncio task. | Any channel (while goal pending) | ~1199 |
| `!cancel` | Cancels a pending goal or active execution gate; clears `pending_goals`, `gate_pending`, `execution_context`. | Any channel (while goal pending or gated) | ~1221 |
| `!modify <changes>` | Replans a pending goal by calling `run_goal_modification` with the modification text; replaces steps in `pending_goals`. | Any channel (while awaiting_approval) | ~1239 |
| `!continue` | Resumes paused goal execution from a mid-execution gate by calling `resume_goal_from_gate` with action `"continue"`. | Any channel (while gated) | ~1139 |
| `!adjust <changes>` | Replans remaining steps at a gate by calling `resume_goal_from_gate` with action `"adjust"`; calls `_replan_remaining_steps`. | Any channel (while gated) | ~1148 |
| `!skip` | Skips a failed step at a `step_failure` gate. | Any channel (while step_failure gate) | ~1157 |
| `!agent <slug> <message>` | Activates a specific specialist agent by slug for one response; if in a thread, pins the agent for the thread. | Any channel | ~1315 |
| `!agents` | Lists all loaded specialist agents with slugs, names, and descriptions; shows current thread pin if any. | Any channel | ~1264 |
| `!use <slug>` / `!use default` | Pins a specialist agent for the current thread/context (`thread_agent_pins[context_id] = slug`); `default` clears the pin. | Any channel | ~1286 |
| `!search <query>` | Full-text search of `conversation_log` (FTS5); summarises matching exchanges via background model; respects health-tracking isolation. | Any channel | ~1402 |
| `!trace [N]` | Shows last N (default 10, max 25) reasoning trace entries from `reasoning_trace` table for the current user/channel. | Any channel | ~1436 |
| `!pin <id>` | Sets `pinned=1` on an `operational_memory` row by ID — exempts it from auto-archiving and consolidation. | Any channel | ~1719 |
| `!unpin <id>` | Sets `pinned=0` on an `operational_memory` row by ID. | Any channel | ~1734 |
| `!save-verbatim [layer] <content>` | Writes content directly to `strategic`, `operational`, or `analytical` memory layer, bypassing AI extraction; returns the assigned memory ID. | Any channel | ~1749 |
| `!roster` | Lists all `entities` of `entity_type='person'` with fact counts and last-updated dates. | Any channel | ~1483 |
| `!profile <name>` | Shows full entity profile from `entities` + `entity_facts` tables, grouped by category with fact IDs and dates. | Any channel | ~1505 |
| `!profile-delete <id>` | Deletes a specific `entity_facts` row by ID (fact ID shown in `!profile` output). | Any channel | ~1542 |
| `!save-thread` | Fetches up to 200 messages from the current Discord thread, summarises via background model, saves to `strategic_memory` as `thread_summary`, optionally logs to `conversation_log`. | Must be inside a Discord thread | ~1591 |

---

### 1.3 Background Processes

| Name | Trigger | What It Does | Location |
|------|---------|-------------|----------|
| `run_proactive_flag_surfacing` | 60s after startup, then every 24 hours (`asyncio.sleep(86400)`) | Pulls all active HIGH priority `review_flags` from `operational_memory`, posts a digest to `#chief-of-staff`. Skips silently if no flags or channel unavailable. | `orchestrator.py` ~line 1053 |
| `run_scheduled_consolidation` | 90s after startup, then every 72 hours (`asyncio.sleep(72 * 3600)`) | Calls `consolidate_all_layers()` with `trigger="scheduled"` across all three memory layers; posts summary to `#chief-of-staff` if merges occurred. | `orchestrator.py` ~line 1104 |
| `_save_session_state_async` | Fire-and-forget (`asyncio.create_task`) after every `process_user_message` call | Appends action summary to `recent_actions`; asks background model to extract `active_task`, `build_list_updates`, and `new_decisions`; persists to `session_state` table. Never blocks the response. | `orchestrator.py` ~line 463 |
| `run_reflection_loop` | Triggered when `is_task_completion()` returns True (based on `COMPLETION_SIGNALS`) and `pending_reflection` meta flag is set | Calls background model with `REFLECTION_PROMPT` against recent completed experiences; saves analytical insights to `analytical_memory` and strategic insights to `strategic_memory`. | `orchestrator.py` ~line 595 |
| `execute_goal` | `asyncio.create_task` spawned when user sends `!approve` | Executes approved goal plan step-by-step; pauses at DRAFT GATE, RESEARCH GATE, and STEP FAILURE GATE; stores state in `gate_pending` so user can `!continue` / `!adjust` / `!retry` / `!skip`. | `orchestrator.py` ~line 1321 |
| `_load_agent_definitions` | Once at startup in `on_ready()` | Reads all `.md` files from `C:\Users\Jerm\.claude\agents`, parses YAML frontmatter for name/description, extracts keywords via background model, caches to `memory/agent_keywords_cache.json`. | `bot.py` ~line 624 |
| `auto_archive_stale_operational` | Once at module import of `memory_manager.py` | Archives active operational memories containing clarification language (`clarify`, `determine`, `confirm`, `?`) that have not been updated in 30+ days. Never touches health-tracking memories. | `memory_manager.py` ~line 2202 |
| `cleanup_old_conversation_log` | Once at startup in `on_ready()` | Deletes `conversation_log` entries older than 90 days. Returns count deleted. | `bot.py` ~line 847 |
| `backfill_conversation_log` | Once at startup in `on_ready()`, guarded by `meta.conversation_log_backfilled` | One-time migration: copies existing `conversation_history` rows into `conversation_log` for `!search` and confabulation checks. | `bot.py` ~line 851 |

---

### 1.4 MCP Tools

| Tool Name | What It Does | Input Parameters |
|-----------|-------------|-----------------|
| `query_memory` | Semantic search of long-term memory across one or all layers. | `query` (string, required), `layer` (enum: all/strategic/operational/analytical, optional) |
| `save_skill` | Crystallises a repeated pattern into a named reusable skill stored in `analytical_memory` with `pattern_type: crystallised_skill`. | `skill_name`, `description`, `trigger_conditions`, `confidence` (all required); `overwrite` (bool, optional) |
| `update_user_model` | Saves a fact about the user to `strategic_memory` with category prefixed `user_model_`. | `category` (enum: communication_style/technical_preferences/goals/working_style/values/background/constraints/general), `content`, `confidence` (all required) |
| `flag_for_review` | Saves a review flag to `operational_memory` with `project_name: review_flags`. HIGH priority flags outside `chief-of-staff` are added to `_escalation_queue`. | `topic`, `reason`, `priority` (enum: high/medium/low, all required) |
| `web_search` | Searches via DuckDuckGo; falls back to Serper (Google) if DDG fails or returns nothing. Cap: 5 results. | `query` (required), `max_results` (optional, default 3, max 5) |
| `web_fetch` | Fetches a URL, strips HTML via BeautifulSoup, returns plain text with keyword-priority relevance filtering. Blocks local network addresses. | `url` (required), `max_chars` (optional, default 5000, max 10000) |
| `search_codebase` | Semantic search of the discord-agent codebase via CocoIndex-Code CLI (`ccc.exe`); returns code sections with file paths and line numbers. | `query` (required), `limit` (optional, default 5, max 10) |
| `calculate_confidence` | Updates the confidence score of an existing memory ±0.1 based on new evidence. | `memory_id` (int), `layer` (enum: strategic/operational/analytical), `direction` (enum: increase/decrease), `reason` (all required) |
| `save_person_fact` | Creates/updates an entity in `entities` table and adds a fact to `entity_facts`. Optional supersede removes outdated category facts. | `person_name`, `category`, `fact` (required); `role`, `supersede_category`, `confidence` (optional) |

---

### 1.5 Database Tables

All tables live in `memory/database.db` (SQLite).

| Table | Purpose | Key Columns |
|-------|---------|------------|
| `strategic_memory` | Long-term user knowledge, decisions, preferences, reflections | `id`, `content`, `category`, `confidence`, `created`, `last_confirmed`, `times_referenced`, `flag_after_days`, `status` (`active`/`archived`), `source`, `channel_name`, `project_tag` |
| `operational_memory` | Active tasks, projects, review flags | `id`, `project_name`, `content`, `status`, `priority`, `created`, `last_updated`, `flag_after_days`, `blockers`, `dependencies`, `channel_name`, `confidence`, `pinned`, `project_tag` |
| `analytical_memory` | Learned patterns, crystallised skills | `id`, `pattern_type`, `observation`, `reasoning`, `outcome`, `pattern`, `confidence`, `trigger_conditions`, `times_observed`, `created`, `last_observed`, `flag_after_days`, `status`, `channel_name`, `project_tag` |
| `experiences` | Completed task episodes for reflection loop | `id`, `request_summary`, `approach_used`, `outcome`, `lesson`, `layers_used` (JSON), `timestamp`, `quality_score`, `task_completed`, `project_tag` |
| `memory_archive` | Consolidated/superseded memories — never deleted, only archived | `id`, `original_layer`, `original_id`, `content`, `reason_archived`, `superseded_by`, `archived_date`, `original_created` |
| `meta` | Key-value system state store | `key` (PK), `value`; known keys: `interaction_count`, `pending_reflection`, `conversation_log_backfilled` |
| `conversation_history` | Per-`(uid:context_id)` conversation JSON for session restore on restart | `user_id` (PK, format `uid:context_id`), `history` (JSON), `updated` |
| `health_panels` | Lab biomarker panel results — fully isolated to `health-tracking` | `id`, `test_date`, `marker`, `value`, `unit`, `reference_range`, `personal_baseline`, `notes`, `created_at` |
| `health_protocols` | Active supplement/peptide/medication protocols | `id`, `protocol_name`, `dose`, `frequency`, `start_date`, `end_date`, `notes`, `created_at` |
| `conversation_log` | FTS5 virtual table for `!search` and confabulation checks | `user_id`, `context_id`, `channel_name`, `role`, `content`, `project_tag`, `timestamp` (all UNINDEXED except `content`) |
| `session_state` | Per-`(uid:context_id)` working context injected into system prompt | `session_key` (PK, format `uid:context_id`), `active_task`, `build_list` (JSON), `decisions` (JSON), `recent_actions` (JSON), `updated` |
| `entities` | People tracked in director-workspace via entity memory | `id`, `name` (UNIQUE), `entity_type`, `role`, `context`, `created_at`, `updated_at` |
| `entity_facts` | Longitudinal facts per entity with supersede support | `id`, `entity_id` (FK), `category`, `fact`, `status` (`active`/superseded), `superseded_by` (FK), `recorded_at`, `updated_at`, `source_channel`, `confidence` |
| `reasoning_trace` | Per-tool-call trace log for `!trace` command | `id`, `timestamp`, `user_id`, `channel_name`, `tool_name`, `tool_inputs` (JSON, truncated to 500 chars), `result_summary` (truncated to 1000 chars), `iteration` |

ChromaDB collections (in `memory/chroma_db/`):
- `strategic` — vector embeddings for `strategic_memory`
- `operational` — vector embeddings for `operational_memory`
- `analytical` — vector embeddings for `analytical_memory`

Embedding model: `all-MiniLM-L6-v2` via `sentence-transformers`.

---

### 1.6 Specialist Agents

Loaded at startup from `.md` files in `C:\Users\Jerm\.claude\agents`. Each file has YAML frontmatter with `name` and `description`.

| Slug | Name (from frontmatter) | Channel Hint |
|------|------------------------|-------------|
| `agents-orchestrator` | (Agents Orchestrator) | No channel hint — available globally |
| `director-advisor` | Director Advisor | `director-workspace`, `chief-of-staff` |
| `engineering-ai-engineer` | AI Engineer | `gamification-dashboard` |
| `engineering-data-engineer` | Data Engineer | `gamification-dashboard` |
| `engineering-database-optimizer` | Database Optimizer | No channel hint |
| `health-researcher` | Health Researcher | `health-tracking` (hard-coded, never overridden) |
| `personal-productivity` | Personal Productivity | `chief-of-staff` |
| `support-analytics-reporter` | Analytics Reporter | `slack-intelligence`, `contact-center` |

Agent selection priority: (1) thread pin → (2) health-tracking hard rule → (3) sandbox exclusion → (4) explicit name/slug mention in message → (5) channel hints resolved by keyword score → (6) global keyword score ≥ 3.

---

### 1.7 Workspace / Channel Structure

| Channel | Memory Mode | Tool Mode | Threaded | Special Behavior |
|---------|-------------|-----------|----------|-----------------|
| `bot-commands` | ephemeral | search_only | No | `!remember` works here only; no long-term memory saved |
| `sandbox` | ephemeral | none | No | No tools, no agents activated; testing only |
| `chief-of-staff` | global | full | Yes | Proactive flag digest posted here daily; scheduled consolidation summary posted here; agent hints: `personal-productivity`, `director-advisor` |
| `director-workspace` | global | full | Yes | Entity memory for people tracking; `save_person_fact` tool active; agent: `director-advisor` |
| `planning` | global | full | Yes | Long-form strategic sessions |
| `contact-center` | project (`contact-center`) | full | Yes | Active project; agent: `support-analytics-reporter` |
| `gamification-dashboard` | project (`gamification-dashboard`) | full | Yes | Active build; agents: `engineering-ai-engineer`, `engineering-data-engineer` |
| `slack-intelligence` | project (`slack-intelligence`) | full | No | Future project; agent: `support-analytics-reporter` |
| `health-tracking` | project (`health-tracking`) | full | Yes | Fully isolated memory (MEMORY_ISOLATED_CHANNELS); always uses `health-researcher`; `health_panels` + `health_protocols` tables; `search_codebase` excluded |
| `bot-logs` | — | — | — | IGNORED — internal log destination |
| `bot-status` | — | — | — | IGNORED — internal status destination |
| `rules-and-info` | — | — | — | IGNORED |
| `research-reports` | — | — | — | IGNORED — output channel |
| `general-output` | — | — | — | IGNORED — output channel |

---

## Section 2 — Port Decision Map

| Command | What It Does | Port Decision | Notes |
|---------|-------------|---------------|-------|
| `!help` | Display command list | Dropped | Web UI is self-documenting; replace with a persistent help sidebar or tooltip system |
| `!memory` | Show memory snapshot for current context | UI Button | "View Memories" button in workspace sidebar |
| `!clear` | Wipe conversation history for current context | UI Button | Thread-level "Clear History" action |
| `!status` | System health report | API Endpoint | `GET /api/v1/status` — admin panel widget |
| `!retry` | Regenerate last response | UI Button | Regenerate button on last assistant message |
| `!remember <text>` | Save text directly to strategic memory | UI Button | "Remember This" action on any message bubble, or a manual save form |
| `!handoff` | Generate dense memory export document | UI Button | "Export Handoff" button — generates and displays/downloads document |
| `!consolidate` | Run memory consolidation manually | UI Button | "Consolidate Memory" action in memory admin section |
| `!goal` / `!plan` / `!research` | Submit goal for step-plan decomposition | Redesigned | Dedicated Goal Mode panel: input triggers planning, plan displays inline with approve/cancel/modify controls |
| `!crew` | Goal mode with per-step agent assignment | Redesigned | Toggle in Goal Mode panel: "Crew Mode" switch that enables per-step agent labels |
| `!approve` | Approve goal plan | UI Button | "Approve & Execute" button in Goal Mode plan view |
| `!cancel` | Cancel pending goal or gate | UI Button | "Cancel" button in Goal Mode panel or execution gate overlay |
| `!modify <changes>` | Revise goal plan before execution | Redesigned | Inline editable plan with free-text "Revision Notes" field before re-submitting to planner |
| `!continue` | Resume execution at gate | UI Button | "Continue" button in mid-execution gate overlay |
| `!adjust <changes>` | Replan remaining steps at gate | Redesigned | "Adjust Remaining Steps" text input + "Replan" button in gate overlay |
| `!skip` | Skip failed step at gate | UI Button | "Skip This Step" button in step-failure gate overlay |
| `!agent <slug> <message>` | Use a specific agent for one response | Redesigned | Agent selector dropdown next to message input; selection pins to thread |
| `!use <slug>` / `!use default` | Pin agent for thread | Redesigned | Agent selector dropdown maintains pin state per thread |
| `!agents` | List all available agents | UI Button | "Agents" panel in sidebar showing slug, name, description |
| `!search <query>` | Full-text conversation search | API Endpoint | Search bar in sidebar — `GET /api/v1/search?q=...` |
| `!trace [N]` | Show reasoning trace | UI Button | "Reasoning Trace" expandable panel per message or debug sidebar |
| `!pin <id>` | Pin a memory by ID | UI Button | Pin icon on memory card in memory browser |
| `!unpin <id>` | Unpin a memory by ID | UI Button | Unpin icon on memory card |
| `!save-verbatim [layer] <content>` | Write directly to memory layer | API Endpoint | `POST /api/v1/memory/save` with layer and content fields |
| `!roster` | List people in entity memory | UI Button | "People" tab in director-workspace workspace sidebar |
| `!profile <name>` | View entity profile | UI Button | Entity profile page/panel showing categorised facts and history |
| `!profile-delete <id>` | Delete a fact by ID | UI Button | Delete (×) button on individual fact row in entity profile view |
| `!save-thread` | Summarise thread to strategic memory | Automatic | Automatic on thread archive/close — no user action needed in web context |
| `!handoff` | Generate handoff document | UI Button | "Export Handoff" button |
| `!status` | System health report | API Endpoint | `GET /api/v1/status` — surfaces in admin panel |

---

## Section 3 — New Web-Native Behavior

**1. Login screen as authentication front door (JWT-based single user auth)**
Single-user JWT auth. Login page is the first route. All API endpoints require `Authorization: Bearer <token>`. Token stored in `localStorage` or `httpOnly` cookie.
Architectural awareness: auth middleware must wrap the entire FastAPI app including WebSocket upgrades. The `OWNER_ID` env var concept maps to a single hashed password stored in env. No user table needed initially.

**2. Manual thread title creation by user (with rename-anytime capability)**
User types a thread title before or after the first message. Rename via double-click on thread name in sidebar. Title stored in a `threads` table (new — does not exist in current SQLite schema).
Architectural awareness: `threads` table must be created as part of the port schema. The `generate_thread_name()` function in `bot.py` (which auto-generates titles via the background model) becomes an opt-in "Suggest Title" action, not automatic.

**3. Workspace navigation replacing Discord channels**
Discord channel names (`chief-of-staff`, `health-tracking`, etc.) become named workspace slugs in the sidebar. `CHANNEL_MEMORY_MODE`, `CHANNEL_PROJECT_TAG`, `CHANNEL_TOOL_MODE`, `CHANNEL_PURPOSE`, and `CHANNEL_AGENT_HINTS` from `config.py` remain the source of truth — they just drive sidebar routing instead of Discord channel matching.
Architectural awareness: workspace config currently lives in `config.py` as Python dicts. These need to be either retained as-is (imported by FastAPI) or migrated to a config file/env for runtime editability.

**4. Thread persistence with sidebar list**
All threads persisted in new `threads` SQLite table. Sidebar lists threads per workspace sorted by last activity. `conversation_history` keys (`uid:context_id`) map naturally — `context_id` becomes the internal thread ID.
Architectural awareness: the `conversation_history` table already keyed by `uid:context_id` supports this. The new `threads` table adds title, workspace slug, created_at, last_message_at.

**5. File upload without Discord size limits**
Multipart `POST /api/v1/files/upload`. The `_process_attachment()` function in `bot.py` is fully reusable — it only takes `filename` (str) and `file_bytes` (bytes). No Discord dependency.
Architectural awareness: The file processing pipeline (`_process_attachment`, vision fallback via `pdf2image`, Poppler path) is portable but the `POPPLER_PATH` constant is Windows-specific and will need an env var for the VPS.

**6. Streaming responses via WebSocket**
The Anthropic API streaming response replaces Discord's `channel.typing()` + `send()` pattern. FastAPI WebSocket endpoint streams tokens as they arrive.
Architectural awareness: `process_user_message` in `orchestrator.py` currently calls `send_long_message()` after the full response is assembled. This function must be refactored to accept a streaming callback or be replaced by a generator that yields to the WebSocket. This is the highest-impact change in the entire port.

**7. Mobile responsive layout**
React app with Tailwind CSS or similar. Sidebar collapses to a hamburger menu on small screens. Chat thread fills the viewport. No architectural backend dependency — purely frontend.
Architectural awareness: None on the backend. Ensure WebSocket reconnection logic handles mobile network switching.

**8. Formatted document export — PDF/DOCX (post-port, but note hook needed)**
`!handoff` generates a text document via the Anthropic API today. The web version needs a "render to PDF/DOCX" step at the end of the handoff pipeline.
Architectural awareness: The handoff generation function (`run_handoff_command` in `bot.py`) is a good extraction candidate. Add an optional `format` parameter (`text` | `pdf` | `docx`) to `POST /api/v1/handoff`. Wire the format rendering as a post-generation step — the text content generation is separable from the output format. Install `weasyprint` or `python-docx` on the VPS at port time so the hook is ready.

---

## Section 4 — Open Decisions

**Decision:** How voice input/output works in web context
**Context:** Currently uses Discord voice attachments (transcribed via faster-whisper) and plays TTS audio in Discord voice channels via ElevenLabs + FFmpeg. Neither mechanism is available in a browser context.
**Options:**
1. Browser-native `MediaRecorder` API → send audio blob to `POST /api/v1/voice/transcribe` → process with existing faster-whisper pipeline; play ElevenLabs audio back via HTML `<audio>` element.
2. Browser `SpeechRecognition` API for transcription (no server round-trip) + Web Audio API or ElevenLabs streaming for TTS playback.
3. Drop voice I/O for the initial port — text-only UI — and add voice as a post-port feature.
**Recommendation:** Option 3 for the port, Option 1 for post-port. The faster-whisper pipeline is reusable server-side. Flag `speak_response()` in `voice_input.py` for replacement with an HTTP streaming audio response.

---

**Decision:** How the reflection loop triggers without Discord task completion signals
**Context:** `run_reflection_loop` currently fires when `is_task_completion()` detects a word from `COMPLETION_SIGNALS` (e.g., "done", "perfect", "sorted") in the user's message. This is Discord message text parsing.
**Options:**
1. Retain the same completion signal detection in the web UI — the `is_task_completion()` function is text-only and fully portable.
2. Add an explicit "Mark Complete" button per message or conversation that triggers reflection.
3. Run reflection on a schedule (e.g., after every 10 interactions or nightly).
**Recommendation:** Option 1 is the cheapest and works immediately. Option 2 adds UX clarity — implement both.

---

**Decision:** How goal mode approval gates work in the UI
**Context:** Current flow is: user sends `!goal` → bot posts plan → user sends `!approve` / `!cancel` / `!modify`. The gate states (`pending_goals`, `gate_pending`) are held in memory in `state.py`. Mid-execution, further gates pause and wait for `!continue`, `!adjust`, `!retry`, or `!skip` messages.
**Options:**
1. Inline approval UI in the chat thread: plan displays as a card with Approve / Cancel / Modify buttons. Gates show an overlay with Continue / Adjust / Skip / Retry.
2. Dedicated Goal Mode side panel separate from chat that shows plan state and controls.
3. Keep a text-command model in the web UI — user types commands in a special input mode during goal execution.
**Recommendation:** Option 1. The plan card + gate overlay pattern maps directly to the existing state machine. `pending_goals` and `gate_pending` in `state.py` become server-side session state keyed by user+thread ID. The WebSocket broadcasts gate events to the UI.

---

**Decision:** How health workspace isolation is enforced in the web UI
**Context:** Currently enforced by `MEMORY_ISOLATED_CHANNELS = {"health-tracking"}` checks scattered across `memory_manager.py`, `orchestrator.py`, and `bot.py`. Any request from `health-tracking` uses isolated memory; any request from other channels excludes health memories.
**Options:**
1. Pass `workspace_slug` through the entire API request chain and preserve all existing isolation checks in `memory_manager.py` unchanged — the isolation logic is workspace-name-driven, not Discord-specific.
2. Add a database-level row-level security policy.
3. Create a separate FastAPI router for health workspace that uses a separate memory service instance.
**Recommendation:** Option 1. The existing isolation code in `memory_manager.py` already works on `channel_name` strings. Pass `workspace_slug` as `channel_name` throughout. Zero rewrite needed.

---

**Decision:** What the embedding model upgrade target is
**Context:** Currently using `all-MiniLM-L6-v2` (384 dimensions, ~23M params). ChromaDB will be rebuilt at cutover regardless, so a model upgrade costs nothing extra in migration effort.
**Options:**
1. `all-MiniLM-L6-v2` — current, fast, small, 384d.
2. `bge-m3` — multi-lingual, 1024d, state-of-the-art retrieval, ~570M params.
3. `text-embedding-3-small` via OpenAI API — no local inference needed, 1536d, pay-per-use.
4. `nomic-embed-text` via Ollama — runs locally, 768d, strong performance.
**Recommendation:** TBD — needs discussion. `nomic-embed-text` via Ollama is a strong candidate: runs locally on the same VPS as the existing Ollama service, no API cost, meaningful quality improvement over MiniLM.

---

**Decision:** How session state persists across browser sessions
**Context:** `session_state` table currently keyed by `uid:context_id` where `uid` is a Discord user ID and `context_id` is a Discord channel/thread ID. In the web UI, there is no Discord user ID.
**Options:**
1. Generate a stable `user_id` at first login (UUID stored in the JWT payload) — reuse as the key. `context_id` becomes the thread/conversation ID (UUID or integer PK from the new `threads` table).
2. Use the JWT `sub` claim as `user_id` and thread DB PK as `context_id` — same structure as today.
3. Session state stored in Redis for fast reads instead of SQLite.
**Recommendation:** Option 2. Minimal change — the `session_state` table schema is unchanged; only the ID format changes from Discord snowflake to internal UUID/int.

---

**Decision:** How push notifications work without Discord
**Context:** The bot posts status/alert messages to `#bot-status` and `#chief-of-staff` Discord channels. Proactive flag surfacing and scheduled consolidation results currently go to those Discord channels.
**Options:**
1. Browser push notifications via Web Push API — requires service worker and user permission.
2. In-app notification bell — alerts stored in DB, displayed in UI on next load.
3. Email notifications via SMTP for high-priority flags.
4. All notifications surface as in-app — `#chief-of-staff` becomes a "Notifications" view in the UI.
**Recommendation:** Option 2 + 4 for the port. An in-app notifications table is sufficient. Browser push (Option 1) is a post-port enhancement. Option 3 requires an email service — defer.

---

## Section 5 — Target Architecture

### 5.1 Backend Structure

```
project/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app factory, lifespan events
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── router.py          # Include all endpoint routers
│   │   │       └── endpoints/
│   │   │           ├── auth.py        # POST /auth/login, POST /auth/logout
│   │   │           ├── chat.py        # POST /chat/message, WS /chat/stream
│   │   │           ├── workspaces.py  # GET /workspaces
│   │   │           ├── threads.py     # CRUD for threads
│   │   │           ├── memory.py      # GET/POST memory endpoints
│   │   │           ├── goal.py        # Goal mode plan/approve/gate flow
│   │   │           ├── files.py       # POST /files/upload
│   │   │           ├── agents.py      # GET /agents
│   │   │           ├── entities.py    # GET/DELETE entity endpoints
│   │   │           ├── search.py      # GET /search
│   │   │           ├── status.py      # GET /status
│   │   │           └── handoff.py     # POST /handoff
│   │   ├── core/
│   │   │   ├── config.py              # ← agents/config.py (minimal changes needed)
│   │   │   ├── model.py               # ← agents/model.py (no changes needed)
│   │   │   ├── state.py               # ← agents/state.py (remove Discord client ref)
│   │   │   ├── auth.py                # JWT generation and validation
│   │   │   └── ws_manager.py          # WebSocket connection manager
│   │   ├── features/
│   │   │   ├── chat/
│   │   │   │   └── orchestrator.py    # ← agents/orchestrator.py (major refactor: replace Discord deps)
│   │   │   ├── tools/
│   │   │   │   └── tool_definitions.py # ← tools/tool_definitions.py (no changes needed)
│   │   │   ├── session/
│   │   │   │   └── session.py         # ← agents/session.py (no changes needed)
│   │   │   └── voice/
│   │   │       └── voice_input.py     # ← agents/voice_input.py (remove Discord voice channel code)
│   │   └── db/
│   │       └── memory_manager.py      # ← memory/memory_manager.py (no changes needed)
│   └── SOUL.md                        # Retained as-is
├── frontend/
│   └── [React app]
└── memory/
    ├── database.db                    # SQLite — unchanged
    └── chroma_db/                     # ChromaDB — rebuilt at cutover
```

**Module change assessment:**

| Module | Discord Dependencies | Change Required |
|--------|---------------------|-----------------|
| `agents/config.py` | None — pure Python dicts | Minimal: remove Discord channel constants (`LOG_CHANNEL`, `STATUS_CHANNEL`), keep workspace config |
| `agents/model.py` | None | None — copy as-is |
| `agents/state.py` | `bot` reference (Discord client) | Minor: remove `bot = None`; add WebSocket manager reference |
| `agents/session.py` | None | None — copy as-is |
| `agents/orchestrator.py` | Heavy: `discord`, `send_to_channel`, `send_long_message`, Discord typing context, Discord thread creation | Major refactor: replace all `discord.*` calls with WebSocket emits and FastAPI responses; extract the pure logic (tool loop, memory extraction, reflection) which has no Discord dependency |
| `agents/services.py` | Pure Discord wrapper | Replace entirely with WebSocket messaging service |
| `agents/bot.py` | Pure Discord bot | Delete — all logic extracted to FastAPI endpoints |
| `agents/voice_input.py` | Discord voice channel for TTS playback only | Partial: `transcribe_attachment` is portable; `speak_response` needs rewrite for HTTP audio streaming |
| `memory/memory_manager.py` | None | None — copy as-is |
| `tools/tool_definitions.py` | None (subprocess call to `ccc.exe` is path-specific) | Minor: update `ccc.exe` path constant from env var; update User-Agent string |

---

### 5.2 API Endpoint Map

```
POST   /api/v1/auth/login
Purpose: Authenticate with password; returns JWT token
Auth required: No
WebSocket: No

POST   /api/v1/auth/logout
Purpose: Invalidate current session token
Auth required: Yes
WebSocket: No

GET    /api/v1/workspaces
Purpose: List all workspaces (channel equivalents) with their memory mode and purpose
Auth required: Yes
WebSocket: No

GET    /api/v1/workspaces/{workspace_slug}/threads
Purpose: List all threads in a workspace, sorted by last activity
Auth required: Yes
WebSocket: No

POST   /api/v1/workspaces/{workspace_slug}/threads
Purpose: Create a new thread with optional title; returns thread_id
Auth required: Yes
WebSocket: No

GET    /api/v1/threads/{thread_id}
Purpose: Get thread metadata and full message history
Auth required: Yes
WebSocket: No

PATCH  /api/v1/threads/{thread_id}
Purpose: Rename thread title
Auth required: Yes
WebSocket: No

DELETE /api/v1/threads/{thread_id}
Purpose: Delete thread and its conversation history
Auth required: Yes
WebSocket: No

POST   /api/v1/chat/message
Purpose: Send a message in a thread; triggers process_user_message pipeline; returns full response (non-streaming fallback)
Auth required: Yes
WebSocket: No

WS     /api/v1/chat/stream
Purpose: WebSocket for streaming responses; client sends message, server streams tokens as they arrive from Anthropic API
Auth required: Yes (token in query param or initial message)
WebSocket: Yes

GET    /api/v1/memory
Purpose: Get memory snapshot for a workspace context (strategic/operational/analytical/stale_flags)
Auth required: Yes
WebSocket: No

POST   /api/v1/memory/save
Purpose: Write directly to a memory layer bypassing AI extraction (replaces !save-verbatim)
Auth required: Yes
WebSocket: No

POST   /api/v1/memory/consolidate
Purpose: Manually trigger memory consolidation for a workspace scope (replaces !consolidate)
Auth required: Yes
WebSocket: No

POST   /api/v1/memory/pin/{memory_id}
Purpose: Pin an operational memory (replaces !pin)
Auth required: Yes
WebSocket: No

DELETE /api/v1/memory/pin/{memory_id}
Purpose: Unpin an operational memory (replaces !unpin)
Auth required: Yes
WebSocket: No

GET    /api/v1/memory/search
Purpose: Full-text search of conversation_log (replaces !search); query param: q
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/plan
Purpose: Submit a goal text for planning; returns plan with step list (replaces !goal / !plan / !research)
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/{goal_id}/approve
Purpose: Approve a pending goal plan and begin execution (replaces !approve)
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/{goal_id}/modify
Purpose: Revise a pending goal plan (replaces !modify)
Auth required: Yes
WebSocket: No

DELETE /api/v1/goal/{goal_id}
Purpose: Cancel a pending goal or active gate (replaces !cancel)
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/{goal_id}/gate/continue
Purpose: Resume execution from a mid-execution gate (replaces !continue)
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/{goal_id}/gate/adjust
Purpose: Replan remaining steps at a gate (replaces !adjust)
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/{goal_id}/gate/skip
Purpose: Skip a failed step at a gate (replaces !skip)
Auth required: Yes
WebSocket: No

POST   /api/v1/goal/{goal_id}/gate/retry
Purpose: Retry a failed step at a gate (replaces !retry during gate)
Auth required: Yes
WebSocket: No

POST   /api/v1/files/upload
Purpose: Upload a file for processing (PDF, DOCX, TXT, MD, CSV, PNG, JPG, WEBP); associates file with a thread
Auth required: Yes
WebSocket: No

GET    /api/v1/agents
Purpose: List all loaded specialist agents with slug, name, description (replaces !agents)
Auth required: Yes
WebSocket: No

POST   /api/v1/agents/select
Purpose: Set the active agent for a thread (replaces !use / !agent)
Auth required: Yes
WebSocket: No

GET    /api/v1/entities
Purpose: List all entities of type=person (replaces !roster)
Auth required: Yes
WebSocket: No

GET    /api/v1/entities/{name}
Purpose: Get full entity profile with facts grouped by category (replaces !profile)
Auth required: Yes
WebSocket: No

DELETE /api/v1/entities/facts/{fact_id}
Purpose: Delete a specific entity fact by ID (replaces !profile-delete)
Auth required: Yes
WebSocket: No

GET    /api/v1/status
Purpose: System health report: Ollama status, memory counts, uptime (replaces !status)
Auth required: Yes
WebSocket: No

POST   /api/v1/handoff
Purpose: Generate dense handoff document from memory snapshot (replaces !handoff)
Auth required: Yes
WebSocket: No

GET    /api/v1/reasoning-trace
Purpose: Return recent reasoning trace entries for a thread (replaces !trace)
Auth required: Yes
WebSocket: No
```

---

### 5.3 Deployment Topology

```
Internet
    │
    ▼
Nginx (port 443, SSL via Let's Encrypt)
    ├── /                → serves React static build from /var/www/drift/
    ├── /api/           → proxy_pass to FastAPI on 127.0.0.1:8000
    └── /api/v1/chat/stream  → proxy_pass with WebSocket upgrade headers

FastAPI via Uvicorn (127.0.0.1:8000)
    ├── Loads SOUL.md, config.py, agent definitions at startup
    ├── Spawns asyncio background tasks:
    │   ├── run_proactive_flag_surfacing (24hr loop)
    │   └── run_scheduled_consolidation (72hr loop)
    ├── Handles WebSocket connections via ws_manager.py
    └── Calls Anthropic API and Ollama for model inference

SQLite (file on disk)
    └── memory/database.db — unchanged schema, unchanged location

ChromaDB (directory on disk)
    └── memory/chroma_db/ — rebuilt at cutover, unchanged thereafter

Ollama (localhost:11434)
    └── qwen3:8b model for background tasks
    └── Managed by existing systemd service (InstallOllamaService.bat pattern)

systemd services required:
    ├── drift-backend.service  — FastAPI via Uvicorn
    │   ExecStart: uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
    ├── ollama.service          — already installed/running
    └── nginx.service           — standard system service
```

---

## Section 6 — Data Migration Plan

### 6.1 Memory Wipe Scope

**Wipe at cutover (Discord-keyed, meaningless in web context):**
- `conversation_history` table — all rows (Discord `uid:channel_id` keys are meaningless; export as JSON backup first)
- `conversation_log` table — all rows (Discord `context_id` values are meaningless; export as JSON backup first)
- `session_state` table — all rows (Discord `context_id` values are meaningless; fresh start is appropriate)
- `reasoning_trace` table — all rows (Discord channel context; optional — low value to retain)

**Preserve at cutover:**
- `strategic_memory` — all active rows (core user knowledge; this is the crown jewel)
- `operational_memory` — all active rows (review manually post-cutover for stale items)
- `analytical_memory` — all active rows (learned patterns and crystallised skills)
- `experiences` — all rows (task episode history for reflection loop)
- `memory_archive` — all rows (historical record)
- `health_panels` — all rows (irreplaceable health data)
- `health_protocols` — all rows (irreplaceable protocol history)
- `entities` — all rows (director-workspace people)
- `entity_facts` — all rows (longitudinal fact history)
- `meta` — all rows except reset `pending_reflection` to `false`

**Export before wipe:**
- `conversation_history` → `backup_conversation_history_YYYY-MM-DD.json`
- `conversation_log` → `backup_conversation_log_YYYY-MM-DD.json`

**New table to create at cutover:**
- `threads` — `id` (PK), `workspace_slug`, `title`, `created_at`, `last_message_at`; thread IDs become the new `context_id` for `conversation_history` and `session_state`

---

### 6.2 Embedding Model Upgrade

**Current model:** `all-MiniLM-L6-v2` from `sentence-transformers` — 384 dimensions, ~23M parameters, loaded locally.

ChromaDB collections (`strategic`, `operational`, `analytical`) will be **fully rebuilt at cutover** because the wipe of `conversation_history` and `conversation_log` is a natural cutover point, and all preserved memory rows in SQLite can be re-embedded in a one-time migration script.

**Target model: TBD — needs discussion.** Strong candidates:
- `nomic-embed-text` via Ollama (runs locally on same VPS, no added API cost, 768d, meaningful quality improvement)
- `text-embedding-3-small` via OpenAI API (1536d, no local inference overhead, pay-per-use)

Since ChromaDB gets rebuilt at cutover anyway, upgrading the embedding model costs nothing extra in migration effort — only the re-embedding script must use the new model consistently.

---

### 6.3 Cutover Sequence

1. **Stop Discord bot** — `StopBot.bat` or systemd stop
2. **Export backups** — dump `conversation_history` and `conversation_log` tables to JSON files
3. **Run database migration script** — create `threads` table; reset `pending_reflection` in `meta`; wipe `conversation_history`, `conversation_log`, `session_state`, `reasoning_trace` tables
4. **Choose and install embedding model** — install new embedding model (e.g., pull via Ollama `ollama pull nomic-embed-text`, or install new sentence-transformers model)
5. **Rebuild ChromaDB** — run re-embedding script that reads all active rows from `strategic_memory`, `operational_memory`, `analytical_memory` and writes new vectors with the new model; delete old `chroma_db/` directory first
6. **Update codebase** — rename `PerMyLastBot` to `Drift` in SOUL.md, config strings, bot name references (see Section 8); update `search_codebase` tool path if needed; update `POPPLER_PATH` env var for VPS
7. **Build React frontend** — `npm run build`, copy to `/var/www/drift/`
8. **Configure Nginx** — install config with proxy_pass rules and WebSocket upgrade headers; install SSL cert via certbot
9. **Install systemd service** — `drift-backend.service` pointing at Uvicorn
10. **Start backend** — `systemctl start drift-backend`; verify health at `/api/v1/status`
11. **Smoke test** — login, send a message, verify memory retrieval, verify goal mode plan flow, verify health workspace isolation
12. **DNS cutover** — point domain to VPS

---

## Section 7 — Post-Transition Roadmap

Priority order with architectural hooks noted:

**1. Formatted document export (PDF/DOCX coaching reports)**
The `POST /api/v1/handoff` endpoint should accept a `format` query param from day one. Backend renders text to PDF via `weasyprint` or `python-docx`. Install these packages at port time even if the format endpoint initially returns text only.

**2. Entity profile timeline dashboard**
All data already exists in `entities` + `entity_facts` tables with `recorded_at` timestamps and `superseded_by` FK for timeline. Add `GET /api/v1/entities/{name}/timeline` endpoint. Pure frontend work once endpoint exists.

**3. Animated agent indicators during goal execution**
The WebSocket stream already needs to emit step-start / step-complete events for the goal execution loop. Design the WebSocket message schema to include `{ type: "step_progress", step_num: N, step_type: "web_search", agent_slug: "..." }` from day one. The animation is purely frontend — the hook is the event schema.

**4. Multi-agent visualization for crew mode**
Crew mode (`pg.get("crew_mode")`) already tags each step with an `agent` slug. The WebSocket step-progress events (same hook as #3) should include the crew agent label. The visualization is a frontend overlay on the goal execution progress view.

**5. File upload with proper preview**
File upload endpoint (`POST /api/v1/files/upload`) should return a preview payload at port time: for documents, return first 500 chars of extracted text; for images, return the base64 thumbnail. Frontend renders these as attachment cards in the chat.

**6. Memory browser (visual interface for all memory layers)**
All three memory layers are queryable via `GET /api/v1/memory`. Add a `GET /api/v1/memory/all` endpoint that returns paginated raw records from all three SQLite tables with filter params (layer, project_tag, date range, status). Memory browser is a dedicated React route.

**7. Parallel step execution in goal mode (architecture must accommodate)**
`execute_goal` in `orchestrator.py` is currently a sequential `for` loop. The step data structure (`step_type`, `step_query`, `agent`) already supports parallelism — steps with no data dependencies can run concurrently. **Design the API response for `POST /api/v1/goal/{goal_id}/approve` to return step dependency metadata even if execution is still sequential.** This prevents a breaking API change later when parallel execution is added.

**8. Inter-agent context passing in crew mode (architecture must accommodate)**
Each `call_agent` step's output is stored in `execution_context[user_id]["steps"]`. **Ensure the step result schema includes `agent_slug`, `step_num`, and `output` as named fields rather than a flat string list.** This allows agent B to reference agent A's structured output explicitly rather than parsing concatenated text.

**9. Claude Dreaming integration (pending Anthropic API access)**
Dreaming mode would allow the bot to run reflection and memory consolidation asynchronously in the background without user interaction. The reflection loop (`run_reflection_loop`) and consolidation (`consolidate_all_layers`) already run as asyncio background tasks — Dreaming would deepen the prompt used in those loops. No architectural change needed; it's a prompt swap once API access is available.

---

## Section 8 — Rename Reference

Every location where the old name "PerMyLastBot" appears and will need updating to "Drift":

**Hard-coded strings:**

| File | Location | Current String |
|------|----------|---------------|
| `SOUL.md` | Line 1 | `You are PerMyLastBot, an operations-minded AI counterpart...` |
| `agents/bot.py` | Line 189 | `HELP_TEXT = """**PerMyLastBot — Commands**` |
| `agents/bot.py` | Line 853 | `print(f"PerMyLastBot is online as {bot.user} "` |
| `agents/bot.py` | Line 868 | `"PerMyLastBot is online — memory system and tools active."` |
| `tools/tool_definitions.py` | Line 295 | `"Search the PerMyLastBot codebase for relevant functions, "` |
| `tools/tool_definitions.py` | Line 714 | `"Mozilla/5.0 (compatible; PerMyLastBot/1.0; +research)"` |
| `StartBot.bat` | Lines 2, 5 | `title PerMyLastBot`, `echo Starting PerMyLastBot...` |
| `StopBot.bat` | Lines 2, 3 | `title Stopping PerMyLastBot`, `echo Stopping PerMyLastBot...` |
| `BUILD_STATUS.md` | Line 1, Line 234 | `# BUILD STATUS — PerMyLastBot`, codebase description |

**Variable names (no code impact — comments/strings only):**
- None found — the codebase uses generic variable names internally.

**Comments:**
- `agents/orchestrator.py` header comment: `# orchestrator.py — Core message processing and goal execution` (no PerMyLastBot mention, but the module path will change)

**Environment variable names:**
- `DISCORD_TOKEN` — remove entirely
- `DISCORD_OWNER_ID` — replace with `DRIFT_OWNER_PASSWORD` (or equivalent JWT secret)
- `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` — retain but mark as post-port optional
- `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_HOST` — retain as-is

**System prompt references:**
- `SOUL.md` line 1: "You are PerMyLastBot" → "You are Drift"

**File names:**
- None contain "PerMyLastBot" directly. Consider renaming `SOUL.md` to `DRIFT_SOUL.md` for clarity (optional).
- `StartBot.bat` / `StopBot.bat` / `InstallOllamaService.bat` — replaced by systemd service; can be deleted or renamed to `StartDrift.sh` etc.

**Agent directory:**
- `C:\Users\Jerm\.claude\agents` — agent `.md` files may reference "PerMyLastBot" in their content; audit each file's body text.

---

*Do not make the above changes now — this section is an inventory only.*
