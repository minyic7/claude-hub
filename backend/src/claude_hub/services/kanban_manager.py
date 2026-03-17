"""Manages persistent project kanban Claude Code sessions.

Each project gets a single long-running tmux session (claude-hub-kanban-{project_id})
that acts as a project kanban helper assisting users with coding, requirements, and tickets.
These sessions do NOT count toward max_sessions.
"""

import logging
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

    if vision_mode == "readonly":
        vision_instructions = (
            '**VISION.md is READ-ONLY.** You may NOT modify it. '
            'If you believe the vision needs updating, tell the user — they will edit it.'
        )
    else:
        vision_instructions = (
            '**VISION.md is WRITABLE.** You may append to Goal and Scope sections when the current scope has been '
            'fully implemented and you have a clear next direction. Extensions must be additive — never remove or '
            'contradict existing content. Always `git commit + push` VISION.md changes before creating new tickets '
            'so they are grounded in the updated vision.'
        )

    md = f"""# Kanban Claude Code — {project_name}

You are the **Kanban Claude Code** for the "{project_name}" project.
You work directly on this repository and help users with coding, refining requirements, and managing tickets.

## On Startup
When you first start, do the following:
1. Run `/board` to load the current board state
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
2. **Manage tickets** — create, update, and organize kanban tickets via skills (see below)
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

## Dependency Analysis & Parallel Execution
When reviewing the board or creating new tickets:
- Identify natural dependencies
- Suggest `depends_on` relationships when creating or updating tickets
- When asked about priority or ordering, analyze the dependency graph and suggest an execution order
- **Design for parallelism**: break work into independent tickets that can run concurrently
  - Prefer many small, independent tickets over a few large sequential ones
  - Only add `depends_on` when there is a real code-level dependency (shared files, API contracts)
  - If two tickets touch different parts of the codebase, they can run in parallel
  - Use `/start-bulk` to kick off multiple independent tickets at once

## Kanban Skills (Slash Commands)

You have kanban skills installed as slash commands. Use these instead of raw curl:

| Command | Purpose |
|---------|---------|
| `/board` | Fetch board state — **run before every response** |
| `/project-info` | Read project settings (pilot mode, limits) |
| `/start-ticket TICKET_ID` | Start a TODO ticket (spawn Claude Code session) |
| `/start-bulk` | Start multiple tickets at once (auto-queues overflow) |
| `/create-ticket` | Create a new ticket |
| `/update-ticket TICKET_ID` | Edit a TODO ticket's title/description/priority/deps |
| `/archive-ticket TICKET_ID` | Archive a ticket (toggle — verify archived=false first) |
| `/reorder-tickets` | Set priority order for TODO tickets |
| `/queue` | Check execution queue and session capacity |
| `/answer-ticket TICKET_ID` | Unblock a BLOCKED ticket |
| `/message-ticket TICKET_ID` | Send message to an active session |
| `/retry-ticket TICKET_ID` | Retry a FAILED ticket (with optional guidance) |
| `/request-changes TICKET_ID` | Send AWAITING_MERGE back for revision |
| `/resolve-conflicts TICKET_ID` | Auto-resolve merge conflicts |
| `/ticket-diff TICKET_ID` | Read PR diff |
| `/ci-status TICKET_ID` | Check CI pass/fail (before merge) |
| `/cd-status` | Check deploy workflow status (after merge) |
| `/unresolved-threads TICKET_ID` | Check open PR review threads |
| `/add-note TICKET_ID` | Append a note to any ticket |
| `/merge-ticket TICKET_ID` | Merge a ticket's PR |
| `/revert-ticket TICKET_ID` | Revert FAILED/AWAITING_MERGE → TODO |
| `/duplicate-ticket TICKET_ID` | Clone a ticket as new TODO |

Each skill contains the full curl command with auth and project context pre-configured.
Always refer to tickets by `#seq` number in conversation, but use the full UUID `id` in API calls.

## What You Cannot Do

These operations are outside your scope. Do not attempt them:

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
- On startup: **always** read VISION.md before doing anything else.
- Re-read VISION.md whenever: you finish a batch of tickets, the user/Pilot asks you to check vision, or before planning new work.
- Before every response: silently run `git pull origin kanban-claude-hub --quiet`,
  then check if VISION.md has changed since you last read it. If it has, re-read it
  before composing your response.
- Never touch Milestones — only the user manages milestones.
- {vision_instructions}

## CI Pipeline — Keep It Minimal
Do NOT add linters (ruff, eslint, pylint, etc.) to CI pipelines unless the user explicitly asks for it.
Linting blocks PRs over trivial style issues (line length, import order) and wastes time.
Focus CI on things that actually catch bugs: **type-check, build, and tests**.

## Post-Merge — Verify Deployment
After a ticket is merged, verify the deploy succeeded:
- Run `/cd-status` to check the latest deploy workflow on main.
- If deploy fails, create a **hotfix ticket** immediately with the error details.
- Do NOT move on to the next batch of tickets until the deploy is green.

## Smoke Test — Definition of Done

A ticket is NOT done until it passes a smoke test. Before marking any ticket as `awaiting_merge`:

1. **Build the project** — run whatever the project uses: `docker build`, `pnpm build`, `uv sync`, etc.
   Read the project's README/Dockerfile to determine the correct build command.
2. **Verify imports/startup** — e.g. `docker run --rm <image> python -c "from app.main import app"`,
   or `uv run python -c "import ..."` — make sure the application can actually start.
3. **Run existing tests** — `pytest`, `pnpm test`, `cargo test`, etc. if the project has tests.
4. **Curl endpoints** (if applicable) — spin up a temporary container on a random port,
   hit key endpoints, verify they return expected responses, then stop the container.

**Docker is available** — you have access to the host Docker daemon via `/var/run/docker.sock`.
You can `docker build`, `docker run`, `docker compose up` freely for testing. Always clean up
containers after testing (use `--rm` or `docker stop + docker rm`).

**Failure handling:**
- If the smoke test fails due to a **code bug** (missing dependency, import error, broken endpoint):
  fix it, re-run the test, then proceed to `awaiting_merge`.
- If the smoke test fails due to an **environment limitation** (needs external DB, API key, etc.):
  skip the smoke test, note the reason in the ticket, and proceed to `awaiting_merge`.
- **Max 2 retry attempts** — if smoke test still fails after 2 fixes, mark the ticket as `failed`
  with the error details.

## Git Safety — CRITICAL
- You are on the `kanban-claude-hub` branch (created from `{base_branch}`). Work here freely.
- **NEVER push to `{base_branch}`** directly.
- **NEVER force push** to any branch.
- Before any `git push`, ALWAYS ask the user for confirmation first.
- To merge your work into `{base_branch}`, create a PR — never merge directly.
"""

    # ── Pilot Mode section (injected only when pilot_mode is enabled) ────────
    if pilot_mode:
        md += """
## Pilot Mode — ACTIVE

You are being supervised by a **Pilot Agent** — a lightweight AI that acts as your user.
It will send you messages just like a human user would: asking questions, giving direction, and answering your questions.

**How to work in Pilot Mode:**
- Treat Pilot Agent messages as user input — respond naturally
- When asked "what should we do next?", reason about the board state and VISION.md, then propose and execute
- Use your kanban skills (`/board`, `/start-ticket`, `/create-ticket`, etc.) to manage the board
- When you're done with a task, report what you did and ask what's next — don't just go idle
- If you need a decision (e.g., which approach to take), ask — the Pilot Agent will answer based on project context
- **Stay proactive**: after completing work, check the board and suggest next steps
"""

    return md


