import json
import os
import subprocess
import sys
from datetime import datetime
from ddgs import DDGS

# Add project root to path
project_root = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))
sys.path.insert(0, project_root)

from memory.memory_manager import (
    get_relevant_memories,
    save_strategic_memory,
    save_analytical_memory,
    save_operational_memory,
    validate_memory,
    update_memory_confidence,
)

_escalation_queue: list = []


def drain_escalation_queue() -> list:
    """Return all pending escalation items and clear the queue."""
    items = list(_escalation_queue)
    _escalation_queue.clear()
    return items


# ============================================================
# TOOL DEFINITIONS
# These get sent to Claude with every request so it knows
# what tools are available and when to use them
# ============================================================

TOOL_DEFINITIONS = [
    {
        "name": "query_memory",
        "description": (
            "Search long term memory for relevant context. "
            "Use this when you need information about the user, "
            "their projects, past decisions, or learned patterns "
            "that may not be in the current conversation. "
            "Always query memory before saying you don't know "
            "something about the user or their work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to search for in memory. "
                        "Be specific — 'user communication preferences' "
                        "is better than 'user info'."
                    )
                },
                "layer": {
                    "type": "string",
                    "enum": [
                        "all",
                        "strategic",
                        "operational",
                        "analytical"
                    ],
                    "description": (
                        "Which memory layer to search. "
                        "Use 'strategic' for user values and decisions, "
                        "'operational' for active projects and tasks, "
                        "'analytical' for patterns and insights, "
                        "'all' when unsure."
                    )
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "save_skill",
        "description": (
            "Crystallise a repeated pattern into a named reusable skill. "
            "Use this when you notice a pattern that has worked well "
            "multiple times and is worth formalising for future use. "
            "Skills are higher confidence than raw analytical memories — "
            "only save something as a skill when you are genuinely "
            "confident it applies broadly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        "Short descriptive name for the skill. "
                        "Example: 'concise_technical_explanation' or "
                        "'decision_framework_for_architecture_choices'"
                    )
                },
                "description": {
                    "type": "string",
                    "description": (
                        "What this skill does and when to apply it."
                    )
                },
                "trigger_conditions": {
                    "type": "string",
                    "description": (
                        "Specific conditions that should trigger "
                        "use of this skill in future conversations."
                    )
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Confidence level from 0.0 to 1.0. "
                        "Only save skills you are at least 0.7 confident in."
                    )
                }
            },
            "required": [
                "skill_name",
                "description",
                "trigger_conditions",
                "confidence"
            ]
        }
    },
    {
        "name": "update_user_model",
        "description": (
            "Update what you know about the user deliberately. "
            "Use this when the user shares something important "
            "about themselves, their preferences, goals, or working style "
            "that should be remembered permanently. "
            "Also use this to fill identified gaps in your user model."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "communication_style",
                        "technical_preferences",
                        "goals",
                        "working_style",
                        "values",
                        "background",
                        "constraints",
                        "general"
                    ],
                    "description": "Category of user information."
                },
                "content": {
                    "type": "string",
                    "description": (
                        "What you learned about the user. "
                        "Be specific and factual."
                    )
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "How confident you are in this observation "
                        "from 0.0 to 1.0."
                    )
                }
            },
            "required": ["category", "content", "confidence"]
        }
    },
    {
        "name": "flag_for_review",
        "description": (
            "Flag something for deeper processing or future review. "
            "Use this when you notice something that needs more thought, "
            "when you are uncertain about something important, "
            "or when you want to revisit a topic in a future session. "
            "This is your self-nudging mechanism — use it proactively."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What needs to be reviewed."
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why this needs review. "
                        "What is uncertain or incomplete."
                    )
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "How urgently this needs attention."
                }
            },
            "required": ["topic", "reason", "priority"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for current information. "
            "Use this when the user asks about recent events, "
            "current data, or anything that may have changed "
            "since your training cutoff. "
            "Always tell the user what you are searching for and why. "
            "Summarise results rather than dumping raw text. "
            "Always cite the source of information found. "
            "Maximum 3 searches per response."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The search query. "
                        "Be specific — 3 to 6 words works best. "
                        "Do not include site: operators or quotes."
                    )
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        "Number of results to return. "
                        "Default 3, maximum 5."
                    )
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_codebase",
        "description": (
            "Search the PerMyLastBot codebase for relevant functions, "
            "constants, or code sections by semantic query. Use this when "
            "you need to see how something is currently implemented before "
            "suggesting changes or additions. Returns exact code sections "
            "with file paths and line numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to search for — function name, concept, or "
                        "description of what you need to see. Examples: "
                        "'memory isolation health-tracking', "
                        "'execute_goal analyze step', "
                        "'channel routing logic'"
                    )
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Number of results to return. Default 5, max 10."
                    ),
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "calculate_confidence",
        "description": (
            "Update the confidence score of an existing memory "
            "based on new evidence. Use this when new information "
            "confirms or contradicts something already stored. "
            "This keeps the memory system self-calibrating over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "integer",
                    "description": "The ID of the memory to update."
                },
                "layer": {
                    "type": "string",
                    "enum": [
                        "strategic",
                        "operational",
                        "analytical"
                    ],
                    "description": "Which layer the memory is in."
                },
                "direction": {
                    "type": "string",
                    "enum": ["increase", "decrease"],
                    "description": (
                        "Whether new evidence supports "
                        "or contradicts this memory."
                    )
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why you are updating this confidence score."
                    )
                }
            },
            "required": [
                "memory_id",
                "layer",
                "direction",
                "reason"
            ]
        }
    }
]


