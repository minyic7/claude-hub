"""QA Agent — Claude Code session that acts as a cost-free fallback for TicketAgent and PilotAgent.

Instead of making API calls (which cost money), this spawns a Claude Code CLI session
(using the user's Max plan subscription) that answers review and supervision questions.

The QA Agent runs in the same kanban directory as the Kanban CC session, but with
file-editing tools disabled (Edit, Write, NotebookEdit). It can read code, run git
commands, and reason — but cannot modify files.

Communication protocol:
  1. Backend sends a structured prompt via tmux send-keys
  2. QA Agent CC processes it and outputs a response
  3. Backend tails the stream-json log for the response text
"""

import asyncio
import json
import logging
import os
import shlex
import subprocess
import time

from claude_hub.config import settings

logger = logging.getLogger(__name__)

# Track active QA sessions: project_id -> session info
_qa_sessions: dict[str, dict] = {}

# Disallow file-modifying tools
DISALLOWED_TOOLS = "Edit,Write,NotebookEdit"


def _session_name(project_id: str) -> str:
    return f"claude-hub-qa-{project_id}"


def _tmux_exists(name: str) -> bool:
    result = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
    return result.returncode == 0


def _tmux_is_dead(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "display-message", "-t", name, "-p", "#{pane_dead}"],
        capture_output=True, text=True,
    )
    return result.returncode != 0 or result.stdout.strip() == "1"


def _build_qa_claude_md(project: dict) -> str:
    """Generate CLAUDE.md content for the QA Agent session."""
    project_name = project.get("name", "Unknown")
    project_id = project["id"]
    repo_url = project.get("repo_url", "")

    return f"""# QA Agent — {project_name}

You are the **QA Agent** for the "{project_name}" project.
You are a read-only reviewer and supervisor. You CANNOT and MUST NOT modify any files.

## Your Role
- **Review code changes** — when asked to review a diff, analyze it and provide structured feedback
- **Supervise the kanban** — when asked about board state, provide guidance on what to do next
- **Answer questions** — provide informed answers based on the codebase and VISION.md

## Important Rules
- You are READ-ONLY. You cannot edit, write, or create files.
- You CAN use Bash for read-only operations: `git diff`, `git log`, `cat`, `ls`, etc.
- You CAN use Read, Grep, Glob to explore the codebase.
- When asked to review, always respond with the exact JSON format requested.
- Be concise — your output is parsed by the backend.
- Do NOT add commentary outside the requested format unless asked.

## Project Context
- **Repository**: {repo_url}
- **Project ID**: {project_id}
- **Working directory**: kanban-claude-hub branch (shared with Kanban CC)
"""


