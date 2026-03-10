import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from claude_hub import redis_client
from claude_hub.config import settings
from claude_hub.models.ticket import Ticket, TicketCreate, TicketStatus, TicketUpdate
from claude_hub.routers.ws import broadcast

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _slugify(text: str, max_len: int = 60) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len]


def _make_branch(branch_type: str, title: str) -> str:
    return f"{branch_type}/{_slugify(title)}"


async def _get_project_for_ticket(ticket: dict) -> dict:
    """Resolve the project for a ticket. Returns project dict with gh_token."""
    project = await redis_client.get_project(ticket.get("project_id", ""))
    if not project:
        # Fallback: use global settings
        return {"gh_token": settings.gh_token, "repo_url": ticket.get("repo_url", "")}
    return project


@router.get("")
async def list_tickets(status: str | None = Query(None), project_id: str | None = Query(None)):
    if project_id:
        tickets = await redis_client.list_tickets_by_project(project_id, status)
    else:
        tickets = await redis_client.list_tickets(status)
    return tickets


@router.post("", status_code=201)
async def create_ticket(body: TicketCreate):
    # Resolve project
    project = await redis_client.get_project(body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    ticket_id = str(uuid.uuid4())
    ticket = Ticket(
        id=ticket_id,
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        branch_type=body.branch_type,
        branch=_make_branch(body.branch_type.value, body.title),
        repo_url=project["repo_url"],
        base_branch=project.get("base_branch", "main"),
        role=body.role,
        source=body.source,
        external_id=body.external_id,
        metadata=body.metadata,
        depends_on=body.depends_on,
        created_at=datetime.now(timezone.utc),
    )

    await redis_client.save_ticket(ticket.model_dump(mode="json"))
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": ticket.model_dump(mode="json"),
    })
    return ticket.model_dump(mode="json")


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: str):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.patch("/{ticket_id}")
async def update_ticket(ticket_id: str, body: TicketUpdate):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")

    await redis_client.update_ticket_fields(ticket_id, updates)
    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.delete("/{ticket_id}", status_code=204)
async def delete_ticket(ticket_id: str):
    from claude_hub.services import clone_manager, session_manager

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    session_manager.stop_session(ticket_id)
    clone_manager.cleanup_clone(ticket_id)

    await redis_client.delete_ticket(ticket_id)
    await broadcast({
        "type": "ticket_deleted",
        "ticket_id": ticket_id,
    })


@router.get("/{ticket_id}/activity")
async def get_activity(ticket_id: str, since: int = Query(0)):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return await redis_client.get_activity(ticket_id, since)


@router.post("/{ticket_id}/start")
async def start_ticket(ticket_id: str):
    import asyncio
    from claude_hub.services import clone_manager, session_manager
    from claude_hub.services.context_engine import get_role_prompt
    from claude_hub.services.ticket_service import InvalidTransition, transition

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   started_at=datetime.now(timezone.utc).isoformat())
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    # Resolve project token
    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "")

    # Clone repo and create branch
    try:
        clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
        clone_path = clone_manager.clone_for_ticket(
            ticket["repo_url"], ticket_id,
            ticket["branch"], ticket["base_branch"],
            gh_token=gh_token,
        )
        await redis_client.update_ticket_fields(ticket_id, {"clone_path": clone_path})
    except Exception as e:
        await transition(ticket_id, TicketStatus.FAILED, failed_reason=f"Clone failed: {e}")
        updated = await redis_client.get_ticket(ticket_id)
        await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
        raise HTTPException(500, f"Clone failed: {e}")

    # Start Claude Code session
    role_prompt = get_role_prompt(ticket.get("role", "builder"), ticket["branch"])
    task = ticket.get("description") or ticket["title"]
    session_name, log_path = session_manager.start_session(
        ticket_id, clone_path, task, role_prompt, gh_token=gh_token,
    )
    await redis_client.update_ticket_fields(ticket_id, {"tmux_session": session_name})

    # Start background log tailing
    asyncio.create_task(_tail_and_broadcast(ticket_id, log_path))

    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/{ticket_id}/stop")