# ============================================================
# TOOL HANDLERS
# These are the functions that actually execute when
# Claude decides to call a tool
# ============================================================

_LAYER_LABELS = {
    "strategic": "Strategic",
    "operational": "Operational",
    "analytical": "Analytical",
}


def handle_query_memory(inputs, channel_name=None):
    """
    Searches memory semantically and returns
    relevant context for Claude to use.
    """
    query = inputs.get("query", "")
    layer = inputs.get("layer", "all")

    memories = get_relevant_memories(
        query, max_results=5, channel_name=channel_name
    )

    if layer != "all":
        memories = {layer: memories.get(layer, [])}

    sections = []
    for key, label in _LAYER_LABELS.items():
        items = memories.get(key)
        if items:
            formatted = "\n".join(f"- {m}" for m in items)
            sections.append(f"{label}:\n{formatted}")

    if not sections:
        return "No relevant memories found for that query."

    return "\n\n".join(sections)


def handle_save_skill(inputs):
    """
    Saves a crystallised skill to the analytical
    memory layer with high confidence weighting.
    """
    skill_name = inputs.get("skill_name", "")
    description = inputs.get("description", "")
    trigger_conditions = inputs.get("trigger_conditions", "")
    confidence = float(inputs.get("confidence", 0.7))

    if confidence < 0.7:
        return (
            "Skill not saved — confidence below 0.7 threshold. "
            "Only save skills you are genuinely confident in."
        )

    skill_content = (
        f"SKILL: {skill_name} | "
        f"Description: {description} | "
        f"Apply when: {trigger_conditions}"
    )

    save_analytical_memory(
        pattern=skill_content,
        observation=f"Skill crystallised from repeated patterns",
        reasoning=f"Pattern observed with sufficient confidence",
        outcome="positive",
        confidence=confidence,
        trigger_conditions=trigger_conditions,
        pattern_type="crystallised_skill"
    )

    return (
        f"Skill '{skill_name}' saved with confidence "
        f"{confidence}. Trigger: {trigger_conditions}"
    )


def handle_update_user_model(inputs):
    """
    Updates the strategic memory layer with
    new information about the user.
    """
    category = inputs.get("category", "general")
    content = inputs.get("content", "")
    confidence = float(inputs.get("confidence", 0.8))

    save_strategic_memory(
        content=content,
        category=f"user_model_{category}",
        confidence=confidence,
        source="active_user_modelling"
    )

    return (
        f"User model updated — category: {category} | "
        f"confidence: {confidence} | content: {content[:100]}"
    )


