---
name: message-ticket
description: Send a message to an IN_PROGRESS or BLOCKED ticket's Claude Code session. If ticket is BLOCKED, this also unblocks it.
argument-hint: <TICKET_ID>
---

Send a message to ticket `$ARGUMENTS`'s active Claude Code session. Replace YOUR_MESSAGE with the actual message.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/message \
  -H "Content-Type: application/json" \
  -d '{"message": "YOUR_MESSAGE_HERE"}'
```

Works for tickets in IN_PROGRESS or BLOCKED status. If the ticket is BLOCKED, sending a message also unblocks it (transitions to IN_PROGRESS).

The session must be alive — returns 409 if no active session exists.
