import asyncio
import discord
import os
import sys
import json
import urllib.request
import urllib.error
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

COMMAND_CHANNEL = "bot-commands"
STATUS_CHANNEL = "bot-status"
LOG_CHANNEL = "bot-logs"

# Maximum tool calls per response to prevent runaway loops
MAX_TOOL_CALLS = 5

conversation_history = {}

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

bot = discord.Client(intents=intents)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

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

        await send_to_channel(
            guild,
            STATUS_CHANNEL,
            f"Reflection complete — "
            f"{stored_analytical} analytical and "
            f"{stored_strategic} strategic insights stored."
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


# ============================================================
# BOT EVENTS
# ============================================================

@bot.event
async def on_ready():
    """Runs once when the bot connects to Discord."""
    print(f"PerMyLastBot is online as {bot.user}")

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

    user_id = str(message.author.id)

    if user_id not in conversation_history:
        conversation_history[user_id] = []

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

    # ── TASK COMPLETION DETECTION ─────────────────────────
    task_completed = is_task_completion(user_message)

    # ── MEMORY RETRIEVAL ──────────────────────────────────
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
        message.guild,
        STATUS_CHANNEL,
        f"Processing request from "
        f"{message.author.display_name}..."
    )

    async with message.channel.typing():
        try:
            tool_call_count = 0
            final_response_text = ""

            # ── AGENTIC TOOL LOOP ─────────────────────────
            # Keep sending to Claude until it stops
            # calling tools and gives a final response
            while True:

                response = client.messages.create(
                    model=MAIN_MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=conversation_history[user_id]
                )

                # Check if Claude wants to use a tool
                if response.stop_reason == "tool_use":

                    # Add Claude's response to history
                    conversation_history[user_id].append({
                        "role": "assistant",
                        "content": response.content
                    })

                    # Process all tool calls in this response
                    tool_results, tool_call_count = \
                        await process_tool_calls(
                            response,
                            message.guild,
                            tool_call_count
                        )

                    # Add tool results to history so
                    # Claude can use them in next response
                    conversation_history[user_id].append({
                        "role": "user",
                        "content": tool_results
                    })

                    # Continue the loop — Claude will
                    # either use another tool or respond
                    continue

                # Claude is done with tools — get final text
                for block in response.content:
                    if hasattr(block, "text"):
                        final_response_text += block.text

                # Add final response to history
                conversation_history[user_id].append({
                    "role": "assistant",
                    "content": final_response_text
                })

                # Exit the tool loop
                break

            # Send final response to Discord
            if final_response_text:
                await send_long_message(
                    message.channel,
                    final_response_text
                )
            else:
                await message.channel.send(
                    "I processed your request but had "
                    "trouble forming a response. "
                    "Check bot-logs for details."
                )

            # ── MEMORY STORAGE ────────────────────────────
            await extract_and_store_memories(
                user_message,
                final_response_text,
                message.guild,
                task_completed
            )

            # ── REFLECTION TRIGGER ────────────────────────
            if task_completed:
                experiences = get_recent_experiences(
                    limit=5,
                    task_completed_only=True
                )
                await run_reflection_loop(
                    message.guild,
                    experiences
                )

            # ── LOGGING ───────────────────────────────────
            stale_count = len(
                memories.get("stale_flags", [])
            )
            await send_to_channel(
                message.guild,
                LOG_CHANNEL,
                f"Responded to "
                f"{message.author.display_name} | "
                f"Model: {response.model} | "
                f"Tokens: {response.usage.input_tokens} in / "
                f"{response.usage.output_tokens} out | "
                f"Tools used: {tool_call_count} | "
                f"Task complete: {task_completed} | "
                f"Stale flags: {stale_count}"
            )

            await send_to_channel(
                message.guild,
                STATUS_CHANNEL,
                f"Response delivered to "
                f"{message.author.display_name}. Ready."
            )

        except Exception as e:
            await message.channel.send(
                "Something went wrong on my end. "
                "Check bot-logs for details."
            )
            await send_to_channel(
                message.guild,
                LOG_CHANNEL,
                f"Error for "
                f"{message.author.display_name}: {str(e)}"
            )


# ============================================================
# START THE BOT
# ============================================================

bot.run(os.getenv("DISCORD_TOKEN"))