---
name: reorder-tickets
description: Set priority order for TODO tickets. First ID in the list = highest priority.
---

Reorder TODO tickets by priority. Provide ticket IDs in desired order (first = highest priority).

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/reorder \
  -H "Content-Type: application/json" \
  -d '{{"project_id": "{project_id}", "ticket_ids": ["ID_1", "ID_2", "ID_3"]}}'
```

All ticket IDs must exist and belong to this project.
