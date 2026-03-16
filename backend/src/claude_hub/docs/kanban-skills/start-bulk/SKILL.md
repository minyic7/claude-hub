---
name: start-bulk
description: Start multiple tickets at once. Tickets that fit within the session limit start immediately; the rest are queued automatically.
---

Start multiple tickets. Those within the session limit start immediately; extras are queued.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/bulk-start \
  -H "Content-Type: application/json" \
  -d '{"ticket_ids": ["TICKET_ID_1", "TICKET_ID_2", "TICKET_ID_3"]}'
```

**Response:** `{"started": [...], "queued": [...]}`

Tickets must be in TODO status with all dependencies met. Tickets that can't start immediately are auto-queued and will start when session slots become available.
