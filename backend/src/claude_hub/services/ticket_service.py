from datetime import datetime, timezone

from claude_hub.models.ticket import TicketStatus
from claude_hub import redis_client

VALID_TRANSITIONS: dict[TicketStatus, list[TicketStatus]] = {
    TicketStatus.TODO: [TicketStatus.IN_PROGRESS, TicketStatus.QUEUED],
    TicketStatus.QUEUED: [TicketStatus.IN_PROGRESS, TicketStatus.TODO],
    TicketStatus.IN_PROGRESS: [TicketStatus.BLOCKED, TicketStatus.VERIFYING, TicketStatus.FAILED],
    TicketStatus.BLOCKED: [TicketStatus.IN_PROGRESS, TicketStatus.FAILED],
    TicketStatus.VERIFYING: [TicketStatus.REVIEWING, TicketStatus.REVIEW, TicketStatus.FAILED],
    TicketStatus.REVIEWING: [TicketStatus.REVIEW, TicketStatus.IN_PROGRESS, TicketStatus.FAILED],
    TicketStatus.REVIEW: [TicketStatus.MERGING, TicketStatus.MERGED, TicketStatus.IN_PROGRESS],
    TicketStatus.MERGING: [TicketStatus.MERGED, TicketStatus.FAILED],
    TicketStatus.FAILED: [TicketStatus.IN_PROGRESS, TicketStatus.REVIEW],
    TicketStatus.MERGED: [],
}


class InvalidTransition(Exception):
    def __init__(self, current: TicketStatus, target: TicketStatus):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


async def transition(ticket_id: str, target: TicketStatus, **extra_fields: object) -> dict:
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
    return updated
