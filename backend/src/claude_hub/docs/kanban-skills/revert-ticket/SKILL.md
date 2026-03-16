---
name: revert-ticket
description: Revert a FAILED or AWAITING_MERGE ticket back to TODO status. Clears runtime fields but keeps branch/PR info.
argument-hint: <TICKET_ID>
---

Revert ticket `$ARGUMENTS` back to TODO.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/revert | python3 -m json.tool
```

Only works on tickets in FAILED or AWAITING_MERGE status. Clears:
- `failed_reason`, `tmux_session`, `started_at`, `completed_at`, `review_status`, `reviewer`

Keeps branch and PR info for reference. After reverting, the ticket can be started fresh or updated with new instructions.
