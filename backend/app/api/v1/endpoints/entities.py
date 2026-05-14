from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import CurrentUser, require_admin
from app.db.memory_manager import (
    add_entity_tag,
    create_entity,
    get_entity_by_id,
    get_entity_tags,
    get_entity_timeline,
    list_entities_full,
    remove_entity_tag,
    update_entity,
)
from app.db.threads import count_threads_for_entity, list_threads_for_entity

router = APIRouter()

VALID_ACCENT_COLORS = {"cyan", "pink", "green", "yellow"}
VALID_RELATIONSHIP_TYPES = {
    "direct_report", "peer", "skip_level", "stakeholder", "external",
}


class EntityCreate(BaseModel):
    name: str
    title: Optional[str] = None
    relationship_type: str = "direct_report"
    accent_color: str = "cyan"
    first_note: Optional[str] = None


class EntityPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    accent_color: Optional[str] = None
    relationship_type: Optional[str] = None
    status: Optional[str] = None
    context: Optional[str] = None


class TagCreate(BaseModel):
    tag: str


@router.get("")
async def list_all_entities(
    user: CurrentUser = Depends(require_admin),
):
    """Admin-only: every entity (active + archived) with the roster-page
    fields, tags, and an active thread_count joined from the threads
    table scoped to this admin's user_id."""
    entities = list_entities_full(include_archived=True)
    for ent in entities:
        ent["thread_count"] = count_threads_for_entity(
            ent["id"], user["user_id"]
        )
    return {"entities": entities}


@router.post("", status_code=201)
async def create_new_entity(
    body: EntityCreate,
    user: CurrentUser = Depends(require_admin),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if body.accent_color not in VALID_ACCENT_COLORS:
        raise HTTPException(
            status_code=400,
            detail=f"accent_color must be one of {sorted(VALID_ACCENT_COLORS)}",
        )
    if body.relationship_type not in VALID_RELATIONSHIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "relationship_type must be one of "
                f"{sorted(VALID_RELATIONSHIP_TYPES)}"
            ),
        )
    try:
        entity = create_entity(
            name=name,
            role=(body.title.strip() if body.title else None),
            relationship_type=body.relationship_type,
            accent_color=body.accent_color,
            first_note=(
                body.first_note.strip() if body.first_note else None
            ),
        )
    except Exception as e:
        # UNIQUE name collision lands here.
        raise HTTPException(
            status_code=400,
            detail=f"Could not create entity: {str(e)[:200]}",
        )
    entity["tags"] = []
    entity["thread_count"] = 0
    entity["fact_count"] = 1 if body.first_note else 0
    return {"entity": entity}


@router.patch("/{entity_id}")
async def patch_entity(
    entity_id: int,
    body: EntityPatch,
    user: CurrentUser = Depends(require_admin),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "accent_color" in updates and updates["accent_color"] not in VALID_ACCENT_COLORS:
        raise HTTPException(
            status_code=400,
            detail=f"accent_color must be one of {sorted(VALID_ACCENT_COLORS)}",
        )
    if (
        "relationship_type" in updates
        and updates["relationship_type"] not in VALID_RELATIONSHIP_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "relationship_type must be one of "
                f"{sorted(VALID_RELATIONSHIP_TYPES)}"
            ),
        )
    if "status" in updates and updates["status"] not in {"active", "archived"}:
        raise HTTPException(
            status_code=400,
            detail="status must be 'active' or 'archived'",
        )
    entity = update_entity(entity_id, updates)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity["tags"] = get_entity_tags(entity_id)
    entity["thread_count"] = count_threads_for_entity(
        entity_id, user["user_id"]
    )
    return {"entity": entity}


@router.post("/{entity_id}/tags", status_code=201)
async def add_tag(
    entity_id: int,
    body: TagCreate,
    user: CurrentUser = Depends(require_admin),
):
    if not get_entity_by_id(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    if not add_entity_tag(entity_id, body.tag):
        # Either empty or already present — return current tag list in
        # either case so the frontend stays in sync.
        return {"tags": get_entity_tags(entity_id)}
    return {"tags": get_entity_tags(entity_id)}


@router.delete("/{entity_id}/tags/{tag}")
async def remove_tag(
    entity_id: int,
    tag: str,
    user: CurrentUser = Depends(require_admin),
):
    if not get_entity_by_id(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    remove_entity_tag(entity_id, tag)
    return {"tags": get_entity_tags(entity_id)}


@router.get("/{entity_id}/timeline")
async def entity_timeline(
    entity_id: int,
    user: CurrentUser = Depends(require_admin),
):
    if not get_entity_by_id(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"timeline": get_entity_timeline(entity_id)}


@router.get("/{entity_id}/threads")
async def entity_threads(
    entity_id: int,
    user: CurrentUser = Depends(require_admin),
):
    """Threads admin has linked to this entity."""
    if not get_entity_by_id(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    return {
        "threads": list_threads_for_entity(entity_id, user["user_id"]),
    }
