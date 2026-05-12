import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.agents import load_agents
import app.core.state as state
from app.features.chat.orchestrator import (
    run_proactive_flag_surfacing,
    run_scheduled_consolidation,
)

logger = logging.getLogger(__name__)

LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    state.BOT_START_TIME = datetime.now(timezone.utc)

    # Langfuse observability
    try:
        if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
            from langfuse import Langfuse
            state._langfuse = Langfuse(
                secret_key=LANGFUSE_SECRET_KEY,
                public_key=LANGFUSE_PUBLIC_KEY,
                host=LANGFUSE_HOST,
            )
            logger.info("Langfuse observability active")
        else:
            logger.info("Langfuse: no keys found — tracing disabled")
    except Exception as e:
        logger.warning(f"Langfuse init failed — tracing disabled: {e}")

    # Agent definitions
    await load_agents()

    # Background tasks
    asyncio.create_task(run_proactive_flag_surfacing())
    asyncio.create_task(run_scheduled_consolidation())

    agent_count = len(state.AGENT_DEFINITIONS)
    logger.info(
        f"Drift is online | {agent_count} agent(s) loaded | "
        f"startup: {state.BOT_START_TIME.isoformat()}"
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────
    logger.info("Drift shutting down...")
    if state._langfuse:
        state._langfuse.flush()


app = FastAPI(
    title="Drift",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
