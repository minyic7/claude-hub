import json
import logging

from claude_hub import redis_client
from claude_hub.routers.ws import broadcast
from claude_hub.services import cost_tracker, session_manager
from claude_hub.services.base_agent import BaseAgent

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


class TicketAgent(BaseAgent):
    def __init__(self, ticket_id: str, ticket: dict, verbose: bool = False,
                 agent_settings: dict | None = None):
        self.ticket = ticket
        self.verbose = verbose
        self.batch_size = (agent_settings or {}).get("batch_size", 8)

        tmux_session = session_manager._session_name(ticket_id)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            title=ticket.get("title", ""),
            description=ticket.get("description", ""),
            branch=ticket.get("branch", ""),
        )

        super().__init__(
            agent_id=ticket_id,
            working_dir=ticket.get("clone_path", ""),
            system_prompt=system_prompt,
            tmux_session=tmux_session,
            agent_settings=agent_settings,
        )

    # ── Extra tools ────────────────────────────────────────────────

    def _extra_tools(self) -> list[dict]:
        tools = [
            {
                "name": "escalate",
                "description": "Escalate to the human. Blocks the ticket until the human answers.",
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
        ]

        web_search = self._settings.get("web_search", False)
        if web_search:
            tools.append({
                "name": "web_search",
                "description": "Search the web for information when Claude Code is stuck.",
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

    async def _execute_extra_tool(self, name: str, input_data: dict) -> str | None:
        if name == "escalate":
            return await self._tool_escalate(input_data)
        elif name == "web_search":
            return await self._tool_web_search(input_data)
        return None

    async def _tool_escalate(self, input_data: dict) -> str:
        question = input_data.get("question", "")
        severity = input_data.get("severity", "info")
        from claude_hub.services.ticket_service import transition
        from claude_hub.models.ticket import TicketStatus
        try:
            await transition(self.agent_id, TicketStatus.BLOCKED,
                             blocked_question=question)
            await broadcast({
                "type": "escalation",
                "ticket_id": self.agent_id,
                "data": {"question": question, "severity": severity},
            })
            updated = await redis_client.get_ticket(self.agent_id)
            await broadcast({
                "type": "ticket_updated",
                "ticket_id": self.agent_id,
                "data": updated,
            })
            await self._record_activity("warning", f"Escalated: {question[:100]}")
            return f"Escalated to human: {question}"
        except Exception as e:
            return f"Error escalating: {e}"

    async def _tool_web_search(self, input_data: dict) -> str:
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

    # ── Hooks ──────────────────────────────────────────────────────

    async def _handle_text_response(self, text: str) -> None:
        if self.verbose:
            logger.info("Agent [%s]: %s", self.agent_id, text[:100])
        await self._record_activity("commentary", text[:200])

    async def _record_cost(self, cost: float, tokens: int) -> None:
        await cost_tracker.record_spend(self.agent_id, cost, tokens=tokens)

    def _activity_source(self) -> str:
        return "ticket_agent"

    # ── Main loop (event-driven) ───────────────────────────────────

    async def _call_api(self) -> None:
        # Budget check before calling LLM
        ok, reason = await cost_tracker.can_spend(self.agent_id, 0.01)
        if not ok:
            logger.warning("Budget exceeded for %s: %s", self.agent_id, reason)
            await self._record_activity("warning", f"Budget exceeded: {reason}")
            return
        await super()._call_api()

    async def run(self, log_path: str) -> None:
        """Main ReAct loop: tail log → batch events → call API → execute tools."""
        logger.info("TicketAgent started for %s", self.agent_id)

        event_buffer: list[dict] = []

        async for event in session_manager.tail_log(self.agent_id, log_path):
            if self._stopped:
                break

            event_dict = event.model_dump()
            event_buffer.append(event_dict)

            # Store and broadcast activity
            await redis_client.append_activity(self.agent_id, event_dict)
            await broadcast({
                "type": "activity",
                "ticket_id": self.agent_id,
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

        logger.info("TicketAgent finished for %s", self.agent_id)

    async def _process_batch(self, events: list[dict]) -> None:
        summary = "\n".join(
            f"[{e.get('timestamp', '')}] {e.get('source', '')}: {e.get('summary', '')}"
            for e in events
        )

        self.messages.append({
            "role": "user",
            "content": f"New activity from Claude Code:\n\n{summary}",
        })

        self._trim_context()
        await self._call_api()
