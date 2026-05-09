# BUILD STATUS — PerMyLastBot

_Regenerated from codebase on 2026-05-08. Update manually when architecture changes._

---

## Python Version & Runtime

| Item | Value |
|---|---|
| Python (venv) | 3.12.9 |
| Venv location | `venv/` (project root) |
| Entry point | `agents/bot.py` |
| Platform | Windows 10 (win32) |

---

## Key Dependencies

| Package | Version | Role |
|---|---|---|
| discord.py | 2.7.1 | Discord bot framework |
| anthropic | 0.97.0 | Claude API SDK |
| elevenlabs | 2.45.0 | Text-to-speech output |
| faster-whisper | 1.2.1 | Voice message transcription |
| chromadb | 1.5.8 | Vector database (semantic memory search) |
| sentence-transformers | 5.4.1 | Embedding model (`all-MiniLM-L6-v2`, 384-dim) |
| duckduckgo-search | 8.1.1 | Web search tool |
| requests | 2.33.1 | HTTP client for `web_fetch` tool |
| beautifulsoup4 | (installed) | HTML stripping for `web_fetch` |
| torch | 2.11.0 | ML backend for embeddings |
| python-dotenv | 1.2.2 | .env loading |
| ctranslate2 | 4.7.1 | Whisper inference engine |

Full dependency list in `requirements.txt` (UTF-16 LE encoded — use PowerShell `-Encoding Unicode` to edit).

---

## Bot Architecture

**File:** `agents/bot.py` (~3400 lines)

### Models

| Constant | Value | Usage |
|---|---|---|
| `MAIN_MODEL` | `claude-sonnet-4-6` | All user-facing Claude calls |
| `BACKGROUND_MODEL` | `claude-haiku-4-5-20251001` | Reflection & memory extraction (fallback) |
| `OLLAMA_MODEL` | `qwen3:8b` | Background tasks (primary local model via Ollama) |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `MAX_TOOL_CALLS` | `20` | Tool loop cap per response |
| `MAX_REASONING_ITERATIONS` | `10` | Max while-loop cycles in `process_user_message` |
| `AGENT_INJECT_CHAR_LIMIT` | `1500` | Max chars of agent .md injected into system prompt |

### Discord Channels

| Constant | Channel Name | Purpose |
|---|---|---|
| `COMMAND_CHANNEL` | `bot-commands` | General-purpose text channel |
| `STATUS_CHANNEL` | `bot-status` | User-visible activity updates |
| `LOG_CHANNEL` | `bot-logs` | Detailed events, token counts, tool calls, errors |

### Discord Intents
`message_content`, `members`, `presences`, `voice_states`

### Channel Configuration

**`CHANNEL_MEMORY_MODE`** — controls memory extraction after each response:

| Channel | Mode | Effect |
|---|---|---|
| `bot-commands` | `ephemeral` | Responds only, no memory extraction |
| `sandbox` | `ephemeral` | Responds only, no memory extraction |
| `chief-of-staff` | `global` | Extracts memories with no project tag |
| `director-workspace` | `global` | Extracts memories with no project tag |
| `planning` | `global` | Extracts memories with no project tag |
| `contact-center` | `project` | Extracts memories tagged to project |
| `gamification-dashboard` | `project` | Extracts memories tagged to project |
| `slack-intelligence` | `project` | Extracts memories tagged to project |
| `health-tracking` | `project` | Extracts memories tagged to project (isolated) |
| (absent) | `ephemeral` | Default — no memory |

**`CHANNEL_TOOL_MODE`** — controls which tools Claude receives:

| Mode | Channels | Tools Available |
|---|---|---|
| `full` | chief-of-staff, director-workspace, planning, contact-center, gamification-dashboard, slack-intelligence, health-tracking | All tools, minus `search_codebase` for excluded channels |
| `search_only` | bot-commands | `web_search`, `web_fetch`, `query_memory`, `search_codebase` |
| `none` | sandbox, (absent) | No tools |

**`CODEBASE_SEARCH_EXCLUDED_CHANNELS`** — `search_codebase` is withheld here even in full mode:
`health-tracking`, `chief-of-staff`, `director-workspace`