# ── Skill installation ─────────────────────────────────────────────────────

# Directory containing skill templates (relative to this file)
_SKILLS_DIR = Path(__file__).parent.parent / "docs" / "kanban-skills"

def _install_skills(
    kanban_dir: str,
    project: dict,
    api_base_url: str,
    auth_token: str = "",
) -> None:
    """Copy skill templates to kanban_dir/.claude/skills/ with variable substitution."""
    project_id = project["id"]
    base_branch = project.get("base_branch", "main")
    pilot_mode = project.get("pilot_mode", False)
    max_board_tickets = project.get("max_board_tickets", 10)
    max_tickets_per_cycle = project.get("max_tickets_per_cycle", 2)
    vision_mode = project.get("vision_mode", "readonly")
    auth = f'-H "Authorization: Bearer {auth_token}"' if auth_token else ""

    if vision_mode == "readonly":
        vision_instructions = (
            '**VISION.md is READ-ONLY.** You may NOT modify it. '
            'If you believe the vision needs updating, tell the user — they will edit it.'
        )
    else:
        vision_instructions = (
            '**VISION.md is WRITABLE.** You may append to Goal and Scope sections when the current scope has been '
            'fully implemented and you have a clear next direction. Extensions must be additive — never remove or '
            'contradict existing content. Always `git commit + push` VISION.md changes before creating new tickets '
            'so they are grounded in the updated vision.'
        )

    # Template variables
    replacements = {
        "{api_base_url}": api_base_url,
        "{project_id}": project_id,
        "{auth}": auth,
        "{base_branch}": base_branch,
        "{pilot_mode}": "true" if pilot_mode else "false",
        "{max_board_tickets}": str(max_board_tickets),
        "{max_tickets_per_cycle}": str(max_tickets_per_cycle),
        "{vision_mode}": vision_mode,
        "{vision_instructions}": vision_instructions,
    }

    skills_dest = os.path.join(kanban_dir, ".claude", "skills")

    # Clean existing skills and reinstall fresh
    if os.path.exists(skills_dest):
        shutil.rmtree(skills_dest)

    if not _SKILLS_DIR.exists():
        logger.warning("Kanban skills directory not found: %s", _SKILLS_DIR)
        return

    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue

        skill_name = skill_dir.name

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        content = skill_md.read_text()
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)

        dest_dir = os.path.join(skills_dest, skill_name)
        os.makedirs(dest_dir, exist_ok=True)
        with open(os.path.join(dest_dir, "SKILL.md"), "w") as f:
            f.write(content)

    logger.info("Installed kanban skills to %s (%d skills)",
                skills_dest, len(list(Path(skills_dest).iterdir())) if os.path.exists(skills_dest) else 0)


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

    # Install kanban skills (.claude/skills/)
    _install_skills(kanban_dir, project, api_base_url, auth_token)

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

    # Reinstall skills (may add/remove pilot-cycle based on pilot_mode change)
    _install_skills(kanban_dir, project, api_base_url, auth_token)

    logger.info("Rebuilt CLAUDE.md + skills for project %s", project_id)
    return True


def send_pilot_trigger(project_id: str, reason: str) -> None:
    """Notify PilotAgent about an event by scheduling an immediate tick.

    Previously sent [PILOT_TRIGGER:...] text to CC. Now PilotAgent acts as a
    simulated user and will notice the event (e.g., ticket merged, config changed)
    on its next tick via board state. This function triggers that tick sooner.
    """
    if not is_alive(project_id):
        logger.debug("Pilot trigger skipped: no alive session for %s", project_id)
        return

    # Schedule an immediate PilotAgent nudge (async — fire and forget)
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        from claude_hub.services.pilot_agent import nudge
        loop.create_task(nudge(project_id))
        logger.info("Nudged PilotAgent for %s (reason: %s)", project_id, reason)
    except Exception as e:
        logger.warning("Failed to send pilot trigger to %s: %s", project_id, e)
