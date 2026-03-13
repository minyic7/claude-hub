"""Kanban endpoints for persistent project kanban sessions."""

import asyncio
import fcntl
import json
import logging
import os
import signal
import struct
import termios

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from claude_hub import redis_client
from claude_hub.auth import verify_ws_token
from claude_hub.config import settings
from claude_hub.services import kanban_manager

router = APIRouter(prefix="/api/projects", tags=["kanban"])
# Separate router for WebSocket (no auth dependency — handled inside endpoint)
ws_router = APIRouter(tags=["kanban"])
logger = logging.getLogger(__name__)


async def _get_project_and_token(project_id: str) -> tuple[dict, str]:
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    gh_token = project.get("gh_token", "")
    return project, gh_token


@router.post("/{project_id}/kanban/start")
async def start_kanban(project_id: str):
    """Create a persistent kanban tmux session for the project."""
    project, gh_token = await _get_project_and_token(project_id)

    try:
        session_name = kanban_manager.start_kanban(project, gh_token)
    except Exception as e:
        logger.error("Failed to start kanban for %s: %s", project_id, e)
        raise HTTPException(500, f"Failed to start kanban: {e}")

    return {
        "session_name": session_name,
        **kanban_manager.get_status(project_id),
    }


@router.post("/{project_id}/kanban/restart")
async def restart_kanban(project_id: str):
    """Kill and recreate the kanban session."""
    project, gh_token = await _get_project_and_token(project_id)

    try:
        session_name = kanban_manager.restart_kanban(project, gh_token)
    except Exception as e:
        logger.error("Failed to restart kanban for %s: %s", project_id, e)
        raise HTTPException(500, f"Failed to restart kanban: {e}")

    return {
        "session_name": session_name,
        **kanban_manager.get_status(project_id),
    }


@router.get("/{project_id}/kanban/status")
async def kanban_status(project_id: str):
    """Get kanban session status."""
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    return kanban_manager.get_status(project_id)


@ws_router.websocket("/ws/kanban/{project_id}/terminal")
async def kanban_terminal(websocket: WebSocket, project_id: str, token: str = Query(default="")):
    """WebSocket endpoint that bridges xterm.js to the kanban tmux session via PTY.

    Uses pty.fork() to get a proper controlling terminal for tmux attach.
    """
    # Auth check
    if settings.auth_enabled and not verify_ws_token(token):
        await websocket.close(code=4001, reason="Invalid or missing token")
        return

    # Verify project exists
    project = await redis_client.get_project(project_id)
    if not project:
        await websocket.close(code=4002, reason="Project not found")
        return

    # Auto-start kanban session if not running
    if not kanban_manager.is_alive(project_id):
        try:
            gh_token = project.get("gh_token", "")
            if not gh_token:
                from claude_hub.routers.settings_router import get_gh_token
                gh_token = await get_gh_token()
            kanban_manager.start_kanban(project, gh_token)
            # Give tmux a moment to initialize
            import asyncio
            await asyncio.sleep(1)
        except Exception as e:
            logger.error("Failed to auto-start kanban for %s: %s", project_id, e)
            await websocket.close(code=4003, reason=f"Failed to start session: {e}")
            return

    session_name = kanban_manager._session_name(project_id)
    await websocket.accept()
    logger.info("Kanban terminal connected for project %s", project_id)

    # Use subprocess with script command to allocate a proper PTY
    # 'script' creates a proper controlling terminal that tmux needs
    import pty
    master_fd, slave_fd = pty.openpty()

    # Set initial terminal size
    _set_pty_size(master_fd, 80, 24)

    # Set slave as controlling terminal in child via preexec_fn
    def _child_setup():
        """Make the slave PTY the controlling terminal for the child process."""
        os.setsid()
        # TIOCSCTTY: set controlling terminal
        import fcntl as _fcntl
        _fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    # TERM must be set for tmux to attach ("terminal does not support clear")
    env = {**os.environ, "TERM": "xterm-256color"}

    process = await asyncio.create_subprocess_exec(
        "tmux", "attach-session", "-t", session_name,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=_child_setup,
        env=env,
    )
    # Close slave in parent — only master is used for I/O
    os.close(slave_fd)

    loop = asyncio.get_event_loop()
    child_pid = process.pid

    async def _read_pty():
        """Read from PTY master and send to WebSocket."""
        try:
            while True:
                data = await loop.run_in_executor(None, _blocking_read, master_fd)
                if not data:
                    break
                await websocket.send_bytes(data)
        except (OSError, WebSocketDisconnect, asyncio.CancelledError):
            pass

    async def _write_pty():
        """Read from WebSocket and write to PTY master."""
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "bytes" in msg:
                    data = msg["bytes"]
                    # Check for resize message (binary: 0x01 + JSON)
                    if data and data[0:1] == b"\x01":
                        try:
                            resize = json.loads(data[1:])
                            cols = resize.get("cols", 80)
                            rows = resize.get("rows", 24)
                            _set_pty_size(master_fd, cols, rows)
                            # Also notify tmux of the size change
                            if child_pid:
                                try:
                                    os.kill(child_pid, signal.SIGWINCH)
                                except ProcessLookupError:
                                    pass
                        except (json.JSONDecodeError, KeyError):
                            pass
                    else:
                        os.write(master_fd, data)
                elif "text" in msg:
                    os.write(master_fd, msg["text"].encode())
        except (OSError, WebSocketDisconnect, asyncio.CancelledError):
            pass

    read_task = asyncio.create_task(_read_pty())
    write_task = asyncio.create_task(_write_pty())

    try:
        # Wait for either direction to finish
        done, pending = await asyncio.wait(
            [read_task, write_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        # Cleanup: detach tmux (don't kill the session)
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        logger.info("Kanban terminal disconnected for project %s", project_id)


def _blocking_read(fd: int) -> bytes:
    """Blocking read from fd, suitable for run_in_executor."""
    try:
        return os.read(fd, 4096)
    except OSError:
        return b""


def _set_pty_size(fd: int, cols: int, rows: int) -> None:
    """Set PTY window size."""
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass
