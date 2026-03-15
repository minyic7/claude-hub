# Ticket Agent

The TicketAgent is an AI supervisor that monitors and guides Claude Code sessions using a trust-but-verify model.

## How It Works

The TicketAgent runs a **ReAct loop** (Reason → Act → Observe) powered by the Anthropic API:

1. **Observe** — reads Claude Code's latest output from the terminal
2. **Reason** — evaluates progress against the ticket's requirements
3. **Act** — decides whether to intervene, wait, or approve

## Supervision Model

The TicketAgent uses a **trust-but-verify** approach:
- Claude Code works autonomously on the ticket
- The agent periodically checks progress
- Intervention only happens when issues are detected

### When the Agent Intervenes

- [ ] Code doesn't match ticket requirements
- [ ] Tests are failing repeatedly
- [ ] Claude Code is stuck in a loop
- [ ] Security or quality concerns detected
- [ ] Dependencies are not being respected

## Agent Actions

| Action | Description |
|--------|-------------|
| **Guide** | Send instructions to Claude Code |
| **Approve** | Mark work as satisfactory |
| **Escalate** | Flag for human review |
| **Block** | Pause work, set ticket to blocked |
| **Retry** | Restart the session with new context |

## Configuration

TicketAgent settings can be configured per-project in **Settings → TicketAgent**:
- Model selection (which Anthropic model to use)
- Supervision frequency
- Auto-approve thresholds
- Custom system prompts

## Review Reports

When the TicketAgent completes a review cycle, it generates a structured report visible in the ticket detail panel, covering:
- Code quality assessment
- Requirements compliance
- Test coverage evaluation
- Suggested improvements
