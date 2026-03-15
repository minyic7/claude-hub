# Ticket Detail

The ticket detail panel provides a comprehensive view of a ticket's state, activity, review results, and available operations. It slides in from the right side of the board on desktop, or appears as a full-screen slide-up on mobile.

## Opening & Closing

- **Open** — click any ticket card on the Kanban board
- **Close (desktop)** — click the X button or click outside the panel
- **Close (mobile)** — swipe down more than 120px to dismiss

## Overview

The detail panel header shows:

- **Title** — editable when the ticket is in To Do status (click the pencil icon)
- **Description** — the task instructions for Claude Code
- **Status badge** — current status with color coding
- **Branch type** — feature, bugfix, hotfix, chore, refactor, docs, or test
- **Sequence number** — project-scoped ticket number
- **Timestamps** — created, started, and completed times
- **Cost** — agent cost in USD and total tokens used (if available)
- **PR link** — link to the GitHub pull request (when a PR exists)

## Notes System

Tickets support a structured notes system with five note types:

| Type | Purpose |
|------|---------|
| **Comment** | General notes from users |
| **Progress** | Status updates and milestone notes |
| **Blocker** | Issues preventing progress |
| **Review** | Review feedback and observations |
| **System** | Auto-generated notes (e.g., "Session stopped by user") |

Add a note using the input field at the bottom of the detail panel. Each note records the author, timestamp, and type.

## Activity Log

The activity log shows a chronological feed of everything that happens on a ticket.

### Event Types

| Type | Source | Description |
|------|--------|-------------|
| `thinking` | Claude Code | Internal reasoning steps |
| `tool_use` | Claude Code | Tool invocations (file edits, commands) |
| `tool_result` | Claude Code | Results from tool invocations |
| `commentary` | TicketAgent | Opinionated observations on progress |
| `intervention` | TicketAgent | Corrections sent to Claude Code |
| `decision` | TicketAgent | Autonomous choices made by the agent |
| `review` | TicketAgent | Code review results |
| `message` | User | Messages sent to the session |
| `info` | System | Informational events |
| `warning` | System | Warnings (e.g., idle detection) |
| `error` | System | Errors and failures |

### Filtering

Use the expandable **type filters** to show or hide specific event types. You can also filter by source:
- **Claude Code** — session output events
- **TicketAgent** — agent supervision events
- **User** — human-initiated events

### Search

Use the **search bar** to filter activity events by text content. Search matches against event summaries.

### Grouping

Consecutive events of the same type are automatically collapsed into groups (3+ events). Click a group to expand and see all events. Count badges show how many events are in each group.

Events are displayed in chronological order (newest at bottom) with auto-scroll to keep the latest events visible.

## Agent Review Report

When the TicketAgent reviews a ticket's code changes, the review report appears in the detail panel.

### Multi-Round Reviews

The review process supports up to **3 rounds**:

1. **Round 1** — initial review after Claude Code finishes
2. **Round 2** — if rejected, Claude Code gets feedback and tries again
3. **Round 3** — final attempt; if rejected again, the ticket fails and requires human review

Each round records its own verdict, scores, and issues.

### Scoring

Four metrics are scored on a **1–10 scale**:

| Metric | What It Measures |
|--------|-----------------|
| **Correctness** | Does the code do what the ticket asks? Any bugs? |
| **Security** | Vulnerabilities, injection risks, auth issues, exposed secrets? |
| **Quality** | Clean code, good naming, no dead code? |
| **Completeness** | All requirements met? Edge cases handled? |

Scores are visualized in two ways:
- **Radar chart** — a 4-point radar showing all metrics at once
- **Score rings** — individual circular progress indicators per metric

### Verdict

Each round results in either:
- **Approve** (green) — code passes review, ticket moves to Review status for human review
- **Reject** (red) — issues found, feedback sent as the task for a new Claude Code session

### Issues

