---
name: ticket-diff
description: Read the PR diff for a ticket to understand what a Claude Code session produced. Use before requesting changes or during triage.
argument-hint: <TICKET_ID>
---

Get the PR diff for ticket `$ARGUMENTS`.

```bash
curl -s {auth} {api_base_url}/api/tickets/$ARGUMENTS/diff | python3 -m json.tool
```

**Response:** `{"diff": "...", "stats": {"files_changed": N, "insertions": N, "deletions": N}}`

Returns `null` diff if the ticket has no PR yet. Large diffs are truncated at 50KB.

Use this to:
- Understand what a session implemented before reviewing
- Decide whether to request changes or approve
- Provide specific feedback when requesting changes