async def stop_ticket(ticket_id: str):
    from claude_hub.services import session_manager
    from claude_hub.services.ticket_service import InvalidTransition, transition
    try:
        updated = await transition(ticket_id, TicketStatus.FAILED,
                                   failed_reason="Manually stopped")
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    session_manager.stop_session(ticket_id)

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/{ticket_id}/answer")
async def answer_ticket(ticket_id: str, body: dict):
    from claude_hub.services.ticket_service import InvalidTransition, transition
    answer = body.get("answer", "")
    if not answer:
        raise HTTPException(400, "answer required")
    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   blocked_question="")
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    # Send answer to tmux session
    from claude_hub.services import session_manager
    if session_manager.is_alive(ticket_id):
        session_manager.send_input(ticket_id, answer)

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/{ticket_id}/retry")
async def retry_ticket(ticket_id: str, body: dict | None = None):
    from claude_hub.services.ticket_service import InvalidTransition, transition
    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   failed_reason="",
                                   started_at=datetime.now(timezone.utc).isoformat())
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    # Re-spawn session
    import asyncio
    from claude_hub.services import clone_manager, session_manager
    from claude_hub.services.context_engine import get_role_prompt

    ticket = await redis_client.get_ticket(ticket_id)
    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "")

    clone_path = ticket.get("clone_path")
    if not clone_path:
        clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
        clone_path = clone_manager.clone_for_ticket(
            ticket["repo_url"], ticket_id,
            ticket["branch"], ticket["base_branch"],
            gh_token=gh_token,
        )
        await redis_client.update_ticket_fields(ticket_id, {"clone_path": clone_path})

    guidance = (body or {}).get("guidance", "")
    task = ticket.get("description") or ticket["title"]
    if guidance:
        task = f"{task}\n\nAdditional guidance: {guidance}"

    role_prompt = get_role_prompt(ticket.get("role", "builder"), ticket["branch"])
    session_name, log_path = session_manager.start_session(
        ticket_id, clone_path, task, role_prompt, gh_token=gh_token,
    )
    await redis_client.update_ticket_fields(ticket_id, {"tmux_session": session_name})
    asyncio.create_task(_tail_and_broadcast(ticket_id, log_path))

    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


async def _tail_and_broadcast(ticket_id: str, log_path: str) -> None:
    """Background task: tail log with optional TicketAgent supervision."""
    import logging
    from claude_hub.services.ticket_service import transition

    logger = logging.getLogger(__name__)
    try:
        if settings.agent_enabled and settings.anthropic_api_key:
            # Agent mode: TicketAgent handles tailing + broadcasting + intervention
            from claude_hub.services.ticket_agent import TicketAgent
            ticket = await redis_client.get_ticket(ticket_id)
            agent = TicketAgent(ticket_id, ticket)
            await agent.run(log_path)
        else:
            # Simple mode: just tail and broadcast
            from claude_hub.services import session_manager
            async for event in session_manager.tail_log(ticket_id, log_path):
                event_dict = event.model_dump()
                await redis_client.append_activity(ticket_id, event_dict)
                await broadcast({
                    "type": "activity",
                    "ticket_id": ticket_id,
                    "data": event_dict,
                })

        # Session ended — verify agent work
        logger.info("Session ended for ticket %s, running verification", ticket_id)
        ticket = await redis_client.get_ticket(ticket_id)
        if not ticket or ticket.get("status") == "blocked":
            return  # Don't verify if blocked (agent escalated)

        try:
            await transition(ticket_id, TicketStatus.VERIFYING)
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": ticket_id,
                "data": await redis_client.get_ticket(ticket_id),
            })
        except Exception:
            pass

        # Run verification
        from claude_hub.services.github_verify import verify_agent_work
        clone_path = ticket.get("clone_path", "")
        if clone_path:
            # Fetch latest from remote before verifying
            import subprocess
            subprocess.run(["git", "fetch", "origin"], cwd=clone_path, capture_output=True)

            result = verify_agent_work(clone_path, ticket["branch"], ticket["base_branch"])
            logger.info("Verification for %s: %s", ticket_id, result)

            if result.passed:
                updated = await transition(ticket_id, TicketStatus.REVIEW,
                                           pr_url=result.pr_url,
                                           pr_number=result.pr_number)
            else:
                updated = await transition(ticket_id, TicketStatus.FAILED,
                                           failed_reason=result.reason)
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": ticket_id,
                "data": updated,
            })

    except Exception as e:
        logger.error("Error tailing log for ticket %s: %s", ticket_id, e)


@router.post("/{ticket_id}/mark-review")
async def mark_review(ticket_id: str):
    from claude_hub.services.ticket_service import InvalidTransition, transition
    try:
        updated = await transition(ticket_id, TicketStatus.REVIEW)
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/{ticket_id}/merge")
async def merge_ticket(ticket_id: str):
    from claude_hub.services.ticket_service import InvalidTransition, transition
    try:
        updated = await transition(ticket_id, TicketStatus.MERGED,
                                   completed_at=datetime.now(timezone.utc).isoformat())
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated
