import asyncio
import json
import logging
import os
import subprocess

import anthropic
import openai

from claude_hub import redis_client
from claude_hub.models.events import ActivityEvent
from claude_hub.routers.ws import broadcast
from claude_hub.services import cost_tracker, session_manager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are the TicketAgent supervising a Claude Code session working on a ticket. You commentate live for the human watching the dashboard.

## Your Role
You are the ticket's supervisor. The human sees YOUR commentary in the activity feed alongside Claude Code's raw events. Your job:
1. **Commentate** — brief, opinionated remarks on what Claude Code is doing ("Good approach", "This might break X", "Interesting choice of library")
2. **Intervene** — send corrections via tmux_send when Claude Code goes off-track
3. **Research** — use web_search when Claude Code is stuck
4. **Escalate** — ask the human when you genuinely need a decision

## Commentary Style
- Write short, punchy observations (1-2 sentences max)
- Be opinionated — "Nice" or "Hmm, risky" is better than "Claude Code is editing file X"
- Don't repeat what the raw events already show (the human sees those too)
- Comment on strategy, not mechanics — skip routine tool_use/tool_result chatter
- Use your judgment: comment every 2-3 batches, not every single one
- When Claude Code finishes a logical milestone, summarize what was accomplished

## Trust But Verify
Claude Code runs with full permissions (--dangerously-skip-permissions). You CANNOT prevent actions — stream events arrive AFTER execution. All work is on a feature branch, so mistakes are safe and fixable.

## When to intervene (tmux_send)
- Claude Code is going off-track or misunderstood the task
- Claude Code is stuck in a loop (retrying same failed approach)
- Claude Code made a mistake that needs correction
- You have useful information from web search

## When to escalate
- Task description is genuinely ambiguous
- Critical decision needed (architecture, security)
- Claude Code is consistently failing and you can't fix it

## When to just comment or wait
- Claude Code is making steady progress — drop a brief comment and let it work
- Minor style issues — note them but don't intervene (PR review will catch these)
- Normal progress — a "Looks good so far" is fine

## Ticket
- Title: {title}
- Description: {description}
- Branch: {branch}

## Tools available
- tmux_send: Send a message to Claude Code (correction, suggestion, instruction)
- file_read: Read a file in the working directory
- git_status: Check git status of the working directory
- escalate: Ask the human for help (blocks the ticket until answered)
- pause_session: Send Ctrl+C to pause Claude Code
- wait: Do nothing, continue monitoring

