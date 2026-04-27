import asyncio
import discord
import os
import sys
import json
import urllib.request
import urllib.error
from discord import app_commands
import discord.ext.voice_recv as voice_recv
from dotenv import load_dotenv
from anthropic import Anthropic

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
    is_task_completion,
    set_pending_reflection,
    get_pending_reflection,
    validate_memory,
    archive_memory,
    check_stale_memories
)

from tools.tool_definitions import (
    TOOL_DEFINITIONS,
    execute_tool
)

from voice_input import WhisperSink, transcribe_utterance

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

COMMAND_CHANNEL = "bot-commands"
STATUS_CHANNEL = "bot-status"
LOG_CHANNEL = "bot-logs"

# Maximum tool calls per response to prevent runaway loops
MAX_TOOL_CALLS = 5

conversation_history = {}
_listen_task = None  # asyncio.Task for the owner voice loop
_sink = None         # WhisperSink attached to the current VoiceRecvClient

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
    user_message, bot_reply, guild, task_completed
):
    """
    Extracts anything worth storing in long term memory
    after each interaction.
    """
    try:
        extraction_prompt = f"""Review this exchange and identify anything worth storing in long term memory.

User said: {user_message}
Assistant replied: {bot_reply[:500]}
Task completed: {task_completed}

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

        for item in extracted.get("strategic", []):
            if item:
                save_strategic_memory(
                    content=item,
                    category="conversation",
                    source="auto_extraction"
                )

        for item in extracted.get("operational", []):
            if item:
                save_operational_memory(
                    content=item,
                    project_name="general"
                )

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
                task_completed=task_completed
            )

    except Exception as e:
        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"Memory extraction note: {str(e)}"
        )


async def process_user_message(
    user_message, user_id, author_display_name, guild, channel
):
    """
    Shared Claude processing pipeline used by on_message and /listen.
    Handles memory retrieval, the agentic tool loop, memory storage,
    reflection, and logging.
    """
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    task_completed = is_task_completion(user_message)

    memories = get_relevant_memories(user_message)
    memory_context = format_memory_for_prompt(memories)

    full_message = user_message
    if memory_context:
        full_message = (
            f"{memory_context}\n\n"
            f"Current message: {user_message}"
        )

    conversation_history[user_id].append({
        "role": "user",
        "content": full_message
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

            while True:
                response = client.messages.create(
                    model=MAIN_MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=conversation_history[user_id]
                )

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

            if final_response_text:
                await send_long_message(channel, final_response_text)
            else:
                await channel.send(
                    "I processed your request but had "
                    "trouble forming a response. "
                    "Check bot-logs for details."
                )

            await extract_and_store_memories(
                user_message,
                final_response_text,
                guild,
                task_completed
            )

            if task_completed:
                experiences = get_recent_experiences(
                    limit=5,
                    task_completed_only=True
                )
                await run_reflection_loop(guild, experiences)

            stale_count = len(memories.get("stale_flags", []))
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"Responded to {author_display_name} | "
                f"Model: {response.model} | "
                f"Tokens: {response.usage.input_tokens} in / "
                f"{response.usage.output_tokens} out | "
                f"Tools used: {tool_call_count} | "
                f"Task complete: {task_completed} | "
                f"Stale flags: {stale_count}"
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

        except Exception as e:
            await channel.send(
                "Something went wrong on my end. "
                "Check bot-logs for details."
            )
            await send_to_channel(
                guild,
                LOG_CHANNEL,
                f"{tag_owner()}Error for {author_display_name}: {str(e)}"
            )


async def _owner_voice_loop(guild, cmd_channel, user_id, display_name, sink):
    """Continuously transcribes and processes voice commands while owner is in channel."""
    try:
        while True:
            try:
                transcription = await transcribe_utterance(sink)
            except Exception as e:
                await cmd_channel.send(
                    f"Voice transcription failed: {str(e)}"
                )
                continue

            if not transcription:
                continue

            await cmd_channel.send(f"Heard: {transcription}")
            await process_user_message(
                transcription, user_id, display_name, guild, cmd_channel
            )

    except asyncio.CancelledError:
        pass


# ============================================================
# BOT EVENTS
# ============================================================

@bot.event
async def on_ready():
    """Runs once when the bot connects to Discord."""
    print(f"PerMyLastBot is online as {bot.user}")
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
    """Handles all incoming messages."""

    if message.author == bot.user:
        return

    if message.channel.name != COMMAND_CHANNEL:
        return

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
        message.channel
    )


@bot.event
async def on_voice_state_update(member, before, after):
    """Auto-joins owner's voice channel and runs a continuous listen loop."""
    print(f"Voice state update: {member.name} before={before.channel} after={after.channel}")
    global _listen_task, _sink

    if not OWNER_ID or str(member.id) != OWNER_ID:
        return

    guild = member.guild
    cmd_channel = discord.utils.get(guild.channels, name=COMMAND_CHANNEL)

    # Owner joined a voice channel (wasn't in one before)
    if before.channel is None and after.channel is not None:
        # Always disconnect first so we can reconnect as VoiceRecvClient
        existing = guild.voice_client
        if existing and existing.is_connected():
            await existing.disconnect()

        try:
            vc = await after.channel.connect(cls=voice_recv.VoiceRecvClient)
        except Exception as e:
            print(f"Voice connect failed: {type(e).__name__}: {e}")
            return

        _sink = WhisperSink(member.id)
        vc.listen(_sink)

        await cmd_channel.send("Listening in voice channel — speak now")

        _listen_task = asyncio.create_task(
            _owner_voice_loop(
                guild,
                cmd_channel,
                str(member.id),
                member.display_name,
                _sink
            )
        )

    # Owner left all voice channels
    elif before.channel is not None and after.channel is None:
        if _listen_task and not _listen_task.done():
            _listen_task.cancel()
        _listen_task = None
        _sink = None

        vc = guild.voice_client
        if vc and vc.is_connected():
            if isinstance(vc, voice_recv.VoiceRecvClient):
                vc.stop_listening()
            await vc.disconnect()

        await cmd_channel.send("Owner left voice channel — disconnecting.")


