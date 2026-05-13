import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.auth import (
    CurrentUser,
    decode_token,
    get_current_user,
)
from app.core.config import WORKSPACES
from app.core.ws_manager import ws_manager
from app.db.threads import get_thread, update_thread_activity
from app.features.chat.orchestrator import (
    _parse_goal_trigger,
    append_history_turn,
    execute_goal,
    persist_history,
    process_user_message,
    resume_goal_from_gate,
    run_goal_modification,
    run_goal_planning,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_ACTIONS = {"approve", "cancel", "modify", "continue", "adjust", "skip", "retry"}


class ThreadActionRequest(BaseModel):
    action: str
    changes: str = ""


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

            # Goal-mode triggers: !goal / !plan / !research route to the
            # planner so a `plan` WebSocket frame is emitted (which the
            # frontend renders with inline approve/modify/cancel buttons).
            # Fire-and-forget so the WS receive loop is not blocked while the
            # planner model runs; the plan/error frame is the terminal signal.
            if content.startswith("!"):
                stripped = content[1:].lstrip()
                goal_trigger = _parse_goal_trigger(stripped)
                if goal_trigger:
                    _, goal_text = goal_trigger
                    asyncio.create_task(run_goal_planning(
                        goal_text=goal_text,
                        user_id=user_id,
                        author_display_name=author_display_name,
                        session_id=thread_id,
                        memory_mode=memory_mode,
                        project_tag=project_tag,
                        channel_name=workspace_slug,
                        # Pass the raw "!goal X" so it gets persisted to
                        # conversation_history alongside the plan response —
                        # without this the user side of the !goal turn is
                        # lost on reload (this branch skips
                        # process_user_message which normally handles it).
                        user_message=content,
                    ))
                    continue

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

        # Strip system context prefix from user messages
        if role == "user" and "Current message: " in content:
            content = content.split("Current message: ", 1)[1]

        content = content.strip()
        if not content:
            continue

        messages.append({
            "id": f"msg-{i}",
            "role": role,
            "content": content,
            "timestamp": "",
        })

    return {"messages": messages}


@router.post("/threads/{thread_id}/action")
async def thread_action(
    thread_id: str,
    body: ThreadActionRequest,
    user: CurrentUser = Depends(get_current_user),
):
    if body.action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Must be one of: {', '.join(sorted(ALLOWED_ACTIONS))}",
        )

    user_id = user["user_id"]
    author_display_name = "Parker" if user_id == "parker" else "Jerm"

    # User-scoped fetch — 404s on threads that aren't owned by the
    # authenticated user even if the id is valid.
    thread = get_thread(thread_id, user_id=user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    workspace_slug = thread["workspace"]
    ws_config = WORKSPACES.get(workspace_slug, {})
    # Per-workspace user restriction: Parker only operates in parker.exe;
    # admin cannot operate inside Parker's workspace.
    restricted = ws_config.get("user_restricted")
    if restricted is not None and user_id != restricted:
        raise HTTPException(status_code=403, detail="Workspace not accessible")
    if restricted is None and user_id == "parker":
        raise HTTPException(status_code=403, detail="Workspace not accessible")
    memory_mode = ws_config.get("memory_mode", "global")
    project_tag = ws_config.get("project_tag")

    action = body.action

    if action == "approve":
        from app.core.state import pending_goals, execution_context
        pg = pending_goals.get(user_id)
        if not pg:
            raise HTTPException(status_code=400, detail="No pending goal to approve.")
        if pg.get("status") != "awaiting_approval":
            raise HTTPException(
                status_code=400,
                detail=f"Goal is not awaiting approval (status: {pg.get('status')}).",
            )
        pg["status"] = "executing"
        pg["current_step"] = 0
        execution_context.pop(user_id, None)
        asyncio.create_task(execute_goal(
            user_id=user_id,
            author_display_name=author_display_name,
        ))

    elif action == "cancel":
        from app.core.state import pending_goals, gate_pending, execution_context
        pending_goals.pop(user_id, None)
        gate_pending.pop(user_id, None)
        execution_context.pop(user_id, None)
        cancel_text = "❌ Goal cancelled."
        await ws_manager.send(thread_id, {
            "type": "response",
            "text": cancel_text,
        })
        append_history_turn(user_id, thread_id, "assistant", cancel_text)
        await persist_history(user_id, thread_id)

    elif action in ("continue", "adjust", "skip", "retry"):
        await resume_goal_from_gate(
            user_id=user_id,
            author_display_name=author_display_name,
            action=action,
            changes=body.changes,
        )

    elif action == "modify":
        await run_goal_modification(
            changes=body.changes,
            user_id=user_id,
            author_display_name=author_display_name,
            session_id=thread_id,
            memory_mode=memory_mode,
            project_tag=project_tag,
        )

    return {"status": "ok", "action": action}
