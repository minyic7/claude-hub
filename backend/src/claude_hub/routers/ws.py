import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_hub import redis_client

router = APIRouter()
logger = logging.getLogger(__name__)

_connections: set[WebSocket] = set()


async def broadcast(event: dict) -> None:
    msg = json.dumps(event)
    dead: list[WebSocket] = []
    for ws in _connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.discard(ws)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _connections.add(websocket)
    logger.info("WebSocket connected (%d total)", len(_connections))

    try:
        # Send init with all projects and tickets
        projects = await redis_client.list_projects()
        # Mask tokens in WS response
        for p in projects:
            token = p.get("gh_token", "")
            p["gh_token"] = (token[:4] + "..." + token[-4:]) if token and len(token) >= 8 else ("***" if token else "")
        tickets = await redis_client.list_tickets()
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {"projects": projects, "tickets": tickets},
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
