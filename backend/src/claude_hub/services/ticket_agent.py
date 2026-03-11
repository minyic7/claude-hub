import asyncio
import json
import logging
import os
import subprocess

import anthropic

from claude_hub import redis_client
from claude_hub.config import settings
from claude_hub.models.events import ActivityEvent
from claude_hub.routers.ws import broadcast
from claude_hub.services import cost_tracker, session_manager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are a technical supervisor monitoring a Claude Code session working on a ticket.

## Your Role
You are watching Claude Code's real-time activity stream. Your job is to:
1. Monitor progress — is Claude Code on track?
2. Intervene when needed — send corrections via tmux_send
3. Research solutions — use web_search when Claude Code is stuck
4. Escalate to human — when you genuinely need a decision or clarification

## Trust But Verify
Claude Code runs with full permissions (--dangerously-skip-permissions). You CANNOT prevent actions — stream events arrive AFTER execution. All work is on a feature branch, so mistakes are safe and fixable.

## When to intervene
- Claude Code is going off-track or misunderstood the task
- Claude Code is stuck in a loop (retrying same failed approach)
- Claude Code made a mistake that needs correction
- You have useful information from web search

## When to escalate
- Task description is genuinely ambiguous
- Critical decision needed (architecture, security)
- Claude Code is consistently failing and you can't fix it

## When to do nothing
- Claude Code is making steady progress (most of the time!)
- Minor style issues (PR review will catch these)
- Normal tool_use/tool_result patterns

## Ticket
- Title: {title}
- Description: {description}
- Branch: {branch}
- Role: {role}

## Tools available
- tmux_send: Send a message to Claude Code (correction, suggestion, instruction)
- file_read: Read a file in the working directory
- git_status: Check git status of the working directory
- escalate: Ask the human for help (blocks the ticket until answered)
- pause_session: Send Ctrl+C to pause Claude Code
- wait: Do nothing, continue monitoring

