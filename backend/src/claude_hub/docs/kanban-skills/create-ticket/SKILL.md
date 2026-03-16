---
name: create-ticket
description: Create a new ticket on the kanban board. Provide title and description. The ticket starts in TODO status.
---

Create a new ticket. Replace the UPPERCASE placeholders with actual values.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets \
  -H "Content-Type: application/json" \
  -d '{{"project_id": "{project_id}", "title": "TICKET_TITLE", "description": "TICKET_DESCRIPTION", "branch_type": "feature", "depends_on": [], "priority": 0, "pilot": {pilot_mode}}}'
```

**Fields:**
- `title` (required) — short summary of the task
- `description` (required) — detailed instructions for Claude Code to follow
- `branch_type` — one of: `feature`, `bugfix`, `hotfix`, `chore`, `refactor`, `docs`, `test`
- `depends_on` — array of ticket IDs that must be MERGED before this ticket can start
- `priority` — lower number = higher priority (0 = highest)
- `pilot` — set to `true` if created autonomously in pilot mode

**Before creating:** Always check for duplicate or overlapping tickets on the board first.
