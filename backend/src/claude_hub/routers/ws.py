import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from claude_hub import redis_client
from claude_hub.auth import verify_ws_token
from claude_hub.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_connections: set[WebSocket] = set()


async def broadcast(event: dict) -> None:
    msg = json.dumps(event)
    dead: list[WebSocket] = []
    for ws in set(_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.discard(ws)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")) -> None:
    # Verify token if auth is enabled
    if settings.auth_enabled and not verify_ws_token(token):
        await websocket.close(code=4001, reason="Invalid or missing token")
        return

    await websocket.accept()
    _connections.add(websocket)
    logger.info("WebSocket connected (%d total)", len(_connections))

    try:
        # Send init with all projects and tickets
        projects_raw = await redis_client.list_projects()
        # Mask tokens in WS response (copy to avoid mutating cached data)
        projects = []
        for p in projects_raw:
            masked = {**p}
            token = masked.get("gh_token", "")
            masked["gh_token"] = (token[:4] + "..." + token[-4:]) if token and len(token) >= 8 else ("***" if token else "")
            projects.append(masked)
        tickets = await redis_client.list_tickets()

        # Include last 50 activities for active tickets (for reconnect sync)
        activities: dict[str, list] = {}
        for t in tickets:
            if t.get("status") in ("in_progress", "blocked", "verifying", "review", "reviewing", "failed", "merged", "merging"):
                recent = await redis_client.get_recent_activity(t["id"], count=50)
                if recent:
                    activities[t["id"]] = recent

        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {"projects": projects, "tickets": tickets, "activities": activities},
        }))

        # Keep alive — just read and discard client messages
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    finally:
        _connections.discard(websocket)
        logger.info("WebSocket disconnected (%d total)", len(_connections))
