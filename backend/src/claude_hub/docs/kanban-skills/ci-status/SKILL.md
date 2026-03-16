---
name: ci-status
description: Check CI pass/fail status for a ticket's branch. Use before merging or when triaging AWAITING_MERGE tickets.
argument-hint: <TICKET_ID>
---

Check CI status for ticket `$ARGUMENTS`.

```bash
curl -s {auth} {api_base_url}/api/tickets/$ARGUMENTS/ci-status | python3 -m json.tool
```

**Response:** `{"status": "passed|failed|pending|no_ci", "checks": [...], "summary": "..."}`

- `passed` — all CI checks passed, safe to merge
- `failed` — CI failed, check `summary` for details
- `pending` — CI still running
- `no_ci` — no CI configured or no branch
