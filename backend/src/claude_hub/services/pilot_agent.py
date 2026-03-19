"""PilotAgent — lightweight LLM supervisor for Kanban CC sessions.

Acts as a simulated user: reads tmux pane output, VISION.md, and board state,
then sends natural-language messages to keep CC productive. PilotAgent asks
questions, confirms decisions, and answers CC's questions — CC does all the
reasoning and hard work.
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

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
DEFAULT_WAIT_SECONDS = 30  # Fallback if LLM doesn't specify wait_seconds

PILOT_SYSTEM_PROMPT = """You are the Pilot Agent — a simulated user interacting with a Claude Code (CC) session that manages a project's kanban board.

## Your role
You are like a product manager checking in on CC. You:
- **Ask questions** to understand what CC is doing and guide its priorities
- **Answer CC's questions** when it needs input (based on VISION.md and board context)
- **Keep CC moving** — if it's idle, start a conversation about what to do next
- **Encourage parallelism** — if multiple independent tickets can run at once, suggest starting them together
- **Never do the work yourself** — CC has the skills and tools, you just keep it engaged

You are NOT a supervisor issuing commands. You are a collaborative user having a natural conversation.

## VISION.md (current project vision):
{vision}

## Board state (active tickets):
{board}

## Your last message to CC:
{last_message_context}

## Claude Code recent terminal output (newest at bottom):
{pane_output}

## Your decision

Respond with a JSON object (no markdown fences):
{{
  "cc_summary": "2-3 sentences describing what CC has been doing. Be specific — mention ticket numbers, file names, actions taken. The real user reads this to understand progress.",
  "action": "wait" | "message",
  "wait_seconds": <number — how many seconds before checking in again>,
  "message": "the natural-language message to send to CC (if action=message), else null",
  "reason": "1 sentence: why you chose this action"
}}

**`wait_seconds` is required for BOTH actions.** It controls when you next check in:
- After sending a message: how long to wait for CC to respond (typically 30-60s)
- While CC is working: how long before your next status check (15-120s depending on task size)

## Action guide:

### "wait" — CC is actively working
Use when CC is writing code, running commands, thinking, or in the middle of a task.
Do NOT interrupt. Just provide a detailed summary of what it's doing.

Suggested `wait_seconds`:
- CC is thinking/planning → 15-20s
- CC is running a command → 20-30s
- CC is writing code or doing a multi-step task → 45-90s
- CC just started a big operation (cloning, building) → 60-120s

### "message" — Send a message to CC
Use when CC is idle, asked a question, or needs direction. Your message should be **natural and conversational**, like a user typing in the terminal.

After sending a message, set `wait_seconds` to give CC time to process and respond:
- Simple question → 30s
- Asked CC to do something (start ticket, check board) → 45-60s
- Asked CC to plan or reason about something complex → 60-90s

**When CC is idle at the `>` prompt:**
- Look at the board state and VISION.md
- Ask CC what it thinks we should do next, or suggest a direction
- **If TODO=0 and IN_PROGRESS < 3**, it's time to plan — ask CC to re-read VISION.md and create the next batch:
  - "We're running low on tickets — can you re-read VISION.md and plan the next set?"
  - "Only one ticket in progress and nothing queued. Let's plan ahead — check VISION.md?"
  - Encourage CC to create small, parallelizable tickets with proper priority
- **If a ticket was recently merged**, remind CC to verify deployment:
  - "#3 just merged — can you run /cd-status to make sure the deploy succeeded?"
  - "Nice, #6 is merged! Let's check /cd-status before moving on."
- **If multiple independent tickets exist**, suggest starting them in parallel:
  - "I see #1 and #2 have no shared dependencies — could we start both at once using /start-bulk?"
  - "Now that #1 is merged, #2 and #3 are both unblocked. Let's get them both going!"
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

## Patience:
- **If you just sent a message**, CC may still be processing it. Check the terminal — if CC is actively responding to your last message, WAIT. Don't send another message on top.
- **Don't repeat yourself.** If the terminal shows CC is already acting on your suggestion, wait for it to finish.
- When in doubt, wait. It's better to check in 30 seconds late than to interrupt CC mid-thought.

## Smoke test enforcement:
- CC has Docker access and is instructed to smoke test every ticket before marking it `awaiting_merge`.
- If CC moves a ticket to `awaiting_merge` without mentioning a smoke test, ask: "Did you run the smoke test? Build + verify imports + test endpoints before we merge."
- If CC says smoke test failed due to environment limitations (needs external DB, API key, etc.), accept the skip — don't insist.
- If CC says smoke test failed due to a code bug, encourage it to fix and retry (max 2 attempts).
- **Never block a ticket indefinitely** on smoke test failure — after 2 retries, let CC mark it `failed` with details.

## Verification-first mindset:
- After a ticket merges, ALWAYS ask CC to run `/cd-status` before moving on to the next task.
- After a batch completes, ask CC to re-read VISION.md and report what percentage of the plan is done.
- Do NOT assume work is complete just because the board is empty — ask CC to verify against VISION.md.
- Be skeptical of optimistic self-reports — ask CC to show evidence (test output, deploy status, actual behavior).
- If CC says "everything looks good" without showing proof, ask "can you verify by running X?"
- **Never suggest stopping pilot mode yourself.** Only CC should decide when the vision is fully implemented.

## Key rules:
- Be conversational, not robotic. You're a user, not a system.
- Ask questions — let CC reason and decide. Don't dictate exact API calls.
- If CC is idle and the board has TODO tickets with nothing IN_PROGRESS, ALWAYS nudge it to start working.
- **Encourage parallel work** — if multiple tickets have no dependency conflicts, suggest starting them together.
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
        wait_seconds: int = 0,
    ):
        super().__init__(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cc_summary=cc_summary,
            action=action,
            message=message,
            reason=reason,
            wait_seconds=wait_seconds,
        )


# ── PilotAgent ─────────────────────────────────────────────────────────

