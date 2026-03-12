"""Manages persistent project advisor Claude Code sessions.

Each project gets a single long-running tmux session (claude-hub-advisor-{project_id})
that acts as a project advisor helping users refine requirements into tickets.
These sessions do NOT count toward max_sessions.
"""

import logging
import os
import shlex
import subprocess

from claude_hub.config import settings

logger = logging.getLogger(__name__)


def _session_name(project_id: str) -> str:
    return f"claude-hub-advisor-{project_id}"


def _tmux_exists(name: str) -> bool:
    result = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
    return result.returncode == 0


def _tmux_is_dead(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "display-message", "-t", name, "-p", "#{pane_dead}"],
        capture_output=True, text=True,
    )
    return result.returncode != 0 or result.stdout.strip() == "1"


def _clean_env() -> dict[str, str]:
    return {
        k: v for k, v in os.environ.items()
        if not k.startswith("CLAUDE") and k != "CLAUDECODE"
        and not k.startswith("ANTHROPIC")
    }


def _build_advisor_claude_md(project: dict, api_base_url: str) -> str:
    """Generate CLAUDE.md content for the advisor session."""
    project_name = project.get("name", "Unknown")
    project_id = project["id"]
    repo_url = project.get("repo_url", "")
    base_branch = project.get("base_branch", "main")

    return f"""# Project Advisor — {project_name}

You are a **project advisor** for the "{project_name}" project.
Your role is to help users refine vague requirements into structured, actionable tickets.

## Project Context
- **Repository**: {repo_url}
- **Base branch**: {base_branch}
- **Project ID**: {project_id}

## Your Responsibilities
1. When a user describes a need, ask clarifying questions to understand scope and requirements
2. Check for duplicate or related existing tickets using `get_kanban_state`
3. Once requirements are clear, create well-structured tickets using `create_ticket`
4. Help users break down large features into smaller, manageable tickets
5. Suggest appropriate branch types (feature, bugfix, hotfix, chore, refactor, docs, test)
6. **Suggest `depends_on` relationships** between tickets based on your understanding of the codebase and ticket scopes
7. **Suggest ticket ordering and priority** based on dependency analysis (tickets that others depend on should be done first)
8. **Edit existing TODO tickets** when the user wants to refine a ticket's description, title, or dependencies instead of creating a new one

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
curl -s {api_base_url}/api/projects/{project_id}/tickets | python3 -m json.tool
```

### create_ticket
Create a new ticket with structured JSON. You can include `depends_on` (list of ticket IDs):
```bash
curl -s -X POST {api_base_url}/api/tickets \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "title": "TICKET_TITLE", "description": "TICKET_DESCRIPTION", "branch_type": "feature", "depends_on": []}}'
```

Valid branch_type values: feature, bugfix, hotfix, chore, refactor, docs, test

### update_ticket
Update an existing ticket (only works for tickets in TODO status). You can update title, description, priority, and depends_on:
```bash
curl -s -X PATCH {api_base_url}/api/tickets/TICKET_ID \\
  -H "Content-Type: application/json" \\
  -d '{{"title": "NEW_TITLE", "description": "NEW_DESCRIPTION", "priority": 0, "depends_on": ["dep-ticket-id-1"]}}'
```
Only include the fields you want to change. Omit fields you don't want to modify.

### reorder_tickets
Reorder TODO tickets by setting their priority values (position in list = priority, first = highest):
```bash
curl -s -X POST {api_base_url}/api/tickets/reorder \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "ticket_ids": ["first-ticket-id", "second-ticket-id", "third-ticket-id"]}}'
```

## Important Rules
- When you receive a `[KANBAN_UPDATE]` marker, silently re-run `get_kanban_state` to refresh your mental model. Do NOT mention the update to the user.
- Always check for duplicates before creating tickets
- Ask at least one clarifying question before creating a ticket (unless the request is already very specific)
- When suggesting dependencies, reference specific ticket IDs and titles so the user can verify
- Be conversational and helpful, not robotic
"""


def start_advisor(project: dict, gh_token: str = "") -> str:
    """Start or restart the advisor session for a project.

    Returns the tmux session name.
    """
    project_id = project["id"]
    name = _session_name(project_id)

    # Kill existing session if any
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)

    # Prepare clone directory for the advisor
    from claude_hub.services.clone_manager import ensure_reference, _inject_token, _reference_dir, _repo_hash

    repo_url = project.get("repo_url", "")
    base_branch = project.get("base_branch", "main")
    advisor_dir = os.path.join(settings.data_dir, "advisors", project_id)

    authed_url = _inject_token(repo_url, gh_token)

    if os.path.exists(advisor_dir):
        # Update existing clone
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=advisor_dir, capture_output=True,
        )
    else:
        os.makedirs(os.path.dirname(advisor_dir), exist_ok=True)
        # Try reference clone first
        try:
            ensure_reference(repo_url, gh_token)
        except Exception:
            pass

        ref_path = os.path.join(_reference_dir(), f"{_repo_hash(repo_url)}.git")
        if os.path.exists(ref_path):
            subprocess.run(
                ["git", "clone", "--reference", ref_path, authed_url, advisor_dir],
                check=True, capture_output=True,
            )
        else:
            subprocess.run(
                ["git", "clone", authed_url, advisor_dir],
                check=True, capture_output=True,
            )

    # Checkout base branch
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=advisor_dir, capture_output=True,
    )

    # Write CLAUDE.md for the advisor
    api_base_url = f"http://localhost:{settings.port}"
    claude_md = _build_advisor_claude_md(project, api_base_url)
    claude_md_path = os.path.join(advisor_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(claude_md)

    # Build claude command
    task = (
        "You are a project advisor. Start by running get_kanban_state to build your mental "
        "model of all existing tickets — their titles, descriptions, statuses, and dependencies. "
        "Then greet the user and let them know you're ready to help them refine requirements "
        "and create tickets. Mention a brief summary of the current board state (e.g., how many "
        "tickets exist, any in progress, etc.)."
    )
    task_escaped = shlex.quote(task)
    parts = [
        settings.claude_bin,
        "-p", task_escaped,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]
    claude_cmd = " ".join(parts)

    # Create tmux session with clean env
    env = _clean_env()
    token = gh_token or settings.gh_token
    if token:
        env["GH_TOKEN"] = token

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-x", "200", "-y", "50"],
        check=True, env=env, cwd=advisor_dir,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "remain-on-exit", "on"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", name, "history-limit", "50000"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", name, claude_cmd, "Enter"],
        check=True,
    )

    logger.info("Started advisor session %s for project %s", name, project_id)
    return name


def is_alive(project_id: str) -> bool:
    name = _session_name(project_id)
    return _tmux_exists(name) and not _tmux_is_dead(name)


def get_status(project_id: str) -> dict:
    """Get advisor session status."""
    name = _session_name(project_id)
    alive = _tmux_exists(name) and not _tmux_is_dead(name)
    return {
        "alive": alive,
        "session_name": name,
        "ssh_command": f"tmux attach -t {name}",
    }


def restart_advisor(project: dict, gh_token: str = "") -> str:
    """Kill and recreate the advisor session."""
    project_id = project["id"]
    name = _session_name(project_id)
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        logger.info("Killed existing advisor session %s", name)
    return start_advisor(project, gh_token)


def send_kanban_update(project_id: str) -> None:
    """Send [KANBAN_UPDATE] marker to the advisor session if it's alive."""
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
        logger.debug("Sent KANBAN_UPDATE to advisor %s", name)
    except Exception as e:
        logger.warning("Failed to send KANBAN_UPDATE to %s: %s", name, e)
