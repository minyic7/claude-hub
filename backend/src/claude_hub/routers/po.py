"""PO Agent REST endpoints — settings, chat, report, approve/reject."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from claude_hub import redis_client
from claude_hub.models.ticket import AgentSettings, POSettings, TicketStatus
from claude_hub.services.po_manager import po_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["po"])


# ─── Agent Settings (per-project) ────────────────────────────────────────────


def _mask_key(key: str) -> str:
    if not key or len(key) < 16:
        return "***" if key else ""
    return key[:8] + "..." + key[-4:]


@router.get("/projects/{project_id}/agent/settings")
async def get_project_agent_settings(project_id: str):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    raw = project.get("agent_settings", "")
    try:
        cfg = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    result = AgentSettings(**cfg).model_dump()
    result["api_key"] = _mask_key(result.get("api_key", ""))
    return result


@router.put("/projects/{project_id}/agent/settings")
async def update_project_agent_settings(project_id: str, body: AgentSettings):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Don't overwrite api_key with masked value
    if body.api_key and "..." in body.api_key:
        raw = project.get("agent_settings", "")
        try:
            old = json.loads(raw) if isinstance(raw, str) and raw else {}
        except (json.JSONDecodeError, TypeError):
            old = {}
        body.api_key = old.get("api_key", "")

    await redis_client.update_project_fields(project_id, {
        "agent_settings": json.dumps(body.model_dump()),
    })

    result = body.model_dump()
    result["api_key"] = _mask_key(result.get("api_key", ""))
    return result


async def get_agent_settings_for_project(project_id: str) -> dict:
    """Load per-project agent settings, returning defaults if not configured."""
    project = await redis_client.get_project(project_id)
    if not project:
        return AgentSettings().model_dump()
    raw = project.get("agent_settings", "")
    try:
        cfg = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    return AgentSettings(**cfg).model_dump()


# ─── PO Settings ────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/po/settings")
async def get_po_settings(project_id: str):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    raw = project.get("po_settings", "")
    try:
        cfg = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    return POSettings(**cfg).model_dump()


@router.put("/projects/{project_id}/po/settings")
async def update_po_settings(project_id: str, body: POSettings):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Load current settings to detect enabled change
    raw = project.get("po_settings", "")
    try:
        old_cfg = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (json.JSONDecodeError, TypeError):
        old_cfg = {}
    old = POSettings(**old_cfg)

    # Save new settings
    await redis_client.update_project_fields(project_id, {
        "po_settings": json.dumps(body.model_dump()),
    })

    # Start/stop PO agent based on enabled state
    if body.enabled and not old.enabled:
        await po_manager.start(project_id)
    elif not body.enabled and old.enabled:
        await po_manager.stop(project_id)

    return body.model_dump()


# ─── PO Status ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/po/status")
async def get_po_status(project_id: str):
    agent = po_manager.get(project_id)
    project = await redis_client.get_project(project_id)
    return {
        "running": po_manager.is_running(project_id),
        "status": agent.status if agent else (project or {}).get("po_status", "idle"),
        "cycle_n": agent.cycle_n if agent else 0,
    }


# ─── Manual Trigger ──────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/po/run")
async def trigger_po_cycle(project_id: str):
    agent = po_manager.get(project_id)
    if not agent:
        raise HTTPException(409, "PO agent is not running for this project")
    agent.enqueue_trigger("manual")
    return {"status": "triggered"}


# ─── Chat ────────────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    message: str


@router.post("/projects/{project_id}/po/chat")
async def chat_with_po(project_id: str, body: ChatMessage):
    agent = po_manager.get(project_id)
    if not agent:
        raise HTTPException(409, "PO agent is not running for this project")
    response = await agent.handle_user_message(body.message)
    return {"response": response}


@router.get("/projects/{project_id}/po/chat/history")
async def get_chat_history(project_id: str, limit: int = 50):
    from claude_hub.services.po_database import PODatabase
    db = PODatabase(project_id)
    try:
        messages = db.load_conversation(limit=limit)
        return {"messages": messages}
    finally:
        db.close()


# ─── Report ──────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/po/report")
async def get_po_report(project_id: str):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {
        "report": project.get("po_last_report", ""),
        "generated_at": project.get("po_last_report_at"),
    }


@router.post("/projects/{project_id}/po/report")
async def request_po_report(project_id: str):
    agent = po_manager.get(project_id)
    if not agent:
        raise HTTPException(409, "PO agent is not running")
    agent.enqueue_trigger("report")
    return {"status": "report_requested"}


# ─── Approve / Reject ───────────────────────────────────────────────────────


@router.post("/tickets/{ticket_id}/po/approve")  # /api/tickets/{id}/po/approve
async def approve_po_ticket(ticket_id: str):
    from claude_hub.services.ticket_service import InvalidTransition, transition

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.get("status") != "po_pending":
        raise HTTPException(409, f"Ticket is not pending approval (status: {ticket.get('status')})")

    try:
        updated = await transition(ticket_id, TicketStatus.TODO)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    from claude_hub.routers.ws import broadcast
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/tickets/{ticket_id}/po/reject")  # /api/tickets/{id}/po/reject
async def reject_po_ticket(ticket_id: str):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.get("status") != "po_pending":
        raise HTTPException(409, f"Ticket is not pending approval (status: {ticket.get('status')})")

    # Archive with rejection note
    from claude_hub.services.ticket_service import append_ticket_note
    await append_ticket_note(ticket_id, "system", "Rejected by user", author="user")
    await redis_client.update_ticket_fields(ticket_id, {"archived": True})

    from claude_hub.routers.ws import broadcast
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": await redis_client.get_ticket(ticket_id),
    })
    return {"status": "rejected"}