class PilotAgent(BaseAgent):
    """Tick-driven agent that acts as a simulated user for a Kanban CC session."""

    def __init__(self, project_id: str, project: dict, agent_settings: dict | None = None):
        self.project_id = project_id
        self.project = project
        self._next_tick_at: datetime | None = None  # LLM-decided next check time
        self._last_message: str | None = None       # what we last sent (for context)
        self._last_message_at: datetime | None = None

        kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)
        tmux_session = _session_name(project_id)

        # Build pilot-specific settings (fully independent from TicketAgent)
        cfg = agent_settings or {}
        pilot_settings = {
            "provider": cfg.get("pilot_provider", "anthropic"),
            "api_key": cfg.get("pilot_api_key", ""),
            "endpoint_url": cfg.get("pilot_endpoint_url", ""),
            "model": cfg.get("pilot_model") or "claude-sonnet-4-6",
        }

        # Use a placeholder system prompt — rebuilt each tick with fresh context
        super().__init__(
            agent_id=f"pilot:{project_id}",
            working_dir=kanban_dir,
            system_prompt="",
            tmux_session=tmux_session,
            agent_settings=pilot_settings,
        )

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

        # 0. Respect LLM-decided wait — skip tick entirely (no LLM call = zero cost)
        now = datetime.now(timezone.utc)
        if self._next_tick_at and now < self._next_tick_at:
            return None

        # 1. Read tmux pane output
        pane_output = self._read_pane()
        if not pane_output:
            return None

        # 2. Read VISION.md
        vision = self._read_vision()

        # 3. Read board state
        board = await self._read_board()

        # 4. Build last_message_context for the prompt
        if self._last_message and self._last_message_at:
            ago = int((now - self._last_message_at).total_seconds())
            last_message_context = f'You sent this {ago}s ago: "{self._last_message}"'
        else:
            last_message_context = "(this is your first check-in — no prior messages sent)"

        # 5. Build system prompt with fresh context
        self.system_prompt = PILOT_SYSTEM_PROMPT.format(
            vision=vision,
            board=board,
            pane_output=pane_output,
            last_message_context=last_message_context,
        )

        # 6. Single LLM call (no conversation history — each tick is independent)
        self.messages = [{"role": "user", "content": "Check on the Claude Code session and decide whether to send a message or wait."}]

        await self._call_api()

        # 7. Parse LLM response
        decision = self._parse_decision()
        if not decision:
            return None

        # 8. Schedule next tick based on LLM-decided wait_seconds
        wait_seconds = decision.get("wait_seconds", DEFAULT_WAIT_SECONDS)
        try:
            wait_seconds = max(0, int(wait_seconds))
        except (TypeError, ValueError):
            wait_seconds = DEFAULT_WAIT_SECONDS
        self._next_tick_at = now + timedelta(seconds=wait_seconds)

        # 9. Act on decision
        action = decision.get("action", "wait")

        if action == "message":
            message = decision.get("message", "")
            if message:
                self._send_to_cc(message)
                self._last_message = message
                self._last_message_at = now

        # 10. Record and broadcast supervisor event
        event = SupervisorEvent(
            cc_summary=decision.get("cc_summary", ""),
            action=action,
            message=decision.get("message"),
            reason=decision.get("reason", ""),
            wait_seconds=wait_seconds,
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
            time.sleep(1)  # let CC process pasted text before pressing Enter
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
_board_complete_notified: set[str] = set()  # prevent repeated completion events

_ACTIVE_STATUSES = {"todo", "queued", "in_progress", "blocked", "verifying",
                     "reviewing", "awaiting_merge", "merging", "failed"}


async def _check_board_complete(project_id: str, project: dict) -> bool:
    """If all tickets are merged/archived (none active), ask Kanban CC whether to stop pilot.

    Instead of auto-disabling pilot mode, sends a message to Kanban CC asking it
    to decide whether to create more tickets or stop. This prevents premature
    completion when there's still work to be done per VISION.md.

    Returns True if board appears complete (notification sent), False otherwise.
    """
    tickets = await redis_client.list_tickets_by_project(project_id)

    # No tickets yet — don't stop, pilot might be telling CC to create some
    if not tickets:
        _board_complete_notified.discard(project_id)
        return False

    # Any ticket in an active status → not complete
    for t in tickets:
        if t.get("status", "") in _ACTIVE_STATUSES and not t.get("archived"):
            _board_complete_notified.discard(project_id)
            return False

    # Already notified for this project — just skip tick silently
    if project_id in _board_complete_notified:
        return True

    # Board complete — ask Kanban CC to decide, do NOT auto-disable pilot
    _board_complete_notified.add(project_id)

    merged = sum(1 for t in tickets if t.get("status") == "merged" and not t.get("archived"))
    archived = sum(1 for t in tickets if t.get("archived"))

    # Ask Kanban CC to verify against VISION.md before stopping
    message = (
        f"All {merged} ticket(s) are merged. Before we stop, please:\n"
        f"1. Re-read VISION.md and check if there's remaining work in the plan\n"
        f"2. Run /cd-status to verify the latest deploy is green\n"
        f"3. If there's more work to do, create the next batch of tickets\n"
        f"4. If VISION.md goals are truly complete, tell me 'pilot mode can stop' and I'll disable it\n"
        f"Don't stop prematurely — verify first."
    )

    event = SupervisorEvent(
        cc_summary=f"All current tickets complete. {merged} merged, {archived} archived. Asking CC to verify against VISION.md before stopping.",
        action="message",
        message=message,
        reason="Board appears complete — asking Kanban CC to verify against VISION.md before disabling pilot mode.",
    )

    # Send message to CC
    tmux_session = _session_name(project_id)
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_session, "-l", message],
            capture_output=True, timeout=5,
        )
        time.sleep(1)
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_session, "Enter"],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        logger.warning("Failed to send board-complete message to CC for %s: %s", project_id, e)

    # Broadcast event
    r = redis_client.get_pool()
    key = f"pilot:{project_id}:supervisor_events"
    await r.rpush(key, json.dumps(dict(event)))
    await r.ltrim(key, -MAX_EVENTS_STORED, -1)
    await broadcast({
        "type": "supervisor_event",
        "data": {"project_id": project_id, **event},
    })

    logger.info("Board complete for %s — asking CC to verify before stopping pilot (%d merged, %d archived)",
                project_id, merged, archived)
    return True


