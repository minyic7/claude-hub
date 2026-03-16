---
name: answer-ticket
description: Unblock a BLOCKED ticket by sending an answer to its question. The answer is forwarded to the waiting Claude Code session.
argument-hint: <TICKET_ID>
---

Unblock ticket `$ARGUMENTS` by answering its question. Replace YOUR_ANSWER with the actual answer.

```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/$ARGUMENTS/answer \
  -H "Content-Type: application/json" \
  -d '{"answer": "YOUR_ANSWER_HERE"}'
```

The ticket transitions from BLOCKED → IN_PROGRESS and the answer is sent to the Claude Code session via tmux.
