"""QA Agent — Claude Code one-shot (-p) fallback for TicketAgent and PilotAgent.

Instead of making API calls (which cost money), this runs `claude -p "prompt"`
as a subprocess (using the user's Max plan subscription) to answer review and
supervision questions.

The QA Agent is invisible to the user — no terminal tab, no persistent session.
It produces the same SupervisorEvent / review JSON as API-based agents.
"""

import asyncio
import json
import logging
import os

from claude_hub.config import settings

logger = logging.getLogger(__name__)

# Disallow file-modifying tools
DISALLOWED_TOOLS = "Edit,Write,NotebookEdit"

# Timeout for a single -p invocation (seconds)
DEFAULT_TIMEOUT = 300


async def ask_qa(
    prompt: str,
    cwd: str,
    gh_token: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """Run a one-shot `claude -p` subprocess and return the response text.

    Returns the assistant response string, or None on error/timeout.
    """
    cmd = [
        settings.claude_bin,
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--disallowedTools", DISALLOWED_TOOLS,
    ]

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    if gh_token:
        env["GH_TOKEN"] = gh_token

    logger.info("QA Agent running: prompt=%s chars, cwd=%s", len(prompt), cwd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("QA Agent timed out after %ds", timeout)
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return None
    except Exception as e:
        logger.error("QA Agent subprocess error: %s", e)
        return None

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")[:500]
        logger.warning("QA Agent exited %d: %s", proc.returncode, stderr_text)

    # Parse stream-json output — each line is a JSON object.
    # We want the "result" message which contains the final assistant text.
    stdout_text = stdout_bytes.decode(errors="replace")
    response_text = _parse_stream_json(stdout_text)

    if response_text:
        logger.info("QA Agent response: %d chars", len(response_text))
    else:
        logger.warning("QA Agent produced no parseable response")

    return response_text


def _parse_stream_json(raw: str) -> str | None:
    """Extract the assistant response from stream-json output.

    stream-json format: one JSON object per line.
    The final result is in a message with type "result" containing
    {"result": "text..."} or the assistant text in result.
    """
    result_text = None
    assistant_parts: list[str] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type", "")

        # "result" message contains the final text
        if msg_type == "result":
            result_val = obj.get("result", "")
            if isinstance(result_val, str) and result_val:
                return result_val

        # Collect assistant text blocks as fallback
        if msg_type == "assistant" and "message" in obj:
            message = obj["message"]
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_parts.append(block.get("text", ""))

        # Content block delta
        if msg_type == "content_block_delta":
            delta = obj.get("delta", {})
            if delta.get("type") == "text_delta":
                assistant_parts.append(delta.get("text", ""))

    # Fallback: join all assistant text parts
    if assistant_parts:
        return "".join(assistant_parts)

    return result_text
