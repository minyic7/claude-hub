"""Manages persistent project kanban Claude Code sessions.

Each project gets a single long-running tmux session (claude-hub-kanban-{project_id})
that acts as a project kanban helper assisting users with coding, requirements, and tickets.
These sessions do NOT count toward max_sessions.
"""

import logging
import os
import shlex
import subprocess
from datetime import datetime, timedelta, timezone

import jwt

from claude_hub.config import settings

logger = logging.getLogger(__name__)


def _session_name(project_id: str) -> str:
    return f"claude-hub-kanban-{project_id}"


def _tmux_exists(name: str) -> bool:
    result = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
    return result.returncode == 0


def _tmux_is_dead(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "display-message", "-t", name, "-p", "#{pane_dead}"],
        capture_output=True, text=True,
    )
    return result.returncode != 0 or result.stdout.strip() == "1"


def _restore_claude_config() -> None:
    """Ensure ~/.claude.json survives container rebuilds.

    The Docker volume persists ~/.claude/ (subdir) but ~/.claude.json is in ~/
    which gets wiped on container rebuild. Strategy:
    1. If ~/.claude.json exists as a regular file, move it into the volume
    2. Create a symlink ~/.claude.json -> ~/.claude/.claude.json
    This way the file lives inside the persisted volume.
    Also ensures settings.json marks onboarding as complete to skip theme picker.
    """
    import json as _json

    home = os.path.expanduser("~")
    config_path = os.path.join(home, ".claude.json")
    volume_path = os.path.join(home, ".claude", ".claude.json")

    # If config exists as a regular file (not symlink), move it into the volume
    if os.path.isfile(config_path) and not os.path.islink(config_path):
        import shutil
        shutil.move(config_path, volume_path)
        logger.info("Moved %s into volume at %s", config_path, volume_path)

    # Create symlink if it doesn't exist but volume copy does
    if not os.path.exists(config_path) and os.path.exists(volume_path):
        os.symlink(volume_path, config_path)
        logger.info("Symlinked %s -> %s", config_path, volume_path)

    # Ensure onboarding is marked complete (skips theme picker in interactive mode)
    settings_path = os.path.join(home, ".claude", "settings.json")
    try:
        existing = {}
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                existing = _json.load(f)
        if not existing.get("hasCompletedOnboarding"):
            existing["hasCompletedOnboarding"] = True
            with open(settings_path, "w") as f:
                _json.dump(existing, f)
            logger.info("Marked onboarding as complete in %s", settings_path)
    except Exception as e:
        logger.warning("Failed to update settings.json: %s", e)

    # Auto-trust kanban directories (skip "trust this folder?" prompt)
    try:
        config_data = {}
        if os.path.exists(volume_path):
            with open(volume_path) as f:
                config_data = _json.load(f)
        elif os.path.exists(config_path):
            with open(config_path) as f:
                config_data = _json.load(f)

        projects = config_data.setdefault("projects", {})
        kanbans_dir = os.path.join(settings.data_dir, "kanbans")
        # Trust any subdirectory under /data/kanbans/
        # Claude Code uses the directory path as key with allowedTools etc.
        needs_write = False
        for entry in os.listdir(kanbans_dir) if os.path.isdir(kanbans_dir) else []:
            kanban_path = os.path.join(kanbans_dir, entry)
            if kanban_path not in projects:
                projects[kanban_path] = {"allowedTools": [], "isTrusted": True}
                needs_write = True

        if needs_write:
            target = volume_path if os.path.exists(os.path.dirname(volume_path)) else config_path
            with open(target, "w") as f:
                _json.dump(config_data, f)
            logger.info("Auto-trusted kanban directories in %s", target)
    except Exception as e:
        logger.warning("Failed to auto-trust kanban dirs: %s", e)


def _generate_internal_token() -> str:
    """Generate a long-lived JWT for kanban internal API calls (localhost only)."""
    exp = datetime.now(timezone.utc) + timedelta(days=3650)
    return jwt.encode({"exp": exp, "kanban": True}, settings.auth_secret, algorithm="HS256")


