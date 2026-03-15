# Ticket Detail

The ticket detail panel slides in from the right side of the board when you click on a ticket card.

## Overview Section

- **Title** — editable ticket title
- **Status** — current status with color badge
- **Branch** — Git branch name (auto-generated from title)
- **Branch Type** — feature, bugfix, hotfix, etc.
- **Created** — timestamp of creation
- **Dependencies** — list of tickets this one depends on

## Activity Log

A chronological log of all activity on the ticket:
- Status changes with timestamps
- Claude Code session events (start, stop, output)
- TicketAgent observations and decisions
- CI/CD status updates
- Human comments and actions

## Actions

Available actions depend on the ticket's current status:

| Action | When Available |
|--------|---------------|
| **Start** | To Do status — launches Claude Code session |
| **Stop** | In Progress — stops the Claude session |
| **Retry** | Failed/Blocked — restarts with optional new instructions |
| **Archive** | Any status — hides from board |
| **Delete** | Any status — permanently removes |

## CI Status

When a PR is open, the detail panel shows:
- GitHub Actions workflow status
- Individual check results
- Link to the PR on GitHub

## Editing

Click the edit icon to modify:
- Ticket title
- Description / instructions
- Dependencies
- Branch type
