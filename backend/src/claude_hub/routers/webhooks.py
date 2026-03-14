import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from claude_hub import redis_client
from claude_hub.models.ticket import TicketStatus
from claude_hub.routers.ws import broadcast
from claude_hub.services.ticket_service import transition

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
):
    body = await request.body()

    # TODO: Verify signature when webhook secret is configured
    # if webhook_secret and x_hub_signature_256:
    #     expected = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    #     if not hmac.compare_digest(expected, x_hub_signature_256):
    #         raise HTTPException(403, "Invalid signature")

    if x_github_event not in ("pull_request", "pull_request_review"):
        return {"status": "ignored", "event": x_github_event}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    if x_github_event == "pull_request_review":
        return await _handle_pr_review(payload)

    # pull_request event
    action = payload.get("action")
    if action != "closed" or not payload.get("pull_request", {}).get("merged"):
        return {"status": "ignored", "action": action}

    pr_number = payload["pull_request"]["number"]
    logger.info("Received PR merge event: PR #%d", pr_number)

    # Find ticket with this PR number
    tickets = await redis_client.list_tickets("review")
    for ticket in tickets:
        if ticket.get("pr_number") == pr_number:
            try:
                from datetime import datetime, timezone
                updated = await transition(
                    ticket["id"], TicketStatus.MERGED,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket["id"],
                    "data": updated,
                })
                logger.info("Auto-merged ticket %s via webhook", ticket["id"])
                return {"status": "merged", "ticket_id": ticket["id"]}
            except Exception as e:
                logger.error("Failed to auto-merge ticket %s: %s", ticket["id"], e)
                return {"status": "error", "message": str(e)}

    return {"status": "no_matching_ticket", "pr_number": pr_number}


async def _handle_pr_review(payload: dict) -> dict:
    """Handle pull_request_review events — notify frontend of review status changes."""
    action = payload.get("action")
    if action not in ("submitted", "dismissed"):
        return {"status": "ignored", "action": action}

    review_state = payload.get("review", {}).get("state", "").upper()
    pr_number = payload.get("pull_request", {}).get("number")
    reviewer = payload.get("review", {}).get("user", {}).get("login", "unknown")

    if not pr_number:
        return {"status": "ignored", "reason": "no PR number"}

    logger.info("PR #%d review %s by %s (action: %s)", pr_number, review_state, reviewer, action)

    # Find ticket with this PR number in review/merging states
    for status in ("review", "merging"):
        tickets = await redis_client.list_tickets(status)
        for ticket in tickets:
            if ticket.get("pr_number") == pr_number:
                if action == "dismissed":
                    # Review dismissed — clear review status
                    review_info: dict = {"review_status": "", "reviewer": ""}
                elif review_state == "COMMENTED":
                    # Comment-only reviews don't affect merge gate
                    return {"status": "ignored", "reason": "comment only"}
                else:
                    review_info = {
                        "review_status": review_state.lower(),
                        "reviewer": reviewer,
                    }
                await redis_client.update_ticket_fields(ticket["id"], review_info)
                updated = await redis_client.get_ticket(ticket["id"])
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": ticket["id"],
                    "data": updated,
                })
                logger.info("Updated review status for ticket %s: %s", ticket["id"], review_state)
                return {"status": "updated", "ticket_id": ticket["id"], "review_state": review_state}

    return {"status": "no_matching_ticket", "pr_number": pr_number}
