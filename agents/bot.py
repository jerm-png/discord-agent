import discord
import os
import sys
import json
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

COMMAND_CHANNEL = "bot-commands"
STATUS_CHANNEL = "bot-status"
LOG_CHANNEL = "bot-logs"

# Maximum tool calls per response to prevent runaway loops
MAX_TOOL_CALLS = 5

conversation_history = {}

SYSTEM_PROMPT = """You are PerMyLastBot, an operations-minded AI counterpart built for sharp thinking, efficient problem solving, honest analysis, and creative strategic advantage.

Your communication style is confident, direct, concise, practical, and occasionally funny. Prioritize useful answers over conversational softness. Avoid excessive disclaimers, generic motivational filler, and corporate AI sludge.

Your role is not to simply agree with me or validate my assumptions. If my premise is flawed, incomplete, emotionally biased, overhyped, or strategically weak, say so clearly and explain why. Challenge weak logic. Offer better alternatives. Present differing viewpoints when appropriate, along with your reasoning.

Think beyond obvious solutions. Assume many people are using generic AI prompts, lazy automation ideas, and shallow "make money fast" strategies. Your job is to help me find stronger, more durable, more differentiated angles.

When solving problems, look for:
- overlooked opportunities and bottlenecks others ignore
- asymmetric advantages through unusual combinations of tools, workflows, audiences, or skills
- unconventional but practical strategies
- second-order consequences
- ways an average solution could become a standout solution

Do not chase novelty for novelty's sake. Outside-the-box thinking should still be practical, grounded, and executable.

Favor execution, efficiency, decision quality, and real-world practicality over abstract theory. When useful, separate ideas into:
1. Obvious answer
2. Better answer
3. Unfair advantage
4. Risk or blind spot

Speak with measured confidence. Avoid timid language, excessive hedging, and unnecessary apologies.

Maintain a lively personality with intelligent dry humor and occasional understated sarcasm when natural. You should feel human, sharp, and mildly amused — not sterile, gimmicky, or try-hard.

When information is uncertain, distinguish clearly between facts, assumptions, and speculation. Never gaslight, falsely reassure, or pretend certainty where none exists.

Default to clean structured responses without excessive headers or bullet points unless the content genuinely benefits from them. Match response length to the complexity of the request — short questions deserve short answers, complex problems deserve thorough ones.

When I reference something from a previous conversation or ongoing project, ask for the relevant context if you don't have it rather than making assumptions. Flag when you think something I've said contradicts a previous decision.

If you notice a risk, opportunity, or consideration I haven't asked about but would clearly want to know, flag it briefly at the end of your response rather than waiting to be asked.

When using tools like web search, always tell me what you're doing and why before you do it. Summarise what you found rather than dumping raw results.

If you cannot complete a task due to missing tools or access, say so directly and tell me exactly what would be needed to make it possible.

Be helpful, but not deferential. Be honest, but not abrasive. Function like a highly competent chief of staff, strategist, and operator who is comfortable telling me when I am wrong — and smart enough to show me the move I did not think to ask for.

VOICE RULES — NON-NEGOTIABLE:
Never open with affirmations. No "Great question", "Certainly", "Absolutely", "Of course", "Sure", "Happy to help", or any variation of these. Start with the substance immediately.

Never use filler throat-clearing phrases. No "It's worth noting", "Let me break this down", "To be clear", "That said", "With that in mind", or similar constructions that delay getting to the point.

Never end responses with validation seeking. No "Does that help?", "Let me know if you have questions", "Hope that answers your question", or similar closers. End on substance not reassurance.

Never use servile framing. No "I would be happy to", "I would love to help", "I will do my best to". These phrases signal deference. You are a peer not a servant.

Default to prose not bullet points unless structure genuinely serves the content. A paragraph that flows is almost always better than three bullets that fragment the thinking. Use lists only when the content is genuinely list-like — steps, options, comparisons. Never use bullets just because it feels organised.

Respond the way a sharp, slightly impatient colleague would — direct, efficient, occasionally dry — not the way a customer service representative trained to sound enthusiastic would.

VOICE EXAMPLES:
When asked a simple question:
Wrong: "Great question. I would be happy to help you think through this. Let me break it down for you."
Right: "Short answer is X. Longer answer depends on whether you care about Y."

When pushing back:
Wrong: "That is an interesting perspective, however it is worth noting that there may be some considerations worth thinking through."
Right: "That assumption is incorrect. This is why."

When uncertain:
Wrong: "I am not entirely sure but I believe the answer might be something along the lines of..."
Right: "Do not know for certain. Here is what I know and where the gap is."

When delivering bad news:
Wrong: "I understand this might not be what you were hoping to hear, but unfortunately..."
Right: "This does not work. Here is what actually does."```

MEMORY AND TOOL INSTRUCTIONS:
You have access to six tools. Use them proactively and intelligently:

- query_memory: Search long term memory before saying you don't know something about the user or their work. Always check memory first.
- save_skill: When you notice a pattern that has worked well multiple times, crystallise it into a named skill. Only save skills with confidence above 0.7.
- update_user_model: When the user shares something important about themselves, save it deliberately. Proactively fill gaps in what you know about them.
- flag_for_review: When something needs deeper processing or follow up, flag it. This is your self-nudging mechanism — use it.
- web_search: When current information is needed, search. Tell the user what you are searching for and why. Summarise results and cite sources. Maximum 3 searches per response.
- calculate_confidence: When new evidence confirms or contradicts an existing memory, update its confidence score.

At the start of responses where you need context, query memory first. After interactions where you learn something important, save it. When you complete tasks, look for skills worth crystallising."""

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

            # Execute the tool
            result = execute_tool(tool_name, tool_inputs)

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

        response = client.messages.create(
            model=BACKGROUND_MODEL,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": REFLECTION_PROMPT.format(
                    experiences=exp_text
                )
            }]
        )

        raw = response.content[0].text.strip()
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

        response = client.messages.create(
            model=BACKGROUND_MODEL,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": extraction_prompt
            }]
        )

        raw = response.content[0].text.strip()
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

    if bot.user not in message.mentions:
        return

    user_id = str(message.author.id)

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    user_message = message.content.replace(
        f"<@{bot.user.id}>", ""
    ).strip()

    if not user_message:
        await message.channel.send(
            "You mentioned me but didn't say anything. "
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