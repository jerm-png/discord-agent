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

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    '.env'
))

client = Anthropic()

COMMAND_CHANNEL = "bot-commands"
STATUS_CHANNEL = "bot-status"
LOG_CHANNEL = "bot-logs"

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

MEMORY INSTRUCTIONS:
You have access to a three layer memory system. At the start of each response you will receive relevant memories under MEMORY CONTEXT. Use this to:
- Reference past decisions and check if they are still current
- Apply patterns and insights from previous interactions
- Stay aware of active projects and their status
- Flag stale memories that need validation by asking the user directly before using them

When you see MEMORIES NEEDING VALIDATION — always ask the user to confirm before using that information. Never silently assume stale memories are still accurate.

When a task feels complete based on the user's response, acknowledge it naturally. The system will handle reflection automatically."""

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


async def run_reflection_loop(guild, experiences):
    """
    Runs when a task completion is detected.
    Reviews completed task experiences and extracts
    structured six part analytical insights.
    """
    try:
        await send_to_channel(
            guild,
            STATUS_CHANNEL,
            "🔄 Task complete — running reflection loop..."
        )

        if not experiences:
            await send_to_channel(
                guild,
                STATUS_CHANNEL,
                "💭 Reflection skipped — "
                "no completed experiences yet."
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
            model="claude-haiku-4-5-20251001",
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
                    observation=insight.get(
                        "observation", ""
                    ),
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

        for insight in reflection.get(
            "strategic_insights", []
        ):
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
            f"✅ Reflection complete — "
            f"{stored_analytical} analytical insights and "
            f"{stored_strategic} strategic insights stored."
        )

        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"🔄 Reflection loop | "
            f"Summary: {reflection.get('summary', 'None')}"
        )

    except Exception as e:
        set_pending_reflection(False)
        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"❌ Reflection loop error: {str(e)}"
        )


async def extract_and_store_memories(
    user_message, bot_reply, guild, task_completed
):
    """
    Extracts anything worth storing in long term memory
    and saves it to the appropriate layer automatically.
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
            model="claude-haiku-4-5-20251001",
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
                approach_used=exp.get(
                    "approach_used", ""
                ),
                outcome=exp.get("outcome", "neutral"),
                lesson=exp.get("lesson", ""),
                layers_used=list(extracted.keys()),
                task_completed=task_completed
            )

    except Exception as e:
        await send_to_channel(
            guild,
            LOG_CHANNEL,
            f"⚠️ Memory extraction note: {str(e)}"
        )


# ============================================================
# BOT EVENTS
# ============================================================

@bot.event
async def on_ready():
    """Runs once when the bot connects to Discord."""
    print(f"✅ PerMyLastBot is online as {bot.user}")

    for guild in bot.guilds:
        await send_to_channel(
            guild,
            STATUS_CHANNEL,
            "✅ PerMyLastBot is online — "
            "memory system active, reflection loops ready."
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
        f"⚙️ Processing request from "
        f"{message.author.display_name}..."
    )

    async with message.channel.typing():
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=conversation_history[user_id]
            )

            bot_reply = response.content[0].text

            conversation_history[user_id].append({
                "role": "assistant",
                "content": bot_reply
            })

            await send_long_message(message.channel, bot_reply)

            # ── MEMORY STORAGE ────────────────────────────
            await extract_and_store_memories(
                user_message,
                bot_reply,
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
                f"✅ Responded to "
                f"{message.author.display_name} | "
                f"Model: {response.model} | "
                f"Tokens: {response.usage.input_tokens} in / "
                f"{response.usage.output_tokens} out | "
                f"Task complete: {task_completed} | "
                f"Stale flags: {stale_count}"
            )

            await send_to_channel(
                message.guild,
                STATUS_CHANNEL,
                f"✅ Response delivered to "
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
                f"❌ Error for "
                f"{message.author.display_name}: {str(e)}"
            )


# ============================================================
# START THE BOT
# ============================================================

bot.run(os.getenv("DISCORD_TOKEN"))