import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.agents import load_agents
from app.api.v1.router import router
from app.db.threads import init_threads_table
from app.db.memory_manager import (
    load_all_conversation_histories,
    load_all_goal_states,
)
import app.core.state as state
from app.features.chat.orchestrator import (
    execute_goal,
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

    # Database tables
    init_threads_table()
    logger.info("Threads table ready")

    # Restore conversation_history from the DB.
    # The orchestrator writes to the in-memory dict with a TUPLE key
    # (user_id, context_id) and persists to SQLite with a STRING key
    # "user_id:context_id". Without this load, the dict starts empty on
    # every restart and GET /threads/{id}/messages returns no history
    # even though the rows exist in the conversation_history table.
    try:
        for combined_key, hist in load_all_conversation_histories().items():
            if ":" in combined_key:
                user_part, context_part = combined_key.split(":", 1)
                state.conversation_history[(user_part, context_part)] = hist
        logger.info(
            f"Conversation history restored: "
            f"{len(state.conversation_history)} thread(s)"
        )
    except Exception as e:
        logger.warning(f"Conversation history load failed: {e}")

    # Agent definitions
    await load_agents()

    # Restore goal-mode state (pending_goals / execution_context /
    # gate_pending) so an in-flight plan survives a server restart.
    # An "executing" goal also gets a fresh execute_goal task spawned
    # to resume from the last persisted current_step — without this,
    # any goal that was mid-flight at shutdown would stay frozen in
    # the DB with no task driving it forward.
    try:
        loaded_states = load_all_goal_states()
        resumed = 0
        for uid, slices in loaded_states.items():
            if "pending_goal" in slices:
                state.pending_goals[uid] = slices["pending_goal"]
            if "execution_context" in slices:
                state.execution_context[uid] = slices["execution_context"]
            if "gate_pending" in slices:
                state.gate_pending[uid] = slices["gate_pending"]
            pg = state.pending_goals.get(uid)
            if pg and pg.get("status") == "executing":
                # The session_id stored on the pg row is the thread_id;
                # ws_manager.send falls back to a no-op if no socket is
                # currently connected for that thread, so the resumed
                # task runs cleanly regardless of whether the user is
                # actively viewing the thread.
                asyncio.create_task(
                    execute_goal(uid, "auto-resume")
                )
                resumed += 1
        logger.info(
            f"Goal state restored: {len(loaded_states)} user(s), "
            f"{resumed} auto-resumed"
        )
    except Exception as e:
        logger.warning(f"Goal state load failed: {e}")

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
    description="Persistent AI cognition system",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://notskynet.app",
        "https://www.notskynet.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")