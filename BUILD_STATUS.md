# BUILD STATUS — PerMyLastBot

_Generated from codebase on 2026-04-27. Update manually when architecture changes._

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
| torch | 2.11.0 | ML backend for embeddings |
| python-dotenv | 1.2.2 | .env loading |
| ctranslate2 | 4.7.1 | Whisper inference engine |

Full dependency list in `requirements.txt` (UTF-16 LE encoded — use PowerShell `-Encoding Unicode` to edit).

---

## Bot Architecture

**File:** `agents/bot.py` (~700 lines)

### Models

| Constant | Value | Usage |
|---|---|---|
| `MAIN_MODEL` | `claude-sonnet-4-6` | All user-facing Claude calls |
| `BACKGROUND_MODEL` | `claude-haiku-4-5-20251001` | Reflection & memory extraction (Haiku fallback) |
| `OLLAMA_MODEL` | `llama3.2` | Background tasks (primary, local) |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `MAX_TOOL_CALLS` | `5` | Tool loop cap per response |

### Discord Channels

| Constant | Channel Name | Purpose |
|---|---|---|
| `COMMAND_CHANNEL` | `bot-commands` | Only channel where bot listens for messages |
| `STATUS_CHANNEL` | `bot-status` | User-visible activity updates |
| `LOG_CHANNEL` | `bot-logs` | Detailed events, token counts, errors |

### Discord Intents
`message_content`, `members`, `presences`, `voice_states`

### Message Entry Points

| Trigger | Condition |
|---|---|
| Text (prefix) | Message in `bot-commands` starting with `!` |
| Text (mention) | Message in `bot-commands` that `@mention`s the bot |
| Voice | Audio attachment with `content_type` starting with `audio/` |

### Processing Pipeline (`process_user_message`)

```
on_message()
  ├─ Detect audio attachment → transcribe → "Heard: ..." → process (speak=True)
  ├─ Detect "speak" keyword at end of text → strip it → process (speak=True)
  └─ Detect !prefix or @mention → process (speak=False)

process_user_message(user_message, user_id, author_display_name, guild, channel, speak)
  1. get_relevant_memories(message)        — semantic search across 3 layers
  2. format_memory_for_prompt()            — inject context into message
  3. Append to conversation_history[user_id]
  4. Loop: client.messages.create()
     ├─ system=SOUL.md, tools=TOOL_DEFINITIONS, model=claude-sonnet-4-6
     ├─ While stop_reason == "tool_use": execute tools, append results, continue
     └─ Break when stop_reason != "tool_use"
  5. send_long_message(channel, response)
  6. If speak=True: speak_response(text, guild)
  7. extract_and_store_memories()          — background model extracts learnings
  8. If task_completed: run_reflection_loop()
  9. Log to STATUS_CHANNEL + LOG_CHANNEL
```

**Conversation history** is in-memory (`dict[user_id → list]`), not persisted across restarts.

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

Plus: `experiences` table (task outcomes, not embedded), `memory_archive` (soft-deleted), `meta` (global state).

### Retrieval
`get_relevant_memories(query)` → semantic search (top 3 per layer) → stale flags appended if memory age exceeds decay threshold → formatted via `format_memory_for_prompt()` and prepended to user message before Claude call.

### Staleness & Maintenance
- Memories older than their decay threshold are flagged with ⚠️ in the prompt
- `validate_memory()` — marks confirmed, increments `times_referenced`
- `update_memory_confidence()` — adjusts confidence ±0.1 (clamped 0.1–1.0)
- `archive_memory()` — soft-deletes with reason and optional superseding memory ID
- Stale count is logged after every response; owner tagged in status if any flagged

### Reflection Loop
Fires after any message matching task-completion signals:
1. Fetch last 5 completed experiences
2. Background model (Ollama → Haiku) processes `REFLECTION_PROMPT`
3. Returns JSON: `{insights[], strategic_insights[], summary}`
4. Each insight saved as `save_analytical_memory(pattern_type="task_reflection")`
5. Each strategic insight saved as `save_strategic_memory(category="reflection")`

---

## Tools

**File:** `tools/tool_definitions.py` (~493 lines)

All tools are defined in `TOOL_DEFINITIONS` (Anthropic tool format) and routed through `execute_tool(tool_name, tool_inputs)`. Tools run in a thread executor (non-blocking). Cap: 5 calls per response.

| Tool | What It Does |
|---|---|
| `query_memory` | Semantic search across strategic / operational / analytical layers (or all) |
| `save_skill` | Crystallises a repeated pattern into the analytical layer (`confidence ≥ 0.7` required) |
| `update_user_model` | Saves a user fact to strategic layer under one of 8 categories (communication_style, goals, values, technical_preferences, working_style, background, constraints, general) |
| `flag_for_review` | Saves a topic to operational layer under `project_name="review_flags"` with priority |
| `web_search` | DuckDuckGo search, returns title + URL + snippet for up to 5 results |
| `calculate_confidence` | Adjusts an existing memory's confidence up or down with a reason |

Tool calls are logged to `bot-logs`; tool name is posted to `bot-status` after each execution.

---

## MCP Servers

Configured in `~/.claude.json` (`mcpServers` key). Available to Claude Code sessions globally.

| Server | Command | Status |
|---|---|---|
| `sequential-thinking` | `npx @modelcontextprotocol/server-sequential-thinking` | Connected |
| `context7` | `npx @upstash/context7-mcp` | Connected |
| `claude.ai Google Drive` | `https://drivemcp.googleapis.com/mcp/v1` | Needs authentication |

No MCP servers are wired into the bot itself (`mcp_servers/` directory exists but is empty).

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

## What Is Working

- [x] Discord bot connects and listens in `bot-commands`
- [x] Text commands via `!prefix` and `@mention`
- [x] Voice message attachment transcription (Discord mobile/desktop voice messages)
- [x] ElevenLabs TTS — speaks response in "General" voice channel when triggered
- [x] Full Claude agentic loop with tool use (max 5 calls)
- [x] All 6 tools functional (memory CRUD, web search, confidence adjustment)
- [x] 3-layer memory system with SQLite + ChromaDB persistence
- [x] Semantic retrieval with stale flagging
- [x] Background memory extraction after every response (Ollama → Haiku fallback)
- [x] Reflection loop on task completion
- [x] Owner tagging for errors and stale memory warnings
- [x] Message splitting for responses over 2000 characters
- [x] Status + log channel reporting

---

## What Is Pending / Known Gaps

- [ ] **Conversation history not persisted** — restarting the bot resets all per-user history
- [ ] **Ollama dependency** — background tasks degrade to Haiku if Ollama isn't running locally; no health check or startup warning
- [ ] **FFmpeg required for TTS** — must be on PATH; bot gives no warning if missing, TTS silently fails
- [ ] **"General" channel hardcoded** — `speak_response` only looks for a voice channel named exactly "General"
- [ ] **No slash commands** — all prior `/listen` and `/leave` commands were removed; bot is text/attachment only
- [ ] **Live voice capture removed** — `discord-ext-voice-recv` architecture was abandoned; no path to real-time voice channel listening
- [ ] **Memory has no size cap** — ChromaDB and SQLite will grow unbounded; no pruning or archival policy enforced automatically
- [ ] **No multi-guild isolation** — `conversation_history` is keyed by user ID only; cross-guild collisions are possible if bot is in multiple servers
- [ ] **SOUL.md loaded once at startup** — changes require bot restart
- [ ] **`mcp_servers/` directory is empty** — reserved but unused