def handle_flag_for_review(inputs, channel_name: str = 'global'):
    """
    Saves a flag to the operational layer for
    future review. This is the self-nudging mechanism.
    """
    topic = inputs.get("topic", "")
    reason = inputs.get("reason", "")
    priority = inputs.get("priority", "medium")

    content = (
        f"REVIEW FLAG [{priority.upper()}]: {topic} | "
        f"Reason: {reason} | "
        f"Flagged: {datetime.now().strftime('%Y-%m-%d')}"
    )

    save_operational_memory(
        content=content,
        project_name="review_flags",
        priority=priority,
        channel_name=channel_name
    )

    if priority == "high" and channel_name and channel_name != "chief-of-staff":
        _escalation_queue.append({
            "topic": topic,
            "reason": reason,
            "source_channel": channel_name
        })

    return (
        f"Flagged for review — topic: {topic} | "
        f"priority: {priority}"
    )


def handle_web_search(inputs):
    """
    Searches the web using DuckDuckGo and returns
    summarised results with sources cited.
    Capped at 5 results maximum.
    """
    query = inputs.get("query", "")
    max_results = min(int(inputs.get("max_results", 3)), 5)

    try:
        with DDGS(timeout=10) as ddgs:
            raw_results = list(ddgs.text(
                query,
                max_results=max_results
            ))

        if not raw_results:
            return f"No results found for: {query}"

        formatted = f"Search results for '{query}':\n\n"

        for i, result in enumerate(raw_results, 1):
            title = result.get("title", "No title")
            url = result.get("href", "No URL")
            snippet = result.get("body", "No description")

            formatted += (
                f"{i}. {title}\n"
                f"   Source: {url}\n"
                f"   {snippet[:200]}\n\n"
            )

        return formatted

    except Exception as e:
        return "Web search unavailable — answering from training knowledge."


def handle_search_codebase(inputs):
    """
    Runs a semantic codebase search via CocoIndex-Code CLI and returns
    matching code sections with file paths and line numbers.
    """
    query = inputs.get("query", "")
    limit = min(inputs.get("limit", 5), 10)
    if not query.strip():
        return "Error: query cannot be empty"
    try:
        result = subprocess.run(
            [
                r"C:\Users\Jerm\.local\bin\ccc.exe",
                "search", query,
                "--limit", str(limit)
            ],
            capture_output=True,
            text=True,
            cwd=r"C:\Projects\discord-agent",
            env=os.environ.copy(),
            timeout=15
        )
        if result.returncode != 0:
            return f"Search failed: {result.stderr[:200]}"
        output = result.stdout.strip()
        if not output:
            return "No results found for that query."
        return output
    except subprocess.TimeoutExpired:
        return "Search timed out after 15 seconds."
    except Exception as e:
        return f"Search error: {str(e)}"


def handle_calculate_confidence(inputs):
    """
    Updates the confidence score of an existing memory
    up or down based on new evidence.
    """
    memory_id = inputs.get("memory_id")
    layer = inputs.get("layer", "strategic")
    direction = inputs.get("direction", "increase")
    reason = inputs.get("reason", "")

    result = update_memory_confidence(layer, memory_id, direction)

    if result is None:
        return f"Memory ID {memory_id} not found in {layer} layer."

    old, new = result
    return (
        f"Confidence updated — memory {memory_id} in "
        f"{layer} layer: {old:.1f} → {new:.1f} | Reason: {reason}"
    )


# ============================================================
# TOOL ROUTER
# Single function that routes tool calls to the right handler
# ============================================================

def execute_tool(tool_name, tool_inputs, channel_name=None):
    """
    Routes a tool call from Claude to the correct handler.
    Returns the result as a string for Claude to use.
    """
    if not tool_name:
        return "Unknown tool: (empty)"

    try:
        if tool_name == "query_memory":
            return handle_query_memory(tool_inputs, channel_name=channel_name)
        if tool_name == "save_skill":
            return handle_save_skill(tool_inputs)
        if tool_name == "update_user_model":
            return handle_update_user_model(tool_inputs)
        if tool_name == "flag_for_review":
            return handle_flag_for_review(tool_inputs, channel_name=channel_name)
        if tool_name == "web_search":
            return handle_web_search(tool_inputs)
        if tool_name == "search_codebase":
            return handle_search_codebase(tool_inputs)
        if tool_name == "calculate_confidence":
            return handle_calculate_confidence(tool_inputs)
        return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool '{tool_name}' encountered an error — continue without this information."