def _build_kanban_claude_md(project: dict, api_base_url: str, auth_token: str = "") -> str:
    """Generate CLAUDE.md content for the kanban session."""
    project_name = project.get("name", "Unknown")
    project_id = project["id"]
    repo_url = project.get("repo_url", "")
    base_branch = project.get("base_branch", "main")
    pilot_mode = project.get("pilot_mode", False)
    max_board_tickets = project.get("max_board_tickets", 10)
    max_tickets_per_cycle = project.get("max_tickets_per_cycle", 2)
    vision_mode = project.get("vision_mode", "readonly")
    auth = f'-H "Authorization: Bearer {auth_token}"' if auth_token else ""

    md = f"""# Kanban Claude Code — {project_name}

You are the **Kanban Claude Code** for the "{project_name}" project.
You work directly on this repository and help users with coding, refining requirements, and managing tickets.

## On Startup
When you first start, do the following:
1. Run `get_kanban_state` (see API Tools below) to load the current board state
2. Read VISION.md if it exists to orient yourself
3. Greet the user with a brief summary of the board (e.g., how many tickets, what's in progress)
4. Let them know you're ready to help — coding, creating tickets, or anything else

## Project Context
- **Repository**: {repo_url}
- **Base branch**: {base_branch}
- **Working branch**: `kanban-claude-hub` (created from {base_branch})
- **Project ID**: {project_id}
- **Pilot Mode**: {"ENABLED" if pilot_mode else "disabled"}

## Your Capabilities
You are a full Claude Code instance with access to the repository. You can:
1. **Read and modify code** — explore the codebase, write features, fix bugs, refactor
2. **Manage tickets** — create, update, and organize kanban tickets via the API tools below
3. **Help with requirements** — refine vague ideas into structured, actionable tickets
4. **Break down work** — split large features into smaller tickets with dependencies
5. **Suggest branch types** (feature, bugfix, hotfix, chore, refactor, docs, test)
6. **Analyze dependencies** between tickets and suggest execution order

## Ticket Format Conventions
- **Title**: Imperative mood, concise (e.g., "Add user authentication endpoint")
- **Description**: Structured with these sections:
  ```
  ## What
  [What needs to be done — specific and actionable]

  ## Acceptance Criteria
  [What done looks like — testable conditions]

  ## Technical Notes
  [Optional: implementation hints, constraints, risks]
  ```
- **Branch type**: Choose the most appropriate type for the work

## Kanban State Awareness
- **On startup**: Always run `get_kanban_state` to build your mental model of the current board.
- **Before every response**: Silently re-run `get_kanban_state` to ensure your mental model is current. Do NOT mention this refresh to the user — just do it.
- **Maintain a mental model**: Keep track of all ticket titles, descriptions, statuses, and dependencies so you can detect overlaps and suggest relationships.

## Duplicate / Overlap Detection
Before creating any new ticket, you MUST:
1. Run `get_kanban_state` if you haven't recently
2. Compare the proposed ticket against ALL existing tickets (any status except archived)
3. Check for title similarity, scope overlap, and subset/superset relationships
4. If overlap is detected, **warn the user** before creating

## Dependency Analysis & Ordering
When reviewing the board or creating new tickets:
- Identify natural dependencies
- Suggest `depends_on` relationships when creating or updating tickets
- When asked about priority or ordering, analyze the dependency graph and suggest an execution order

## API Tools

You communicate with the Kanban system via these curl commands.
Always use the exact format shown. Replace UPPERCASE placeholders with actual values.

### get_kanban_state
Fetch all active (non-archived) tickets for this project.
Run this before every response to ensure your mental model is current.
```bash
curl -s {auth} {api_base_url}/api/projects/{project_id}/tickets | python3 -m json.tool
```

### get_project_info
Read project settings including pilot mode and ticket limits.
```bash
curl -s {auth} {api_base_url}/api/projects/{project_id} | python3 -m json.tool
```

### get_ticket
Read full detail for a single ticket.
```bash
curl -s {auth} {api_base_url}/api/tickets/TICKET_ID | python3 -m json.tool
```

### create_ticket
Create a new ticket. All fields required unless marked optional.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "title": "TICKET_TITLE", "description": "TICKET_DESCRIPTION", "branch_type": "feature", "depends_on": [], "priority": 0, "pilot": {"true" if pilot_mode else "false"}}}'
```
Valid branch_type values: feature, bugfix, hotfix, chore, refactor, docs, test

### update_ticket
Update a ticket. Only works on TODO tickets. Include only fields to change.
```bash
curl -s -X PATCH {auth} {api_base_url}/api/tickets/TICKET_ID \\
  -H "Content-Type: application/json" \\
  -d '{{"title": "NEW_TITLE", "priority": 0, "depends_on": []}}'
```

### archive_ticket
Archive a ticket. WARNING: this is a toggle — calling it on an already-archived ticket will unarchive it.
Always verify ticket.archived == false before calling.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/archive
```

### reorder_tickets
Set priority order for TODO tickets. First ID = highest priority.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/reorder \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "ticket_ids": ["ID_1", "ID_2", "ID_3"]}}'
```

### get_queue
Check current execution queue and session capacity.
```bash
curl -s {auth} {api_base_url}/api/tickets/queue | python3 -m json.tool
```

### answer_ticket
Unblock a BLOCKED ticket and send the answer to its tmux session.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/answer \\
  -H "Content-Type: application/json" \\
  -d '{{"answer": "YOUR_ANSWER_HERE"}}'
```

### message_ticket
Send a message to an IN_PROGRESS or BLOCKED session. Also unblocks if ticket is BLOCKED.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/message \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "YOUR_MESSAGE_HERE"}}'
```

### retry_ticket
Restart a FAILED ticket. Optionally include guidance to avoid repeating the same mistake.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/retry \\
  -H "Content-Type: application/json" \\
  -d '{{"guidance": "OPTIONAL_GUIDANCE"}}'
```

### request_changes
Flag wrong or incomplete implementation on AWAITING_MERGE. Transitions back to IN_PROGRESS.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/request-changes \\
  -H "Content-Type: application/json" \\
  -d '{{"feedback": "SPECIFIC_FEEDBACK_ABOUT_WHAT_IS_WRONG"}}'
```

### resolve_conflicts
Trigger conflict resolution for an AWAITING_MERGE ticket where has_conflicts is true.
Spawns a CC session that runs git rebase and resolves any conflicts.
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/resolve-conflicts
```

### add_note
Append a note to any ticket. Use to log observations during triage.
Valid types: comment (default), progress, blocker, review, system
```bash
curl -s -X POST {auth} {api_base_url}/api/tickets/TICKET_ID/notes \\
  -H "Content-Type: application/json" \\
  -d '{{"content": "YOUR_NOTE", "type": "progress"}}'
```

### get_ticket_diff
Read the PR diff for a ticket. Use this to understand what a session produced.
Returns null diff if the ticket has no PR.
```bash
curl -s {auth} {api_base_url}/api/tickets/TICKET_ID/diff | python3 -m json.tool
```

### get_ci_status
Check CI pass/fail for a ticket with an open PR.
```bash
curl -s {auth} {api_base_url}/api/tickets/TICKET_ID/ci-status | python3 -m json.tool
```

### get_unresolved_threads
Check open PR review threads for an AWAITING_MERGE ticket.
```bash
curl -s {auth} {api_base_url}/api/tickets/TICKET_ID/unresolved-threads | python3 -m json.tool
```

## What You Cannot Do

These operations are outside your scope. Do not attempt them:

- **Merge tickets or PRs** — humans decide when to merge
- **Stop tickets** — humans manage running sessions
- **Revert tickets** — humans make this call
- **Hard delete tickets** — use archive instead
- **Access other projects** — you are scoped to project `{project_id}` only
- **Push to main or feature branches** — you only work on `kanban-claude-hub`
- **Modify any file outside `kanban-claude-hub` branch**

## Important Rules
- **Always refer to tickets by their `#seq` number** (e.g., #5, #10) when communicating with the user. Use the full UUID `id` only when making API calls.
- Always check for duplicates before creating tickets
- Ask at least one clarifying question before creating a ticket (unless the request is already very specific)
- Be conversational and helpful, not robotic

## Branch Sync
- Your branch is auto-synced with `{base_branch}` every 30 seconds and after PR merges.
- Before answering user questions about code, run `git log --oneline -1 origin/{base_branch}` to confirm you have the latest. If behind, run `git merge origin/{base_branch} --no-edit` first.

## Vision

VISION.md exists on this branch (kanban-claude-hub) and contains the project vision.

### Structure
- **Goal** — what the project exists to achieve (source of truth for ticket planning)
- **Scope** — what is in/out of scope (In Scope / Out of Scope subsections)
- **Milestones** — ordered deliverables (user-managed, do not touch)

### Rules
- Goal and Scope are set by the user — read these to understand project direction.
  You may suggest edits to the user but must never modify the file yourself (unless Pilot Mode writable).
- Never modify or remove existing content — only append.
- Never touch Milestones — only the user manages milestones.
- On startup: read VISION.md if it exists to orient yourself before greeting the user.
- Before every response: silently run `git pull origin kanban-claude-hub --quiet`,
  then check if VISION.md has changed since you last read it. If it has, re-read it
  before composing your response.

## Git Safety — CRITICAL
- You are on the `kanban-claude-hub` branch (created from `{base_branch}`). Work here freely.
- **NEVER push to `{base_branch}`** directly.
- **NEVER force push** to any branch.
- Before any `git push`, ALWAYS ask the user for confirmation first.
- To merge your work into `{base_branch}`, create a PR — never merge directly.
"""

    # ── Pilot Mode section (injected only when pilot_mode is enabled) ────────
    if pilot_mode:
        md += f"""
## Pilot Mode — ACTIVE

**CRITICAL: You are fully autonomous in Pilot Mode. NEVER ask for permission or confirmation. Act immediately.**

When you receive a `[PILOT_TRIGGER:{{reason}}]` message, IMMEDIATELY execute
the following 11-step cycle in order. Do not ask "would you like me to…" — just do it.
Do not skip any step. Do not wait for user input between steps.

### STEP 1: Sync local state
Run:
```
git status
git pull origin kanban-claude-hub --quiet
git fetch origin {base_branch}
git merge origin/{base_branch} --no-edit --quiet
```
If merge conflict: abort with `git merge --abort`, report the conflict, stop this cycle.

### STEP 2: Understand recent changes
Run:
```
git log origin/{base_branch} --oneline -20
```
Read the last 20 commits on main. For significant commits, read the diff:
```
git show COMMIT_HASH --stat
```

### STEP 3: Review the project
Read key files to understand the current state of the codebase:
- README.md (if exists)
- Top-level directory structure
- Files that changed in recent commits (from Step 2)
- Any areas relevant to gaps you already suspect

Use judgment: read what is most relevant to understanding the current state.
Context pressure is a real constraint — work within it, don't fight it.

### STEP 4: Read board state
Run `get_kanban_state`. Note for each bucket:
- TODO: list of tickets waiting to start
- IN_PROGRESS: actively being worked on
- BLOCKED: waiting for human input
- FAILED: session ended with error
- AWAITING_MERGE: PR open, waiting for merge
- MERGED: completed but not yet archived

### STEP 5: Triage existing tickets
Review every non-archived ticket. For each one, decide its fate:

**TODO tickets:**
- Still needed? → keep, possibly update description if stale
- Already implemented or no longer relevant? → archive it

**IN_PROGRESS tickets:**
- Leave them alone — a session is active, don't interrupt.

**BLOCKED tickets:**
- Read the blocked_question. Can you answer it? → POST /tickets/{{id}}/answer
- Cannot answer? → leave it, note in report as needing human attention

**FAILED tickets:**
- Conflict → POST /tickets/{{id}}/retry directly, no guidance needed
- Transient error → POST /tickets/{{id}}/retry directly
- Code problem → read the PR diff (use get_ticket_diff), update description with better guidance, then retry
- Blocked on human decision → leave it, note in report

**AWAITING_MERGE tickets:**
- has_conflicts: true → POST /tickets/{{id}}/resolve-conflicts
- has_conflicts: false → check the PR diff: correct implementation? No action needed.
  Wrong implementation? → POST /tickets/{{id}}/request-changes with specific feedback

**MERGED tickets:**
- Skip. Trust that Claude Code completed the work.

### STEP 6: Read VISION.md
Read VISION.md from this branch.

VISION.md has three sections:
- **Goal** — what the project exists to achieve
- **Scope** — In Scope / Out of Scope subsections
- **Milestones** — ordered deliverables (user-managed, NEVER touch)

Focus on Goal and Scope — these are the source of truth for all ticket planning.

Vision mode is: **{vision_mode}**

{"You may NOT modify VISION.md. If you believe the vision should be extended, include a **Vision Amendment Proposals** section at the end of your Step 10 report. The user will review and update VISION.md manually." if vision_mode == "readonly" else "You MAY APPEND to Goal and Scope sections when: (1) the current Goal/Scope has been fully implemented, (2) you have a clear next direction based on what exists, (3) the extension is additive — never remove or contradict existing content. Always edit VISION.md and `git commit + push` before creating new tickets so they are grounded in the updated vision. NEVER touch Milestones — only the user manages milestones."}

### STEP 7: Identify gaps
Cross-reference:
- What VISION.md says should exist
- What you saw in code (Step 3)
- What tickets are active after triage (Step 5)

List the gaps explicitly before moving to planning.

### STEP 8: Plan & Sanity Check
Count active tickets after triage (TODO + IN_PROGRESS + AWAITING_MERGE).

- IF active_count >= {max_board_tickets}: Do NOT create tickets. Focus on triage. Report board state.
- IF active_count < {max_board_tickets}: Pick the most important gap. Draft at most {max_tickets_per_cycle} ticket(s).
  You can create up to ({max_board_tickets} - active_count) tickets, but never more than {max_tickets_per_cycle} per cycle.

Sanity check:
- Does each ticket address a real gap (not just nice-to-have)?
- Is the description specific enough for Claude Code to act on?
- Are dependencies set correctly?
- Would a senior engineer agree this is the right next step?

### STEP 9: Execute
Execute the plan using the API tools.
Set `"pilot": true` on every ticket you create.

### STEP 10: Report
Post a brief summary:
- What you found in the review
- Triage actions taken (archived, unblocked, retried, request-changes)
- What gaps you identified
- What you created/updated and why
- Or why you decided not to act this cycle

### STEP 11: Compact
Run `/compact` now. This is mandatory — even if the cycle seemed short.
This ensures the next trigger starts with a clean context.
After /compact completes, the cycle is done. Wait for the next trigger.
"""

    return md


def start_kanban(project: dict, gh_token: str = "") -> str:
    """Start or restart the kanban session for a project.

    Returns the tmux session name.
    """
    project_id = project["id"]
    name = _session_name(project_id)

    # Ensure Claude CLI config exists (may be lost on container rebuild)
    _restore_claude_config()

    # Kill existing session if any
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)

    # Prepare clone directory for the kanban session
    from claude_hub.services.clone_manager import ensure_reference, _inject_token, _reference_dir, _repo_hash

    repo_url = project.get("repo_url", "")
    base_branch = project.get("base_branch", "main")
    kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)

    authed_url = _inject_token(repo_url, gh_token)

    if os.path.exists(kanban_dir):
        # Update existing clone
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=kanban_dir, capture_output=True,
        )
    else:
        os.makedirs(os.path.dirname(kanban_dir), exist_ok=True)
        # Try reference clone first
        try:
            ensure_reference(repo_url, gh_token)
        except Exception:
            pass

        ref_path = os.path.join(_reference_dir(), f"{_repo_hash(repo_url)}.git")
        if os.path.exists(ref_path):
            subprocess.run(
                ["git", "clone", "--reference", ref_path, authed_url, kanban_dir],
                check=True, capture_output=True,
            )
        else:
            subprocess.run(
                ["git", "clone", authed_url, kanban_dir],
                check=True, capture_output=True,
            )

    # Checkout dedicated kanban branch (keeps main clean)
    kanban_branch = "kanban-claude-hub"
    subprocess.run(
        ["git", "fetch", "origin"],
        cwd=kanban_dir, capture_output=True,
    )
    # Check if branch exists on remote
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", kanban_branch],
        cwd=kanban_dir, capture_output=True, text=True,
    )
    if kanban_branch in (result.stdout or ""):
        # Branch exists on remote — switch to it and pull latest
        subprocess.run(
            ["git", "checkout", kanban_branch],
            cwd=kanban_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "pull", "origin", kanban_branch],
            cwd=kanban_dir, capture_output=True,
        )
    else:
        # Create new branch from latest base and push it
        logger.info("Creating kanban branch '%s' for project %s", kanban_branch, project_id)
        subprocess.run(
            ["git", "checkout", base_branch],
            cwd=kanban_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{base_branch}"],
            cwd=kanban_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", kanban_branch],
            cwd=kanban_dir, capture_output=True,
        )

        # Create initial VISION.md if it doesn't exist
        vision_path = os.path.join(kanban_dir, "VISION.md")
        if not os.path.exists(vision_path):
            project_name = project.get("name", "Project")
            with open(vision_path, "w") as f:
                f.write(f"# {project_name} — Vision\n\n"
                        "## Goal\n\n"
                        "What this project exists to achieve.\n\n"
                        "- (Add your project goals here)\n\n"
                        "## Scope\n\n"
                        "What is in scope and what is explicitly out of scope.\n\n"
                        "### In Scope\n"
                        "- (Define what is in scope)\n\n"
                        "### Out of Scope\n"
                        "- (Define what is out of scope)\n\n"
                        "## Milestones\n\n"
                        "Ordered list of deliverables. Check off as completed.\n\n"
                        "- [ ] (First milestone)\n\n"
                        "---\n\n"
                        "<!-- KANBAN_CC_RULES:\n"
                        "  - Goal and Scope are the source of truth for all ticket planning.\n"
                        "  - In writable mode, CC may APPEND to Goal and Scope sections only.\n"
                        "  - CC must NEVER modify or remove existing content in any section.\n"
                        "  - CC must NEVER touch Milestones — only the user manages milestones.\n"
                        "  - In readonly mode, CC proposes amendments in the Step 10 report.\n"
                        "-->\n")
            subprocess.run(
                ["git", "add", "VISION.md"],
                cwd=kanban_dir, capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initialize VISION.md for Claude Hub kanban"],
                cwd=kanban_dir, capture_output=True,
            )
            logger.info("Created initial VISION.md for project %s", project_id)

        push_result = subprocess.run(
            ["git", "push", "-u", "origin", kanban_branch],
            cwd=kanban_dir, capture_output=True, text=True,
        )
        if push_result.returncode != 0:
            logger.error("Failed to push kanban branch: %s", push_result.stderr)
        else:
            logger.info("Pushed kanban branch '%s' for project %s", kanban_branch, project_id)

    # Write CLAUDE.md for the kanban session
    api_base_url = f"http://localhost:{settings.port}"
    auth_token = _generate_internal_token() if settings.auth_enabled else ""
    claude_md = _build_kanban_claude_md(project, api_base_url, auth_token)
    claude_md_path = os.path.join(kanban_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(claude_md)

    # Pre-approve kanban tools (merge with existing user-granted permissions)
    import json as _json
    claude_settings_dir = os.path.join(kanban_dir, ".claude")
    os.makedirs(claude_settings_dir, exist_ok=True)
    claude_settings_path = os.path.join(claude_settings_dir, "settings.json")
    required_allow = {"Bash(*)"}
    try:
        existing = {}
        if os.path.exists(claude_settings_path):
            with open(claude_settings_path) as f:
                existing = _json.load(f)
        perms = existing.setdefault("permissions", {})
        current_allow = set(perms.get("allow", []))
        current_allow.update(required_allow)
        perms["allow"] = sorted(current_allow)
        with open(claude_settings_path, "w") as f:
            _json.dump(existing, f, indent=2)
    except Exception as e:
        logger.warning("Failed to update .claude/settings.json: %s", e)

    # Build claude command — interactive mode (no -p, no --output-format)
    # Wrapped in a restart loop so accidental exit doesn't kill the session
    parts = [
        settings.claude_bin,
        "--verbose",
    ]
    inner_cmd = " ".join(parts)
    # Wrapper: auto-restart Claude Code if it exits, with a 2s pause to avoid tight loops
    claude_cmd = f'while true; do {inner_cmd}; echo -e "\\n\\033[33mClaude Code exited. Restarting in 2s... (Ctrl+C to stop)\\033[0m"; sleep 2; done'

    # Create tmux session — strip ANTHROPIC_API_KEY so Claude Code uses
    # its own subscription login, not the API key from the host environment.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    token = gh_token or settings.gh_token
    if token:
        env["GH_TOKEN"] = token

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-x", "200", "-y", "50"],
        check=True, env=env, cwd=kanban_dir,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "remain-on-exit", "on"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "mouse", "off"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "history-limit", "200000"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "extended-keys", "on"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "allow-passthrough", "on"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", name, claude_cmd, "Enter"],
        check=True,
    )

    logger.info("Started kanban session %s for project %s", name, project_id)
    return name


