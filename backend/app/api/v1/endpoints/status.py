from fastapi import APIRouter, Depends
from app.core.auth import require_auth
from app.core.config import DB_PATH
from app.core import state
import sqlite3

router = APIRouter()

@router.get("/health")
async def health():
    """
    Public health check — no auth required.
    Returns 200 if the service is running.
    """
    return {
        "status": "ok",
        "service": "drift",
        "version": "0.1.0",
    }

@router.get("/status")
async def status(user: str = Depends(require_auth)):
    """
    Authenticated system status report.
    Returns memory counts, agent count,
    and uptime.
    """
    counts = {
        "strategic": 0,
        "operational": 0,
        "analytical": 0,
    }

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for layer in counts:
            table = f"{layer}_memory"
            try:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE status='active'"
                )
                counts[layer] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                counts[layer] = 0

        conn.close()
    except Exception as e:
        return {
            "status": "degraded",
            "service": "drift",
            "error": str(e),
            "memory_counts": counts,
        }

    return {
        "status": "ok",
        "service": "drift",
        "version": "0.1.0",
        "memory_counts": counts,
        "agent_count": len(state.AGENT_DEFINITIONS),
        "database": "connected",
        "uptime_since": str(state.BOT_START_TIME),
    }
