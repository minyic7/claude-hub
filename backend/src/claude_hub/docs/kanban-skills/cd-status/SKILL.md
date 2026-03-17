---
name: cd-status
description: Check the latest deploy (CD) workflow status on main branch after a ticket is merged. Use after merging to verify deployment succeeded.
argument-hint: (no arguments)
---

Check the latest deploy workflow status on the main branch.

Run this after merging a ticket to verify the deployment succeeded:

```bash
gh run list --branch main -L 1 --json status,conclusion,name,createdAt,url
```

**Interpreting results:**
- `conclusion: "success"` — deploy succeeded, safe to continue
- `conclusion: "failure"` — deploy failed, create a hotfix ticket immediately with the error
- `status: "in_progress"` — deploy still running, wait and re-check in 60 seconds

If the deploy failed, get the error details:
```bash
gh run view <RUN_ID> --log-failed
```

**Important:** Do NOT start the next batch of tickets until the deploy is green.