IMPORTANT: Your text responses are shown as "commentary" in the dashboard. Write them for the human audience — concise, opinionated, useful."""


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

    web_search = agent_settings.get("web_search", False) if agent_settings else False
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
        # Use hot-reloadable settings from Redis, fallback to env
        self._settings = agent_settings or {}
        self.provider = self._settings.get("provider", "anthropic")
        self.model = self._settings.get("model", "claude-haiku-4-5-20251001")
        self.batch_size = self._settings.get("batch_size", 8)
        self.max_context = self._settings.get("max_context_messages", 25)
        self.messages: list[dict] = []
        self.tools = _build_tools(self._settings)
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            title=ticket.get("title", ""),
            description=ticket.get("description", ""),
            branch=ticket.get("branch", ""),
        )
        self._stopped = False

        # Initialize client based on provider
        api_key = self._settings.get("api_key", "")
        endpoint_url = self._settings.get("endpoint_url", "")

        if self.provider == "anthropic":
            self._anthropic = anthropic.Anthropic(api_key=api_key)
            self._openai = None
        else:
            # openai or openai_compatible
            kwargs = {"api_key": api_key}
            if endpoint_url:
                kwargs["base_url"] = endpoint_url
            self._openai = openai.OpenAI(**kwargs)
            self._anthropic = None

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

        # Trim context — must keep assistant+tool_result pairs intact
        if len(self.messages) > self.max_context:
            trimmed = self.messages[-self.max_context:]
            # Ensure we don't start with a tool_result (user msg containing tool_result blocks)
            # which would be orphaned without its preceding assistant tool_use
            while trimmed and trimmed[0]["role"] == "user":
                content = trimmed[0].get("content", "")
                if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    trimmed = trimmed[1:]  # Drop orphaned tool_result
                else:
                    break
            # Also ensure we don't start with an assistant message (API expects user-first)
            while trimmed and trimmed[0]["role"] == "assistant":
                trimmed = trimmed[1:]
            self.messages = trimmed

        await self._call_api()

    async def _call_api(self) -> None:
        # Budget check
        ok, reason = await cost_tracker.can_spend(self.ticket_id, 0.01)
        if not ok:
            logger.warning("Budget exceeded for %s: %s", self.ticket_id, reason)
            await self._record_activity("warning", f"Budget exceeded: {reason}")
            return

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
            logger.error("Anthropic API call failed for %s: %s", self.ticket_id, e)
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
        await cost_tracker.record_spend(self.ticket_id, cost, tokens=total_tokens)

        # Process response
        assistant_content = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                if self.verbose:
                    logger.info("Agent [%s]: %s", self.ticket_id, block.text[:100])
                await self._record_activity("commentary", block.text[:200])
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
        # Convert Anthropic-style tools to OpenAI function calling format
        oai_tools = []
        for t in self.tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        # Convert Anthropic-style messages to OpenAI format
        oai_messages = [{"role": "system", "content": self.system_prompt}]
        for msg in self.messages:
            if msg["role"] == "assistant":
                # Anthropic content blocks → OpenAI format
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
                    oai_msg = {"role": "assistant", "content": "\n".join(text_parts) or None}
                    if tool_calls:
                        oai_msg["tool_calls"] = tool_calls
                    oai_messages.append(oai_msg)
                else:
                    oai_messages.append({"role": "assistant", "content": str(content)})
            elif msg["role"] == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Tool results
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
            logger.error("OpenAI API call failed for %s: %s", self.ticket_id, e)
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
        total_tokens = input_tokens + output_tokens
        await cost_tracker.record_spend(self.ticket_id, cost, tokens=total_tokens)

        # Process response
        choice = response.choices[0]
        message = choice.message

        assistant_content = []
        tool_uses = []

        if message.content:
            assistant_content.append({"type": "text", "text": message.content})
            if self.verbose:
                logger.info("Agent [%s]: %s", self.ticket_id, message.content[:100])
            await self._record_activity("commentary", message.content[:200])

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

        # Execute tools
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
                # In full_auto mode, let PO Agent answer instead of waiting for human
                asyncio.create_task(
                    _po_auto_answer(self.ticket_id, question)
                )
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
                if self._anthropic:
                    response = self._anthropic.messages.create(
                        model=self.model,
                        max_tokens=1024,
                        messages=[{"role": "user", "content": f"Search the web for: {query}. Summarize the key findings."}],
                        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                    )
                    result_text = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            result_text += block.text
                else:
                    # OpenAI providers: use web_search_preview tool
                    response = self._openai.chat.completions.create(
                        model=self.model,
                        max_tokens=1024,
                        messages=[{"role": "user", "content": f"Search the web for: {query}. Summarize the key findings."}],
                        tools=[{"type": "web_search_preview"}],
                    )
                    result_text = response.choices[0].message.content or ""
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


async def _po_auto_answer(ticket_id: str, question: str) -> None:
    """If PO Agent is running in full_auto for this ticket's project, answer the escalation."""
    try:
        # Small delay to let the escalation state settle
        await asyncio.sleep(2)

        ticket = await redis_client.get_ticket(ticket_id)
        if not ticket or ticket.get("status") != "blocked":
            return

        project_id = ticket.get("project_id")
        if not project_id:
            return

        from claude_hub.services.po_manager import po_manager
        agent = po_manager.get(project_id)
        if not agent or agent.settings.mode != "full_auto":
            return

        # Use PO Agent's LLM to formulate an answer
        ticket_title = ticket.get("title", ticket_id[:8])
        ticket_desc = ticket.get("description", "")

        answer = await agent._call_llm(
            model=agent.settings.observe_model,
            messages=[{"role": "user", "content": (
                f"A Claude Code agent working on ticket '{ticket_title}' has a question:\n\n"
                f"{question}\n\n"
                f"Ticket description: {ticket_desc}\n\n"
                "As the Product Owner, give a clear, actionable answer. "
                "Be decisive — pick the best approach and tell the agent to proceed. "
                "Keep your answer concise (2-3 sentences max)."
            )}],
            max_tokens=500,
        )

        if not answer:
            return

        # Send the answer via the ticket answer endpoint
        from claude_hub.routers.tickets import answer_ticket
        await answer_ticket(ticket_id, {"answer": answer})

        await agent._emit_activity(
            "info",
            f"Auto-answered escalation for '{ticket_title}': {answer[:80]}",
        )

    except Exception as e:
        logger.warning("PO auto-answer failed for %s: %s", ticket_id, e)
