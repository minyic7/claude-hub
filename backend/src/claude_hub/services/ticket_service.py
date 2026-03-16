import asyncio
import json
import logging
from datetime import datetime, timezone

from claude_hub.models.ticket import TicketStatus
from claude_hub import redis_client

logger = logging.getLogger(__name__)

# Per-ticket locks to prevent concurrent transitions (TOCTOU race)
_transition_locks: dict[str, asyncio.Lock] = {}

VALID_TRANSITIONS: dict[TicketStatus, list[TicketStatus]] = {
    TicketStatus.PO_PENDING: [TicketStatus.TODO],  # Approve → TODO
    TicketStatus.TODO: [TicketStatus.IN_PROGRESS, TicketStatus.QUEUED],
    TicketStatus.QUEUED: [TicketStatus.IN_PROGRESS, TicketStatus.TODO],
    TicketStatus.IN_PROGRESS: [TicketStatus.TODO, TicketStatus.BLOCKED, TicketStatus.VERIFYING, TicketStatus.FAILED],
    TicketStatus.BLOCKED: [TicketStatus.IN_PROGRESS, TicketStatus.FAILED],
    TicketStatus.VERIFYING: [TicketStatus.REVIEWING, TicketStatus.REVIEW, TicketStatus.FAILED],
    TicketStatus.REVIEWING: [TicketStatus.REVIEW, TicketStatus.IN_PROGRESS, TicketStatus.FAILED],
    TicketStatus.REVIEW: [TicketStatus.MERGING, TicketStatus.MERGED, TicketStatus.IN_PROGRESS, TicketStatus.TODO],
    TicketStatus.MERGING: [TicketStatus.MERGED, TicketStatus.FAILED],
    TicketStatus.FAILED: [TicketStatus.IN_PROGRESS, TicketStatus.REVIEW, TicketStatus.TODO],
    TicketStatus.MERGED: [],
}


class InvalidTransition(Exception):
    def __init__(self, current: TicketStatus, target: TicketStatus):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


async def transition(ticket_id: str, target: TicketStatus, **extra_fields: object) -> dict:
    # Per-ticket lock prevents concurrent transitions (TOCTOU race)
    if ticket_id not in _transition_locks:
        _transition_locks[ticket_id] = asyncio.Lock()
    async with _transition_locks[ticket_id]:
        return await _transition_inner(ticket_id, target, **extra_fields)


async def _transition_inner(ticket_id: str, target: TicketStatus, **extra_fields: object) -> dict:
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"Ticket {ticket_id} not found")

    current = TicketStatus(ticket["status"])
    if target not in VALID_TRANSITIONS.get(current, []):
        raise InvalidTransition(current, target)

    await redis_client.update_ticket_status(ticket_id, current.value, target.value)

    fields: dict = {"status": target.value, "status_changed_at": datetime.now(timezone.utc).isoformat()}
    fields.update(extra_fields)
    await redis_client.update_ticket_fields(ticket_id, fields)

    updated = await redis_client.get_ticket(ticket_id)

    # Notify kanban session of kanban state change
    project_id = updated.get("project_id", "") if updated else ""
    if project_id:
        from claude_hub.services.kanban_manager import send_kanban_update
        send_kanban_update(project_id)

    # Auto-sync PR reviews when entering review status
    if target == TicketStatus.REVIEW and updated and updated.get("pr_number"):
        asyncio.create_task(_auto_sync_reviews(ticket_id))

    # Trigger PO agent to rank review queue when a ticket enters review
    if target == TicketStatus.REVIEW and project_id:
        from claude_hub.services.po_manager import po_manager
        po_manager.trigger(project_id, "review_entered")

    # Trigger PO agent when a ticket merges
    if target == TicketStatus.MERGED and project_id:
        from claude_hub.services.po_manager import po_manager
        po_manager.trigger(project_id, "merged")

    return updated


async def _auto_sync_reviews(ticket_id: str) -> None:
    """Fire-and-forget: sync PR reviews from GitHub when ticket enters review."""
    try:
        from claude_hub.routers.tickets import sync_pr_reviews
        await sync_pr_reviews(ticket_id)
        logger.info("Auto-synced PR reviews for ticket %s", ticket_id)
    except Exception as e:
        logger.warning("Auto-sync reviews failed for %s: %s", ticket_id, e)


async def append_ticket_note(
    ticket_id: str,
    note_type: str,
    content: str,
    author: str = "user",
) -> dict:
    """Append a structured note to a ticket. Returns updated ticket."""
    ticket = await redis_client.get_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"Ticket {ticket_id} not found")

    # Parse existing notes (stored as JSON string in Redis)
    existing = ticket.get("notes")
    if isinstance(existing, str):
        try:
            notes = json.loads(existing)
        except json.JSONDecodeError:
            notes = []
    elif isinstance(existing, list):
        notes = existing
    else:
        notes = []

    note = {
        "type": note_type,
        "content": content,
        "author": author,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    notes.append(note)

    await redis_client.update_ticket_fields(ticket_id, {"notes": json.dumps(notes)})
    return await redis_client.get_ticket(ticket_id)