**`THREADED_CHANNELS`** — new conversations create a Discord thread; all replies stay in-thread:
`chief-of-staff`, `director-workspace`, `planning`, `contact-center`, `gamification-dashboard`, `health-tracking`

**`MEMORY_ISOLATED_CHANNELS`** — bidirectional isolation (health data never bleeds to/from other channels):
`health-tracking`

### Message Entry Points

| Trigger | Condition |
|---|---|
| Text (prefix) | Message starting with `!` in any non-ignored channel |
| Text (mention) | Message `@mention`ing the bot |
| Voice | Audio attachment with `content_type` starting with `audio/` |

### Processing Pipeline (`process_user_message`)

```
on_message()
  ├─ Detect audio attachment → transcribe → "Heard: ..." → process (speak=True)
  ├─ Detect "speak" keyword at end of text → strip it → process (speak=True)
  └─ Detect !prefix or @mention → process (speak=False)

process_user_message(user_message, user_id, author_display_name, guild, channel, ...)
  1. select_agent()                          — keyword/channel/pin routing to specialist
  2. get_relevant_memories(message)          — semantic search across 3 layers (isolated for health-tracking)
  3. format_memory_for_prompt()              — inject context into message
  4. Append to conversation_history[(user_id, context_id)]
  5. AsyncExitStack: channel.typing() — 429 silently skipped, not retried
  6. Loop (max MAX_REASONING_ITERATIONS=10): client.messages.create()
     ├─ system=SOUL.md [+ active agent definition], tools=active_tools, model=claude-sonnet-4-6
     ├─ While stop_reason == "tool_use": execute tools (max 20), append results, continue
     └─ Break when stop_reason != "tool_use"
  7. send_long_message(channel, response)
  8. If speak=True: speak_response(text, guild)
  9. save_conversation_history()             — persisted to SQLite after every response
 10. extract_and_store_memories()            — background model extracts learnings (rubric-gated)
 11. If task_completed: run_reflection_loop()
 12. Log token usage + agent info to LOG_CHANNEL
```

**Conversation history** is persisted to SQLite via `save_conversation_history()` (called at line ~2812) and loaded at startup via `load_all_conversation_histories()`. History is keyed by `(user_id, context_id)` where `context_id` is the thread ID (threaded channels) or channel ID.

### Task Completion Detection
`is_task_completion(message)` matches against ~20 signals: done, finished, perfect, thanks, complete, ship it, etc. Triggers the reflection loop when matched.

---

## Voice Input

**File:** `agents/voice_input.py`

- Trigger: Discord voice message attachment (`audio/*` content type)
- Download: `attachment.read()` → raw bytes
- Model: `WhisperModel("small", device="cpu", compute_type="int8")`
- Flow: bytes → temp file (correct suffix) → `transcribe()` → joined segment text → delete temp file
- Model loads lazily on first transcription call and stays in memory

**Limitation:** Only works with Discord voice message attachments (mobile/desktop "hold to record" feature). Does not capture live voice channel audio.

---

## Voice Output (TTS)

**Function:** `speak_response(text, guild)`