def start_qa_session(project: dict, gh_token: str = "") -> str:
    """Start the QA Agent CC session for a project.

    Returns the tmux session name.
    """
    project_id = project["id"]
    name = _session_name(project_id)

    # Kill existing session if any
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)

    # Use the kanban directory (shared with Kanban CC)
    kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)
    if not os.path.exists(kanban_dir):
        raise RuntimeError(f"Kanban directory not found: {kanban_dir}. Start the kanban session first.")

    # Write QA-specific CLAUDE.md to a subdirectory so it doesn't conflict with kanban CLAUDE.md
    qa_dir = os.path.join(kanban_dir, ".qa-agent")
    os.makedirs(qa_dir, exist_ok=True)
    claude_md_path = os.path.join(qa_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(_build_qa_claude_md(project))

    # Build claude command — interactive mode with disallowed tools
    parts = [
        settings.claude_bin,
        "--verbose",
        "--disallowedTools", shlex.quote(DISALLOWED_TOOLS),
    ]
    inner_cmd = " ".join(parts)
    # Auto-restart loop like kanban
    claude_cmd = f'while true; do {inner_cmd}; echo -e "\\n\\033[33mQA Agent exited. Restarting in 2s...\\033[0m"; sleep 2; done'

    # Create tmux session — strip ANTHROPIC_API_KEY so Claude Code uses subscription
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

    _qa_sessions[project_id] = {
        "session_name": name,
        "kanban_dir": kanban_dir,
        "started_at": time.time(),
    }

    logger.info("Started QA Agent session %s for project %s", name, project_id)
    return name


def is_alive(project_id: str) -> bool:
    name = _session_name(project_id)
    return _tmux_exists(name) and not _tmux_is_dead(name)


def get_status(project_id: str) -> dict:
    name = _session_name(project_id)
    alive = _tmux_exists(name) and not _tmux_is_dead(name)
    return {
        "alive": alive,
        "session_name": name,
    }


def stop_qa_session(project_id: str) -> None:
    name = _session_name(project_id)
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        logger.info("Stopped QA Agent session %s", name)
    _qa_sessions.pop(project_id, None)


def restart_qa_session(project: dict, gh_token: str = "") -> str:
    """Kill and recreate the QA Agent session."""
    stop_qa_session(project["id"])
    return start_qa_session(project, gh_token)


def send_message(project_id: str, message: str) -> None:
    """Send a message to the QA Agent session via tmux send-keys."""
    name = _session_name(project_id)
    if not _tmux_exists(name):
        raise RuntimeError(f"QA Agent session {name} does not exist")
    subprocess.run(
        ["tmux", "send-keys", "-t", name, "-l", message],
        check=True, timeout=5,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", name, "Enter"],
        check=True, timeout=5,
    )
    logger.info("Sent message to QA Agent %s: %s", project_id, message[:80])


def read_pane(project_id: str, lines: int = 200) -> str:
    """Capture recent tmux pane content from QA Agent session."""
    name = _session_name(project_id)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning("Failed to read QA Agent pane for %s: %s", project_id, e)
    return ""


async def ask_qa_agent(project_id: str, prompt: str, timeout: int = 120) -> str | None:
    """Send a prompt to QA Agent and wait for a response.

    Monitors the tmux pane for the QA Agent's response by watching for the
    appearance of a new '>' prompt after our message.

    Returns the response text, or None if timeout.
    """
    name = _session_name(project_id)
    if not _tmux_exists(name) or _tmux_is_dead(name):
        logger.warning("QA Agent not available for %s", project_id)
        return None

    # Capture pane state before sending
    pane_before = read_pane(project_id)
    before_lines = len(pane_before.splitlines())

    # Send the prompt
    send_message(project_id, prompt)

    # Poll for response — wait until we see new content followed by a '>' prompt
    start = time.time()
    last_content = ""
    stable_count = 0

    while time.time() - start < timeout:
        await asyncio.sleep(2)

        pane_now = read_pane(project_id)
        lines = pane_now.splitlines()

        # Look for content after our prompt
        new_content = "\n".join(lines[before_lines:]) if len(lines) > before_lines else ""

        if not new_content:
            continue

        # Check if output has stabilized (CC finished responding)
        # Look for the idle prompt '>' at the end
        stripped = pane_now.rstrip()
        if stripped.endswith(">") or stripped.endswith("❯"):
            # CC is back at prompt — response is complete
            # Extract just the response (between our prompt and the final prompt)
            response_lines = []
            found_prompt = False
            for line in lines[before_lines:]:
                stripped_line = line.strip()
                if stripped_line == ">" or stripped_line == "❯":
                    break
                response_lines.append(line)
            return "\n".join(response_lines).strip()

        # Also detect stability (same content for 3 checks = 6 seconds)
        if new_content == last_content:
            stable_count += 1
            if stable_count >= 3:
                return new_content.strip()
        else:
            stable_count = 0
            last_content = new_content

    logger.warning("QA Agent response timeout for %s after %ds", project_id, timeout)
    # Return whatever we have
    pane_final = read_pane(project_id)
    final_lines = pane_final.splitlines()
    return "\n".join(final_lines[before_lines:]).strip() or None
