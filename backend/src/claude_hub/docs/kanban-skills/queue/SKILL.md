---
name: queue
description: Check the current execution queue — shows queued tickets and available session slots.
---

Check the execution queue and session capacity.

```bash
curl -s {auth} {api_base_url}/api/tickets/queue | python3 -m json.tool
```

**Response:** `{"queue": [...ticket_ids], "active_sessions": N, "max_sessions": M}`

Use this to understand how many sessions are available before starting new tickets.
