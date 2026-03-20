import logging
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

from claude_hub import redis_client
from claude_hub.config import settings
from claude_hub.routers.settings_router import get_max_sessions, get_max_total_sessions
from claude_hub.models.ticket import Ticket, TicketCreate, TicketStatus, TicketUpdate
from claude_hub.routers.ws import broadcast
from claude_hub.services.kanban_manager import send_kanban_update, send_pilot_trigger
from claude_hub.services.ticket_service import append_ticket_note

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _fire_pilot_trigger(project_id: str, ticket_id: str) -> None:
    """Fire pilot trigger if project has pilot_mode enabled. Non-blocking."""
    if not project_id:
        return
    import asyncio

    async def _check_and_fire():
        project = await redis_client.get_project(project_id)
        if project and project.get("pilot_mode"):
            send_pilot_trigger(project_id, f"ticket_merged:{ticket_id}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_check_and_fire())
    except RuntimeError:
        pass


def _extract_repo_nwo(repo_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub repo URL."""
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", repo_url)
    return m.group(1) if m else None


def _cleanup_remote_branch(ticket: dict) -> None:
    """Delete the remote branch for a ticket. Best-effort, never raises."""
    branch = ticket.get("branch", "")
    repo_url = ticket.get("repo_url", "")
    if not branch or not repo_url:
        return

    nwo = _extract_repo_nwo(repo_url)
    if not nwo:
        return

    try:
        result = subprocess.run(
            ["gh", "api", "-X", "DELETE", f"/repos/{nwo}/git/refs/heads/{branch}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            logger.info("Deleted remote branch %s on %s", branch, nwo)
        else:
            # 422 = branch doesn't exist (already deleted), that's fine
            if "Reference does not exist" not in result.stderr:
                logger.warning("Failed to delete remote branch %s: %s", branch, result.stderr.strip())
    except Exception:
        logger.warning("Exception deleting remote branch %s", branch, exc_info=True)


def _is_conflicted(ticket: dict) -> bool:
    """Check if a ticket has merge conflicts. Handles Redis string values."""
    val = ticket.get("has_conflicts", False)
    if isinstance(val, str):
        return val.lower() == "true"
    return bool(val)

# Appended to every task prompt to ensure Claude Code pushes all changes
_PUSH_VERIFICATION_INSTRUCTION = (
    "\n\n## IMPORTANT — Polish Pass (do this BEFORE final verification)\n"
    "Before marking your work as done, do one round of self-review:\n"
    "1. Re-read the ticket description and VISION.md spec for the area you changed.\n"
    "2. Compare what you built against the spec — did you miss anything?\n"
    "3. Check for edge cases, error handling, and UI/UX quality.\n"
    "4. Run the feature end-to-end if possible. Fix anything that feels rough.\n"
    "5. Review your own code — would you approve this PR? Clean up anything you wouldn't.\n"
    "\n## IMPORTANT — Final Verification (do this LAST before exiting)\n"
    "Before you finish:\n"
    "1. If you modified frontend files, run `cd frontend && pnpm exec tsc -b` to check for TypeScript errors. Fix any errors before pushing.\n"
    "2. Run `git status` and `git log --oneline -5` to verify:\n"
    "   - No uncommitted changes remain (working tree clean)\n"
    "   - All commits have been pushed to the remote branch\n"
    "   - A PR exists (create one if missing)\n"
    "If anything is missing, fix it before exiting."
)


def _read_vision_for_ticket(project_id: str) -> str:
    """Read VISION.md from the kanban directory to inject into ticket CC context.

    This gives ticket CC sessions the full project vision so they make
    architecture decisions consistent with the overall plan.
    """
    vision_path = os.path.join(settings.data_dir, "kanbans", project_id, "VISION.md")
    try:
        with open(vision_path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _build_vision_context(project_id: str) -> str:
    """Build the VISION.md context section for a ticket CC prompt."""
    vision = _read_vision_for_ticket(project_id)
    if not vision:
        return ""
    return (
        "\n\n## Project Vision (VISION.md — GROUND TRUTH)\n"
        "This is the authoritative project specification. Your implementation MUST follow it.\n"
        "- If the vision specifies an approach, use that approach — do not invent alternatives.\n"
        "- If the vision specifies API contracts, data structures, or file layout, match them exactly.\n"
        "- If your ticket description conflicts with the vision, the vision wins.\n"
        "- If the vision doesn't cover something, use your best judgment but stay consistent with its style and patterns.\n\n"
        f"{vision}\n"
    )


def _slugify(text: str, max_len: int = 60) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len]


def _make_branch(branch_type: str, title: str, ticket_id: str) -> str:
    short_id = ticket_id[:6]
    return f"{branch_type}/{_slugify(title, max_len=40)}-{short_id}"


async def _get_project_for_ticket(ticket: dict) -> dict:
    """Resolve the project for a ticket. Returns project dict with gh_token."""
    project = await redis_client.get_project(ticket.get("project_id", ""))
    if not project:
        # Fallback: use global settings
        return {"gh_token": settings.gh_token, "repo_url": ticket.get("repo_url", "")}
    return project


@router.get("")
async def list_tickets(
    status: str | None = Query(None),
    project_id: str | None = Query(None),
    include_archived: bool = Query(False),
):
    if project_id:
        await redis_client.backfill_ticket_seqs(project_id)
        tickets = await redis_client.list_tickets_by_project(project_id, status)
    else:
        tickets = await redis_client.list_tickets(status)
    if not include_archived:
        tickets = [t for t in tickets if not t.get("archived")]
    return tickets


@router.post("", status_code=201)
async def create_ticket(body: TicketCreate):
    # Resolve project
    project = await redis_client.get_project(body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    ticket_id = str(uuid.uuid4())
    seq = await redis_client.next_ticket_seq(body.project_id)
    ticket = Ticket(
        id=ticket_id,
        project_id=body.project_id,
        seq=seq,
        title=body.title,
        description=body.description,
        branch_type=body.branch_type,
        branch=_make_branch(body.branch_type.value, body.title, ticket_id),
        repo_url=project["repo_url"],
        base_branch=project.get("base_branch", "main"),
        source=body.source,
        external_id=body.external_id,
        metadata=body.metadata,
        depends_on=body.depends_on,
        pilot=body.pilot,
        created_at=datetime.now(timezone.utc),
        status_changed_at=datetime.now(timezone.utc),
    )

    await redis_client.save_ticket(ticket.model_dump(mode="json"))
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": ticket.model_dump(mode="json"),
    })
    send_kanban_update(body.project_id)
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

    # Only allow editing title/description when ticket is still in TODO
    if ticket.get("status") != TicketStatus.TODO.value:
        raise HTTPException(409, "Can only edit tickets in TODO status")

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
    send_kanban_update(ticket.get("project_id", ""))
    return updated


@router.post("/{ticket_id}/archive")
async def toggle_archive(ticket_id: str):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    new_val = not ticket.get("archived", False)
    if new_val:
        _cleanup_remote_branch(ticket)
    await redis_client.update_ticket_fields(ticket_id, {"archived": new_val})
    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/{ticket_id}/force-status")
async def force_status(ticket_id: str, body: dict):
    """Admin endpoint: force ticket to any status, bypassing transition rules.

    Use when system state is out of sync with reality (e.g., PR merged externally
    but ticket stuck in failed).
    """
    from claude_hub.services import session_manager

    target_status = body.get("status", "")
    try:
        target = TicketStatus(target_status)
    except ValueError:
        raise HTTPException(422, f"Invalid status: {target_status}. "
                            f"Valid: {[s.value for s in TicketStatus]}")

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    old_status = ticket.get("status")

    # Stop any running session if moving to a terminal state
    if target in (TicketStatus.MERGED, TicketStatus.FAILED):
        session_manager.stop_session(ticket_id)

    extra: dict = {"status_changed_at": datetime.now(timezone.utc).isoformat()}
    if target == TicketStatus.MERGED:
        extra["completed_at"] = datetime.now(timezone.utc).isoformat()

    await redis_client.update_ticket_status(ticket_id, old_status, target.value)
    await redis_client.update_ticket_fields(ticket_id, extra)
    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})

    send_kanban_update(ticket.get("project_id", ""))
    _fire_pilot_trigger(ticket.get("project_id", ""), ticket_id)

    return updated


@router.delete("/{ticket_id}", status_code=204)
async def delete_ticket(ticket_id: str):
    from claude_hub.services import clone_manager, session_manager

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    session_manager.stop_session(ticket_id)
    clone_manager.cleanup_clone(ticket_id)
    _cleanup_remote_branch(ticket)

    await redis_client.delete_ticket(ticket_id)
    await broadcast({
        "type": "ticket_deleted",
        "ticket_id": ticket_id,
    })


@router.post("/bulk-delete")
async def bulk_delete_tickets(body: dict):
    """Delete multiple tickets at once. Returns list of deleted IDs."""
    from claude_hub.services import clone_manager, session_manager

    ticket_ids = body.get("ticket_ids", [])
    if not ticket_ids:
        raise HTTPException(422, "ticket_ids required")

    deleted = []
    errors = []
    for tid in ticket_ids:
        ticket = await redis_client.get_ticket(tid)
        if not ticket:
            errors.append({"id": tid, "error": "not found"})
            continue
        try:
            session_manager.stop_session(tid)
            clone_manager.cleanup_clone(tid)
            _cleanup_remote_branch(ticket)
            await redis_client.delete_ticket(tid)
            await broadcast({"type": "ticket_deleted", "ticket_id": tid})
            deleted.append(tid)
        except Exception as e:
            errors.append({"id": tid, "error": str(e)})

    return {"deleted": deleted, "errors": errors}


@router.get("/{ticket_id}/activity")
async def get_activity(ticket_id: str, since: int = Query(0)):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return await redis_client.get_activity(ticket_id, since)


@router.delete("/{ticket_id}/activity")
async def clear_activity(ticket_id: str):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    await redis_client.clear_activity(ticket_id)
    await broadcast({"type": "activity_cleared", "ticket_id": ticket_id})
    return {"status": "cleared"}


@router.post("/{ticket_id}/start")
async def start_ticket(ticket_id: str):
    import asyncio
    from claude_hub.services import clone_manager, session_manager
    from claude_hub.services.ticket_service import InvalidTransition, transition

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    # Guard: check dependencies are all merged
    depends_on = ticket.get("depends_on", [])
    if depends_on:
        for dep_id in depends_on:
            dep = await redis_client.get_ticket(dep_id)
            if not dep or dep.get("status") != "merged":
                dep_title = dep.get("title", dep_id[:8]) if dep else dep_id[:8]
                raise HTTPException(
                    400, f"Cannot start: depends on '{dep_title}' ({dep.get('status', 'missing') if dep else 'not found'}). Must be merged first."
                )

    # Guard: prevent double-start and enforce max sessions
    if session_manager.has_active_session(ticket_id):
        # Ticket is in a startable state but has a leftover tmux session — clean it up
        if ticket["status"] in ("todo", "queued"):
            logger.warning("Ticket %s in %s but has stale tmux session — cleaning up", ticket_id, ticket["status"])
            session_manager.cleanup_session(ticket_id)
        else:
            raise HTTPException(409, "Ticket already has an active session")
    max_sess = await get_max_sessions()
    if session_manager.active_session_count() >= max_sess:
        raise HTTPException(
            429, f"Max concurrent sessions ({max_sess}) reached. Wait for a session to finish."
        )

    # Evict oldest idle sessions if total exceeds limit
    max_total = await get_max_total_sessions()
    evicted = session_manager.evict_idle_sessions(max_total)
    if evicted:
        logger.info("Evicted %d idle session(s) to stay under total limit", len(evicted))

    # Resolve project token
    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "")

    # Clone repo BEFORE transitioning status (so failure doesn't leave ticket stuck)
    try:
        clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
        clone_path = clone_manager.clone_for_ticket(
            ticket["repo_url"], ticket_id,
            ticket["branch"], ticket["base_branch"],
            gh_token=gh_token,
        )
    except Exception as e:
        raise HTTPException(500, f"Clone failed: {e}")

    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   started_at=datetime.now(timezone.utc).isoformat())
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    await redis_client.update_ticket_fields(ticket_id, {"clone_path": clone_path})

    # Start Claude Code session — rollback to TODO if anything fails
    try:
        description = ticket.get("description") or ticket["title"]
        branch = ticket["branch"]
        base_branch = ticket.get("base_branch", "main")
        project_id = ticket.get("project_id", "")
        vision_context = _build_vision_context(project_id)
        task = (
            f"{description}\n\n"
            f"You are working on branch '{branch}' (based on '{base_branch}').\n"
            f"When done, commit your changes, push the branch, and create a draft PR against '{base_branch}'."
            + vision_context
            + _PUSH_VERIFICATION_INSTRUCTION
        )
        session_name, log_path = session_manager.start_session(
            ticket_id, clone_path, task, gh_token=gh_token,
            model="claude-opus-4-6",
        )
        await redis_client.update_ticket_fields(ticket_id, {"tmux_session": session_name})
    except Exception as e:
        logger.error("Session start failed for %s, rolling back to TODO: %s", ticket_id, e)
        session_manager.cleanup_session(ticket_id)  # Kill any partially-created tmux session
        await transition(ticket_id, TicketStatus.TODO, started_at="")
        await broadcast({
            "type": "ticket_updated",
            "ticket_id": ticket_id,
            "data": await redis_client.get_ticket(ticket_id),
        })
        raise HTTPException(500, f"Failed to start session: {e}")

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

    # Send Ctrl+C but keep session alive for inspection
    session_manager.stop_session(ticket_id)
    session_manager.update_session_status(ticket_id, "failed")

    # Record system note
    await append_ticket_note(ticket_id, "system", "Session stopped by user", author="system")

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": await redis_client.get_ticket(ticket_id),
    })

    # Session stopped — process queue
    await process_queue()

    return await redis_client.get_ticket(ticket_id)


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
    import asyncio
    from claude_hub.services import session_manager
    if session_manager.is_alive(ticket_id):
        session_manager.send_input(ticket_id, answer)
    else:
        # Session already finished while blocked — trigger verification directly
        logger.info("Session dead for %s after unblock, triggering verification", ticket_id)
        asyncio.create_task(_verify_and_review(ticket_id))

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/{ticket_id}/message")
async def message_ticket(ticket_id: str, body: dict):
    """Send a message to the Claude Code session. Works for IN_PROGRESS and BLOCKED tickets."""
    from claude_hub.services import session_manager

    message = body.get("message", "")
    if not message:
        raise HTTPException(400, "message required")

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    status = ticket.get("status")
    if status not in ("in_progress", "blocked"):
        raise HTTPException(409, f"Cannot send message to ticket in {status} status")

    if not session_manager.is_alive(ticket_id):
        raise HTTPException(409, "No active session — tmux session does not exist")

    if not session_manager.is_claude_running(ticket_id):
        raise HTTPException(
            409,
            "Claude process has exited — session is at a shell prompt. "
            "Use /request-changes or /retry-ticket to start a new session."
        )

    # If BLOCKED, also unblock
    if status == "blocked":
        from claude_hub.services.ticket_service import transition
        await transition(ticket_id, TicketStatus.IN_PROGRESS, blocked_question="")

    session_manager.send_input(ticket_id, message)

    # Log as activity event
    from datetime import datetime, timezone
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "user",
        "type": "message",
        "summary": f"User: {message[:200]}",
    }
    await redis_client.append_activity(ticket_id, event)
    await broadcast({"type": "activity", "ticket_id": ticket_id, "data": event})

    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
    return updated


@router.post("/{ticket_id}/retry")
async def retry_ticket(ticket_id: str, body: dict | None = None):
    from claude_hub.services import session_manager
    from claude_hub.services.ticket_service import InvalidTransition, transition

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    # Guard: prevent double-start and enforce max sessions
    if session_manager.has_active_session(ticket_id):
        # If ticket is in a retryable state but has a leftover tmux session — clean it up
        if ticket["status"] in ("failed", "todo", "queued"):
            logger.warning("Ticket %s in %s but has stale tmux session — cleaning up", ticket_id, ticket["status"])
            session_manager.cleanup_session(ticket_id)
        else:
            raise HTTPException(409, "Ticket already has an active session")
    max_sess = await get_max_sessions()
    if session_manager.active_session_count() >= max_sess:
        raise HTTPException(
            429, f"Max concurrent sessions ({max_sess}) reached. Wait for a session to finish."
        )

    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   failed_reason="",
                                   agent_review="[]",
                                   started_at=datetime.now(timezone.utc).isoformat())
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        # Orphan recovery: ticket stuck in IN_PROGRESS with no live session
        ticket = await redis_client.get_ticket(ticket_id)
        if ticket and ticket.get("status") == "in_progress" and not session_manager.has_active_session(ticket_id):
            await redis_client.update_ticket_fields(ticket_id, {
                "failed_reason": "",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status_changed_at": datetime.now(timezone.utc).isoformat(),
            })
            updated = await redis_client.get_ticket(ticket_id)
        else:
            raise HTTPException(409, str(e))

    # Re-spawn session
    import asyncio
    from claude_hub.services import clone_manager

    ticket = await redis_client.get_ticket(ticket_id)
    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "")

    clone_path = ticket.get("clone_path")
    if not clone_path or not Path(clone_path).exists():
        clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
        clone_path = clone_manager.clone_for_ticket(
            ticket["repo_url"], ticket_id,
            ticket["branch"], ticket["base_branch"],
            gh_token=gh_token,
        )
        await redis_client.update_ticket_fields(ticket_id, {"clone_path": clone_path})

    guidance = (body or {}).get("guidance", "")
    description = ticket.get("description") or ticket["title"]
    branch = ticket["branch"]
    base_branch = ticket.get("base_branch", "main")
    project_id = ticket.get("project_id", "")
    vision_context = _build_vision_context(project_id)

    has_pr = bool(ticket.get("pr_url"))
    pr_instruction = (
        f"A PR already exists — do NOT create a new one, just push to the same branch."
        if has_pr else
        f"When done, commit your changes, push the branch, and create a draft PR against '{base_branch}'."
    )
    task = (
        f"{description}\n\n"
        f"You are working on branch '{branch}' (based on '{base_branch}').\n"
        f"{pr_instruction}"
        + vision_context
        + _PUSH_VERIFICATION_INSTRUCTION
    )

    # Auto-include CI failure reason as context for retry
    failed_reason = ticket.get("failed_reason", "")
    if failed_reason and "CI failed" in failed_reason:
        ci_context = f"\n\n## Previous CI Failure\nThe previous attempt failed CI checks. Fix the issues below:\n{failed_reason}"
        task = f"{task}{ci_context}"

    if guidance:
        task = f"{task}\n\nAdditional guidance: {guidance}"

    session_name, log_path = session_manager.start_session(
        ticket_id, clone_path, task, gh_token=gh_token,
        model="claude-opus-4-6",
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


MAX_REVIEW_ROUNDS = 3


async def _run_contextual_review(ticket_id: str, ticket_agent, agent_cfg: dict) -> None:
    """Run review using TicketAgent that already watched the session (has full context)."""
    from claude_hub.services.ticket_service import transition
    from claude_hub.services.agent_review import _record_activity

    try:
        await transition(ticket_id, TicketStatus.REVIEWING)
        await broadcast({
            "type": "ticket_updated",
            "ticket_id": ticket_id,
            "data": await redis_client.get_ticket(ticket_id),
        })
    except Exception as e:
        logger.warning("Failed to transition %s to REVIEWING: %s", ticket_id, e)
        return

    await _record_activity(ticket_id, "review", "Starting code review (TicketAgent with full session context)...")

    try:
        result = await ticket_agent.review()
    except Exception as e:
        logger.error("TicketAgent review failed for %s: %s", ticket_id, e)
        result = {
            "verdict": "approve",
            "scores": {"correctness": 5, "security": 5, "quality": 5, "completeness": 5},
            "summary": f"Review error: {e}. Auto-approving for human review.",
            "issues": [],
            "feedback": "",
        }

    # Record review result (same format as cold review)
    import json as _json
    from datetime import datetime, timezone
    ticket = await redis_client.get_ticket(ticket_id)
    history = ticket.get("agent_review") or []
    if isinstance(history, str):
        try:
            history = _json.loads(history)
        except (ValueError, TypeError):
            history = []
    if not isinstance(history, list):
        history = [history]
    entry = {
        "round": len(history) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "contextual": True,  # flag: this review had full session context
        **result,
    }
    history.append(entry)
    await redis_client.update_ticket_fields(ticket_id, {
        "agent_review": _json.dumps(history),
    })

    verdict = result.get("verdict", "approve")
    summary = result.get("summary", "")
    issues = result.get("issues", [])
    critical = sum(1 for i in issues if i.get("severity") == "critical")
    major = sum(1 for i in issues if i.get("severity") == "major")

    if verdict == "approve":
        await _record_activity(ticket_id, "review",
                               f"Review APPROVED: {summary} (issues: {critical} critical, {major} major)")
        try:
            updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE)
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": ticket_id,
                "data": updated,
            })
            await process_queue()
        except Exception as e:
            logger.error("Failed to transition %s to AWAITING_MERGE after approval: %s", ticket_id, e)
    else:
        await _record_activity(ticket_id, "review",
                               f"Review REJECTED: {summary} (issues: {critical} critical, {major} major)")
        # Rejected — same flow as cold review: respawn with feedback
        feedback = result.get("feedback", "Address the review issues.")
        try:
            await _respawn_with_feedback(ticket_id, feedback)
        except Exception as e:
            logger.error("Failed to respawn session for %s after rejection: %s", ticket_id, e)
            try:
                updated = await transition(ticket_id, TicketStatus.FAILED,
                                           failed_reason=f"Review rejected, respawn failed: {e}")
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket_id,
                    "data": updated,
                })
                await process_queue()
            except Exception:
                pass

    # Append structured review note
    issues_text = ""
    if issues:
        issues_text = "\n".join(
            f"- [{i.get('severity', '?')}] {i.get('file', '?')}: {i.get('description', '')}"
            for i in issues[:5]
        )
    note_content = f"{'APPROVED' if verdict == 'approve' else 'REJECTED'} (contextual review): {summary}"
    if issues_text:
        note_content += f"\n{issues_text}"
    await append_ticket_note(ticket_id, "review", note_content, author="ticket_agent")


async def _try_qa_agent_review(ticket_id: str, ticket: dict, verify_result) -> bool:
    """Try to review using QA Agent CC (-p one-shot). Returns True if review was performed."""
    from claude_hub.services.qa_session import ask_qa
    from claude_hub.services.ticket_service import transition
    from claude_hub.services.agent_review import _record_activity

    project_id = ticket.get("project_id", "")

    # Get diff for review
    clone_path = ticket.get("clone_path", "")
    if not clone_path:
        return False

    try:
        import subprocess
        diff_result = subprocess.run(
            ["git", "diff", f"origin/{ticket['base_branch']}...{ticket['branch']}", "--stat"],
            cwd=clone_path, capture_output=True, text=True, timeout=30,
        )
        diff_stat = diff_result.stdout[:2000] if diff_result.returncode == 0 else "(diff unavailable)"

        diff_result2 = subprocess.run(
            ["git", "diff", f"origin/{ticket['base_branch']}...{ticket['branch']}"],
            cwd=clone_path, capture_output=True, text=True, timeout=30,
        )
        diff_content = diff_result2.stdout[:30000] if diff_result2.returncode == 0 else ""
    except Exception:
        diff_stat = "(diff unavailable)"
        diff_content = ""

    try:
        await transition(ticket_id, TicketStatus.REVIEWING)
        await broadcast({
            "type": "ticket_updated",
            "ticket_id": ticket_id,
            "data": await redis_client.get_ticket(ticket_id),
        })
    except Exception:
        pass

    await _record_activity(ticket_id, "review", "Starting code review (QA Agent CC)...")

    # Build review prompt
    prompt = f"""Review this code change for ticket: {ticket.get('title', 'Unknown')}

Description: {ticket.get('description', 'N/A')[:500]}

Diff stats:
{diff_stat}

Diff:
{diff_content[:20000]}

Respond with ONLY a JSON object (no markdown, no commentary):
{{"verdict": "approve" or "reject", "summary": "1-2 sentence review summary", "issues": [{{"severity": "critical|major|minor", "file": "path", "description": "issue"}}], "feedback": "if rejecting, what to fix"}}

Rules:
- approve if the code reasonably addresses the ticket description
- reject only for critical issues (bugs, security, missing core functionality)
- be pragmatic — minor style issues are not grounds for rejection"""

    # Run one-shot QA Agent review
    project = await redis_client.get_project(project_id)
    gh_token = project.get("gh_token", "") if project else ""
    response = await ask_qa(prompt, cwd=clone_path, gh_token=gh_token, timeout=120)
    if not response:
        logger.warning("QA Agent review timeout for %s", ticket_id)
        # Timeout — approve to avoid blocking
        try:
            updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE,
                                       pr_url=verify_result.pr_url,
                                       pr_number=verify_result.pr_number)
            await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
            await process_queue()
        except Exception:
            pass
        return True

    # Parse review result
    from claude_hub.services.pilot_agent import PilotAgent
    result = PilotAgent._try_parse_json(response)
    if not result:
        logger.warning("QA Agent review returned unparseable response for %s", ticket_id)
        # Unparseable — approve to avoid blocking
        try:
            updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE,
                                       pr_url=verify_result.pr_url,
                                       pr_number=verify_result.pr_number)
            await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
            await process_queue()
        except Exception:
            pass
        return True

    verdict = result.get("verdict", "approve")
    summary = result.get("summary", "")
    issues = result.get("issues", [])

    if verdict == "approve":
        await _record_activity(ticket_id, "review", f"QA Agent APPROVED: {summary}")
        try:
            updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE,
                                       pr_url=verify_result.pr_url,
                                       pr_number=verify_result.pr_number)
            await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
            await process_queue()
        except Exception as e:
            logger.error("Failed to transition %s after QA approval: %s", ticket_id, e)
    else:
        await _record_activity(ticket_id, "review", f"QA Agent REJECTED: {summary}")
        feedback = result.get("feedback", "Address the review issues.")
        try:
            await _respawn_with_feedback(ticket_id, feedback)
        except Exception as e:
            logger.error("Failed to respawn %s after QA rejection: %s", ticket_id, e)
            try:
                updated = await transition(ticket_id, TicketStatus.FAILED,
                                           failed_reason=f"QA review rejected, respawn failed: {e}")
                await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
                await process_queue()
            except Exception:
                pass

    # Record review note
    note_content = f"{'APPROVED' if verdict == 'approve' else 'REJECTED'} (QA Agent CC): {summary}"
    await append_ticket_note(ticket_id, "review", note_content, author="qa_agent")

    return True


async def _run_agent_review(ticket_id: str, agent_cfg: dict) -> None:
    """Run agent code review. On approve → REVIEW, on reject → spawn new session."""
    from claude_hub.services.agent_review import review_pr
    from claude_hub.services.ticket_service import transition

    # Derive review round from agent_review history length
    ticket = await redis_client.get_ticket(ticket_id)
    history = ticket.get("agent_review") or []
    if isinstance(history, str):
        import json as _json
        try:
            history = _json.loads(history)
        except (ValueError, TypeError):
            history = []
    if not isinstance(history, list):
        history = []
    review_round = len(history) + 1  # this round will be appended by review_pr()

    if review_round > MAX_REVIEW_ROUNDS:
        logger.warning("Ticket %s hit max review rounds (%d), marking as failed for human attention",
                        ticket_id, MAX_REVIEW_ROUNDS)
        from claude_hub.services.agent_review import _record_activity
        await _record_activity(ticket_id, "warning",
                               f"Agent review failed {MAX_REVIEW_ROUNDS} times. Needs human review — check the PR directly.")
        try:
            updated = await transition(ticket_id, TicketStatus.FAILED,
                                       failed_reason=f"Agent review rejected {MAX_REVIEW_ROUNDS} times. "
                                                     "Manual review required — check the PR and use 'Mark Ready' if acceptable.")
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": ticket_id,
                "data": updated,
            })
        except Exception as e:
            logger.error("Failed to transition %s to FAILED after max rounds: %s", ticket_id, e)
        return

    try:
        await transition(ticket_id, TicketStatus.REVIEWING)
        await broadcast({
            "type": "ticket_updated",
            "ticket_id": ticket_id,
            "data": await redis_client.get_ticket(ticket_id),
        })
    except Exception as e:
        logger.warning("Failed to transition %s to REVIEWING: %s", ticket_id, e)
        return

    ticket = await redis_client.get_ticket(ticket_id)
    result = await review_pr(ticket_id, ticket, agent_settings=agent_cfg)
    verdict = result.get("verdict", "approve")

    if verdict == "approve":
        try:
            updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE)
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": ticket_id,
                "data": updated,
            })
            # Session freed a slot — process queue
            await process_queue()
        except Exception as e:
            logger.error("Failed to transition %s to REVIEW after approval: %s", ticket_id, e)
    else:
        # Rejected — spawn new session with feedback (like request_changes)
        feedback = result.get("feedback", "Address the review issues.")
        try:
            await _respawn_with_feedback(ticket_id, feedback)
        except Exception as e:
            logger.error("Failed to respawn session for %s after rejection: %s", ticket_id, e)
            try:
                updated = await transition(ticket_id, TicketStatus.FAILED,
                                           failed_reason=f"Review rejected, respawn failed: {e}")
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket_id,
                    "data": updated,
                })
                await process_queue()
            except Exception:
                pass


async def _respawn_with_feedback(ticket_id: str, feedback: str) -> None:
    """Transition REVIEWING → IN_PROGRESS and spawn a new Claude Code session."""
    import asyncio
    from claude_hub.services import clone_manager, session_manager
    from claude_hub.services.ticket_service import transition
    from pathlib import Path

    # Guard: enforce max sessions
    max_sess = await get_max_sessions()
    if session_manager.active_session_count() >= max_sess:
        logger.warning("Cannot respawn %s: max sessions reached", ticket_id)
        updated = await transition(ticket_id, TicketStatus.FAILED,
                                   failed_reason="Review rejected but max sessions reached. Retry manually.")
        await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
        return

    updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                               started_at=datetime.now(timezone.utc).isoformat())
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})

    ticket = await redis_client.get_ticket(ticket_id)
    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "")

    clone_path = ticket.get("clone_path")
    if not clone_path or not Path(clone_path).exists():
        clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
        clone_path = clone_manager.clone_for_ticket(
            ticket["repo_url"], ticket_id,
            ticket["branch"], ticket["base_branch"],
            gh_token=gh_token,
        )
        await redis_client.update_ticket_fields(ticket_id, {"clone_path": clone_path})

    original_task = ticket.get("description") or ticket["title"]
    pr_number = ticket.get("pr_number", "")
    project_id = ticket.get("project_id", "")
    vision_context = _build_vision_context(project_id)
    task = (
        f"{original_task}\n\n"
        f"## Agent Review Feedback — Address These Issues:\n{feedback}\n\n"
        f"You are on branch {ticket['branch']} which already has your previous work.\n"
        f"Read the existing code, address the review feedback above, commit, push, "
        f"and update the PR."
    )
    if pr_number:
        task += f"\nDo NOT create a new PR — push to the same branch so the existing PR #{pr_number} is updated."
    task += vision_context
    task += _PUSH_VERIFICATION_INSTRUCTION

    session_name, log_path = session_manager.start_session(
        ticket_id, clone_path, task, gh_token=gh_token,
        model="claude-opus-4-6",
    )
    await redis_client.update_ticket_fields(ticket_id, {"tmux_session": session_name})
    asyncio.create_task(_tail_and_broadcast(ticket_id, log_path))


async def _verify_and_review(ticket_id: str, ticket_agent=None) -> None:
    """Run verification + review flow after a session ends.

    If ticket_agent is provided (TicketAgent with full conversation context),
    it will be used for review instead of a cold LLM call.
    """
    from claude_hub.services.ticket_service import transition

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket or ticket.get("status") in ("blocked", "todo", "queued", "failed"):
        return  # Don't verify if blocked/rolled-back/already-failed

    logger.info("Running verification for ticket %s", ticket_id)

    try:
        await transition(ticket_id, TicketStatus.VERIFYING)
        await broadcast({
            "type": "ticket_updated",
            "ticket_id": ticket_id,
            "data": await redis_client.get_ticket(ticket_id),
        })
    except Exception:
        pass

    # Load per-project agent settings
    from claude_hub.routers.settings_router import get_agent_settings_for_project
    project = await _get_project_for_ticket(ticket)
    agent_cfg = await get_agent_settings_for_project(ticket.get("project_id", ""))
    agent_enabled = agent_cfg.get("enabled", True)

    # Run safety net + verification
    from claude_hub.services.github_verify import ensure_pushed, verify_agent_work
    clone_path = ticket.get("clone_path", "")
    if clone_path:
        gh_token = project.get("gh_token", "")
        actions = ensure_pushed(clone_path, ticket["branch"], ticket["base_branch"], gh_token)
        if actions:
            logger.info("ensure_pushed for %s: %s", ticket_id, actions)

        import subprocess
        subprocess.run(["git", "fetch", "origin"], cwd=clone_path, capture_output=True)

        result = verify_agent_work(clone_path, ticket["branch"], ticket["base_branch"], gh_token)
        logger.info("Verification for %s: %s", ticket_id, result)

        if result.passed:
            await redis_client.update_ticket_fields(ticket_id, {
                "pr_url": result.pr_url or "",
                "pr_number": result.pr_number or 0,
                "has_conflicts": "False",  # Clear conflict flag after successful session
            })
            from claude_hub.services.github_verify import mark_pr_ready
            mark_pr_ready(clone_path, ticket["branch"], gh_token)

            # Record progress note
            await append_ticket_note(
                ticket_id, "progress",
                f"Session completed. PR #{result.pr_number or 'N/A'} ready for review.",
                author="claude_code",
            )

            if agent_enabled and agent_cfg.get("api_key") and ticket_agent:
                # Use the TicketAgent that watched the session — it has full context
                await _run_contextual_review(ticket_id, ticket_agent, agent_cfg)
            else:
                # Try QA Agent CC fallback for review (zero API cost)
                qa_reviewed = await _try_qa_agent_review(ticket_id, ticket, result)
                if not qa_reviewed:
                    # No QA Agent available — go straight to AWAITING_MERGE
                    updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE,
                                               pr_url=result.pr_url,
                                               pr_number=result.pr_number)
                    await broadcast({
                        "type": "ticket_updated",
                        "ticket_id": ticket_id,
                        "data": updated,
                    })
                    await process_queue()
        else:
            # Record blocker note
            await append_ticket_note(
                ticket_id, "blocker",
                f"Verification failed: {result.reason}",
                author="claude_code",
            )

            updated = await transition(ticket_id, TicketStatus.FAILED,
                                       failed_reason=result.reason)
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": ticket_id,
                "data": updated,
            })
            await process_queue()


async def _tail_and_broadcast(ticket_id: str, log_path: str) -> None:
    """Background task: tail log with optional TicketAgent supervision."""
    from claude_hub.services.ticket_service import transition

    try:
        # Load per-project agent settings
        from claude_hub.routers.settings_router import get_agent_settings_for_project
        ticket = await redis_client.get_ticket(ticket_id)
        agent_cfg = await get_agent_settings_for_project(ticket.get("project_id", "") if ticket else "")
        agent_enabled = agent_cfg.get("enabled", True)

        ticket_agent = None
        if agent_enabled and agent_cfg.get("api_key"):
            # Agent mode: TicketAgent handles tailing + broadcasting + intervention
            from claude_hub.services.ticket_agent import TicketAgent
            ticket_agent = TicketAgent(ticket_id, ticket, agent_settings=agent_cfg)
            await ticket_agent.run(log_path)
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

        # Session ended — clean up tmux and run verification
        from claude_hub.services import session_manager as _sm
        _sm.cleanup_session(ticket_id)

        await _verify_and_review(ticket_id, ticket_agent=ticket_agent)

    except Exception as e:
        logger.error("Error tailing log for ticket %s: %s", ticket_id, e)
        # Clean up tmux on error too
        try:
            from claude_hub.services import session_manager as _sm2
            _sm2.cleanup_session(ticket_id)
        except Exception:
            pass
        # If session errored out and ticket is still in_progress, mark as failed
        try:
            ticket = await redis_client.get_ticket(ticket_id)
            if ticket and ticket.get("status") in ("in_progress", "verifying", "reviewing"):
                from claude_hub.services.ticket_service import transition as _transition
                updated = await _transition(
                    ticket_id, TicketStatus.FAILED,
                    failed_reason=f"Session error: {e}",
                )
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket_id,
                    "data": updated,
                })
        except Exception:
            logger.error("Failed to mark ticket %s as failed after error", ticket_id)
        # Session freed a slot — process queue
        try:
            await process_queue()
        except Exception:
            pass


@router.post("/{ticket_id}/mark-review")
async def mark_review(ticket_id: str):
    from claude_hub.services.ticket_service import InvalidTransition, transition
    try:
        updated = await transition(ticket_id, TicketStatus.AWAITING_MERGE)
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


@router.post("/{ticket_id}/resolve-conflicts")
async def resolve_conflicts(ticket_id: str):
    """Auto-trigger a Claude Code session to rebase and resolve merge conflicts."""
    from claude_hub.services import session_manager
    if session_manager.has_active_session(ticket_id):
        logger.info("Skipping resolve_conflicts for %s: session already active", ticket_id)
        return {"status": "already_resolving"}

    CONFLICT_FEEDBACK = (
        "The PR has merge conflicts with the base branch. You must:\n"
        "1. Run `git fetch origin` to get the latest changes\n"
        "2. Run `git rebase origin/main` (or the correct base branch)\n"
        "3. Resolve any merge conflicts\n"
        "4. Run `git push --force-with-lease` to update the PR\n"
        "Do NOT create a new PR. Fix conflicts on this branch."
    )
    # Reset agent_review history — conflict resolution is a fresh session,
    # review count should not carry over from previous rounds
    await redis_client.update_ticket_fields(ticket_id, {"agent_review": "[]"})
    # Delegate to request_changes with pre-filled conflict feedback
    return await request_changes(ticket_id, {"feedback": CONFLICT_FEEDBACK})


@router.post("/{ticket_id}/request-changes")
async def request_changes(ticket_id: str, body: dict):
    """Send ticket back to IN_PROGRESS with review feedback for a new Claude Code session."""
    import asyncio
    from claude_hub.services import clone_manager, session_manager
    from claude_hub.services.ticket_service import InvalidTransition, transition

    feedback = body.get("feedback", "")
    if not feedback:
        raise HTTPException(400, "feedback required")

    # Guard: enforce max sessions
    max_sess = await get_max_sessions()
    if session_manager.active_session_count() >= max_sess:
        raise HTTPException(
            429, f"Max concurrent sessions ({max_sess}) reached."
        )

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    # Stop any existing session before starting a new one
    session_manager.stop_session(ticket_id)

    current_status = ticket.get("status")
    if current_status != TicketStatus.IN_PROGRESS:
        try:
            updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                       started_at=datetime.now(timezone.utc).isoformat())
        except InvalidTransition as e:
            raise HTTPException(409, str(e))
    else:
        # Already in_progress — just update started_at for the new session
        await redis_client.update_ticket_fields(ticket_id, {
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    ticket = await redis_client.get_ticket(ticket_id)
    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "")

    clone_path = ticket.get("clone_path")
    if not clone_path or not Path(clone_path).exists():
        clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
        clone_path = clone_manager.clone_for_ticket(
            ticket["repo_url"], ticket_id,
            ticket["branch"], ticket["base_branch"],
            gh_token=gh_token,
        )
        await redis_client.update_ticket_fields(ticket_id, {"clone_path": clone_path})

    # Build task with original description + review feedback
    original_task = ticket.get("description") or ticket["title"]
    pr_number = ticket.get("pr_number", "")
    project_id = ticket.get("project_id", "")
    vision_context = _build_vision_context(project_id)
    task = (
        f"{original_task}\n\n"
        f"## Review Feedback — Address These Issues:\n{feedback}\n\n"
        f"You are on branch {ticket['branch']} which already has your previous work.\n"
        f"Read the existing code, address the review feedback above, commit, push, "
        f"and update the PR."
    )
    if pr_number:
        task += f"\nDo NOT create a new PR — push to the same branch so the existing PR #{pr_number} is updated."

    # Auto-resolve conversations if enabled
    from claude_hub.routers.settings_router import get_agent_settings_for_project
    agent_cfg = await get_agent_settings_for_project(ticket.get("project_id", ""))
    if agent_cfg.get("auto_resolve_conversations") and pr_number:
        repo_url = project.get("repo_url", "")
        from claude_hub.services.webhook_registration import _parse_owner_repo
        parsed = _parse_owner_repo(repo_url)
        if parsed:
            threads = _get_unresolved_threads(parsed[0], parsed[1], pr_number, gh_token)
            if threads:
                resolve_section = "\n\n## Resolve Review Conversations\n"
                resolve_section += (
                    "After addressing ALL the feedback above and pushing your changes, "
                    "resolve each conversation thread using the GitHub GraphQL API.\n"
                    "For each thread below, run:\n"
                    "```\n"
                    'gh api graphql -f query=\'mutation { resolveReviewThread(input: {threadId: "THREAD_ID"}) { thread { isResolved } } }\'\n'
                    "```\n\n"
                    "Threads to resolve (ONLY after you have addressed the corresponding feedback):\n"
                )
                for t in threads:
                    resolve_section += f"- Thread `{t['thread_id']}` — {t['author']} on `{t['path']}`: {t['body'][:100]}\n"
                task += resolve_section

    task += vision_context
    task += _PUSH_VERIFICATION_INSTRUCTION

    try:
        session_name, log_path = session_manager.start_session(
            ticket_id, clone_path, task, gh_token=gh_token,
            model="claude-opus-4-6",
        )
    except Exception as e:
        from claude_hub.services.ticket_service import transition as _tr
        await _tr(ticket_id, TicketStatus.FAILED, failed_reason=f"Session start failed: {e}")
        updated = await redis_client.get_ticket(ticket_id)
        await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
        raise HTTPException(500, f"Session start failed: {e}")

    await redis_client.update_ticket_fields(ticket_id, {"tmux_session": session_name})
    asyncio.create_task(_tail_and_broadcast(ticket_id, log_path))

    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/bulk-start")
async def bulk_start_tickets(body: dict):
    """Start multiple tickets. Those that fit within max_sessions start immediately;
    the rest are queued and auto-started when sessions complete."""
    from claude_hub.services import session_manager

    ticket_ids = body.get("ticket_ids", [])
    if not ticket_ids or not isinstance(ticket_ids, list):
        raise HTTPException(400, "ticket_ids required (array)")

    started = []
    queued = []
    max_sess = await get_max_sessions()

    for tid in ticket_ids:
        ticket = await redis_client.get_ticket(tid)
        if not ticket:
            continue
        if ticket.get("status") not in ("todo",):
            continue

        # Check dependencies
        depends_on = ticket.get("depends_on", [])
        if depends_on:
            deps_met = True
            for dep_id in depends_on:
                dep = await redis_client.get_ticket(dep_id)
                if not dep or dep.get("status") != "merged":
                    deps_met = False
                    break
            if not deps_met:
                continue

        # Try to start immediately if under limit
        priority = ticket.get("priority", 0)
        if (session_manager.active_session_count() < max_sess
                and not session_manager.has_active_session(tid)):
            try:
                result = await start_ticket(tid)
                started.append(tid)
            except HTTPException:
                # Failed to start — queue it instead
                await _enqueue_ticket(tid, priority=priority)
                queued.append(tid)
        else:
            await _enqueue_ticket(tid, priority=priority)
            queued.append(tid)

    return {"started": started, "queued": queued}


async def _enqueue_ticket(ticket_id: str, priority: int = 0) -> None:
    """Transition a TODO ticket to QUEUED and add to the Redis queue."""
    from claude_hub.services.ticket_service import InvalidTransition, transition

    try:
        updated = await transition(ticket_id, TicketStatus.QUEUED)
    except (InvalidTransition, ValueError):
        return
    await redis_client.enqueue_tickets([ticket_id], priorities=[priority])
    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })


async def process_queue() -> str | None:
    """Try to start the next queued ticket. Called when a session completes."""
    from claude_hub.services import session_manager
    from claude_hub.services.ticket_service import transition

    # Iterative loop instead of recursion to avoid stack overflow
    max_sess = await get_max_sessions()
    for _ in range(50):  # Safety limit
        if session_manager.active_session_count() >= max_sess:
            return None

        ticket_id = await redis_client.dequeue_ticket()
        if not ticket_id:
            return None

        ticket = await redis_client.get_ticket(ticket_id)
        if not ticket or ticket.get("status") != "queued":
            continue  # Skip invalid, try next

        try:
            await transition(ticket_id, TicketStatus.TODO)
        except Exception:
            continue  # Skip failed transition, try next

        try:
            await start_ticket(ticket_id)
            return ticket_id
        except HTTPException:
            continue  # Skip failed start, try next

    return None


@router.get("/queue")
async def get_queue():
    """Get the current queue of tickets waiting to start."""
    from claude_hub.services import session_manager
    queue_ids = await redis_client.get_queue()
    return {
        "queue": queue_ids,
        "active_sessions": session_manager.active_session_count(),
        "max_sessions": await get_max_sessions(),
    }


@router.delete("/queue/{ticket_id}")
async def remove_from_queue(ticket_id: str):
    """Remove a ticket from the queue and revert to TODO."""
    from claude_hub.services.ticket_service import InvalidTransition, transition

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.get("status") != "queued":
        raise HTTPException(409, "Ticket is not queued")

    await redis_client.remove_from_queue(ticket_id)
    try:
        updated = await transition(ticket_id, TicketStatus.TODO)
    except (InvalidTransition, ValueError) as e:
        raise HTTPException(409, str(e))

    await broadcast({
        "type": "ticket_updated",
        "ticket_id": ticket_id,
        "data": updated,
    })
    return updated


@router.post("/reorder")
async def reorder_tickets(body: dict):
    """Reorder TODO tickets by setting priority based on position in the list."""
    project_id = body.get("project_id")
    ticket_ids = body.get("ticket_ids", [])
    if not ticket_ids or not isinstance(ticket_ids, list):
        raise HTTPException(400, "ticket_ids required (array)")

    # Validate all ticket_ids exist and belong to the project
    for tid in ticket_ids:
        if not isinstance(tid, str):
            raise HTTPException(400, "ticket_ids must be strings")
        t = await redis_client.get_ticket(tid)
        if not t:
            raise HTTPException(404, f"Ticket {tid[:8]} not found")
        if project_id and t.get("project_id") != project_id:
            raise HTTPException(400, f"Ticket {tid[:8]} does not belong to project")

    for index, tid in enumerate(ticket_ids):
        await redis_client.update_ticket_fields(tid, {"priority": index})

    return {"ok": True}


@router.post("/queue/reorder")
async def reorder_queue(body: dict):
    """Reorder queued tickets. Updates both queue scores and ticket priorities."""
    ticket_ids = body.get("ticket_ids", [])
    if not ticket_ids or not isinstance(ticket_ids, list):
        raise HTTPException(400, "ticket_ids required (array)")

    for tid in ticket_ids:
        if not isinstance(tid, str):
            raise HTTPException(400, "ticket_ids must be strings")
        t = await redis_client.get_ticket(tid)
        if not t:
            raise HTTPException(404, f"Ticket {tid[:8]} not found")
        if t.get("status") != "queued":
            raise HTTPException(409, f"Ticket {tid[:8]} is not queued")

    # Re-score with position-based priorities (0, 1, 2...) to maintain order
    await redis_client.reorder_queue(ticket_ids)

    # Also update the priority field on each ticket for display
    for index, tid in enumerate(ticket_ids):
        await redis_client.update_ticket_fields(tid, {"priority": index})

    # Broadcast updated tickets
    for tid in ticket_ids:
        updated = await redis_client.get_ticket(tid)
        await broadcast({
            "type": "ticket_updated",
            "ticket_id": tid,
            "data": updated,
        })

    return {"ok": True}


@router.post("/sync-review-status")
async def sync_review_status():
    """Check GitHub for any review tickets whose PRs have been merged externally."""
    import json as _json
    import os
    import subprocess
    from claude_hub.services.ticket_service import transition

    review_tickets = await redis_client.list_tickets("awaiting_merge")
    synced = []
    for ticket in review_tickets:
        pr_number = ticket.get("pr_number")
        clone_path = ticket.get("clone_path", "")
        if not pr_number or not clone_path:
            continue

        project = await _get_project_for_ticket(ticket)
        gh_token = project.get("gh_token", "") or settings.gh_token
        env = {**os.environ, "GH_TOKEN": gh_token} if gh_token else None

        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "state,mergedAt,mergeable"],
            cwd=clone_path, capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            continue

        try:
            pr_data = _json.loads(result.stdout)
        except _json.JSONDecodeError:
            continue

        if pr_data.get("state") == "MERGED":
            try:
                updated = await transition(
                    ticket["id"], TicketStatus.MERGED,
                    completed_at=pr_data.get("mergedAt") or datetime.now(timezone.utc).isoformat(),
                )
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket["id"],
                    "data": updated,
                })
                synced.append(ticket["id"])
                _fire_pilot_trigger(ticket.get("project_id", ""), ticket["id"])
            except Exception:
                pass
        else:
            # Check for merge conflicts (mergeable = "CONFLICTING")
            mergeable = pr_data.get("mergeable", "")
            now_conflicted = mergeable == "CONFLICTING"
            was_conflicted = _is_conflicted(ticket)

            if now_conflicted != was_conflicted:
                await redis_client.update_ticket_fields(
                    ticket["id"], {"has_conflicts": str(now_conflicted)}
                )
                updated = await redis_client.get_ticket(ticket["id"])
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket["id"],
                    "data": updated,
                })

            # Trigger conflict resolution if conflicts exist and no session is working on it
            if now_conflicted:
                from claude_hub.services import session_manager
                if not session_manager.has_active_session(ticket["id"]):
                    await broadcast({
                        "type": "notification",
                        "data": {
                            "level": "warning",
                            "title": f"Auto-resolving conflicts for #{ticket.get('seq', '?')}",
                            "message": "Merge conflict detected. Starting auto-resolution session.",
                            "ticket_id": ticket["id"],
                        },
                    })
                    try:
                        await resolve_conflicts(ticket["id"])
                        logger.info("Auto-triggered conflict resolution for ticket %s", ticket["id"])
                    except Exception as e:
                        logger.warning("Auto-resolve failed for %s: %s", ticket["id"], e)

    # When tickets were merged, update other review branches with latest base
    if synced:
        from claude_hub.routers.webhooks import _update_review_branches
        for merged_id in synced:
            merged_ticket = await redis_client.get_ticket(merged_id)
            if merged_ticket:
                base = merged_ticket.get("base_branch", "main")
                pr_num = merged_ticket.get("pr_number", 0)
                import asyncio
                asyncio.create_task(_update_review_branches(pr_num, base))

    return {"synced": synced}


@router.post("/{ticket_id}/sync-reviews")
async def sync_pr_reviews(ticket_id: str):
    """Fetch all PR reviews and comments from GitHub and sync as ticket notes."""
    import json as _json
    import os
    import subprocess

    from claude_hub.services.ticket_service import append_ticket_note

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    pr_number = ticket.get("pr_number")
    if not pr_number:
        return {"synced": 0, "message": "No PR linked to this ticket"}

    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "") or settings.gh_token
    repo_url = project.get("repo_url", "")
    if not gh_token or not repo_url:
        return {"synced": 0, "message": "No GitHub token or repo URL"}

    # Parse owner/repo
    from claude_hub.services.webhook_registration import _parse_owner_repo
    parsed = _parse_owner_repo(repo_url)
    if not parsed:
        return {"synced": 0, "message": f"Cannot parse repo URL: {repo_url}"}
    owner, repo = parsed
    env = {**os.environ, "GH_TOKEN": gh_token}

    # Get existing notes to deduplicate
    existing_notes = ticket.get("notes")
    if isinstance(existing_notes, str):
        try:
            existing_notes = _json.loads(existing_notes)
        except _json.JSONDecodeError:
            existing_notes = []
    existing_notes = existing_notes or []
    existing_contents = {n.get("content", "") for n in existing_notes}

    synced_count = 0

    # 1. Fetch PR reviews (approve/reject/comment)
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
         "--jq", '[.[] | {id: .id, state: .state, body: .body, user: .user.login, submitted_at: .submitted_at}]'],
        capture_output=True, text=True, env=env,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            reviews = _json.loads(result.stdout)
        except _json.JSONDecodeError:
            reviews = []

        for review in reviews:
            body = (review.get("body") or "").strip()
            state = review.get("state", "").upper()
            user = review.get("user", "unknown")

            # Update review_status from latest non-comment review
            if state in ("APPROVED", "CHANGES_REQUESTED"):
                await redis_client.update_ticket_fields(ticket_id, {
                    "review_status": state.lower(),
                    "reviewer": user,
                })

            if not body:
                continue
            note = f"PR review ({state}) by {user}:\n{body}"
            if note not in existing_contents:
                await append_ticket_note(ticket_id, "review", note, author=user)
                existing_contents.add(note)
                synced_count += 1

    # 2. Fetch PR review comments (inline diff comments)
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
         "--jq", '[.[] | {id: .id, body: .body, path: .path, user: .user.login, created_at: .created_at}]'],
        capture_output=True, text=True, env=env,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            comments = _json.loads(result.stdout)
        except _json.JSONDecodeError:
            comments = []

        for comment in comments:
            body = (comment.get("body") or "").strip()
            user = comment.get("user", "unknown")
            path = comment.get("path", "")
            if not body:
                continue
            note = f"Review comment by {user} on `{path}`:\n{body}" if path else f"Review comment by {user}:\n{body}"
            if note not in existing_contents:
                await append_ticket_note(ticket_id, "review", note, author=user)
                existing_contents.add(note)
                synced_count += 1

    # Also sync unresolved thread count
    threads = _get_unresolved_threads(owner, repo, pr_number, gh_token)
    await redis_client.update_ticket_fields(ticket_id, {
        "unresolved_thread_count": str(len(threads))
    })

    # Broadcast update
    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})

    # Auto-trigger request-changes if unresolved threads and setting enabled
    auto_dispatched = False
    if threads and updated and updated.get("status") == "awaiting_merge":
        from claude_hub.routers.settings_router import get_agent_settings_for_project
        agent_cfg = await get_agent_settings_for_project(updated.get("project_id", ""))
        if agent_cfg.get("auto_resolve_conversations"):
            feedback_lines = ["Address these unresolved review conversations:\n"]
            for t in threads:
                path_info = f" on `{t['path']}`" if t.get("path") else ""
                feedback_lines.append(f"- {t['author']}{path_info}: {t['body']}")
            feedback = "\n".join(feedback_lines)
            try:
                await request_changes(ticket_id, {"feedback": feedback})
                auto_dispatched = True
                logger.info("Auto-dispatched request-changes for ticket %s (%d unresolved threads)", ticket_id, len(threads))
            except Exception as e:
                logger.warning("Auto request-changes failed for %s: %s", ticket_id, e)

    return {"synced": synced_count, "unresolved_threads": len(threads), "auto_dispatched": auto_dispatched}


def _get_unresolved_threads(owner: str, repo: str, pr_number: int, gh_token: str) -> list[dict]:
    """Fetch unresolved review threads from GitHub GraphQL API."""
    import json as _json
    import os
    import subprocess

    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              comments(first: 5) {
                nodes {
                  body
                  author { login }
                  path
                }
              }
            }
          }
        }
      }
    }
    """
    env = {**os.environ, "GH_TOKEN": gh_token}
    result = subprocess.run(
        ["gh", "api", "graphql",
         "-f", f"query={query}",
         "-f", f"owner={owner}",
         "-f", f"repo={repo}",
         "-F", f"pr={pr_number}"],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        logger.warning("GraphQL query failed: %s", result.stderr.strip())
        return []

    try:
        data = _json.loads(result.stdout)
    except _json.JSONDecodeError:
        return []

    threads = (data.get("data", {}).get("repository", {})
               .get("pullRequest", {}).get("reviewThreads", {}).get("nodes", []))

    unresolved = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = thread.get("comments", {}).get("nodes", [])
        if not comments:
            continue
        first = comments[0]
        unresolved.append({
            "thread_id": thread["id"],
            "path": first.get("path", ""),
            "author": first.get("author", {}).get("login", "unknown"),
            "body": first.get("body", ""),
        })

    return unresolved


@router.get("/{ticket_id}/unresolved-threads")
async def get_unresolved_threads(ticket_id: str):
    """Get unresolved review threads for a ticket's PR."""
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    pr_number = ticket.get("pr_number")
    if not pr_number:
        return {"unresolved": [], "count": 0}

    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "") or settings.gh_token
    repo_url = project.get("repo_url", "")
    if not gh_token or not repo_url:
        return {"unresolved": [], "count": 0}

    from claude_hub.services.webhook_registration import _parse_owner_repo
    parsed = _parse_owner_repo(repo_url)
    if not parsed:
        return {"unresolved": [], "count": 0}

    owner, repo = parsed
    threads = _get_unresolved_threads(owner, repo, pr_number, gh_token)

    # Update ticket field
    await redis_client.update_ticket_fields(ticket_id, {
        "unresolved_thread_count": str(len(threads))
    })

    return {"unresolved": threads, "count": len(threads)}


@router.get("/{ticket_id}/ci-status")
async def get_ticket_ci_status(ticket_id: str):
    """Get CI check status for a ticket's branch."""
    from claude_hub.services.ci_check import get_ci_status

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    clone_path = ticket.get("clone_path", "")
    branch = ticket.get("branch", "")
    if not clone_path or not branch:
        return {"status": "no_ci", "checks": [], "summary": "No branch or clone path"}

    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "") or settings.gh_token

    pr_number = ticket.get("pr_number") or 0
    return get_ci_status(clone_path, branch, gh_token, pr_number=pr_number)


@router.get("/{ticket_id}/diff")
async def get_ticket_diff(ticket_id: str):
    """Get PR diff for a ticket via gh pr diff."""
    import subprocess

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    pr_number = ticket.get("pr_number")
    if not pr_number:
        return {"diff": None, "stats": None}

    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "") or settings.gh_token
    clone_path = ticket.get("clone_path", "")

    if not clone_path:
        return {"diff": None, "stats": None}

    import os
    env = {**os.environ, "GH_TOKEN": gh_token} if gh_token else None

    # Get diff
    result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number)],
        cwd=clone_path, capture_output=True, text=True, env=env, timeout=30,
    )
    if result.returncode != 0:
        return {"diff": None, "stats": None}

    diff = result.stdout
    # Truncate large diffs (50KB limit)
    if len(diff) > 50_000:
        diff = diff[:50_000] + "\n... (truncated, diff too large)"

    # Get stats
    stat_result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--stat"],
        cwd=clone_path, capture_output=True, text=True, env=env, timeout=30,
    )
    stats = None
    if stat_result.returncode == 0 and stat_result.stdout.strip():
        lines = stat_result.stdout.strip().split("\n")
        # Last line is summary like " 3 files changed, 45 insertions(+), 12 deletions(-)"
        summary_line = lines[-1].strip() if lines else ""
        import re
        files_match = re.search(r"(\d+) files? changed", summary_line)
        ins_match = re.search(r"(\d+) insertions?", summary_line)
        del_match = re.search(r"(\d+) deletions?", summary_line)
        stats = {
            "files_changed": int(files_match.group(1)) if files_match else 0,
            "insertions": int(ins_match.group(1)) if ins_match else 0,
            "deletions": int(del_match.group(1)) if del_match else 0,
        }

    return {"diff": diff, "stats": stats}


