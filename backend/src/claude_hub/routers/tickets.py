import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

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
        branch=_make_branch(body.branch_type.value, body.title, ticket_id),
        repo_url=project["repo_url"],
        base_branch=project.get("base_branch", "main"),
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
    return updated


@router.post("/{ticket_id}/archive")
async def toggle_archive(ticket_id: str):
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    new_val = not ticket.get("archived", False)
    await redis_client.update_ticket_fields(ticket_id, {"archived": new_val})
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
        raise HTTPException(409, "Ticket already has an active session")
    if session_manager.active_session_count() >= settings.max_sessions:
        raise HTTPException(
            429, f"Max concurrent sessions ({settings.max_sessions}) reached. Wait for a session to finish."
        )

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

    # Start Claude Code session
    description = ticket.get("description") or ticket["title"]
    branch = ticket["branch"]
    base_branch = ticket.get("base_branch", "main")
    task = (
        f"{description}\n\n"
        f"You are working on branch '{branch}' (based on '{base_branch}').\n"
        f"When done, commit your changes, push the branch, and create a PR against '{base_branch}'."
    )
    session_name, log_path = session_manager.start_session(
        ticket_id, clone_path, task, gh_token=gh_token,
        model="claude-opus-4-6",
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
    from claude_hub.services import session_manager
    from claude_hub.services.ticket_service import InvalidTransition, transition

    # Guard: prevent double-start and enforce max sessions
    if session_manager.has_active_session(ticket_id):
        raise HTTPException(409, "Ticket already has an active session")
    if session_manager.active_session_count() >= settings.max_sessions:
        raise HTTPException(
            429, f"Max concurrent sessions ({settings.max_sessions}) reached. Wait for a session to finish."
        )

    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   failed_reason="",
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
    task = (
        f"{description}\n\n"
        f"You are working on branch '{branch}' (based on '{base_branch}').\n"
        f"When done, commit your changes, push the branch, and create a PR against '{base_branch}'."
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


async def _tail_and_broadcast(ticket_id: str, log_path: str) -> None:
    """Background task: tail log with optional TicketAgent supervision."""
    from claude_hub.services.ticket_service import transition

    try:
        # Load agent settings from Redis (hot-reloadable)
        from claude_hub.routers.settings_router import get_agent_settings
        agent_cfg = await get_agent_settings()
        agent_enabled = agent_cfg.get("enabled", settings.agent_enabled)

        if agent_enabled and agent_cfg.get("api_key"):
            # Agent mode: TicketAgent handles tailing + broadcasting + intervention
            from claude_hub.services.ticket_agent import TicketAgent
            ticket = await redis_client.get_ticket(ticket_id)
            agent = TicketAgent(ticket_id, ticket, agent_settings=agent_cfg)
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

        # Session ended — clean up tmux session
        from claude_hub.services import session_manager
        session_manager.cleanup_session(ticket_id)

        # Verify agent work
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
        # If session errored out and ticket is still in_progress, mark as failed
        try:
            ticket = await redis_client.get_ticket(ticket_id)
            if ticket and ticket.get("status") in ("in_progress", "verifying"):
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


@router.post("/{ticket_id}/resolve-conflicts")
async def resolve_conflicts(ticket_id: str):
    """Auto-trigger a Claude Code session to rebase and resolve merge conflicts."""
    CONFLICT_FEEDBACK = (
        "The PR has merge conflicts with the base branch. You must:\n"
        "1. Run `git fetch origin` to get the latest changes\n"
        "2. Run `git rebase origin/main` (or the correct base branch)\n"
        "3. Resolve any merge conflicts\n"
        "4. Run `git push --force-with-lease` to update the PR\n"
        "Do NOT create a new PR. Fix conflicts on this branch."
    )
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
    if session_manager.active_session_count() >= settings.max_sessions:
        raise HTTPException(
            429, f"Max concurrent sessions ({settings.max_sessions}) reached."
        )

    try:
        updated = await transition(ticket_id, TicketStatus.IN_PROGRESS,
                                   started_at=datetime.now(timezone.utc).isoformat())
    except ValueError:
        raise HTTPException(404, "Ticket not found")
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

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
    task = (
        f"{original_task}\n\n"
        f"## Review Feedback — Address These Issues:\n{feedback}\n\n"
        f"You are on branch {ticket['branch']} which already has your previous work.\n"
        f"Read the existing code, address the review feedback above, commit, push, "
        f"and update the PR."
    )
    if pr_number:
        task += f"\nDo NOT create a new PR — push to the same branch so the existing PR #{pr_number} is updated."

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


@router.post("/sync-review-status")
async def sync_review_status():
    """Check GitHub for any review tickets whose PRs have been merged externally."""
    import json as _json
    import os
    import subprocess
    from claude_hub.services.ticket_service import transition

    review_tickets = await redis_client.list_tickets("review")
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
            except Exception:
                pass
        else:
            # Check for merge conflicts (mergeable = "CONFLICTING")
            mergeable = pr_data.get("mergeable", "")
            has_conflicts = mergeable == "CONFLICTING"
            old_conflicts = ticket.get("has_conflicts", False)
            if has_conflicts != old_conflicts:
                await redis_client.update_ticket_fields(
                    ticket["id"], {"has_conflicts": str(has_conflicts)}
                )
                updated = await redis_client.get_ticket(ticket["id"])
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket["id"],
                    "data": updated,
                })

                # Auto-trigger conflict resolution when conflicts are newly detected
                if has_conflicts and not old_conflicts:
                    try:
                        await resolve_conflicts(ticket["id"])
                        logger.info("Auto-triggered conflict resolution for ticket %s", ticket["id"])
                    except Exception as e:
                        logger.warning("Auto-resolve failed for %s: %s", ticket["id"], e)

    return {"synced": synced}


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


@router.post("/{ticket_id}/merge")
async def merge_ticket(ticket_id: str):
    import asyncio
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
        return updated

    project = await _get_project_for_ticket(ticket)
    gh_token = project.get("gh_token", "") or settings.gh_token

    # Check CI status before merging
    ci = get_ci_status(clone_path, branch, gh_token, pr_number=pr_number)

    if ci["status"] == "failed":
        from claude_hub.services.ci_check import get_failed_log
        fail_log = get_failed_log(clone_path, gh_token)
        reason = ci["summary"]
        if fail_log:
            reason = f"{reason}\n\n--- CI Log (last 80 lines) ---\n{fail_log}"
        # Store failure reason so retry can use it
        await redis_client.update_ticket_fields(ticket_id, {"failed_reason": reason})
        raise HTTPException(400, f"CI check failed: {ci['summary']}")

    if ci["status"] == "pending":
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

    # Cleanup clone directory after merge
    from claude_hub.services import clone_manager
    clone_manager.cleanup_clone(ticket_id)
    await redis_client.update_ticket_fields(ticket_id, {"clone_path": ""})
    updated = await redis_client.get_ticket(ticket_id)

    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
    return updated
