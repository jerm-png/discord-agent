import json
import os
import subprocess
import sys
from datetime import datetime
from ddgs import DDGS
import requests

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

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
    upsert_entity,
    add_entity_fact,
    get_entity_profile,
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
        "name": "web_fetch",
        "description": (
            "Fetch and read the full content of a specific URL. "
            "Use this after web_search returns promising URLs to read "
            "complete content such as GitHub READMEs, HuggingFace model "
            "cards, documentation, blog posts, and research papers. "
            "Returns plain text stripped of HTML. Always use web_search "
            "first to find URLs, then web_fetch to read them fully. "
            "In health-tracking channel, prefer PubMed, NIH, and clinical "
            "sources over general web content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "The full URL to fetch including https://"
                    )
                },
                "max_chars": {
                    "type": "integer",
                    "description": (
                        "Maximum characters to return. "
                        "Default 5000, max 10000."
                    ),
                    "default": 5000
                }
            },
            "required": ["url"]
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
    },
    {
        "name": "save_person_fact",
        "description": (
            "Save a fact about a specific person to their entity "
            "profile in director-workspace. Use when the user shares "
            "new information about a direct report or colleague — "
            "performance updates, coaching outcomes, development "
            "goals, behavioral patterns, feedback given or received, "
            "role changes, or situation updates. "
            "Set supersede_category=true when the new fact replaces "
            "an outdated one in the same category (e.g. a performance "
            "rating changed, a goal was updated, a situation resolved). "
            "Categories to use: performance, coaching, development, "
            "feedback, goals, situation, role, pattern, notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_name": {
                    "type": "string",
                    "description": "Full name or common name of the person"
                },
                "role": {
                    "type": "string",
                    "description": (
                        "Their role or title if known — "
                        "only needed first time"
                    )
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Fact category: performance, coaching, "
                        "development, feedback, goals, situation, "
                        "role, pattern, or notes"
                    )
                },
                "fact": {
                    "type": "string",
                    "description": (
                        "The fact to record — be specific and "
                        "include relevant dates or context. "
                        "Write in third person: "
                        "'Marcus missed his Q2 call quality target "
                        "for the second consecutive quarter.'"
                    )
                },
                "supersede_category": {
                    "type": "boolean",
                    "description": (
                        "If true, marks all previous active facts "
                        "in this category as superseded by this one. "
                        "Use when the new fact replaces old information "
                        "rather than adding to it."
                    )
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Confidence in this fact 0.0-1.0. "
                        "Default 0.8. Use lower values for "
                        "secondhand information or impressions."
                    )
                }
            },
            "required": ["person_name", "category", "fact"]
        }
    },
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


