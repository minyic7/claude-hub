---
name: delete-ticket
description: Permanently delete a ticket and clean up its session, clone, and remote branch.
argument-hint: <TICKET_ID>
---

Permanently delete ticket `$ARGUMENTS`.

```bash
curl -s -X DELETE {auth} {api_base_url}/api/tickets/$ARGUMENTS
```

**Returns:** 204 No Content on success.

This permanently removes the ticket from the board. The session, clone directory, and remote branch are cleaned up automatically.

Use this instead of archive when a ticket is no longer needed (e.g., duplicate, obsolete, created by mistake).