- Provider: ElevenLabs SDK (`elevenlabs==2.45.0`)
- Model: `eleven_monolingual_v1`
- Voice: configured via `ELEVENLABS_VOICE_ID` env var
- Flow: ElevenLabs API → stream chunks → temp `.mp3` → join "General" voice channel → `FFmpegPCMAudio` → play → disconnect → delete temp file
- Errors are swallowed silently — text response always delivers even if TTS fails
- Requires: FFmpeg on PATH; `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in `.env`

**Trigger conditions:**
- Voice message attachment (always speaks back)
- Text message ending with the word `speak` (stripped before processing)

---

## Memory System

**File:** `memory/memory_manager.py` (~648 lines)

### Storage Backends

| Backend | Location | Purpose |
|---|---|---|
| SQLite | `memory/database.db` | Primary persistent store |
| ChromaDB | `memory/chroma_db/` | Vector index for semantic search |
| Embedding model | `all-MiniLM-L6-v2` (384-dim) | Converts queries and memories to vectors |

### Three Layers

| Layer | Decay | Token Budget | What Goes Here |
|---|---|---|---|
| **Strategic** | 60 days | 150 tokens | Long-term user model: goals, values, preferences, decisions |
| **Operational** | 7 days | 100 tokens | Active projects, tasks, blockers, dependencies |
| **Analytical** | 21 days | 100 tokens | Patterns, insights, crystallised skills |

Additional SQLite tables: `experiences` (task outcomes, not embedded), `memory_archive` (soft-deleted), `meta` (global state), `conversation_history` (full message history, persisted), `health_panels`, `health_protocols`, `reasoning_traces`.

### Retrieval
`get_relevant_memories(query)` → semantic search (top 3 per layer) → stale flags appended if memory age exceeds decay threshold → formatted via `format_memory_for_prompt()` and prepended to user message before Claude call.

### Isolation
`health-tracking` is bidirectionally isolated: its memories never surface in other channels and it never receives memories from other channels.

### Memory Extraction Gate
Memories extracted by the background model are scored on a 4-criterion rubric (threshold 8/12) before storage. A similarity pre-filter at 0.88 blocks near-duplicates. Rejections are logged to `bot-logs`.

### Staleness & Maintenance
- Memories older than their decay threshold are flagged with ⚠️ in the prompt
- `validate_memory()` — marks confirmed, increments `times_referenced`
- `update_memory_confidence()` — adjusts confidence ±0.1 (clamped 0.1–1.0)
- `archive_memory()` — soft-deletes with reason and optional superseding memory ID
- Auto-consolidation thresholds: strategic 100, operational 50, analytical 75, health 150

### Reflection Loop
Fires after any message matching task-completion signals:
1. Fetch last 5 completed experiences
2. Background model (Ollama qwen3:8b → Haiku fallback) processes `REFLECTION_PROMPT`
3. Returns JSON: `{insights[], strategic_insights[], summary}`
4. Each insight saved as `save_analytical_memory(pattern_type="task_reflection")`
5. Each strategic insight saved as `save_strategic_memory(category="reflection")`

---

## Tools

**File:** `tools/tool_definitions.py` (~689 lines)

All tools are defined in `TOOL_DEFINITIONS` (Anthropic tool format) and routed through `execute_tool(tool_name, tool_inputs, channel_name)`. Tools run in a thread executor (non-blocking). Cap: `MAX_TOOL_CALLS = 20` per response (applies to all tools combined).

| Tool | What It Does | Channels |
|---|---|---|
| `query_memory` | Semantic search across strategic / operational / analytical layers (or all); respects channel isolation | All tool-enabled channels |
| `save_skill` | Crystallises a repeated pattern into the analytical layer (`confidence ≥ 0.7` required) | Full channels |
| `update_user_model` | Saves a user fact to strategic layer under one of 8 categories | Full channels |
| `flag_for_review` | Saves a topic to operational layer under `project_name="review_flags"` with priority; high-priority flags escalate to chief-of-staff | Full channels |
| `web_search` | DuckDuckGo search, returns title + URL + snippet for up to 5 results | All tool-enabled channels |
| `web_fetch` | Fetches a URL via `requests`, strips HTML with BeautifulSoup, returns up to 10000 chars of plain text; blocks local network addresses; no per-response cap | All tool-enabled channels |
| `search_codebase` | Semantic search of PerMyLastBot codebase via CocoIndex-Code CLI (`ccc.exe`); returns code sections with file paths and line numbers; up to 10 results | Technical channels only (excluded from health-tracking, chief-of-staff, director-workspace) |
| `calculate_confidence` | Adjusts an existing memory's confidence up or down with a reason | Full channels |

Tool calls are logged to `bot-logs` with tool name and truncated inputs. `web_fetch` additionally logs URL, content size, and a token-cost warning if the fetch exceeds ~2000 tokens. `search_codebase` logs query and result size. `bot-status` shows a per-tool status message before execution.

---

## Agent System

**Agents directory:** `C:\Users\Jerm\.claude\agents` (`.md` files, loaded at startup)

**Keyword cache:** `memory/agent_keywords_cache.json` (extracted once by background model, cached to disk)

### Agent Selection Priority (`select_agent`)
0. **Thread pin** — if `context_id` is in `thread_agent_pins`, return that slug (sticky for thread lifetime)
1. **Channel hint** — `CHANNEL_AGENT_HINTS` maps channels to preferred agent slugs
2. **Keyword match** — message text matched against each agent's keyword list
3. **Fallback** — no agent (bare SOUL.md system prompt)

### Channel → Agent Hints
| Channel | Preferred Agent |
|---|---|
| `health-tracking` | `health-researcher` (hard rule, not overridable) |
| `gamification-dashboard` | `engineering-ai-engineer`, `engineering-data-engineer` |
| `director-workspace` | `director-advisor` |
| `chief-of-staff` | `personal-productivity`, `director-advisor` |
| `slack-intelligence` | `support-analytics-reporter` |
| `contact-center` | `support-analytics-reporter` |

### Commands
- `!agent [slug] [message]` — activate a specific agent for one response
- `!agents` — list all loaded agents with slugs and descriptions
- Active agent definition is injected into the system prompt (truncated to `AGENT_INJECT_CHAR_LIMIT = 1500` chars)

---

## Goal Mode

**Commands:** `!goal [description]`, `!plan`, `!research`

**Flow:**
1. Background model decomposes goal into 3–8 steps (types: `web_search`, `query_memory`, `analyze`, `draft`)
2. Plan displayed to user; user replies `!approve` / `!cancel` / `!modify [changes]`
3. `execute_goal()` runs steps sequentially as a background task
4. **Gates** pause execution for user review:
   - **DRAFT GATE** — always pauses before any `draft` step
   - **RESEARCH GATE** — pauses after `web_search` in `smart`/`always` modes
   - **STEP FAILURE GATE** — pauses on any step exception
5. During execution: `!continue`, `!adjust [changes]`, `!retry`, `!skip`, `!cancel`

**Gate mode** (`GOAL_GATE_MODE = "smart"`): gates fire when search results are low quality, surprising, or the last search before synthesis. `"always"` gates every search. `"minimal"` only gates before drafts.

**Analyze critique loop** (non-minimal modes): Haiku reviews each `analyze` step output; one retry with critique injected if not `PASS`. Revised output always appended to execution context.

---

## CocoIndex-Code Integration

**CLI:** `C:\Users\Jerm\.local\bin\ccc.exe`
**Codebase indexed:** `C:\Projects\discord-agent`
**MCP server:** added to Claude Code (`cocoindex-code`) — enables semantic search in Claude Code sessions
**Bot tool:** `search_codebase` calls `ccc.exe search <query> --limit <n>` via subprocess with `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` to prevent Windows cp1252 encoding errors

---

## MCP Servers (Claude Code)

Configured in `~/.claude.json` (`mcpServers` key). Available to Claude Code sessions globally.

| Server | Command / Endpoint | Status |
|---|---|---|
| `sequential-thinking` | `npx @modelcontextprotocol/server-sequential-thinking` | Connected |
| `context7` | `npx @upstash/context7-mcp` | Connected |
| `claude.ai Google Drive` | `https://drivemcp.googleapis.com/mcp/v1` | Needs authentication |
| `cocoindex-code` | `ccc.exe` (local binary) | Connected — semantic codebase search |

