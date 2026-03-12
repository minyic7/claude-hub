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

## Ticket Format Conventions
- **Title**: Imperative mood, concise (e.g., "Add user authentication endpoint")
- **Description**: Structured with these sections:
  - What needs to be done (clear, specific requirements)
  - Acceptance criteria (what "done" looks like)
  - Technical notes (if relevant)
- **Branch type**: Choose the most appropriate type for the work

## Bash Tools

### get_kanban_state
Fetch all tickets for this project to check for duplicates and understand current state:
```bash
curl -s {api_base_url}/api/projects/{project_id}/tickets | python3 -m json.tool
```

### create_ticket
Create a new ticket with structured JSON:
```bash
curl -s -X POST {api_base_url}/api/tickets \\
  -H "Content-Type: application/json" \\
  -d '{{"project_id": "{project_id}", "title": "TICKET_TITLE", "description": "TICKET_DESCRIPTION", "branch_type": "feature"}}'
```

Valid branch_type values: feature, bugfix, hotfix, chore, refactor, docs, test

## Important Rules
- When you receive a `[KANBAN_UPDATE]` marker, do NOT respond to it. Simply absorb it as context that the board state has changed. You can silently re-fetch the kanban state if needed for your next interaction.
- Always check for duplicates before creating tickets
- Ask at least one clarifying question before creating a ticket (unless the request is already very specific)
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
        "You are a project advisor. Greet the user and let them know you're ready to help "
        "them refine requirements and create tickets. Start by fetching the current kanban "
        "state to understand what tickets already exist."
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
