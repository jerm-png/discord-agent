# ============================================================
# model.py — Anthropic client and background model functions
# Owns the Anthropic client instance so orchestrator.py and
# bot.py can both import without circular dependencies.
# ============================================================

import asyncio
import json
import urllib.request
from anthropic import Anthropic
from config import MAIN_MODEL, BACKGROUND_MODEL, OLLAMA_URL, OLLAMA_MODEL

# ── Anthropic client ─────────────────────────────────────────
client = Anthropic()


# ── Background model functions ───────────────────────────────
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


async def call_background_model_json(
    prompt: str
) -> dict | list | None:
    """
    Like call_background_model but expects and validates
    a JSON response. Retries with Haiku if Ollama returns
    malformed JSON. Returns parsed object or None on failure.
    Never raises — always returns None on unrecoverable failure.
    """
    for _attempt, _use_haiku in enumerate([False, True]):
        try:
            if _use_haiku:
                response = client.messages.create(
                    model=BACKGROUND_MODEL,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw = response.content[0].text.strip()
            else:
                raw = await call_background_model(prompt)

            raw = raw.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)
            return parsed

        except json.JSONDecodeError:
            if _attempt == 0:
                print(
                    "[Background] Ollama returned malformed JSON "
                    "— retrying with Haiku"
                )
                continue
            print(
                "[Background] Haiku also returned malformed JSON "
                "— giving up"
            )
            return None
        except Exception as e:
            print(
                f"[Background] call_background_model_json "
                f"failed: {e}"
            )
            return None

    return None