def is_alive(project_id: str) -> bool:
    name = _session_name(project_id)
    return _tmux_exists(name) and not _tmux_is_dead(name)


def get_status(project_id: str) -> dict:
    """Get kanban session status."""
    name = _session_name(project_id)
    alive = _tmux_exists(name) and not _tmux_is_dead(name)
    return {
        "alive": alive,
        "session_name": name,
        "ssh_command": f"tmux attach -t {name}",
    }


def restart_kanban(project: dict, gh_token: str = "") -> str:
    """Kill and recreate the kanban session."""
    project_id = project["id"]
    name = _session_name(project_id)
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        logger.info("Killed existing kanban session %s", name)
    return start_kanban(project, gh_token)


def sync_kanban_branch(project_id: str, gh_token: str = "", base_branch: str = "main") -> dict:
    """Merge latest base branch into the kanban working branch.

    Returns {"status": "updated"|"up_to_date"|"conflict"|"error", "message": str}
    """
    kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)
    if not os.path.exists(kanban_dir):
        return {"status": "error", "message": "Kanban directory not found"}

    env = {**os.environ}
    if gh_token:
        env["GH_TOKEN"] = gh_token

    # Fetch latest
    subprocess.run(["git", "fetch", "origin"], cwd=kanban_dir, capture_output=True, env=env)

    # Check if behind
    result = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..origin/{base_branch}"],
        cwd=kanban_dir, capture_output=True, text=True, env=env,
    )
    behind = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else 0
    if behind == 0:
        return {"status": "up_to_date", "message": "Already up to date"}

    # Try merge
    result = subprocess.run(
        ["git", "merge", f"origin/{base_branch}", "--no-edit"],
        cwd=kanban_dir, capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        subprocess.run(["git", "merge", "--abort"], cwd=kanban_dir, capture_output=True)
        logger.warning("Kanban branch merge conflict for project %s: %s", project_id, result.stderr.strip())
        # Reset to base branch to unblock — kanban branch is ephemeral
        subprocess.run(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=kanban_dir, capture_output=True, env=env)
        logger.info("Reset kanban branch to origin/%s for project %s", base_branch, project_id)
        return {"status": "conflict", "message": f"Conflict resolved by resetting to {base_branch}"}

    # Push updated branch
    subprocess.run(["git", "push"], cwd=kanban_dir, capture_output=True, env=env)
    logger.info("Synced kanban branch for project %s (%d commits from %s)", project_id, behind, base_branch)
    return {"status": "updated", "message": f"Merged {behind} new commit(s) from {base_branch}"}


def send_kanban_update(project_id: str) -> None:
    """No-op: kanban CC now refreshes state on each user interaction via CLAUDE.md instructions.

    Previously sent [KANBAN_UPDATE] via tmux send-keys, which interrupted user conversations.
    """
    pass


def rebuild_claude_md(project_id: str, project: dict) -> bool:
    """Rewrite CLAUDE.md for an existing kanban session (e.g. after pilot config change).

    Returns True if the file was written, False if the kanban dir doesn't exist.
    """
    kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)
    if not os.path.exists(kanban_dir):
        return False

    api_base_url = f"http://localhost:{settings.port}"
    auth_token = _generate_internal_token() if settings.auth_enabled else ""
    claude_md = _build_kanban_claude_md(project, api_base_url, auth_token)
    claude_md_path = os.path.join(kanban_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(claude_md)
    logger.info("Rebuilt CLAUDE.md for project %s", project_id)
    return True


def send_pilot_trigger(project_id: str, reason: str) -> None:
    """Send a pilot mode trigger to the kanban CC session via tmux send-keys.

    Only sends if the project has pilot_mode enabled and the session is alive.
    The trigger text is typed into the terminal as user input for Claude Code.
    """
    name = _session_name(project_id)
    if not is_alive(project_id):
        logger.debug("Pilot trigger skipped: no alive session for %s", project_id)
        return

    trigger_text = f"[PILOT_TRIGGER:{reason}]"
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", name, trigger_text, "Enter"],
            capture_output=True, timeout=5,
        )
        logger.info("Sent pilot trigger to %s: %s", project_id, reason)
    except Exception as e:
        logger.warning("Failed to send pilot trigger to %s: %s", project_id, e)