async def tick_all_pilots() -> None:
    """Called periodically from main.py. Ticks all active pilot agents."""
    projects = await redis_client.list_projects()
    for project in projects:
        project_id = project.get("id", "")
        if not project.get("pilot_mode") or not is_alive(project_id):
            _active_pilots.pop(project_id, None)
            continue

        # Check if board is complete — all tickets merged/archived, none active
        if await _check_board_complete(project_id, project):
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

            pilot_key = agent_settings.get("pilot_api_key", "")
            if not pilot_key:
                # No API key — use QA Agent CC session as fallback
                await _tick_via_qa_agent(project_id, project, agent_settings)
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

        pilot_key = agent_settings.get("pilot_api_key", "")
        if not pilot_key:
            # Use QA Agent CC fallback
            return await _tick_via_qa_agent(project_id, project, agent_settings, force=True)

        _active_pilots[project_id] = PilotAgent(
            project_id=project_id,
            project=project,
            agent_settings=agent_settings,
        )

    try:
        # Nudge clears the wait timer — this is an explicit external trigger
        _active_pilots[project_id]._next_tick_at = None
        event = await _active_pilots[project_id].tick()
        return dict(event) if event else None
    except Exception as e:
        logger.error("PilotAgent nudge failed for %s: %s", project_id, e)
        return None


# ── QA Agent fallback ─────────────────────────────────────────────────

_qa_next_tick_at: dict[str, datetime] = {}
_qa_last_message: dict[str, str] = {}
_qa_last_message_at: dict[str, datetime] = {}
_qa_in_flight: set[str] = set()  # prevent concurrent QA ticks per project
_qa_last_pane_hash: dict[str, str] = {}  # detect stale pane output


async def _tick_via_qa_agent(
    project_id: str, project: dict, agent_settings: dict, force: bool = False,
) -> dict | None:
    """Run a PilotAgent tick using QA Agent CC (-p one-shot) instead of API call."""
    if not is_alive(project_id):
        return None

    # Prevent concurrent QA ticks for the same project
    if project_id in _qa_in_flight:
        logger.debug("QA Agent already in-flight for %s, skipping", project_id)
        return None

    # Respect wait timer (unless forced by nudge)
    now = datetime.now(timezone.utc)
    if not force and project_id in _qa_next_tick_at and now < _qa_next_tick_at[project_id]:
        return None

    _qa_in_flight.add(project_id)
    try:
        return await _tick_via_qa_agent_inner(project_id, project, agent_settings, force)
    finally:
        _qa_in_flight.discard(project_id)