No MCP servers are wired into the bot itself.

---

## Claude Code Configuration

**Project permissions** (`.claude/settings.json`):
- `venv/Scripts/pip install *` / `pip show *` / `pip uninstall *`
- `PowerShell(...)` — scoped to requirements.txt edits and pip installs

**User-local permissions** (`.claude/settings.local.json`):
- `git add *` / `git commit *`
- `pip show *` / `pip list *`
- `python -c *` (import verification)

**Claude Code skills available** (global install):
`simplify`, `security-review`, `review`, `init`, `claude-api`, `fewer-permission-prompts`, `loop`, `schedule`, `update-config`, `keybindings-help`

---

## Environment Variables

All loaded from `.env` at project root.

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | Bot authentication |
| `ANTHROPIC_API_KEY` | Claude API access |
| `DISCORD_OWNER_ID` | Discord user ID — used for `tag_owner()` mentions in error/status messages |
| `ELEVENLABS_API_KEY` | TTS API authentication |
| `ELEVENLABS_VOICE_ID` | Selects the ElevenLabs voice for TTS output |

---

## Changes — May 8 2026 Session

| Change | Detail |
|---|---|
| `OLLAMA_MODEL` updated | `llama3.2` → `qwen3:8b` — better instruction following for memory extraction, rubric scoring, and consolidation |
| `MAX_TOOL_CALLS` raised | `5` → `20` — supports research-heavy sessions chaining web_search + web_fetch + search_codebase |
| `web_fetch` tool added | Fetches full URL content via requests + BeautifulSoup; no per-response cap; available in all tool-enabled channels including health-tracking |
| `search_codebase` tool added | Semantic codebase search via CocoIndex-Code CLI; restricted to technical channels |
| CocoIndex-Code installed | `ccc.exe` indexed at project root; MCP server added to Claude Code |
| Typing indicator 429 fix | `channel.typing()` entry wrapped in `contextlib.AsyncExitStack`; 429 silently skipped instead of cascading |
| `PYTHONIOENCODING=utf-8` | Set for `ccc.exe` subprocess to prevent Windows cp1252 encoding crashes on Unicode output |
| Agent token logging fix | Reports actual injected chars (capped at `AGENT_INJECT_CHAR_LIMIT`) not full file size |
| `web_fetch` per-response cap removed | Original 3-fetch cap removed; `MAX_TOOL_CALLS=20` is the only limit |

