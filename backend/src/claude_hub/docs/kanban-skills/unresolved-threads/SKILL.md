---
name: unresolved-threads
description: Check open PR review threads for an AWAITING_MERGE ticket. Shows unresolved conversations that need addressing before merge.
argument-hint: <TICKET_ID>
---

Get unresolved review threads for ticket `$ARGUMENTS`.

```bash
curl -s {auth} {api_base_url}/api/tickets/$ARGUMENTS/unresolved-threads | python3 -m json.tool
```

**Response:** `{"unresolved": [{"thread_id": "...", "path": "...", "author": "...", "body": "..."}], "count": N}`

Use this to:
- Check if there are unresolved conversations blocking merge
- Understand review feedback before requesting changes
- Decide whether the ticket needs another revision round