@router.post("/{ticket_id}/merge")
async def merge_ticket(ticket_id: str, force: bool = Query(False)):
    import asyncio
    from claude_hub.services import session_manager
    from claude_hub.services.ticket_service import InvalidTransition, transition
    from claude_hub.services.ci_check import get_ci_status, merge_pr, wait_for_ci_and_merge

    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    pr_number = ticket.get("pr_number")
    clone_path = ticket.get("clone_path", "")
    branch = ticket.get("branch", "")

    if not pr_number or not clone_path:
        # No PR — just merge directly (legacy behavior)
        try:
            updated = await transition(ticket_id, TicketStatus.MERGED,
                                       completed_at=datetime.now(timezone.utc).isoformat())
        except InvalidTransition as e:
            raise HTTPException(409, str(e))
        await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
        _fire_pilot_trigger(ticket.get("project_id", ""), ticket_id)
        return updated

    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "") or settings.gh_token

    if not force:
        # Check PR review status before merging
        from claude_hub.services.ci_check import get_pr_review_status
        review = get_pr_review_status(clone_path, pr_number, gh_token)
        if review["status"] == "changes_requested":
            raise HTTPException(400, f"Cannot merge: {review['summary']}")

        # Check unresolved review threads before merging
        repo_url = project.get("repo_url", "")
        if repo_url:
            from claude_hub.services.webhook_registration import _parse_owner_repo
            parsed = _parse_owner_repo(repo_url)
            if parsed:
                threads = _get_unresolved_threads(parsed[0], parsed[1], pr_number, gh_token)
                if threads:
                    count = len(threads)
                    raise HTTPException(
                        400,
                        f"Cannot merge: {count} unresolved conversation{'s' if count > 1 else ''}. "
                        f"Resolve them on GitHub before merging."
                    )

        # Check CI status before merging
        ci = get_ci_status(clone_path, branch, gh_token, pr_number=pr_number)

        if ci["status"] == "failed":
            raise HTTPException(400, f"CI check failed: {ci['summary']}")

    if ci["status"] == "pending" and not force:
        # CI still running — transition to MERGING and poll in background
        try:
            updated = await transition(ticket_id, TicketStatus.MERGING)
        except InvalidTransition as e:
            raise HTTPException(409, str(e))
        await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
        asyncio.create_task(
            wait_for_ci_and_merge(ticket_id, clone_path, branch, pr_number, gh_token)
        )
        return updated

    # CI passed or no CI — merge immediately
    try:
        await merge_pr(ticket_id, clone_path, pr_number, gh_token)
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    try:
        updated = await transition(ticket_id, TicketStatus.MERGED,
                                   completed_at=datetime.now(timezone.utc).isoformat())
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    # Cleanup session, clone directory, and remote branch after merge
    from claude_hub.services import clone_manager
    session_manager.cleanup_session(ticket_id)
    clone_manager.cleanup_clone(ticket_id)
    _cleanup_remote_branch(ticket)  # fallback in case --delete-branch didn't work
    await redis_client.update_ticket_fields(ticket_id, {"clone_path": "", "tmux_session": ""})
    updated = await redis_client.get_ticket(ticket_id)

    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})

    # Immediately check other tickets for merge conflicts (don't wait for webhook)
    import asyncio
    from claude_hub.routers.webhooks import _update_review_branches
    base_branch = ticket.get("base_branch", project.get("base_branch", "main"))
    asyncio.create_task(_update_review_branches(pr_number, base_branch))

    # Sync kanban branch with latest base
    from claude_hub.routers.webhooks import _sync_kanban_branch_for_project
    project_id = ticket.get("project_id", "")
    if project_id:
        asyncio.create_task(_sync_kanban_branch_for_project(project_id))

    # Merged — session slot freed, process queue
    await process_queue()

    _fire_pilot_trigger(ticket.get("project_id", ""), ticket_id)

    return updated


