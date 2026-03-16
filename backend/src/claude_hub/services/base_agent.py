"""Base class for LLM agents that supervise Claude Code sessions.

Shared infrastructure:
- Anthropic / OpenAI dual-provider LLM calls with tool use
- Message context management + trimming
- Cost tracking
- Activity recording + WebSocket broadcast
- Common tools: tmux_send, file_read, git_status, wait, pause_session
"""

import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod

import anthropic
import openai

from claude_hub import redis_client
from claude_hub.models.events import ActivityEvent
from claude_hub.routers.ws import broadcast
from claude_hub.services import cost_tracker

logger = logging.getLogger(__name__)


# ── Common tools shared by all agents ──────────────────────────────────

def _common_tools() -> list[dict]:
    return [
        {
            "name": "tmux_send",
            "description": "Send a text message to the Claude Code session.",
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
            "description": "Read a file from the working directory.",
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
            "description": "Run git status in the working directory.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "pause_session",
            "description": "Send Ctrl+C to pause the Claude Code session. Use sparingly.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "wait",
            "description": "Do nothing and continue monitoring.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


# ── Base Agent ─────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """Abstract base for agents that call an LLM and execute tools."""

    def __init__(
        self,
        agent_id: str,
        working_dir: str,
        system_prompt: str,
        tmux_session: str,
        agent_settings: dict | None = None,
    ):
        self.agent_id = agent_id
        self.working_dir = working_dir
        self.system_prompt = system_prompt
        self.tmux_session = tmux_session
        self._settings = agent_settings or {}
        self.provider = self._settings.get("provider", "anthropic")
        self.model = self._settings.get("model", "claude-haiku-4-5-20251001")
        self.max_context = self._settings.get("max_context_messages", 25)
        self.messages: list[dict] = []
        self.tools = self._build_tools()
        self._stopped = False

        # Initialize LLM client
        api_key = self._settings.get("api_key", "")
        endpoint_url = self._settings.get("endpoint_url", "")

        if self.provider == "anthropic":
            self._anthropic = anthropic.Anthropic(api_key=api_key)
            self._openai = None
        else:
            kwargs: dict = {"api_key": api_key}
            if endpoint_url:
                kwargs["base_url"] = endpoint_url
            self._openai = openai.OpenAI(**kwargs)
            self._anthropic = None

    def stop(self):
        self._stopped = True

    # ── Tools ──────────────────────────────────────────────────────

    def _build_tools(self) -> list[dict]:
        """Common tools + subclass-specific tools."""
        tools = _common_tools()
        tools.extend(self._extra_tools())
        return tools

    @abstractmethod
    def _extra_tools(self) -> list[dict]:
        """Return additional tools specific to this agent type."""
        ...

    # ── Tool execution ─────────────────────────────────────────────

    async def _execute_tool(self, name: str, input_data: dict) -> str:
        # Common tools
        if name == "tmux_send":
            return await self._tool_tmux_send(input_data)
        elif name == "file_read":
            return await self._tool_file_read(input_data)
        elif name == "git_status":
            return await self._tool_git_status()
        elif name == "pause_session":
            return await self._tool_pause_session()
        elif name == "wait":
            return "Continuing to monitor."

        # Subclass tools
        result = await self._execute_extra_tool(name, input_data)
        if result is not None:
            return result

        return f"Unknown tool: {name}"

    @abstractmethod
    async def _execute_extra_tool(self, name: str, input_data: dict) -> str | None:
        """Execute a subclass-specific tool. Return None if not handled."""
        ...

    async def _tool_tmux_send(self, input_data: dict) -> str:
        message = input_data.get("message", "")
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", self.tmux_session, "-l", message],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", self.tmux_session, "Enter"],
                check=True, capture_output=True,
            )
            await self._record_activity("intervention", f"Sent to CC: {message[:100]}")
            return f"Message sent: {message[:50]}"
        except Exception as e:
            return f"Error: {e}"

    async def _tool_file_read(self, input_data: dict) -> str:
        path = input_data.get("path", "")
        full_path = os.path.join(self.working_dir, path)
        try:
            with open(full_path) as f:
                content = f.read()
            return content[:5000]
        except Exception as e:
            return f"Error reading {path}: {e}"

    async def _tool_git_status(self) -> str:
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.working_dir, capture_output=True, text=True,
            )
            return result.stdout or "(clean)"
        except Exception as e:
            return f"Error: {e}"

    async def _tool_pause_session(self) -> str:
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", self.tmux_session, "C-c", ""],
                check=True, capture_output=True,
            )
            await self._record_activity("warning", "Paused CC session (Ctrl+C)")
            return "Session paused with Ctrl+C"
        except Exception as e:
            return f"Error: {e}"

    # ── LLM calls ──────────────────────────────────────────────────

    async def _call_api(self) -> None:
        if self._anthropic:
            await self._call_anthropic()
        else:
            await self._call_openai()

    async def _call_anthropic(self) -> None:
        try:
            response = self._anthropic.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                tools=self.tools,
                messages=self.messages,
            )
        except Exception as e:
            logger.error("Anthropic API call failed for %s: %s", self.agent_id, e)
            return

        # Record cost
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cache_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
        cost = cost_tracker.calculate_cost({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_tokens,
        }, self.model)
        total_tokens = input_tokens + output_tokens + cache_tokens
        await self._record_cost(cost, total_tokens)

        # Process response
        assistant_content = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                await self._handle_text_response(block.text)
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

            if response.stop_reason == "tool_use":
                await self._call_api()

    async def _call_openai(self) -> None:
        # Convert tools to OpenAI format
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in self.tools
        ]

        # Convert messages to OpenAI format
        oai_messages = [{"role": "system", "content": self.system_prompt}]
        for msg in self.messages:
            if msg["role"] == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            })
                    oai_msg: dict = {"role": "assistant", "content": "\n".join(text_parts) or None}
                    if tool_calls:
                        oai_msg["tool_calls"] = tool_calls
                    oai_messages.append(oai_msg)
                else:
                    oai_messages.append({"role": "assistant", "content": str(content)})
            elif msg["role"] == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            oai_messages.append({
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": block["content"],
                            })
                        else:
                            oai_messages.append({"role": "user", "content": str(block)})
                else:
                    oai_messages.append({"role": "user", "content": content})

        try:
            response = self._openai.chat.completions.create(
                model=self.model,
                max_tokens=1024,
                messages=oai_messages,
                tools=oai_tools if oai_tools else openai.NOT_GIVEN,
            )
        except Exception as e:
            logger.error("OpenAI API call failed for %s: %s", self.agent_id, e)
            return

        # Record cost
        usage = response.usage
        input_tokens = usage.prompt_tokens or 0
        output_tokens = usage.completion_tokens or 0
        cost = cost_tracker.calculate_cost({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
        }, self.model)
        await self._record_cost(cost, input_tokens + output_tokens)

        # Process response
        choice = response.choices[0]
        message = choice.message
        assistant_content = []
        tool_uses = []

        if message.content:
            assistant_content.append({"type": "text", "text": message.content})
            await self._handle_text_response(message.content)

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": args,
                })
                tool_uses.append(tc)

        self.messages.append({"role": "assistant", "content": assistant_content})

        if tool_uses:
            tool_results = []
            for tc in tool_uses:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = await self._execute_tool(tc.function.name, args)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })
            self.messages.append({"role": "user", "content": tool_results})

            if choice.finish_reason == "tool_calls":
                await self._call_api()

    # ── Context management ─────────────────────────────────────────

    def _trim_context(self) -> None:
        """Trim messages to max_context, keeping assistant+tool_result pairs intact."""
        if len(self.messages) <= self.max_context:
            return
        trimmed = self.messages[-self.max_context:]
        # Don't start with an orphaned tool_result
        while trimmed and trimmed[0]["role"] == "user":
            content = trimmed[0].get("content", "")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                trimmed = trimmed[1:]
            else:
                break
        # Must start with user message
        while trimmed and trimmed[0]["role"] == "assistant":
            trimmed = trimmed[1:]
        self.messages = trimmed

    # ── Hooks for subclasses ───────────────────────────────────────

    @abstractmethod
    async def _handle_text_response(self, text: str) -> None:
        """Called when the LLM returns a text block. Subclass decides how to record/broadcast it."""
        ...

    @abstractmethod
    async def _record_cost(self, cost: float, tokens: int) -> None:
        """Record LLM cost. Subclass decides scope (per-ticket vs per-project)."""
        ...

    async def _record_activity(self, event_type: str, summary: str) -> None:
        """Record an activity event. Default implementation uses ticket activity stream."""
        from datetime import datetime, timezone
        event = ActivityEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            source=self._activity_source(),
            type=event_type,
            summary=summary,
        )
        event_dict = event.model_dump()
        await redis_client.append_activity(self.agent_id, event_dict)
        await broadcast({
            "type": "activity",
            "ticket_id": self.agent_id,
            "data": event_dict,
        })

    def _activity_source(self) -> str:
        """Source name for activity events."""
        return "agent"
