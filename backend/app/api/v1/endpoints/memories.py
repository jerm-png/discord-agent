from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import CurrentUser, require_admin
from app.db.memory_manager import (
    archive_memory,
    list_active_memories,
    toggle_memory_pin,
    validate_memory,
)

router = APIRouter()

_VALID_LAYERS = {"strategic", "operational", "analytical"}


@router.get("")
@router.get("/")
async def list_memories(
    layer: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    status: str | None = Query(
        None, description="Filter by computed status: stale | pinned"
    ),
    user: CurrentUser = Depends(require_admin),
):
    """
    Returns active memories across all three layers (or one, when
    `layer` is set). Each row includes the server-computed `stale` flag
    so the client doesn't reimplement the deadline math.
    """
    if layer is not None and layer not in _VALID_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid layer. Must be one of: {sorted(_VALID_LAYERS)}",
        )
    if status is not None and status not in ("stale", "pinned"):
        raise HTTPException(
            status_code=400,
            detail="Invalid status filter. Must be 'stale' or 'pinned'.",
        )
    memories = list_active_memories(
        layer=layer,
        search=search.strip() if search else None,
        status_filter=status,
    )
    return {"memories": memories, "count": len(memories)}


@router.post("/{layer}/{memory_id}/confirm")
async def confirm_memory(
    layer: str,
    memory_id: int,
    user: CurrentUser = Depends(require_admin),
):
    """Refreshes the layer's timestamp column (last_confirmed /
    last_updated / last_observed) to now and bumps times_referenced."""
    if layer not in _VALID_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid layer. Must be one of: {sorted(_VALID_LAYERS)}",
        )
    validate_memory(layer, memory_id)
    return {"status": "ok", "id": memory_id, "layer": layer}


@router.post("/{layer}/{memory_id}/pin")
async def toggle_pin(
    layer: str,
    memory_id: int,
    user: CurrentUser = Depends(require_admin),
):
    """Toggles the pinned bit on the row. Returns the new state."""
    if layer not in _VALID_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid layer. Must be one of: {sorted(_VALID_LAYERS)}",
        )
    result = toggle_memory_pin(layer, memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"status": "ok", **result}


@router.delete("/{layer}/{memory_id}")
async def delete_memory(
    layer: str,
    memory_id: int,
    user: CurrentUser = Depends(require_admin),
):
    """Archives the memory — soft delete. The row stays in SQLite with
    status='active' flipped to 'archived', the original is copied into
    memory_archive, and the matching ChromaDB vector is removed."""
    if layer not in _VALID_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid layer. Must be one of: {sorted(_VALID_LAYERS)}",
        )
    ok = archive_memory(layer, memory_id, "archived via memory browser")
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"status": "ok", "id": memory_id, "layer": layer}
