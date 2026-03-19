---
name: merge-ticket
description: Merge an AWAITING_MERGE ticket's PR into the base branch. Checks CI status, review status, and unresolved threads before merging.
argument-hint: <TICKET_ID>
---

Merge ticket `$ARGUMENTS`'s PR.

```bash
curl -s -X POST {auth} "{api_base_url}/api/tickets/$ARGUMENTS/merge" | python3 -m json.tool
```

To force-merge (skip CI/review checks):
```bash
curl -s -X POST {auth} "{api_base_url}/api/tickets/$ARGUMENTS/merge?force=true" | python3 -m json.tool
```

**Server-side checks before merge (skipped with `?force=true`):**
- PR review status (blocks if changes_requested)
- Unresolved review threads (blocks if any exist)
- CI status (waits if pending, blocks if failed)

**Responses:**
- Success → ticket transitions to MERGED
- CI pending → ticket transitions to MERGING (auto-merges when CI passes)
- `400` — CI failed, changes requested, or unresolved threads
- `409` — wrong ticket status

**Note:** In pilot mode, merging is typically left to humans. Only merge if you are certain the implementation is correct.
