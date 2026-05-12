import json
import logging
import os
import re as _re

from app.core.config import AGENTS_PATH, AGENT_KEYWORDS_CACHE_PATH
from app.core.model import call_background_model
import app.core.state as state

logger = logging.getLogger(__name__)


async def _load_agent_definitions():
    """
    Reads all .md files from AGENTS_PATH at startup, parses YAML frontmatter
    for name/description, and extracts keywords via the background model.
    Keywords are cached to AGENT_KEYWORDS_CACHE_PATH so the model is only
    called once per agent (or when new agents are added).
    Skips unreadable files — logs a warning, does not raise.
    """
    if not os.path.isdir(AGENTS_PATH):
        logger.info(f"Agents directory not found: {AGENTS_PATH} — skipping agent load")
        return

    # Load keyword cache from disk
    cache: dict = {}
    if os.path.exists(AGENT_KEYWORDS_CACHE_PATH):
        try:
            with open(AGENT_KEYWORDS_CACHE_PATH, "r", encoding="utf-8") as _cf:
                cache = json.load(_cf)
        except Exception:
            cache = {}

    cache_updated = False

    for filename in sorted(os.listdir(AGENTS_PATH)):
        if not filename.endswith(".md"):
            continue
        slug = filename[:-3]
        path = os.path.join(AGENTS_PATH, filename)
        try:
            with open(path, "r", encoding="utf-8") as _f:
                content = _f.read()
        except Exception as e:
            logger.warning(f"Skipping agent file {filename}: {e}")
            continue

        # Parse frontmatter for name and description
        name = slug
        description = ""
        fm_match = _re.search(r"^---\n(.*?)\n---", content, _re.DOTALL)
        if fm_match:
            fm_body = fm_match.group(1)
            name_m = _re.search(r"^name:\s*(.+)$", fm_body, _re.MULTILINE)
            if name_m:
                name = name_m.group(1).strip()
            desc_m = _re.search(r"^description:\s*(.+)$", fm_body, _re.MULTILINE)
            if desc_m:
                description = desc_m.group(1).strip()

        # Get keywords: use cache if present, otherwise extract via background model
        if slug in cache:
            keywords = cache[slug]
        else:
            try:
                kw_prompt = (
                    "Read this agent definition and return a JSON array of 15 keywords "
                    "that would indicate a user needs this agent. "
                    "Return only the JSON array, no other text.\n\n"
                    + content[:2000]
                )
                raw_kw = await call_background_model(kw_prompt)
                keywords = json.loads(
                    raw_kw.replace("```json", "").replace("```", "").strip()
                )
                if not isinstance(keywords, list):
                    keywords = []
                cache[slug] = keywords
                cache_updated = True
            except Exception as e:
                logger.warning(f"Keyword extraction failed for {slug}: {e}")
                keywords = []

        state.AGENT_DEFINITIONS[slug] = {
            "name": name,
            "slug": slug,
            "description": description,
            "content": content,
            "keywords": [str(k).lower() for k in keywords],
        }
        logger.info(f"Agent loaded: {name} ({slug})")

    if cache_updated:
        try:
            with open(AGENT_KEYWORDS_CACHE_PATH, "w", encoding="utf-8") as _cf:
                json.dump(cache, _cf, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save agent keyword cache: {e}")


async def load_agents():
    logger.info("Loading agent definitions...")
    await _load_agent_definitions()
    count = len(state.AGENT_DEFINITIONS)
    logger.info(f"Loaded {count} agent(s)")
