---
name: archive-ticket
description: Archive a ticket (removes from active board). WARNING — this is a toggle. Calling on an already-archived ticket will unarchive it.
argument-hint: <TICKET_ID>
---

Archive ticket `$ARGUMENTS`.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/archive | python3 -m json.tool
```

**WARNING:** This is a toggle — calling it on an already-archived ticket will **unarchive** it.
Always verify the ticket's `archived` field is `false` before calling.

Use this for:
- Tickets that are no longer needed
- Tickets that were implemented outside the board
- Cleaning up stale or duplicate tickets
