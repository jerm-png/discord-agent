from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import CurrentUser, require_admin
from app.db.memory_manager import (
    get_unreviewed_flags,
    mark_flag_reviewed,
)

router = APIRouter()


@router.get("/unreviewed")
async def list_unreviewed_flags(
    user: CurrentUser = Depends(require_admin),
):
    """Admin-only: list unreviewed content flags, newest first."""
    return {"flags": get_unreviewed_flags()}


@router.post("/{flag_id}/review")
async def review_flag(
    flag_id: int,
    user: CurrentUser = Depends(require_admin),
):
    """Admin-only: mark a flag as reviewed."""
    updated = mark_flag_reviewed(flag_id)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Flag not found or already reviewed.",
        )
    return {"status": "ok", "id": flag_id}
