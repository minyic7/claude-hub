import json
import logging
import re
from datetime import datetime, timezone

from claude_hub.models.events import ActivityEvent

logger = logging.getLogger(__name__)


def parse_line(line: str) -> list[ActivityEvent]:
    """Parse one NDJSON line from Claude Code stream-json output.

    Returns a list because one assistant message can contain multiple content blocks.
    """
    line = line.strip()
    if not line:
        return []

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return []

    event_type = data.get("type", "")
    now = datetime.now(timezone.utc).isoformat()
    events: list[ActivityEvent] = []

    if event_type == "system":
        subtype = data.get("subtype", "")
        if subtype == "init":
            model = data.get("model", "unknown")
            tools = data.get("tools", [])
            events.append(ActivityEvent(
                timestamp=now,
                source="claude_code",
                type="info",
                summary=f"Session started — model: {model}, tools: {len(tools)}",
            ))

    elif event_type == "assistant":
        message = data.get("message", {})
        content_blocks = message.get("content", [])
        for block in content_blocks:
            block_type = block.get("type", "")

            if block_type == "thinking":
                text = block.get("thinking", "")
                summary = text[:120].replace("\n", " ") + ("..." if len(text) > 120 else "")
                events.append(ActivityEvent(
                    timestamp=now,
                    source="claude_code",
                    type="thinking",
                    summary=f"Thinking: {summary}",
                ))

            elif block_type == "text":
                text = block.get("text", "")
                summary = text[:120].replace("\n", " ") + ("..." if len(text) > 120 else "")
                events.append(ActivityEvent(
                    timestamp=now,
                    source="claude_code",
                    type="info",
                    summary=summary,
                ))

            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                input_summary = _tool_input_summary(tool_name, tool_input)
                events.append(ActivityEvent(
                    timestamp=now,
                    source="claude_code",
                    type="tool_use",
                    summary=f"{tool_name}: {input_summary}",
                ))

    elif event_type == "user":
        message = data.get("message", {})
        content_blocks = message.get("content", [])
        for block in content_blocks:
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                is_error = block.get("is_error", False)
                if isinstance(content, str):
                    summary = content[:100].replace("\n", " ")
                else:
                    summary = str(content)[:100]
                events.append(ActivityEvent(
                    timestamp=now,
                    source="claude_code",
                    type="error" if is_error else "tool_result",
                    summary=f"{'Error: ' if is_error else ''}{summary}" if summary else "OK",
                ))

    elif event_type == "result":
        subtype = data.get("subtype", "")
        duration = data.get("duration_ms", 0)
        turns = data.get("num_turns", 0)
        usage = data.get("usage", {})
        output_tokens = usage.get("output_tokens", 0)
        if subtype == "success":
            events.append(ActivityEvent(
                timestamp=now,
                source="claude_code",
                type="info",
                summary=f"Completed — {duration/1000:.1f}s, {turns} turns, {output_tokens} output tokens",
            ))
        else:
            error = data.get("error", "unknown error")
            events.append(ActivityEvent(
                timestamp=now,
                source="claude_code",
                type="error",
                summary=f"Failed: {error}",
            ))

    return events


def _tool_input_summary(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Read", "Glob"):
        return tool_input.get("file_path", "") or tool_input.get("pattern", "")
    elif tool_name == "Write":
        path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        lines = content.count("\n") + 1 if content else 0
        return f"{path} ({lines} lines)"
    elif tool_name == "Edit":
        return tool_input.get("file_path", "")
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:80] + ("..." if len(cmd) > 80 else "")
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"/{pattern}/ in {path}" if path else f"/{pattern}/"
    else:
        return str(tool_input)[:80]


_PR_URL_PATTERN = re.compile(r'https://github\.com/[^/]+/[^/]+/pull/(\d+)')


def extract_pr_url(line: str) -> tuple[str, int] | None:
    """Extract PR URL and number from a stream-json line, if present."""
    try:
        data = json.loads(line.strip())
    except (json.JSONDecodeError, AttributeError):
        return None

    if data.get("type") != "assistant":
        return None

    message = data.get("message", {})
    for block in message.get("content", []):
        text = block.get("text", "")
        if text:
            match = _PR_URL_PATTERN.search(text)
            if match:
                return match.group(0), int(match.group(1))