Rejected reviews list specific issues, each with:
- **Severity** — critical, major, or minor
- **File** — the affected file path
- **Line** — the relevant line number
- **Description** — what's wrong and how to fix it

## Dependency Management

### Adding Dependencies

1. Click the **pencil icon** to enter edit mode (To Do status only)
2. Use the dependency picker to select tickets this one depends on
3. All project tickets are available except the ticket itself

### Dependency Guards

- A ticket **cannot be started** if any of its dependencies are not yet merged
- Dependencies are shown as chips with status icons indicating their current state
- **Reverse dependencies** (tickets that depend on this one) are shown read-only

## Status Operations

Available actions depend on the ticket's current status:

### Start

Launches a Claude Code session for this ticket. The backend:
1. Verifies all dependencies are merged
2. Checks the concurrent session limit (`max_sessions`)
3. Clones the repository and creates a feature branch
4. Starts a tmux session with Claude Code
5. Transitions the ticket to **In Progress**

If the session limit is reached, the ticket is queued instead.

### Stop

Sends `Ctrl+C` to the Claude Code session and transitions to **Failed**. The tmux session is kept alive for inspection (read-only). A system note "Session stopped by user" is added. Stopping a ticket frees a session slot and triggers queue processing.

### Retry

Restarts a failed ticket with optional **guidance** — additional instructions appended to the original task. The retry reuses the existing clone directory and includes any previous CI failure context.

### Merge

Initiates the merge process:
1. Polls CI status until all checks pass
2. Verifies PR review status (blocks if changes are requested)
3. Auto-merges via `gh pr merge --squash --delete-branch`
4. Cleans up the clone directory and tmux session
5. Transitions to **Merged**

### Request Changes

Sends the ticket back to **In Progress** with feedback. The feedback text becomes the task for a new Claude Code session. A pre-filled option is available for merge conflict resolution.

### Resolve Conflicts

A shortcut for Request Changes with pre-filled instructions to fetch, rebase on the base branch, resolve conflicts, and force-push with lease.

### Mark Ready for Review

Manually overrides the ticket status to **Review**, bypassing the agent review process. Useful when the agent incorrectly rejects code.

### Duplicate

Creates a new ticket copied from the current one with a new branch name. The description and settings carry over.

### Delete

Permanently removes the ticket. Kills any active session, cleans up the clone directory, and removes all data from Redis. Requires confirmation.

## Escalation Handling

When the TicketAgent encounters a decision it can't make autonomously, it **escalates** to a human — the ticket enters **Blocked** status.

### Escalation Banner

A prominent banner appears at the top of the detail panel showing the agent's question.

### Quick Answers

Respond quickly with predefined options:
- **Yes** / **No** — for yes/no questions
- **Continue** — proceed with the current approach
- **Skip** — skip the current step

Or type a **custom answer** in the text field and press Enter or click Send.

Your answer is sent to the Claude Code session via tmux, and the ticket transitions back to **In Progress**.

## CI Status

When a pull request exists, the detail panel shows live CI status:

- **Status** — passed, failed, pending, or no_ci
- **Individual checks** — name, state, and link for each GitHub Actions check
- **Polling** — CI status is polled every 10 seconds while the ticket is in Review or Merging status

## Merge Conflict Detection

The detail panel monitors for merge conflicts via `gh pr view --json mergeable`:

- A **warning indicator** appears when conflicts are detected (`has_conflicts` flag)
- Click **Resolve Conflicts** to automatically spawn a new session that rebases and resolves conflicts

## Idle Detection

If a ticket is in **In Progress** status with no activity for more than 2 minutes:

- An "Appears stuck" warning is shown
- A **Restart** button allows you to kill and restart the session
- Idle status is checked every 10 seconds

## tmux Session Reference

Each ticket's Claude Code session runs in a tmux session named `ch-{ticket_id[:8]}` (e.g., `ch-abc12345`). The session name is shown in the terminal header for reference. You can access the session directly via the integrated terminal panel.
