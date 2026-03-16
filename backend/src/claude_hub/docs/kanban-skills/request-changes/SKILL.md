---
name: request-changes
description: Send an AWAITING_MERGE ticket back to IN_PROGRESS with specific feedback about what needs to change. Spawns a new Claude Code session to address the issues.
argument-hint: <TICKET_ID>
---

Request changes on ticket `$ARGUMENTS`. Provide specific feedback about what is wrong or incomplete.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/request-changes \
  -H "Content-Type: application/json" \
  -d '{"feedback": "SPECIFIC_FEEDBACK_ABOUT_WHAT_IS_WRONG"}'
```

The ticket transitions from AWAITING_MERGE → IN_PROGRESS. A new Claude Code session starts with the original task description plus your feedback.

**Best practices:**
- Be specific about what's wrong (file names, line numbers, expected behavior)
- Read the PR diff first (`/ticket-diff`) to understand what was implemented
- Check CI status (`/ci-status`) and unresolved threads (`/unresolved-threads`) before requesting changes
