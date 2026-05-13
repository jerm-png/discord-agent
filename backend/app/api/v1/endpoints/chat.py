import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.auth import require_auth, verify_token
from app.core.config import WORKSPACES
from app.core.ws_manager import ws_manager
from app.db.threads import get_thread, update_thread_activity
from app.features.chat.orchestrator import (
    _parse_goal_trigger,
    execute_goal,
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
    # Authentication
    drift_token = websocket.cookies.get("drift_token")
    if not drift_token or not verify_token(drift_token):
        await websocket.close(code=1008)
        return

    # Workspace validation
    if workspace_slug not in WORKSPACES:
        await websocket.close(code=1008)
        return
    ws_config = WORKSPACES[workspace_slug]
    memory_mode = ws_config["memory_mode"]
    project_tag = ws_config.get("project_tag")

    # Thread validation
    thread = get_thread(thread_id)
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
            if content.startswith("!"):
                stripped = content[1:].lstrip()
                goal_trigger = _parse_goal_trigger(stripped)
                if goal_trigger:
                    _, goal_text = goal_trigger
                    await run_goal_planning(
                        goal_text=goal_text,
                        user_id="drift-owner",
                        author_display_name="Jerm",
                        session_id=thread_id,
                        memory_mode=memory_mode,
                        project_tag=project_tag,
                        channel_name=workspace_slug,
                    )
                    await ws_manager.send(thread_id, {"type": "done"})
                    continue

            await process_user_message(
                user_message=content,
                user_id="drift-owner",
                author_display_name="Jerm",
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
    user: str = Depends(require_auth),
):
    from app.core.state import conversation_history
    key = ("drift-owner", thread_id)
    history = conversation_history.get(key, [])

    messages = []
    for i, msg in enumerate(history):
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue

        content = msg.get("content", "")

        # Handle list-format content from Claude API
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )

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
    user: str = Depends(require_auth),
):
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if body.action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Must be one of: {', '.join(sorted(ALLOWED_ACTIONS))}",
        )

    workspace_slug = thread["workspace"]
    ws_config = WORKSPACES.get(workspace_slug, {})
    memory_mode = ws_config.get("memory_mode", "global")
    project_tag = ws_config.get("project_tag")

    action = body.action

    if action == "approve":
        await execute_goal(
            user_id="drift-owner",
            author_display_name="Jerm",
            skip_gate_for_step=None,
        )

    elif action == "cancel":
        from app.core.state import pending_goals, gate_pending, execution_context
        pending_goals.pop("drift-owner", None)
        gate_pending.pop("drift-owner", None)
        execution_context.pop("drift-owner", None)
        await ws_manager.send(thread_id, {
            "type": "status",
            "text": "Goal cancelled.",
        })

    elif action in ("continue", "adjust", "skip", "retry"):
        await resume_goal_from_gate(
            user_id="drift-owner",
            author_display_name="Jerm",
            action=action,
            changes=body.changes,
        )

    elif action == "modify":
        await run_goal_modification(
            changes=body.changes,
            user_id="drift-owner",
            author_display_name="Jerm",
            session_id=thread_id,
            memory_mode=memory_mode,
            project_tag=project_tag,
        )

    return {"status": "ok", "action": action}