# ============================================================
# SLASH COMMANDS
# ============================================================

@tree.command(
    name="listen",
    description="Join your voice channel and listen for a voice command"
)
async def slash_listen(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(
            "You need to be in a voice channel first.", ephemeral=True
        )
        return

    voice_channel = interaction.user.voice.channel
    guild = interaction.guild
    cmd_channel = discord.utils.get(guild.channels, name=COMMAND_CHANNEL)

    # If the owner's continuous loop is already running, don't double-up
    if _listen_task and not _listen_task.done():
        await interaction.response.send_message(
            "Already listening via auto-join — just speak.", ephemeral=True
        )
        return

    existing = guild.voice_client
    if existing and existing.is_connected():
        await existing.disconnect()

    try:
        vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
    except Exception as e:
        await interaction.response.send_message(
            f"Could not join voice channel: {e}", ephemeral=True
        )
        return

    sink = WhisperSink(interaction.user.id)
    vc.listen(sink)

    await interaction.response.send_message(
        "Listening in voice channel — speak now"
    )

    try:
        transcription = await transcribe_utterance(sink)
    except Exception as e:
        await cmd_channel.send(f"Voice transcription failed: {str(e)}")
        return
    finally:
        vc.stop_listening()

    if not transcription:
        await cmd_channel.send(
            "I didn't catch anything — try /listen again."
        )
        return

    await cmd_channel.send(f"Heard: {transcription}")

    await process_user_message(
        transcription,
        str(interaction.user.id),
        interaction.user.display_name,
        guild,
        cmd_channel
    )


@tree.command(
    name="leave",
    description="Disconnect from the voice channel"
)
async def slash_leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message(
            "Disconnected from voice channel."
        )
    else:
        await interaction.response.send_message(
            "Not currently in a voice channel.", ephemeral=True
        )


# ============================================================
# START THE BOT
# ============================================================

bot.run(os.getenv("DISCORD_TOKEN"))