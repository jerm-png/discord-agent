import logging
import re

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.core.auth import (
    CurrentUser,
    decode_token,
    get_current_user,
)
from app.core.config import WORKSPACES
from app.core.ws_manager import ws_manager
from app.db.threads import get_thread, update_thread_activity
from app.features.chat.orchestrator import process_user_message

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{workspace_slug}/{thread_id}")
async def chat_websocket(
    websocket: WebSocket,
    workspace_slug: str,
    thread_id: str,
):
    # Authentication — decode user_id + role from the cookie JWT.
    drift_token = websocket.cookies.get("drift_token")
    auth_user = decode_token(drift_token) if drift_token else None
    if not auth_user:
        await websocket.close(code=1008)
        return
    user_id = auth_user["user_id"]
    author_display_name = "Parker" if user_id == "parker" else "Jerm"

    # Workspace validation
    if workspace_slug not in WORKSPACES:
        await websocket.close(code=1008)
        return
    ws_config = WORKSPACES[workspace_slug]
    # Enforce per-workspace user restriction. Parker can only chat in
    # parker.exe; admin can chat in any workspace except parker.exe.
    restricted = ws_config.get("user_restricted")
    if restricted is not None and user_id != restricted:
        await websocket.close(code=1008)
        return
    if restricted is None and user_id == "parker":
        await websocket.close(code=1008)
        return
    memory_mode = ws_config["memory_mode"]
    project_tag = ws_config.get("project_tag")

    # Thread validation — user_id filter ensures the requested thread
    # actually belongs to the authenticated user.
    thread = get_thread(thread_id, user_id=user_id)
    if not thread or thread["workspace"] != workspace_slug:
        await websocket.close(code=1008)
        return

    # Accept and register connection
    await websocket.accept()
    ws_manager.connect(thread_id, websocket)
    await ws_manager.send(thread_id, {
        "type": "connected",
        "thread_id": thread_id,
        "workspace": workspace_slug,
    })

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") != "message":
                continue
            content = (data.get("content") or "").strip()
            if not content:
                continue

            update_thread_activity(thread_id)

            await process_user_message(
                user_message=content,
                user_id=user_id,
                author_display_name=author_display_name,
                session_id=thread_id,
                memory_mode=memory_mode,
                project_tag=project_tag,
                active_agent_slug=data.get("agent_slug"),
                agent_trigger="none",
                context_id=thread_id,
                channel_name=workspace_slug,
            )
            await ws_manager.send(thread_id, {"type": "done"})

    except WebSocketDisconnect:
        ws_manager.disconnect(thread_id)

    except Exception as exc:
        logger.error("chat_websocket error on thread %s: %s", thread_id, exc, exc_info=True)
        try:
            await ws_manager.send(thread_id, {
                "type": "error",
                "text": "An internal error occurred.",
            })
        except Exception:
            pass
        ws_manager.disconnect(thread_id)

    finally:
        ws_manager.disconnect(thread_id)


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    # Verify the thread exists AND belongs to this user. Without this a
    # caller could probe other users' thread ids — even though the
    # conversation_history lookup is keyed by (user_id, thread_id) and
    # would return an empty list, a 404 is the truthful response.
    thread = get_thread(thread_id, user_id=user["user_id"])
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    from app.core.state import conversation_history
    key = (user["user_id"], thread_id)
    history = conversation_history.get(key, [])

    messages = []
    for i, msg in enumerate(history):
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue

        content = msg.get("content", "")

        # Handle list-format content from Claude API. Blocks may arrive as
        # dicts (when manually constructed for vision attachments / tool
        # results) OR as Anthropic SDK Block objects (TextBlock, ToolUseBlock)
        # when assistant turns are stored straight from response.content.
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                elif getattr(block, "type", None) == "text":
                    parts.append(getattr(block, "text", ""))
            content = " ".join(parts)

        # Strip system-context prefix from user messages so the chat
        # bubble shows only what the user typed.
        if role == "user":
            if "Current message: " in content:
                # Standard path — orchestrator wraps every user turn
                # with this marker, the tail is the raw text.
                content = content.split("Current message: ", 1)[1]
            else:
                # Pre-migration fallback: messages stored before the
                # orchestrator started always-wrapping with "Current
                # message:". Strip the leading [Channel: #X | Purpose:
                # ...] block (workspace personalities don't contain ']'
                # chars, so the first ']' is the closing bracket), then
                # the [SESSION ARCHIVE ... [Use these records ...]]
                # block if a confabulation check fired. Anything else
                # gracefully degrades to "first turn looks a bit noisy."
                _channel_re = re.compile(
                    r"^\[Channel: #[^\]]*\]\s*", re.DOTALL
                )
                _archive_re = re.compile(
                    r"^\[SESSION ARCHIVE[\s\S]*?\[Use these records[^\]]*\]\s*",
                    re.DOTALL,
                )
                for _r in (_channel_re, _archive_re):
                    m = _r.match(content)
                    if m:
                        content = content[m.end():]

        content = content.strip()
        if not content:
            continue

        messages.append({
            "id": f"msg-{i}",
            "role": role,
            "content": content,
            # ISO timestamp written by the orchestrator at append time.
            # Pre-migration rows without the field fall back to "" so the
            # frontend's formatTime guard renders nothing (no "Invalid date").
            "timestamp": msg.get("timestamp", "") or "",
        })

    return {"messages": messages}
