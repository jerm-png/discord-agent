import json
from anthropic import Anthropic
from app.core.config import MAIN_MODEL, BACKGROUND_MODEL, ANTHROPIC_API_KEY

# ── Anthropic client ─────────────────────────────────────────
client = Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Background model functions ───────────────────────────────
async def call_background_model(
    prompt: str, max_tokens: int = 1500
) -> str:
    response = client.messages.create(
        model=BACKGROUND_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


async def call_background_model_json(
    prompt: str,
) -> dict | list | None:
    """
    Calls Haiku and parses the JSON response.
    Returns parsed object or None on failure. Never raises.
    """
    try:
        raw = await call_background_model(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        print("[Background] Haiku returned malformed JSON")
        return None
    except Exception as e:
        print(f"[Background] call_background_model_json failed: {e}")
        return None