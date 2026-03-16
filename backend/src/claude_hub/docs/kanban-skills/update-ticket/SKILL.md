---
name: update-ticket
description: Update a TODO ticket's title, description, priority, or dependencies. Only works on tickets in TODO status.
argument-hint: <TICKET_ID>
---

Update ticket `$ARGUMENTS`. Only include fields you want to change.

```bash
curl -s -X PATCH {auth} {api_base_url}/api/tickets/$ARGUMENTS \
  -H "Content-Type: application/json" \
  -d '{"title": "NEW_TITLE", "description": "NEW_DESCRIPTION", "priority": 0, "depends_on": []}'
```

**Constraints:**
- Only works on tickets in TODO status
- Omit fields you don't want to change
- `depends_on` replaces the entire array (not append)
