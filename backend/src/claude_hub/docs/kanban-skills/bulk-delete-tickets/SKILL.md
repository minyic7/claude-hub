---
name: bulk-delete-tickets
description: Permanently delete multiple tickets at once. Cleans up sessions, clones, and remote branches.
---

Delete multiple tickets at once.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/bulk-delete \
  -H "Content-Type: application/json" \
  -d '{"ticket_ids": ["TICKET_ID_1", "TICKET_ID_2", "TICKET_ID_3"]}'
```

**Response:** `{"deleted": [...], "errors": [...]}`

Use this to clean up batches of unneeded tickets (duplicates, obsolete, created by mistake).
