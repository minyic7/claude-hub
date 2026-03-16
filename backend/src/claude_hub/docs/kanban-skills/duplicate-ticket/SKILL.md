---
name: duplicate-ticket
description: Create a new TODO ticket by cloning an existing ticket's title and description. Useful for creating follow-up work.
argument-hint: <TICKET_ID>
---

Duplicate ticket `$ARGUMENTS` — creates a new TODO ticket with the same title and description.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/duplicate | python3 -m json.tool
```

The new ticket gets a fresh ID, new branch name, and starts in TODO status. Dependencies are NOT copied.
