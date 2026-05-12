from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_auth
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


class ThreadRename(BaseModel):
    title: str


# Workspace-scoped routes — mounted under /workspaces
@router.get("/{workspace_slug}/threads")
async def get_workspace_threads(
    workspace_slug: str,
    status: str = "active",
    _: str = Depends(require_auth),
):
    if workspace_slug not in WORKSPACES:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_slug}' not found"
        )
    return {"threads": list_threads(workspace_slug, status=status)}


@router.post("/{workspace_slug}/threads", status_code=201)
async def create_workspace_thread(
    workspace_slug: str,
    body: ThreadCreate,
    _: str = Depends(require_auth),
):
    if workspace_slug not in WORKSPACES:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_slug}' not found"
        )
    title = body.title.strip()
    if not title:
        raise HTTPException(
            status_code=400,
            detail="Thread title cannot be empty"
        )
    thread = create_thread(workspace_slug, title)
    return {"thread": thread}


# Direct thread routes — mounted under /workspaces too
# but accessed via /threads/{id} separately
@router.get("/threads/{thread_id}")
async def get_thread_by_id(
    thread_id: str,
    _: str = Depends(require_auth),
):
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(
            status_code=404,
            detail="Thread not found"
        )
    return {"thread": thread}


@router.patch("/threads/{thread_id}")
async def update_thread(
    thread_id: str,
    body: ThreadRename,
    _: str = Depends(require_auth),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(
            status_code=400,
            detail="Thread title cannot be empty"
        )
    thread = rename_thread(thread_id, title)
    if not thread:
        raise HTTPException(
            status_code=404,
            detail="Thread not found"
        )
    return {"thread": thread}


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    _: str = Depends(require_auth),
):
    ok = archive_thread(thread_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Thread not found"
        )
    return {"message": "Thread archived"}