# ── Notes ──────────────────────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel


class _NoteBody(_BaseModel):
    type: str = "comment"  # comment | progress | blocker | review | system
    content: str


@router.post("/{ticket_id}/notes")
async def add_note(ticket_id: str, body: _NoteBody):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    valid_types = {"comment", "progress", "blocker", "review", "system"}
    note_type = body.type if body.type in valid_types else "comment"

    updated = await append_ticket_note(ticket_id, note_type, body.content, author="user")
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
    return updated


# ── Revert to TODO ─────────────────────────────────────────────────────────────


@router.post("/{ticket_id}/revert")
async def revert_ticket(ticket_id: str):
    """Revert a FAILED or REVIEW ticket back to TODO status."""
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    current = ticket.get("status")
    if current not in ("failed", "awaiting_merge"):
        raise HTTPException(409, f"Cannot revert ticket in {current} status (only failed or awaiting_merge)")

    from claude_hub.services.ticket_service import InvalidTransition, transition

    try:
        updated = await transition(ticket_id, TicketStatus.TODO)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    # Clear runtime fields but keep branch/PR info for reference
    clear_fields = {
        "failed_reason": "",
        "tmux_session": "",
        "started_at": "",
        "completed_at": "",
        "review_status": "",
        "reviewer": "",
    }
    await redis_client.update_ticket_fields(ticket_id, clear_fields)

    # Append system note
    await append_ticket_note(
        ticket_id, "system",
        f"Reverted from {current} to todo",
        author="system",
    )

    updated = await redis_client.get_ticket(ticket_id)
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
    send_kanban_update(ticket.get("project_id", ""))
    return updated


