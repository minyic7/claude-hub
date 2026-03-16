"""PilotAgent — lightweight LLM supervisor for Kanban CC sessions.

Reads tmux pane output, VISION.md, and board state on each tick.
Decides whether to intervene (send input to CC), trigger a pilot cycle,
or wait. Stores supervisor events for the frontend Pilot Agent tab.
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
    send_pilot_trigger,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

MAX_PANE_LINES = 200       # Max lines to capture from tmux pane
MAX_EVENTS_STORED = 200    # Max supervisor events kept in Redis
IDLE_TICKS_BEFORE_TRIGGER = 1  # Trigger on first idle detection

PILOT_SYSTEM_PROMPT = """You are the Pilot Agent monitoring a Claude Code session that manages a project's kanban board.
Your job: keep CC productive and keep the user informed about what's happening.

You are NOT doing the work — Claude Code is. You keep it moving and report its progress.

## VISION.md (current project vision):
{vision}

## Board state (active tickets):
{board}

## Claude Code recent terminal output (newest at bottom):
{pane_output}

## Your decision

Respond with a JSON object (no markdown fences):
{{
  "cc_summary": "2-3 sentences describing what CC has been doing or just accomplished. Be specific — mention ticket numbers, file names, actions taken. The user reads this to understand progress without looking at the terminal.",
  "cc_asked_for": "what CC is waiting for, or null if not waiting",
  "action": "wait" | "send" | "trigger",
  "message": "exact text to send to CC if action=send, else null",
  "reason": "1 sentence: why you chose this action"
}}

## Action guide:
- **"wait"**: CC is actively working (writing code, running commands, thinking). Provide a detailed summary of what it's doing.
- **"send"**: CC is waiting for input — a question, permission prompt, confirmation, or it's stuck. Send the appropriate response. Be concise and direct.
- **"trigger"**: CC has finished its work and is sitting at the `>` prompt idle. Send a pilot trigger to start a new cycle.

## How to detect idle CC:
CC is idle when you see the `>` prompt at the bottom of the terminal with NO ongoing work above it.
Signs of idle: "Cycle complete", "Ready for the next trigger", a bare `>` prompt after a report.
Signs of working: "Thinking...", "Running...", tool calls in progress, code being written.
**When CC is clearly idle, ALWAYS use "trigger" — do not wait.**

## Rules:
- If CC asked a yes/no question, answer it based on the VISION and board context
- If CC is in the middle of writing code or running commands, "wait" but describe what it's doing
- If CC just finished a cycle/report and is at the prompt, "trigger" IMMEDIATELY
- Never interrupt CC mid-task
- Keep messages short and direct when sending input
- If CC seems stuck in a loop (same error 3+ times), send corrective guidance
- ALWAYS write a detailed, specific cc_summary — the user relies on this for progress updates
"""


# ── Supervisor Event model ─────────────────────────────────────────────

class SupervisorEvent(dict):
    """Supervisor event stored in Redis. Just a dict with typed constructor."""

    def __init__(
        self,
        cc_summary: str,
        cc_asked_for: str | None,
        action: str,
        message: str | None,
        reason: str,
    ):
        super().__init__(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cc_summary=cc_summary,
            cc_asked_for=cc_asked_for,
            action=action,
            message=message,
            reason=reason,
        )


# ── PilotAgent ─────────────────────────────────────────────────────────

class PilotAgent(BaseAgent):
    """Tick-driven agent that monitors a Kanban CC session."""

    def __init__(self, project_id: str, project: dict, agent_settings: dict | None = None):
        self.project_id = project_id
        self.project = project
        self._idle_ticks = 0

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
        # Pilot agent text responses are parsed as JSON decisions, not commentary
        pass

    async def _record_cost(self, cost: float, tokens: int) -> None:
        # Record under project scope, not per-ticket
        r = redis_client.get_pool()
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        pipe = r.pipeline()
        pipe.incrbyfloat(f"pilot:cost:project:{self.project_id}", cost)
        pipe.incrbyfloat(f"agent:cost:daily:{today}", cost)
        pipe.incrbyfloat(f"agent:cost:monthly:{month}", cost)
        await pipe.execute()

    async def _record_activity(self, event_type: str, summary: str) -> None:
        """Pilot agent records to project-level supervisor events, not ticket activity."""
        pass  # Supervisor events are recorded via _record_supervisor_event

    def _activity_source(self) -> str:
        return "pilot_agent"

    # ── Tick cycle ─────────────────────────────────────────────────

    async def tick(self) -> SupervisorEvent | None:
        """Run one supervisor tick. Returns event if action taken, None if waiting."""
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
            idle_threshold=IDLE_TICKS_BEFORE_TRIGGER,
        )

        # 5. Single LLM call (no conversation history — each tick is independent)
        self.messages = [{"role": "user", "content": "Analyze the Claude Code session and decide your action."}]

        await self._call_api()

        # 6. Parse LLM response
        decision = self._parse_decision()
        if not decision:
            return None

        # 7. Act on decision
        action = decision.get("action", "wait")

        if action == "wait":
            self._idle_ticks = 0
        elif action == "trigger":
            self._idle_ticks += 1
            if self._idle_ticks < IDLE_TICKS_BEFORE_TRIGGER:
                # Not enough idle ticks yet — record as wait instead
                action = "wait"
            else:
                send_pilot_trigger(self.project_id, "supervisor")
                self._idle_ticks = 0
        elif action == "send":
            message = decision.get("message", "")
            if message:
                self._send_to_cc(message)
            self._idle_ticks = 0

        # 8. Always record and broadcast supervisor event (including wait)
        event = SupervisorEvent(
            cc_summary=decision.get("cc_summary", ""),
            cc_asked_for=decision.get("cc_asked_for"),
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
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
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
_api_key_warned: set[str] = set()  # Track which projects we've warned about missing API key


async def tick_all_pilots() -> None:
    """Called periodically from main.py. Ticks all active pilot agents."""
    projects = await redis_client.list_projects()
    for project in projects:
        project_id = project.get("id", "")
        if not project.get("pilot_mode") or not is_alive(project_id):
            # Stop tracking if pilot mode disabled or session dead
            _active_pilots.pop(project_id, None)
            continue

        if project_id not in _active_pilots:
            # Load agent settings
            agent_settings_raw = project.get("agent_settings", "{}")
            if isinstance(agent_settings_raw, str):
                try:
                    agent_settings = json.loads(agent_settings_raw)
                except json.JSONDecodeError:
                    agent_settings = {}
            else:
                agent_settings = agent_settings_raw

            # Require API key for PilotAgent to function
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
    """Trigger an immediate PilotAgent tick for a project (called by frontend on CC idle)."""
    if project_id not in _active_pilots:
        # Create pilot agent on the fly if needed
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
