---
name: retry-ticket
description: Retry a FAILED ticket — starts a new Claude Code session with optional guidance to avoid repeating the same mistake.
argument-hint: <TICKET_ID>
---

Retry failed ticket `$ARGUMENTS`. Optionally include guidance to help avoid the previous failure.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/retry \
  -H "Content-Type: application/json" \
  -d '{"guidance": "OPTIONAL_GUIDANCE"}'
```

**When to include guidance:**
- Code problem → read the PR diff first (`/ticket-diff`), then provide specific guidance
- Conflict → no guidance needed, just retry
- Transient error → no guidance needed, just retry

The guidance is prepended to the original task description for the new session.