def _search_serper(query: str, num_results: int = 5) -> list:
    """
    Searches Google via Serper API.
    Returns list of dicts with keys: title, link, snippet.
    Returns empty list if API key missing or request fails.
    """
    if not SERPER_API_KEY:
        return []
    try:
        import urllib.request
        payload = json.dumps({
            "q": query,
            "num": num_results
        }).encode()
        req = urllib.request.Request(
            "https://google.serper.dev/search",
            data=payload,
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for item in data.get("organic", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
    except Exception as e:
        print(f"[Serper] Search failed: {e}")
        return []


def handle_web_search(inputs):
    """
    Searches the web using DuckDuckGo and returns
    summarised results with sources cited.
    Capped at 5 results maximum.
    """
    query = inputs.get("query", "")
    max_results = min(int(inputs.get("max_results", 3)), 5)

    raw_results = []
    _ddg_failed = False
    try:
        with DDGS(timeout=10) as ddgs:
            raw_results = list(ddgs.text(
                query,
                max_results=max_results
            ))
    except Exception as _ddg_err:
        print(f"[Search] DuckDuckGo failed: {_ddg_err}")
        _ddg_failed = True

    # Fall back to Serper if DDG failed or returned nothing
    _used_serper = False
    if not raw_results:
        _serper_results = _search_serper(query, num_results=max_results)
        if _serper_results:
            _used_serper = True
            for r in _serper_results:
                raw_results.append({
                    "title": r["title"],
                    "href": r["link"],
                    "body": r["snippet"],
                })

    if not raw_results:
        return "No search results found. Both DuckDuckGo and Serper returned nothing."

    _source_note = "[Source: Google via Serper]\n" if _used_serper else ""
    formatted = _source_note + f"Search results for '{query}':\n\n"

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


def handle_web_fetch(inputs):
    """
    Fetches a URL and returns its plain-text content with HTML stripped.
    Blocks local network addresses. Capped at 10000 chars.
    """
    url = inputs.get("url", "").strip()
    max_chars = min(inputs.get("max_chars", 5000), 10000)

    if not url.startswith("http"):
        return "Error: URL must start with http:// or https://"

    blocked = ["localhost", "127.0.0.1", "192.168.", "10.0.", "172.16."]
    if any(b in url for b in blocked):
        return "Error: Local network URLs not allowed"

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PerMyLastBot/1.0; +research)"
            )
        }
        response = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )
        response.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer",
                         "header", "aside", "form", "noscript"]):
            tag.decompose()

        # Keep only content-bearing elements
        content_tags = soup.find_all(
            ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "code"]
        )

        # Build compressed text from content tags only
        lines = []
        for tag in content_tags:
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 30:  # skip trivially short fragments
                lines.append(text)

        compressed = "\n".join(lines)

        # Relevance filter — if a query context is available in inputs,
        # prioritise lines that contain query keywords
        query_hint = inputs.get("query") or inputs.get("url", "")
        if query_hint and len(compressed) > 4000:
            keywords = [
                w.lower() for w in query_hint.replace("/", " ")
                .replace("-", " ").split()
                if len(w) > 3
            ]
            if keywords:
                scored = []
                for line in lines:
                    line_lower = line.lower()
                    score = sum(1 for kw in keywords if kw in line_lower)
                    scored.append((score, line))
                # Keep all lines with any keyword match, then fill to cap
                priority = [l for s, l in scored if s > 0]
                remainder = [l for s, l in scored if s == 0]
                compressed = "\n".join(priority + remainder)

        # Hard cap at 4000 chars by default
        char_limit = int(inputs.get("char_limit", 4000))
        char_limit = min(char_limit, 10000)  # never exceed original max
        if len(compressed) > char_limit:
            compressed = compressed[:char_limit] + "\n[Content truncated]"

        if not compressed.strip():
            return "No readable content found at that URL."

        return f"[{url}]\n{compressed}"

    except requests.exceptions.Timeout:
        return f"Timeout fetching {url} after 15s."
    except requests.exceptions.ConnectionError:
        return f"Could not connect to {url}."
    except requests.exceptions.HTTPError as e:
        return f"HTTP error {e.response.status_code} fetching {url}."
    except Exception as e:
        return f"Error fetching {url}: {str(e)}"


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
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [
                r"C:\Users\Jerm\.local\bin\ccc.exe",
                "search", query,
                "--limit", str(limit)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=r"C:\Projects\discord-agent",
            env=env,
            timeout=15
        )
        output = result.stdout.decode('utf-8', errors='replace').strip()
        stderr = result.stderr.decode('utf-8', errors='replace').strip()
        if result.returncode != 0:
            return f"Search failed: {stderr[:200]}"
        if not output:
            return "No results found for that query."
        if len(output) > 3000:
            output = output[:3000] + "\n[Results truncated at 3000 chars to reduce token cost. Use a more specific query to narrow results.]"
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
        if tool_name == "web_fetch":
            return handle_web_fetch(tool_inputs)
        if tool_name == "search_codebase":
            return handle_search_codebase(tool_inputs)
        if tool_name == "calculate_confidence":
            return handle_calculate_confidence(tool_inputs)
        elif tool_name == "save_person_fact":
            person_name = tool_inputs.get("person_name", "").strip()
            role = tool_inputs.get("role")
            category = tool_inputs.get("category", "notes").strip().lower()
            fact = tool_inputs.get("fact", "").strip()
            supersede = tool_inputs.get("supersede_category", False)
            confidence = float(tool_inputs.get("confidence", 0.8))

            if not person_name or not fact:
                return "Error: person_name and fact are required."

            valid_categories = {
                "performance", "coaching", "development",
                "feedback", "goals", "situation", "role",
                "pattern", "notes"
            }
            if category not in valid_categories:
                category = "notes"

            try:
                entity_id = upsert_entity(
                    person_name, "person", role, None
                )
                fact_id = add_entity_fact(
                    entity_id,
                    category,
                    fact,
                    channel_name or "director-workspace",
                    confidence,
                    supersede,
                )
                supersede_note = (
                    " Previous facts in this category marked superseded."
                    if supersede else ""
                )
                return (
                    f"Saved [{category}] fact for {person_name} "
                    f"(fact_id: {fact_id}).{supersede_note}"
                )
            except Exception as e:
                return f"Error saving person fact: {e}"
        return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool '{tool_name}' encountered an error — continue without this information."