# ── Duplicate as New Ticket ────────────────────────────────────────────────────


@router.post("/{ticket_id}/duplicate", status_code=201)
async def duplicate_ticket(ticket_id: str):
    """Create a new TODO ticket by cloning an existing ticket's title/description."""
    source = await redis_client.get_ticket(ticket_id)
    if not source:
        raise HTTPException(404, "Ticket not found")

    project = await redis_client.get_project(source.get("project_id", ""))
    if not project:
        raise HTTPException(404, "Project not found")

    new_id = str(uuid.uuid4())
    seq = await redis_client.next_ticket_seq(source["project_id"])
    branch_type = source.get("branch_type", "feature")

    new_ticket = Ticket(
        id=new_id,
        project_id=source["project_id"],
        seq=seq,
        title=source["title"],
        description=source.get("description", ""),
        branch_type=branch_type,
        branch=_make_branch(branch_type, source["title"], new_id),
        repo_url=source.get("repo_url", project["repo_url"]),
        base_branch=source.get("base_branch", project.get("base_branch", "main")),
        priority=source.get("priority", 0),
        source="duplicate",
        created_at=datetime.now(timezone.utc),
        status_changed_at=datetime.now(timezone.utc),
    )

    await redis_client.save_ticket(new_ticket.model_dump(mode="json"))

    # Add system note referencing source ticket
    source_seq = source.get("seq", 0)
    ref = f"#{source_seq}" if source_seq else ticket_id[:8]
    await append_ticket_note(
        new_id, "system",
        f"Duplicated from {ref} ({source.get('title', '')})",
        author="system",
    )

    updated = await redis_client.get_ticket(new_id)
    await broadcast({"type": "ticket_updated", "ticket_id": new_id, "data": updated})
    send_kanban_update(source["project_id"])
    return updated
