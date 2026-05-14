from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import CurrentUser, get_current_user
from app.core.config import WORKSPACES
from app.db.threads import (
    archive_thread,
    create_thread,
    get_thread,
    list_threads,
    rename_thread,
)

router = APIRouter()


class ThreadCreate(BaseModel):
    title: str
    entity_id: int | None = None


class ThreadRename(BaseModel):
    title: str


def _workspace_accessible(workspace_slug: str, user_id: str) -> bool:
    """
    Mirrors the visibility rules in workspaces.py: Parker only operates in
    his own workspace; admin operates in everything except parker.
    """
    if workspace_slug not in WORKSPACES:
        return False
    restricted = WORKSPACES[workspace_slug].get("user_restricted")
    if restricted is not None:
        return user_id == restricted
    return user_id != "parker"


# Workspace-scoped routes — mounted under /workspaces
@router.get("/{workspace_slug}/threads")
async def get_workspace_threads(
    workspace_slug: str,
    status: str = "active",
    user: CurrentUser = Depends(get_current_user),
):
    if workspace_slug not in WORKSPACES:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_slug}' not found",
        )
    if not _workspace_accessible(workspace_slug, user["user_id"]):
        raise HTTPException(status_code=403, detail="Workspace not accessible")
    return {
        "threads": list_threads(
            workspace_slug, user["user_id"], status=status
        )
    }


@router.post("/{workspace_slug}/threads", status_code=201)
async def create_workspace_thread(
    workspace_slug: str,
    body: ThreadCreate,
    user: CurrentUser = Depends(get_current_user),
):
    if workspace_slug not in WORKSPACES:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_slug}' not found",
        )
    if not _workspace_accessible(workspace_slug, user["user_id"]):
        raise HTTPException(status_code=403, detail="Workspace not accessible")
    title = body.title.strip()
    if not title:
        raise HTTPException(
            status_code=400,
            detail="Thread title cannot be empty",
        )
    thread = create_thread(
        workspace_slug, title, user["user_id"], entity_id=body.entity_id
    )
    return {"thread": thread}


# Direct thread routes — mounted under /workspaces too
# but accessed via /threads/{id} separately
@router.get("/threads/{thread_id}")
async def get_thread_by_id(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    thread = get_thread(thread_id, user_id=user["user_id"])
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"thread": thread}


@router.patch("/threads/{thread_id}")
async def update_thread(
    thread_id: str,
    body: ThreadRename,
    user: CurrentUser = Depends(get_current_user),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(
            status_code=400,
            detail="Thread title cannot be empty",
        )
    thread = rename_thread(thread_id, title, user["user_id"])
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"thread": thread}


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    ok = archive_thread(thread_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"message": "Thread archived"}
