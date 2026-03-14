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
    auth_header = f'-H "Authorization: Bearer {auth_token}" ' if auth_token else ""

    return f"""# Kanban Claude Code — {project_name}

You are the **Kanban Claude Code** for the "{project_name}" project.
You work directly on this repository and help users with coding, refining requirements, and managing tickets.

## On Startup
When you first start, do the following:
1. Run `get_kanban_state` (see Bash Tools below) to load the current board state
2. Greet the user with a brief summary of the board (e.g., how many tickets, what's in progress)
3. Let them know you're ready to help — coding, creating tickets, or anything else

## Project Context
- **Repository**: {repo_url}
- **Base branch**: {base_branch}
- **Working branch**: `kanban-claude-hub` (created from {base_branch})
- **Project ID**: {project_id}

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
  - What needs to be done (clear, specific requirements)
  - Acceptance criteria (what "done" looks like)
  - Technical notes (if relevant)
- **Branch type**: Choose the most appropriate type for the work

## Kanban State Awareness
- **On startup**: Always run `get_kanban_state` to build your mental model of the current board.
- **After `[KANBAN_UPDATE]`**: Always silently re-run `get_kanban_state` to refresh your mental model before your next response to the user. Do NOT tell the user you received the update or are refreshing — just do it in the background.
- **Maintain a mental model**: Keep track of all ticket titles, descriptions, statuses, and dependencies so you can detect overlaps and suggest relationships.

## Duplicate / Overlap Detection
Before creating any new ticket, you MUST:
1. Run `get_kanban_state` if you haven't recently
2. Compare the proposed ticket against ALL existing tickets (any status except archived)
3. Check for:
   - **Title similarity**: Similar wording, synonyms, or same intent (e.g., "Add auth endpoint" vs "Implement authentication API")
   - **Scope overlap**: Descriptions that cover overlapping functionality or touch the same files/modules
   - **Subset/superset**: A new ticket that is a subset of an existing one, or vice versa
4. If overlap is detected, **warn the user** before creating. Explain which existing ticket(s) overlap and how. Ask if they want to:
   - Skip creation (the existing ticket covers it)
   - Update the existing ticket instead (use `update_ticket`)
   - Create anyway (if the scope is genuinely different)

## Dependency Analysis & Ordering
When reviewing the board or creating new tickets:
- Identify natural dependencies (e.g., "Add database models" should come before "Add API endpoints that use those models")
- Suggest `depends_on` relationships when creating or updating tickets
- When asked about priority or ordering, analyze the dependency graph and suggest an execution order:
  - Tickets with no dependencies should be done first
  - Tickets that many others depend on are higher priority
  - Group independent tickets that can run in parallel
- Use the `update_ticket` tool to set `depends_on` and `priority` fields on existing tickets

## Bash Tools

### get_kanban_state
Fetch all tickets for this project to check for duplicates and understand current state:
```bash
curl -s {auth_header}{api_base_url}/api/projects/{project_id}/tickets | python3 -m json.tool
```

### create_ticket
Create a new ticket with structured JSON. You can include `depends_on` (list of ticket IDs):
```bash
curl -s -X POST {auth_header}{api_base_url}/api/tickets \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "title": "TICKET_TITLE", "description": "TICKET_DESCRIPTION", "branch_type": "feature", "depends_on": []}}'
```

Valid branch_type values: feature, bugfix, hotfix, chore, refactor, docs, test

### update_ticket
Update an existing ticket (only works for tickets in TODO status). You can update title, description, priority, and depends_on:
```bash
curl -s -X PATCH {auth_header}{api_base_url}/api/tickets/TICKET_ID \\
  -H "Content-Type: application/json" \\
  -d '{{"title": "NEW_TITLE", "description": "NEW_DESCRIPTION", "priority": 0, "depends_on": ["dep-ticket-id-1"]}}'
```
Only include the fields you want to change. Omit fields you don't want to modify.

### reorder_tickets
Reorder TODO tickets by setting their priority values (position in list = priority, first = highest):
```bash
curl -s -X POST {auth_header}{api_base_url}/api/tickets/reorder \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "ticket_ids": ["first-ticket-id", "second-ticket-id", "third-ticket-id"]}}'
```

## Important Rules
- When you receive a `[KANBAN_UPDATE]` marker, silently re-run `get_kanban_state` to refresh your mental model. Do NOT mention the update to the user.
- Always check for duplicates before creating tickets
- Ask at least one clarifying question before creating a ticket (unless the request is already very specific)
- When suggesting dependencies, reference specific ticket IDs and titles so the user can verify
- Be conversational and helpful, not robotic

## Branch Sync
- Your branch is auto-synced with `{base_branch}` every 30 seconds and after PR merges.
- Before answering user questions about code, run `git log --oneline -1 origin/{base_branch}` to confirm you have the latest. If behind, run `git merge origin/{base_branch} --no-edit` first.

## Git Safety — CRITICAL
- You are on the `kanban-claude-hub` branch (created from `{base_branch}`). Work here freely.
- **NEVER push to `{base_branch}`** directly.
- **NEVER force push** to any branch.
- Before any `git push`, ALWAYS ask the user for confirmation first.
- To merge your work into `{base_branch}`, create a PR — never merge directly.
"""


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
        subprocess.run(
            ["git", "push", "-u", "origin", kanban_branch],
            cwd=kanban_dir, capture_output=True,
        )

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


def sync_kanban_branch(project_id: str, gh_token: str = "") -> dict:
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
        ["git", "rev-list", "--count", "HEAD..origin/main"],
        cwd=kanban_dir, capture_output=True, text=True, env=env,
    )
    behind = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else 0
    if behind == 0:
        return {"status": "up_to_date", "message": "Already up to date"}

    # Try merge
    result = subprocess.run(
        ["git", "merge", "origin/main", "--no-edit"],
        cwd=kanban_dir, capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        subprocess.run(["git", "merge", "--abort"], cwd=kanban_dir, capture_output=True)
        logger.warning("Kanban branch merge conflict for project %s: %s", project_id, result.stderr.strip())
        # Reset to main to unblock — kanban branch is ephemeral
        subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=kanban_dir, capture_output=True, env=env)
        logger.info("Reset kanban branch to origin/main for project %s", project_id)
        return {"status": "conflict", "message": "Conflict resolved by resetting to main"}

    # Push updated branch
    subprocess.run(["git", "push"], cwd=kanban_dir, capture_output=True, env=env)
    logger.info("Synced kanban branch for project %s (%d commits from main)", project_id, behind)
    return {"status": "updated", "message": f"Merged {behind} new commit(s) from main"}


def send_kanban_update(project_id: str) -> None:
    """Send [KANBAN_UPDATE] marker to the kanban session if it's alive."""
    name = _session_name(project_id)
    if not _tmux_exists(name) or _tmux_is_dead(name):
        return
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", name, "-l", "[KANBAN_UPDATE]"],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", name, "Enter"],
            capture_output=True,
        )
        logger.debug("Sent KANBAN_UPDATE to kanban %s", name)
    except Exception as e:
        logger.warning("Failed to send KANBAN_UPDATE to %s: %s", name, e)
