import asyncio
import json
import logging
import os
import shlex
import subprocess
import time

from claude_hub.config import settings
from claude_hub.services.stream_parser import parse_line
from claude_hub.models.events import ActivityEvent

logger = logging.getLogger(__name__)

# Track active sessions: ticket_id -> session info
_active_sessions: dict[str, dict] = {}


def _session_name(ticket_id: str) -> str:
    return f"ch-{ticket_id[:8]}"


def _clean_env() -> dict[str, str]:
    """Return env dict with CLAUDE* vars removed to avoid nested session detection."""
    return {
        k: v for k, v in os.environ.items()
        if not k.startswith("CLAUDE") and k != "CLAUDECODE"
    }


def active_session_count() -> int:
    """Count currently alive tmux sessions."""
    return sum(1 for tid in list(_active_sessions) if is_alive(tid))


def has_active_session(ticket_id: str) -> bool:
    """Check if a ticket already has a running session."""
    return ticket_id in _active_sessions and is_alive(ticket_id)


def _tmux_exists(name: str) -> bool:
    result = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
    return result.returncode == 0


def _tmux_is_dead(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "display-message", "-t", name, "-p", "#{pane_dead}"],
        capture_output=True, text=True,
    )
    return result.returncode != 0 or result.stdout.strip() == "1"


def start_session(
    ticket_id: str,
    clone_path: str,
    task: str,
    role_prompt: str = "",
    disallowed_tools: str = "",
    gh_token: str = "",
    model: str = "",
) -> tuple[str, str]:
    """Start a Claude Code session in tmux.

    Returns (session_name, log_path).
    """
    name = _session_name(ticket_id)
    log_path = os.path.join(clone_path, ".claude-hub.jsonl")

    # Kill existing session if any
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)

    # Build claude command
    full_task = task
    if role_prompt:
        full_task = f"{role_prompt}\n\n## Task\n{task}"

    task_escaped = shlex.quote(full_task)
    parts = [
        settings.claude_bin,
        "-p", task_escaped,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]

    if model:
        parts.extend(["--model", model])

    disallowed = disallowed_tools or settings.disallowed_tools
    if disallowed:
        parts.extend(["--disallowedTools", shlex.quote(disallowed)])

    claude_cmd = " ".join(parts) + f" 2>&1 | tee {shlex.quote(log_path)}"

    # Create tmux session with clean env
    env = _clean_env()
    # Pass through required env vars
    api_key = os.environ.get("ANTHROPIC_API_KEY", "") or settings.anthropic_api_key
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    token = gh_token or settings.gh_token
    if token:
        env["GH_TOKEN"] = token

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-x", "200", "-y", "50"],
        check=True, env=env, cwd=clone_path,
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

    _active_sessions[ticket_id] = {
        "session_name": name,
        "log_path": log_path,
        "clone_path": clone_path,
        "started_at": time.time(),
    }

    logger.info("Started session %s for ticket %s", name, ticket_id)
    return name, log_path


def send_input(ticket_id: str, text: str) -> None:
    name = _session_name(ticket_id)
    if not _tmux_exists(name):
        raise RuntimeError(f"Session {name} does not exist")
    subprocess.run(["tmux", "send-keys", "-t", name, "-l", text], check=True)
    subprocess.run(["tmux", "send-keys", "-t", name, "Enter"], check=True)
    logger.info("Sent input to %s: %s", name, text[:80])


def stop_session(ticket_id: str) -> None:
    name = _session_name(ticket_id)
    if _tmux_exists(name):
        # Send Ctrl+C first to gracefully stop
        subprocess.run(["tmux", "send-keys", "-t", name, "C-c", ""], capture_output=True)
        time.sleep(1)
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        logger.info("Stopped session %s", name)
    _active_sessions.pop(ticket_id, None)


def cleanup_session(ticket_id: str) -> None:
    """Kill tmux session after it has finished (no Ctrl+C needed)."""
    name = _session_name(ticket_id)
    if _tmux_exists(name):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        logger.info("Cleaned up session %s", name)
    _active_sessions.pop(ticket_id, None)


def is_alive(ticket_id: str) -> bool:
    name = _session_name(ticket_id)
    return _tmux_exists(name) and not _tmux_is_dead(name)


def get_session_info(ticket_id: str) -> dict | None:
    return _active_sessions.get(ticket_id)


async def tail_log(ticket_id: str, log_path: str):
    """Async generator that yields parsed ActivityEvents from the JSONL log."""
    # Wait for log file to appear
    for _ in range(120):  # 60 seconds
        if os.path.exists(log_path):
            break
        await asyncio.sleep(0.5)
    else:
        logger.warning("Log file never appeared: %s", log_path)
        return

    name = _session_name(ticket_id)

    with open(log_path, "r") as f:
        while True:
            line = f.readline()
            if line:
                events = parse_line(line)
                for event in events:
                    yield event

                # Check if session ended
                try:
                    data = json.loads(line.strip())
                    if data.get("type") == "result":
                        return
                except (json.JSONDecodeError, AttributeError):
                    pass
            else:
                # No new data — check if session is dead
                if _tmux_is_dead(name):
                    await asyncio.sleep(1)  # Give a moment for final writes
                    # Read any remaining lines
                    remaining = f.read()
                    if remaining:
                        for rem_line in remaining.strip().split("\n"):
                            events = parse_line(rem_line)
                            for event in events:
                                yield event
                    return

                await asyncio.sleep(0.3)
