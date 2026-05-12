from fastapi import APIRouter, Depends
from app.core.auth import require_auth
from app.core.config import WORKSPACES

router = APIRouter()

@router.get("")
async def list_workspaces(
    user: str = Depends(require_auth)
):
    """
    List all workspaces with their configuration.
    This is what the frontend sidebar loads on login.
    """
    return {
        "workspaces": [
            {
                "slug": slug,
                "label": config["label"],
                "memory_mode": config["memory_mode"],
                "isolated": config.get(
                    "isolated", False
                ),
                "entity_memory": config.get(
                    "entity_memory", False
                ),
            }
            for slug, config in WORKSPACES.items()
        ]
    }