Be concise. Don't over-supervise. Let Claude Code work unless there's a real problem."""


def _build_tools(agent_settings: dict | None = None) -> list[dict]:
    tools = [
        {
            "name": "tmux_send",
            "description": "Send a text message to the Claude Code session. Use this to give corrections, suggestions, or new instructions.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to send to Claude Code",
                    }
                },
                "required": ["message"],
            },
        },
        {
            "name": "file_read",
            "description": "Read a file from the ticket's working directory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from the clone root",
                    }
                },
                "required": ["path"],
            },
        },
        {
            "name": "git_status",
            "description": "Run git status in the ticket's working directory.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "escalate",
            "description": "Escalate to the human. Blocks the ticket until the human answers. Use only when you genuinely need human input.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question for the human",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "critical"],
                        "description": "How urgent is this escalation",
                    },
                },
                "required": ["question", "severity"],
            },
        },
        {
            "name": "pause_session",
            "description": "Send Ctrl+C to pause the Claude Code session. Use sparingly — only for emergencies.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "wait",
            "description": "Do nothing and continue monitoring. Use when everything looks fine.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
    ]

    web_search = agent_settings.get("web_search", settings.agent_web_search) if agent_settings else settings.agent_web_search
    if web_search:
        tools.append({
            "name": "web_search",
            "description": "Search the web for information. Use to research solutions when Claude Code is stuck.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    }
                },
                "required": ["query"],
            },
        })

    return tools


# Critical patterns that trigger immediate API call
_DANGEROUS_COMMANDS = ["rm -rf", "drop table", "drop database", "format", "mkfs", "dd if="]
_SENSITIVE_PATHS = [".env", "credentials", "secret", "private_key", "id_rsa"]


def _is_critical(events: list[dict]) -> bool:
    for event in events:
        summary = event.get("summary", "").lower()
        if event.get("type") == "tool_use":
            for cmd in _DANGEROUS_COMMANDS:
                if cmd in summary:
                    return True
            for path in _SENSITIVE_PATHS:
                if path in summary and ("write" in summary.lower() or "edit" in summary.lower()):
                    return True
    return False


class TicketAgent:
    def __init__(self, ticket_id: str, ticket: dict, verbose: bool = False,
                 agent_settings: dict | None = None):
        self.ticket_id = ticket_id
        self.ticket = ticket
        self.verbose = verbose
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        # Use hot-reloadable settings from Redis, fallback to env
        self._settings = agent_settings or {}
        self.model = self._settings.get("model", settings.agent_model)
        self.batch_size = self._settings.get("batch_size", settings.agent_batch_size)
        self.max_context = self._settings.get("max_context_messages", settings.agent_max_context_messages)
        self.messages: list[dict] = []
        self.tools = _build_tools(self._settings)
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            title=ticket.get("title", ""),
            description=ticket.get("description", ""),
            branch=ticket.get("branch", ""),
            role=ticket.get("role", "builder"),
        )
        self._stopped = False

    def stop(self):
        self._stopped = True

    async def run(self, log_path: str) -> None:
        """Main ReAct loop: tail log → batch events → call API → execute tools."""
        logger.info("TicketAgent started for %s", self.ticket_id)

        event_buffer: list[dict] = []

        async for event in session_manager.tail_log(self.ticket_id, log_path):
            if self._stopped:
                break

            event_dict = event.model_dump()
            event_buffer.append(event_dict)

            # Store and broadcast activity
            await redis_client.append_activity(self.ticket_id, event_dict)
            await broadcast({
                "type": "activity",
                "ticket_id": self.ticket_id,
                "data": event_dict,
            })

            should_call = (
                _is_critical(event_buffer)
                or len(event_buffer) >= self.batch_size
            )

            if should_call:
                await self._process_batch(event_buffer)
                event_buffer = []

        # Process any remaining events
        if event_buffer and not self._stopped:
            await self._process_batch(event_buffer)

        logger.info("TicketAgent finished for %s", self.ticket_id)

    async def _process_batch(self, events: list[dict]) -> None:
        summary = "\n".join(
            f"[{e.get('timestamp', '')}] {e.get('source', '')}: {e.get('summary', '')}"
            for e in events
        )

        self.messages.append({
            "role": "user",
            "content": f"New activity from Claude Code:\n\n{summary}",
        })

        # Trim context
        if len(self.messages) > self.max_context:
            self.messages = self.messages[-self.max_context:]

        await self._call_api()

    async def _call_api(self) -> None:
        # Budget check
        ok, reason = await cost_tracker.can_spend(self.ticket_id, 0.01)
        if not ok:
            logger.warning("Budget exceeded for %s: %s", self.ticket_id, reason)
            await self._record_activity("warning", f"Budget exceeded: {reason}")
            return

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                tools=self.tools,
                messages=self.messages,
            )
        except Exception as e:
            logger.error("API call failed for %s: %s", self.ticket_id, e)
            return

        # Record cost
        usage = response.usage
        cost = cost_tracker.calculate_cost({
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        }, self.model)
        await cost_tracker.record_spend(self.ticket_id, cost)

        # Process response
        assistant_content = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                if self.verbose:
                    logger.info("Agent [%s]: %s", self.ticket_id, block.text[:100])
                await self._record_activity("decision", block.text[:200])
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                tool_uses.append(block)

        self.messages.append({"role": "assistant", "content": assistant_content})

        # Execute tools
        if tool_uses:
            tool_results = []
            for tool in tool_uses:
                result = await self._execute_tool(tool.name, tool.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool.id,
                    "content": result,
                })
            self.messages.append({"role": "user", "content": tool_results})

            # If there were tool uses and stop_reason is tool_use, continue the loop
            if response.stop_reason == "tool_use":
                await self._call_api()  # Recursive, with safety limit below

    async def _execute_tool(self, name: str, input_data: dict) -> str:
        clone_path = self.ticket.get("clone_path", "")

        if name == "tmux_send":
            message = input_data.get("message", "")
            try:
                session_manager.send_input(self.ticket_id, message)
                await self._record_activity("intervention", f"Sent to Claude Code: {message[:100]}")
                return f"Message sent: {message[:50]}"
            except Exception as e:
                return f"Error: {e}"

        elif name == "file_read":
            path = input_data.get("path", "")
            full_path = os.path.join(clone_path, path)
            try:
                with open(full_path) as f:
                    content = f.read()
                return content[:5000]
            except Exception as e:
                return f"Error reading {path}: {e}"

        elif name == "git_status":
            try:
                result = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=clone_path, capture_output=True, text=True,
                )
                return result.stdout or "(clean)"
            except Exception as e:
                return f"Error: {e}"

        elif name == "escalate":
            question = input_data.get("question", "")
            severity = input_data.get("severity", "info")
            from claude_hub.services.ticket_service import transition
            from claude_hub.models.ticket import TicketStatus
            try:
                await transition(self.ticket_id, TicketStatus.BLOCKED,
                                 blocked_question=question)
                await broadcast({
                    "type": "escalation",
                    "ticket_id": self.ticket_id,
                    "data": {"question": question, "severity": severity},
                })
                updated = await redis_client.get_ticket(self.ticket_id)
                await broadcast({
                    "type": "ticket_updated",
                    "ticket_id": self.ticket_id,
                    "data": updated,
                })
                await self._record_activity("warning", f"Escalated: {question[:100]}")
                return f"Escalated to human: {question}"
            except Exception as e:
                return f"Error escalating: {e}"

        elif name == "pause_session":
            try:
                tmux_name = session_manager._session_name(self.ticket_id)
                subprocess.run(
                    ["tmux", "send-keys", "-t", tmux_name, "C-c", ""],
                    check=True,
                )
                await self._record_activity("warning", "Paused Claude Code session (Ctrl+C)")
                return "Session paused with Ctrl+C"
            except Exception as e:
                return f"Error: {e}"

        elif name == "wait":
            return "Continuing to monitor."

        elif name == "web_search":
            query = input_data.get("query", "")
            try:
                # Use Anthropic's built-in web search via server-side tool
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": f"Search the web for: {query}. Summarize the key findings."}],
                    tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                )
                result_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        result_text += block.text
                await self._record_activity("info", f"Web search: {query[:60]}")
                return result_text[:3000]
            except Exception as e:
                return f"Search error: {e}"

        return f"Unknown tool: {name}"

    async def _record_activity(self, event_type: str, summary: str) -> None:
        from datetime import datetime, timezone
        event = ActivityEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="ticket_agent",
            type=event_type,
            summary=summary,
        )
        event_dict = event.model_dump()
        await redis_client.append_activity(self.ticket_id, event_dict)
        await broadcast({
            "type": "activity",
            "ticket_id": self.ticket_id,
            "data": event_dict,
        })