async def _tick_via_qa_agent_inner(
    project_id: str, project: dict, agent_settings: dict, force: bool = False,
) -> dict | None:
    from claude_hub.services.qa_session import ask_qa
    now = datetime.now(timezone.utc)

    # Read context (same as PilotAgent.tick)
    kanban_dir = os.path.join(settings.data_dir, "kanbans", project_id)
    tmux_session = _session_name(project_id)

    # 1. Pane output
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", tmux_session, "-p", "-S", f"-{MAX_PANE_LINES}"],
            capture_output=True, text=True, timeout=5,
        )
        pane_output = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        pane_output = ""

    if not pane_output:
        return None

    # 2. Vision
    vision_path = os.path.join(kanban_dir, "VISION.md")
    try:
        with open(vision_path) as f:
            vision = f.read()[:3000]
    except FileNotFoundError:
        vision = "(no VISION.md found)"

    # 3. Board
    tickets = await redis_client.list_tickets_by_project(project_id)
    if tickets:
        board_lines = []
        for t in tickets:
            line = f"  #{t.get('seq', '?')} [{t.get('status', '?')}] {t.get('title', 'untitled')}"
            if t.get("pr_number"):
                line += f" (PR #{t['pr_number']})"
            board_lines.append(line)
        board = "\n".join(board_lines)
    else:
        board = "(empty board)"

    # 4. Last message context + staleness detection
    last_msg = _qa_last_message.get(project_id)
    last_msg_at = _qa_last_message_at.get(project_id)
    if last_msg and last_msg_at:
        ago = int((now - last_msg_at).total_seconds())
        last_message_context = f'You sent this {ago}s ago: "{last_msg}"'
    else:
        ago = 0
        last_message_context = "(this is your first check-in — no prior messages sent)"

    # Detect stale pane output (same content as last tick)
    pane_hash = hashlib.md5(pane_output.encode()).hexdigest()
    prev_hash = _qa_last_pane_hash.get(project_id)
    _qa_last_pane_hash[project_id] = pane_hash
    pane_unchanged = prev_hash == pane_hash

    # Build staleness warning
    staleness_warning = ""
    if pane_unchanged and ago > 30:
        staleness_warning = f"""
⚠️ STALE WARNING: The terminal output has NOT changed since your last check, and you last sent a message {ago}s ago.
CC is likely idle and waiting for you. You MUST send a message — do NOT return action "wait" again."""

    # Build prompt for QA Agent
    prompt = f"""You are acting as the Pilot Agent — a simulated user for a Claude Code kanban session.

VISION.md:
{vision}

Board state:
{board}

Your last message to CC:
{last_message_context}
{staleness_warning}

CC terminal output (newest at bottom):
{pane_output[-3000:]}

Respond with ONLY a JSON object (no markdown, no commentary):
{{"cc_summary": "what CC has been doing", "action": "wait" or "message", "wait_seconds": <number>, "message": "text to send (if action=message, else null)", "reason": "why"}}

Rules:
- If CC is actively working (running commands, editing files) → action: "wait"
- If CC is idle at '❯' or '>' prompt with no active task → action: "message" with guidance on what to do next
- If CC asked a question → action: "message" with an answer
- If tickets are in_progress, tell CC to check their status (e.g. /board)
- wait_seconds: 15-30 (never more than 30)
- IMPORTANT: if CC is idle and waiting, you MUST send a message. Do NOT keep waiting indefinitely.
- SMOKE TEST: If CC marks a ticket awaiting_merge without mentioning a smoke test (docker build, test run, endpoint check), ask it to run one before merging. Accept skips for environment limitations (external DB, API keys).
- POST-MERGE DEPLOY: After a ticket is merged, remind CC to run /cd-status. If deploy failed, CC should create a hotfix ticket immediately. Don't move on until deploy is green.
- VERIFICATION FIRST: After a batch of tickets is done, ask CC to re-read VISION.md and check if there's more work. Never suggest stopping pilot mode — only CC decides when the vision is fully implemented.
- BE SKEPTICAL: If CC says "done" without proof, ask for evidence (test output, deploy status). Don't take self-reports at face value."""

    # Run one-shot QA Agent
    gh_token = project.get("gh_token", "")
    response = await ask_qa(prompt, cwd=kanban_dir, gh_token=gh_token, timeout=90)
    if not response:
        return None

    # Parse JSON from response
    decision = PilotAgent._try_parse_json(response)
    if not decision:
        logger.warning("QA Agent returned unparseable response for %s: %s", project_id, response[:200])
        return None

    # Schedule next tick (hard cap at 30s to prevent indefinite stalls)
    MAX_WAIT = 30
    wait_seconds = decision.get("wait_seconds", DEFAULT_WAIT_SECONDS)
    try:
        wait_seconds = min(max(0, int(wait_seconds)), MAX_WAIT)
    except (TypeError, ValueError):
        wait_seconds = DEFAULT_WAIT_SECONDS
    _qa_next_tick_at[project_id] = now + timedelta(seconds=wait_seconds)

    # Act on decision
    action = decision.get("action", "wait")
    if action == "message":
        message = decision.get("message", "")
        if message:
            try:
                subprocess.run(
                    ["tmux", "send-keys", "-t", tmux_session, "-l", message],
                    capture_output=True, timeout=5,
                )
                time.sleep(1)  # let CC process pasted text before pressing Enter
                subprocess.run(
                    ["tmux", "send-keys", "-t", tmux_session, "Enter"],
                    capture_output=True, timeout=5,
                )
                _qa_last_message[project_id] = message
                _qa_last_message_at[project_id] = now
                logger.info("QA PilotAgent sent to %s: %s", project_id, message[:80])
            except Exception as e:
                logger.warning("QA PilotAgent send failed for %s: %s", project_id, e)

    # Record event (same format as API-based PilotAgent)
    event = SupervisorEvent(
        cc_summary=decision.get("cc_summary", ""),
        action=action,
        message=decision.get("message"),
        reason=decision.get("reason", ""),
        wait_seconds=wait_seconds,
    )

    # Store in Redis and broadcast
    r = redis_client.get_pool()
    key = f"pilot:{project_id}:supervisor_events"
    await r.rpush(key, json.dumps(dict(event)))
    await r.ltrim(key, -MAX_EVENTS_STORED, -1)

    await broadcast({
        "type": "supervisor_event",
        "data": {"project_id": project_id, **event},
    })

    return dict(event)
