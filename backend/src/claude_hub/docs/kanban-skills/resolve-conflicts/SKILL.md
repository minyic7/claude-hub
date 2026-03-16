---
name: resolve-conflicts
description: Trigger automatic conflict resolution for an AWAITING_MERGE ticket with merge conflicts. Spawns a Claude Code session to rebase and resolve.
argument-hint: <TICKET_ID>
---

Trigger conflict resolution for ticket `$ARGUMENTS`.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/resolve-conflicts | python3 -m json.tool
```

Use when a ticket in AWAITING_MERGE has `has_conflicts: true`. This spawns a Claude Code session that:
1. Fetches the latest base branch
2. Rebases the ticket's branch
3. Resolves merge conflicts
4. Force-pushes to update the PR

Returns `{"status": "already_resolving"}` if a session is already active for this ticket.
