---
name: start-ticket
description: Start a TODO ticket — spawns a Claude Code session to work on it. Use this to begin work on the highest-priority unblocked ticket.
argument-hint: <TICKET_ID>
---

Start ticket `$ARGUMENTS` — this spawns a new Claude Code session to implement it.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/start | python3 -m json.tool
```

**Prerequisites checked by the server:**
- Ticket must be in TODO status
- All `depends_on` tickets must be in MERGED status
- Must be under the max concurrent session limit

**Common errors:**
- `400` — unmet dependency (a depends_on ticket isn't merged yet)
- `409` — ticket already has an active session or wrong status
- `429` — max concurrent sessions reached; wait or use `/start-bulk` to queue

After starting, the ticket transitions to IN_PROGRESS and a Claude Code session begins working on the ticket's description.
