---
name: pilot-cycle
description: Execute the full autonomous pilot cycle — sync, review, triage, plan, execute, report. Run this when you receive a [PILOT_TRIGGER] message.
disable-model-invocation: true
---

**CRITICAL: You are fully autonomous in Pilot Mode. NEVER ask for permission or confirmation. Act immediately.**

Execute the following 11-step cycle in order. Do not ask "would you like me to…" — just do it.
Do not skip any step. Do not wait for user input between steps.

Use the kanban skills (`/board`, `/start-ticket`, `/create-ticket`, etc.) for API operations.

## STEP 1: Sync local state
```
git status
git pull origin kanban-claude-hub --quiet
git fetch origin {base_branch}
git merge origin/{base_branch} --no-edit --quiet
```
If merge conflict: abort with `git merge --abort`, report the conflict, stop this cycle.

## STEP 2: Understand recent changes
```
git log origin/{base_branch} --oneline -20
```
Read the last 20 commits on main. For significant commits, read the diff:
```
git show COMMIT_HASH --stat
```

## STEP 3: Review the project
Read key files to understand the current state of the codebase:
- README.md (if exists)
- Top-level directory structure
- Files that changed in recent commits (from Step 2)
- Any areas relevant to gaps you already suspect

Use judgment: read what is most relevant to understanding the current state.
Context pressure is a real constraint — work within it, don't fight it.

## STEP 4: Read board state
Run `/board`. Note for each bucket:
- TODO: list of tickets waiting to start
- IN_PROGRESS: actively being worked on
- BLOCKED: waiting for human input
- FAILED: session ended with error
- AWAITING_MERGE: PR open, waiting for merge
- MERGED: completed but not yet archived

## STEP 5: Triage existing tickets
Review every non-archived ticket. For each one, decide its fate:

**TODO tickets:**
- Still needed? → keep, possibly update description if stale
- Already implemented or no longer relevant? → `/archive-ticket TICKET_ID`
- Ready to start (no unmet dependencies, no other ticket in progress)? → `/start-ticket TICKET_ID`
- **IMPORTANT:** Always start the highest-priority unblocked TODO ticket if nothing is currently IN_PROGRESS. The board won't make progress unless you start tickets!

**IN_PROGRESS tickets:**
- Leave them alone — a session is active, don't interrupt.

**BLOCKED tickets:**
- Read the blocked_question. Can you answer it? → `/answer-ticket TICKET_ID`
- Cannot answer? → leave it, note in report as needing human attention

**FAILED tickets:**
- Conflict → `/retry-ticket TICKET_ID` directly, no guidance needed
- Transient error → `/retry-ticket TICKET_ID` directly
- Code problem → read the PR diff (`/ticket-diff TICKET_ID`), update description with better guidance, then retry
- Blocked on human decision → leave it, note in report

**AWAITING_MERGE tickets:**
- has_conflicts: true → `/resolve-conflicts TICKET_ID`
- has_conflicts: false → check the PR diff (`/ticket-diff`): correct implementation? No action needed.
  Wrong implementation? → `/request-changes TICKET_ID` with specific feedback

**MERGED tickets:**
- Skip. Trust that Claude Code completed the work.

## STEP 6: Read VISION.md
Read VISION.md from this branch.

VISION.md has three sections:
- **Goal** — what the project exists to achieve
- **Scope** — In Scope / Out of Scope subsections
- **Milestones** — ordered deliverables (user-managed, NEVER touch)

Focus on Goal and Scope — these are the source of truth for all ticket planning.

Vision mode is: **{vision_mode}**

{vision_instructions}

## STEP 7: Identify gaps
Cross-reference:
- What VISION.md says should exist
- What you saw in code (Step 3)
- What tickets are active after triage (Step 5)

List the gaps explicitly before moving to planning.

## STEP 8: Plan & Sanity Check
Count active tickets after triage (TODO + IN_PROGRESS + AWAITING_MERGE).

- IF active_count >= {max_board_tickets}: Do NOT create tickets. Focus on triage. Report board state.
- IF active_count < {max_board_tickets}: Pick the most important gap. Draft at most {max_tickets_per_cycle} ticket(s).
  You can create up to ({max_board_tickets} - active_count) tickets, but never more than {max_tickets_per_cycle} per cycle.

Sanity check:
- Does each ticket address a real gap (not just nice-to-have)?
- Is the description specific enough for Claude Code to act on?
- Are dependencies set correctly?
- Would a senior engineer agree this is the right next step?

## STEP 9: Execute
Execute the plan:
- **Start tickets**: If you identified TODO tickets to start in Step 5, use `/start-ticket TICKET_ID` NOW
- **Create tickets**: Use `/create-ticket` — set `"pilot": true` on every ticket you create
- **Other actions**: retry, answer, resolve-conflicts, request-changes as decided in triage

**The most important action is starting work.** If nothing is IN_PROGRESS and there are startable TODO tickets, you MUST start one.

## STEP 10: Report
Post a brief summary:
- What you found in the review
- Triage actions taken (archived, unblocked, retried, request-changes)
- What gaps you identified
- What you created/updated and why
- Or why you decided not to act this cycle

## STEP 11: Compact
Run `/compact` now. This is mandatory — even if the cycle seemed short.
This ensures the next trigger starts with a clean context.
After /compact completes, the cycle is done. Wait for the next trigger.
