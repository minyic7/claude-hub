"""PilotAgent — lightweight LLM supervisor for Kanban CC sessions.

Acts as a simulated user: reads tmux pane output, VISION.md, and board state,
then sends natural-language messages to keep CC productive. PilotAgent asks
questions, confirms decisions, and answers CC's questions — CC does all the
reasoning and hard work.
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone

from claude_hub import redis_client
from claude_hub.config import settings
from claude_hub.models.events import ActivityEvent
from claude_hub.routers.ws import broadcast
from claude_hub.services import cost_tracker
from claude_hub.services.base_agent import BaseAgent
from claude_hub.services.kanban_manager import (
    _session_name,
    is_alive,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

MAX_PANE_LINES = 200       # Max lines to capture from tmux pane
MAX_EVENTS_STORED = 200    # Max supervisor events kept in Redis

PILOT_SYSTEM_PROMPT = """You are the Pilot Agent — a simulated user interacting with a Claude Code (CC) session that manages a project's kanban board.

## Your role
You are like a product manager checking in on CC. You:
- **Ask questions** to understand what CC is doing and guide its priorities
- **Answer CC's questions** when it needs input (based on VISION.md and board context)
- **Keep CC moving** — if it's idle, start a conversation about what to do next
- **Never do the work yourself** — CC has the skills and tools, you just keep it engaged

You are NOT a supervisor issuing commands. You are a collaborative user having a natural conversation.

## VISION.md (current project vision):
{vision}

## Board state (active tickets):
{board}

## Claude Code recent terminal output (newest at bottom):
{pane_output}

## Your decision

Respond with a JSON object (no markdown fences):
{{
  "cc_summary": "2-3 sentences describing what CC has been doing. Be specific — mention ticket numbers, file names, actions taken. The real user reads this to understand progress.",
  "action": "wait" | "message",
  "message": "the natural-language message to send to CC (if action=message), else null",
  "reason": "1 sentence: why you chose this action"
}}

## Action guide:

### "wait" — CC is actively working
Use when CC is writing code, running commands, thinking, or in the middle of a task.
Do NOT interrupt. Just provide a detailed summary of what it's doing.

### "message" — Send a message to CC
Use when CC is idle, asked a question, or needs direction. Your message should be **natural and conversational**, like a user typing in the terminal.

**When CC is idle at the `>` prompt:**
- Look at the board state and VISION.md
- Ask CC what it thinks we should do next, or suggest a direction
- Examples:
  - "I see we have 6 TODO tickets and nothing in progress. What do you think we should tackle first?"
  - "Ticket #1 looks ready to start — it has no dependencies. What do you think?"
  - "Nice work on #3! The PR looks good. What's next on the board?"
  - "I notice #2 failed — can you check what went wrong?"

**When CC asked a question:**
- Answer based on VISION.md and board context
- Be direct and helpful, like a knowledgeable user

**When CC seems stuck or confused:**
- Ask clarifying questions
- Gently redirect: "I think the priority right now is..."
- Remind it of available skills: "You can use /board to check the current state"

## How to detect CC state:

**Working** (→ wait): "Thinking...", "Running...", tool calls in progress, code being written, commands executing
**Idle** (→ message): bare `>` prompt at bottom, "Cycle complete", report just finished, no ongoing work
**Asking** (→ message): question mark at end, "Should I...?", "Which approach...?", permission prompts
**Stuck** (→ message): same error 3+ times, no progress for multiple ticks, confused output