---

## What Is Working

- [x] Discord bot connects and listens across all configured channels
- [x] Text commands via `!prefix` and `@mention`
- [x] Voice message attachment transcription (Discord mobile/desktop voice messages)
- [x] ElevenLabs TTS — speaks response in "General" voice channel when triggered
- [x] Full Claude agentic loop with tool use (max 20 calls per response)
- [x] All 8 tools functional: memory CRUD, web search, web fetch, codebase search, confidence adjustment
- [x] 3-layer memory system with SQLite + ChromaDB persistence
- [x] Semantic retrieval with stale flagging
- [x] **Conversation history persisted** — saved to SQLite after every response, loaded at startup
- [x] Background memory extraction after every response (qwen3:8b → Haiku fallback) with rubric gate
- [x] Reflection loop on task completion
- [x] Goal mode with step-by-step execution, gate system, and analyze critique loop
- [x] Specialist agent system — keyword routing, thread pinning, channel hints
- [x] Threaded conversations in 6 channels
- [x] Memory isolation for health-tracking (bidirectional)
- [x] Auto-consolidation at configurable thresholds
- [x] Owner tagging for errors and stale memory warnings
- [x] Message splitting for responses over 2000 characters
- [x] Status + log channel reporting per tool call
- [x] CocoIndex-Code semantic search in Claude Code sessions and via bot tool

---

## What Is Pending / Known Gaps

- [ ] **Ollama dependency** — background tasks degrade to Haiku if Ollama isn't running; startup check exists (`check_ollama_health`) but bot continues regardless
- [ ] **FFmpeg required for TTS** — must be on PATH; bot gives no warning if missing, TTS silently fails
- [ ] **"General" channel hardcoded** — `speak_response` only looks for a voice channel named exactly "General"
- [ ] **No slash commands** — all prior `/listen` and `/leave` commands were removed; bot is text/attachment only
- [ ] **Live voice capture removed** — `discord-ext-voice-recv` architecture was abandoned; no path to real-time voice channel listening
- [ ] **Memory has no hard size cap** — ChromaDB and SQLite grow until consolidation triggers; auto-consolidation is threshold-based but not size-bounded
- [ ] **No multi-guild isolation** — `conversation_history` keyed by `(user_id, context_id)`; cross-guild collisions possible if bot is in multiple servers
- [ ] **SOUL.md loaded once at startup** — changes require bot restart
- [ ] **`mcp_servers/` directory is empty** — reserved for future bot-side MCP integration
