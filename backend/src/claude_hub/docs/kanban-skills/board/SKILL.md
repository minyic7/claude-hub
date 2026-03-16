---
name: board
description: Fetch the kanban board state — all active (non-archived) tickets for this project. Run this before making decisions to ensure your mental model is current.
---

Fetch and display the current kanban board state for this project.

```bash
curl -s {auth} {api_base_url}/api/projects/{project_id}/tickets | python3 -m json.tool
```

After fetching, summarize the board by status bucket:
- **TODO**: tickets waiting to start
- **QUEUED**: tickets waiting for a session slot
- **IN_PROGRESS**: actively being worked on
- **BLOCKED**: waiting for human input
- **FAILED**: session ended with error
- **AWAITING_MERGE**: PR open, waiting for merge
- **MERGING**: PR merge in progress (CI pending)
- **MERGED**: completed

Always refer to tickets by their `#seq` number (e.g., #5) in summaries. Use the full UUID `id` only in API calls.
