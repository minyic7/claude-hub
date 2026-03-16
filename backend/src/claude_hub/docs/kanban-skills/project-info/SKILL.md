---
name: project-info
description: Read project settings including pilot mode, ticket limits, and configuration.
---

Fetch project settings and configuration.

```bash
curl -s {auth} {api_base_url}/api/projects/{project_id} | python3 -m json.tool
```

Key fields to check:
- `pilot_mode` — whether autonomous pilot mode is active
- `max_board_tickets` — max active tickets allowed on the board
- `max_tickets_per_cycle` — max tickets to create per pilot cycle
- `vision_mode` — "readonly" or "writable"
- `base_branch` — the branch tickets merge into
