---
name: force-status
description: Force a ticket to any status, bypassing transition rules. Use when system state is out of sync with reality.
argument-hint: <TICKET_ID> <STATUS>
---

Force ticket status. Use when the normal state machine can't reach the correct state (e.g., PR merged externally but ticket stuck in `failed`).

Extract TICKET_ID and STATUS from `$ARGUMENTS`. Valid statuses: `todo`, `in_progress`, `blocked`, `verifying`, `reviewing`, `awaiting_merge`, `merging`, `merged`, `failed`, `queued`.

```bash
curl -s -X POST {auth} -H "Content-Type: application/json" -d '{"status": "STATUS_HERE"}' {api_base_url}/api/tickets/TICKET_ID_HERE/force-status | python3 -m json.tool
```

**Warning:** This bypasses all validation. Use only when necessary.