## Key rules:
- Be conversational, not robotic. You're a user, not a system.
- Ask questions — let CC reason and decide. Don't dictate exact API calls.
- If CC is idle and the board has TODO tickets with nothing IN_PROGRESS, ALWAYS nudge it to start working.
- If CC asks about project goals or scope, reference VISION.md.
- Keep messages concise — 1-3 sentences is ideal.
- ALWAYS write a detailed, specific cc_summary — the real user relies on this.
"""


# ── Supervisor Event model ─────────────────────────────────────────────

class SupervisorEvent(dict):
    """Supervisor event stored in Redis. Just a dict with typed constructor."""

    def __init__(
        self,
        cc_summary: str,
        action: str,
        message: str | None,
        reason: str,
    ):
        super().__init__(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cc_summary=cc_summary,
            action=action,
            message=message,
            reason=reason,
        )


# ── PilotAgent ─────────────────────────────────────────────────────────

class PilotAgent(BaseAgent):
    """Tick-driven agent that acts as a simulated user for a Kanban CC session."""

    def __init__(self, project_id: str, project: dict, agent_settings: dict | None = None):
        self.project_id = project_id
        self.project = project

        kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)
        tmux_session = _session_name(project_id)

        # Use a placeholder system prompt — rebuilt each tick with fresh context
        super().__init__(
            agent_id=f"pilot:{project_id}",
            working_dir=kanban_dir,
            system_prompt="",
            tmux_session=tmux_session,
            agent_settings=agent_settings,
        )

        # Override model — pilot uses Sonnet for speed + cost efficiency
        if not agent_settings or not agent_settings.get("model"):
            self.model = "claude-sonnet-4-6"

    # ── Extra tools (none — pilot uses structured output, not tool use) ──

    def _extra_tools(self) -> list[dict]:
        return []

    async def _execute_extra_tool(self, name: str, input_data: dict) -> str | None:
        return None

    # ── Hooks ──────────────────────────────────────────────────────

    async def _handle_text_response(self, text: str) -> None:
        pass

    async def _record_cost(self, cost: float, tokens: int) -> None:
        r = redis_client.get_pool()
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        pipe = r.pipeline()
        pipe.incrbyfloat(f"pilot:cost:project:{self.project_id}", cost)
        pipe.incrbyfloat(f"agent:cost:daily:{today}", cost)
        pipe.incrbyfloat(f"agent:cost:monthly:{month}", cost)
        await pipe.execute()

    async def _record_activity(self, event_type: str, summary: str) -> None:
        pass

    def _activity_source(self) -> str:
        return "pilot_agent"

    # ── Tick cycle ─────────────────────────────────────────────────

    async def tick(self) -> SupervisorEvent | None:
        """Run one supervisor tick. Returns event if action taken, None if skipped."""
        if not is_alive(self.project_id):
            return None

        # 1. Read tmux pane output
        pane_output = self._read_pane()
        if not pane_output:
            return None

        # 2. Read VISION.md
        vision = self._read_vision()

        # 3. Read board state
        board = await self._read_board()

        # 4. Build system prompt with fresh context
        self.system_prompt = PILOT_SYSTEM_PROMPT.format(
            vision=vision,
            board=board,
            pane_output=pane_output,
        )

        # 5. Single LLM call (no conversation history — each tick is independent)
        self.messages = [{"role": "user", "content": "Check on the Claude Code session and decide whether to send a message or wait."}]

        await self._call_api()

        # 6. Parse LLM response
        decision = self._parse_decision()
        if not decision:
            return None

        # 7. Act on decision
        action = decision.get("action", "wait")

        if action == "message":
            message = decision.get("message", "")
            if message:
                self._send_to_cc(message)

        # 8. Record and broadcast supervisor event
        event = SupervisorEvent(
            cc_summary=decision.get("cc_summary", ""),
            action=action,
            message=decision.get("message"),
            reason=decision.get("reason", ""),
        )
        await self._record_supervisor_event(event)
        return event

    # ── Context reading ────────────────────────────────────────────

    def _read_pane(self) -> str:
        """Capture recent tmux pane content."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", self.tmux_session, "-p",
                 "-S", f"-{MAX_PANE_LINES}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.warning("Failed to read tmux pane for %s: %s", self.project_id, e)
        return ""

    def _read_vision(self) -> str:
        """Read VISION.md from the kanban working directory."""
        vision_path = os.path.join(self.working_dir, "VISION.md")
        try:
            with open(vision_path) as f:
                return f.read()[:3000]
        except FileNotFoundError:
            return "(no VISION.md found)"
        except Exception as e:
            return f"(error reading VISION.md: {e})"

    async def _read_board(self) -> str:
        """Get formatted board state for the LLM."""
        tickets = await redis_client.list_tickets_by_project(self.project_id)
        if not tickets:
            return "(empty board)"

        lines = []
        for t in tickets:
            status = t.get("status", "unknown")
            seq = t.get("seq", "?")
            title = t.get("title", "untitled")
            line = f"  #{seq} [{status}] {title}"
            if t.get("pr_number"):
                line += f" (PR #{t['pr_number']})"
            if t.get("has_conflicts") == "True":
                line += " ⚠️ conflicts"
            if t.get("blocked_question"):
                line += f" — blocked: {t['blocked_question'][:60]}"
            lines.append(line)
        return "\n".join(lines)

    # ── Decision parsing ───────────────────────────────────────────

    def _parse_decision(self) -> dict | None:
        """Extract the JSON decision from the last assistant message."""
        if not self.messages:
            return None

        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return self._try_parse_json(block["text"])
                elif isinstance(content, str):
                    return self._try_parse_json(content)
        return None

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Try to extract JSON from text, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning("PilotAgent: failed to parse decision JSON: %s", text[:200])
            return None

    # ── Actions ────────────────────────────────────────────────────

    def _send_to_cc(self, message: str) -> None:
        """Send a message to the Kanban CC session via tmux."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", self.tmux_session, "-l", message],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", self.tmux_session, "Enter"],
                capture_output=True, timeout=5,
            )
            logger.info("PilotAgent sent to %s: %s", self.project_id, message[:80])
        except Exception as e:
            logger.warning("PilotAgent send failed for %s: %s", self.project_id, e)

    # ── Supervisor event storage ───────────────────────────────────

    async def _record_supervisor_event(self, event: SupervisorEvent) -> None:
        """Store event in Redis and broadcast via WebSocket."""
        r = redis_client.get_pool()
        key = f"pilot:{self.project_id}:supervisor_events"
        await r.rpush(key, json.dumps(event))
        await r.ltrim(key, -MAX_EVENTS_STORED, -1)

        await broadcast({
            "type": "supervisor_event",
            "data": {
                "project_id": self.project_id,
                **event,
            },
        })


# ── Module-level helpers for main.py ───────────────────────────────────

_active_pilots: dict[str, PilotAgent] = {}
_api_key_warned: set[str] = set()


async def tick_all_pilots() -> None:
    """Called periodically from main.py. Ticks all active pilot agents."""
    projects = await redis_client.list_projects()
    for project in projects:
        project_id = project.get("id", "")
        if not project.get("pilot_mode") or not is_alive(project_id):
            _active_pilots.pop(project_id, None)
            continue

        if project_id not in _active_pilots:
            agent_settings_raw = project.get("agent_settings", "{}")
            if isinstance(agent_settings_raw, str):
                try:
                    agent_settings = json.loads(agent_settings_raw)
                except json.JSONDecodeError:
                    agent_settings = {}
            else:
                agent_settings = agent_settings_raw

            if not agent_settings.get("api_key"):
                if project_id not in _api_key_warned:
                    _api_key_warned.add(project_id)
                    await broadcast({
                        "type": "notification",
                        "data": {
                            "level": "warning",
                            "title": "Pilot Agent requires API key",
                            "message": "Go to Settings → Agent → TicketAgent to configure an API key. Pilot Agent needs it to operate.",
                        },
                    })
                continue

            _api_key_warned.discard(project_id)
            _active_pilots[project_id] = PilotAgent(
                project_id=project_id,
                project=project,
                agent_settings=agent_settings,
            )

        try:
            await _active_pilots[project_id].tick()
        except Exception as e:
            logger.error("PilotAgent tick failed for %s: %s", project_id, e)


async def get_supervisor_events(project_id: str, limit: int = 50) -> list[dict]:
    """Get recent supervisor events for a project."""
    r = redis_client.get_pool()
    key = f"pilot:{project_id}:supervisor_events"
    raw = await r.lrange(key, -limit, -1)
    return [json.loads(item) for item in raw]


async def nudge(project_id: str) -> dict | None:
    """Trigger an immediate PilotAgent tick for a project."""
    if project_id not in _active_pilots:
        project = await redis_client.get_project(project_id)
        if not project or not project.get("pilot_mode") or not is_alive(project_id):
            return None

        agent_settings_raw = project.get("agent_settings", "{}")
        if isinstance(agent_settings_raw, str):
            try:
                agent_settings = json.loads(agent_settings_raw)
            except json.JSONDecodeError:
                agent_settings = {}
        else:
            agent_settings = agent_settings_raw

        if not agent_settings.get("api_key"):
            await broadcast({
                "type": "notification",
                "data": {
                    "level": "warning",
                    "title": "Pilot Agent requires API key",
                    "message": "Go to Settings → Agent → TicketAgent to configure an API key. Pilot Agent needs it to operate.",
                },
            })
            return None

        _active_pilots[project_id] = PilotAgent(
            project_id=project_id,
            project=project,
            agent_settings=agent_settings,
        )

    try:
        event = await _active_pilots[project_id].tick()
        return dict(event) if event else None
    except Exception as e:
        logger.error("PilotAgent nudge failed for %s: %s", project_id, e)
        return None
