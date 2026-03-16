---
name: add-note
description: Append a note to any ticket. Use to log observations during triage or record progress.
argument-hint: <TICKET_ID>
---

Add a note to ticket `$ARGUMENTS`. Replace YOUR_NOTE and TYPE with actual values.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/notes \
  -H "Content-Type: application/json" \
  -d '{"content": "YOUR_NOTE", "type": "TYPE"}'
```

**Valid types:** `comment` (default), `progress`, `blocker`, `review`, `system`

Use this to:
- Log triage observations during pilot cycles
- Record why you decided to retry/skip a ticket
- Note blockers that need human attention
