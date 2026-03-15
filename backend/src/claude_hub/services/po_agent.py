"""Product Owner Agent — autonomous project planning and ticket creation.

Each POAgent instance runs as a long-lived asyncio task, one per project.
It observes the board, thinks about what to do next, and creates tickets.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import anthropic
import httpx

from claude_hub import redis_client
from claude_hub.config import settings
from claude_hub.models.ticket import POSettings, TicketStatus
from claude_hub.services.po_database import PODatabase

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

VISION_TOKEN_CAP = 1500
COMPACTION_MERGED_THRESHOLD = 5
FREEZE_THRESHOLD_SECONDS = 3600  # Watchdog: 1 hour without a cycle
WATCHDOG_CHECK_INTERVAL = 300  # 5 minutes
MAX_CONSECUTIVE_WAITS = 3
STUCK_SESSION_MINUTES = 15  # Stop+retry sessions with no log output for this long
RETRYABLE_STATUS = {429, 500, 529}

USER_SECTION_START = "<!-- USER_SECTION_START"
USER_SECTION_END = "<!-- USER_SECTION_END -->"

# ─── Branch helpers ──────────────────────────────────────────────────────────


def _slugify(text: str, max_len: int = 60) -> str:
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len]


def _make_branch(branch_type: str, title: str, ticket_id: str) -> str:
    return f"{branch_type}/{_slugify(title, max_len=40)}-{ticket_id[:6]}"


# ─── Vision.md helpers ───────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _extract_user_section(content: str) -> str:
    start = content.find(USER_SECTION_START)
    end = content.find(USER_SECTION_END)
    if start == -1 or end == -1:
        return ""
    return content[start : end + len(USER_SECTION_END)]


def _validate_po_edit(original: str, proposed: str) -> bool:
    return _extract_user_section(original) == _extract_user_section(proposed)


# ─── PO Agent ────────────────────────────────────────────────────────────────


class POAgent:
    def __init__(self, project_id: str, po_settings: POSettings, api_key: str = ""):
        self.project_id = project_id
        self.settings = po_settings
        self._trigger_queue: asyncio.Queue[str] = asyncio.Queue()
        self._stopped = False
        self.last_cycle_at: float = time.time()
        self.cycle_n: int = 0
        self.consecutive_waits: int = 0
        self.status: str = "idle"
        self.db = PODatabase(project_id)
        # Use per-project API key if provided, otherwise fall back to env var
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._project: dict | None = None
        self._gh_token: str = ""
        self._repo_owner: str = ""
        self._repo_name: str = ""

    # ─── Lifecycle ───────────────────────────────────────────────────────

    def enqueue_trigger(self, trigger: str) -> None:
        self._trigger_queue.put_nowait(trigger)

    async def stop(self) -> None:
        self._stopped = True
        self.db.close()

    async def start(self) -> None:
        await self._restore_on_startup()
        await asyncio.gather(
            self._watchdog(),
            self._cycle_loop(),
        )

    async def _restore_on_startup(self) -> None:
        state = self.db.get_state()
        if isinstance(state, dict):
            self.cycle_n = state.get("cycle_n", 0)

        self._project = await redis_client.get_project(self.project_id)
        if self._project:
            self._gh_token = self._project.get("gh_token", "")
            repo_url = self._project.get("repo_url", "")
            # Parse owner/repo from URL
            parts = repo_url.rstrip("/").rstrip(".git").split("/")
            if len(parts) >= 2:
                self._repo_owner = parts[-2]
                self._repo_name = parts[-1]

        self.db.append_message(
            "system",
            f"PO process started at {datetime.now(timezone.utc).isoformat()}. "
            f"Resuming from cycle {self.cycle_n}.",
        )
        logger.info(
            "PO restored for %s: cycle=%d", self.project_id[:8], self.cycle_n
        )
        await self._emit_activity("info", f"PO Agent started (resuming from cycle {self.cycle_n})")

    async def _cycle_loop(self) -> None:
        self._trigger_queue.put_nowait("startup")

        while not self._stopped:
            try:
                trigger = await asyncio.wait_for(
                    self._trigger_queue.get(),
                    timeout=self.settings.report_interval_hours * 3600,
                )
            except asyncio.TimeoutError:
                trigger = "timer"

            if self._stopped:
                break

            try:
                await self.run_cycle(trigger)
            except Exception as e:
                logger.error("PO cycle failed for %s: %s", self.project_id[:8], e)
                self.status = "idle"
                await self._emit_activity("error", f"Cycle failed: {e}")

    async def _watchdog(self) -> None:
        while not self._stopped:
            await asyncio.sleep(WATCHDOG_CHECK_INTERVAL)
            elapsed = time.time() - self.last_cycle_at
            if elapsed > FREEZE_THRESHOLD_SECONDS:
                logger.error(
                    "PO watchdog: no cycle in %.0f min for %s",
                    elapsed / 60,
                    self.project_id[:8],
                )
                try:
                    from claude_hub.routers.ws import broadcast
                    await broadcast({
                        "type": "po_alert",
                        "project_id": self.project_id,
                        "message": f"PO Agent has not run a cycle in {int(elapsed // 60)} minutes.",
                    })
                except Exception:
                    pass
                self.last_cycle_at = time.time()

    # ─── Core Loop ───────────────────────────────────────────────────────

    async def run_cycle(self, trigger: str) -> None:
        self.last_cycle_at = time.time()
        self.cycle_n += 1
        self.db.set_state("cycle_n", self.cycle_n)

        logger.info(
            "PO cycle %d for %s (trigger: %s)",
            self.cycle_n, self.project_id[:8], trigger,
        )
        await self._emit_activity("info", f"Cycle {self.cycle_n} started (trigger: {trigger})")

        # ── OBSERVE ──────────────────────────────────────────────────
        self.status = "analyzing"
        await self._broadcast_status()
        await self._emit_activity("info", "Observing: reading board, VISION.md, git history…")

        board_state = await self._get_board_state()

        # Fix broken dependency references (e.g. "TICKET-001" → UUID)
        await self._fix_broken_deps(board_state)

        vision = await self._read_vision()
        conversation = self.db.load_conversation(limit=50)
        constraints = self._check_constraints(board_state)
        git_context = await self._get_git_context_if_needed(trigger, board_state)

        if vision is None:
            # No VISION.md — raise to user
            self.status = "blocked"
            await self._broadcast_status()
            await self._emit_activity("warn", "VISION.md not found — blocked")
            msg = (
                "No VISION.md found on the kanban-claude-hub branch. "
                "Please create one with at least a Goal and Scope section "
                "so I can begin planning."
            )
            self.db.append_message("po", msg, self.cycle_n)
            await self._broadcast_po_message(msg)
            return

        observe_summary = await self._llm_observe(
            board=board_state,
            vision=vision,
            git_context=git_context,
            conversation_tail=conversation[-10:],
            trigger=trigger,
            constraints=constraints,
        )

        # ── THINK ────────────────────────────────────────────────────
        self.status = "planning"
        await self._broadcast_status()
        await self._emit_activity("info", "Thinking: deciding next actions…")

        think_result = await self._llm_think(
            observe_summary=observe_summary,
            full_vision=vision,
            conversation=conversation,
            constraints=constraints,
        )

        # ── ACT ──────────────────────────────────────────────────────
        actions_taken = []
        for action in think_result.get("actions", []):
            action_type = action.get("type")
            try:
                if action_type == "create_ticket":
                    title = action.get("title", "untitled")
                    await self._emit_activity("info", f"Creating ticket: {title}")
                    await self._create_ticket(action, board_state)
                    actions_taken.append(action)
                elif action_type == "raise_to_user":
                    msg = action.get("message", "")
                    if self.settings.mode == "full_auto":
                        # In full_auto, convert raise_to_user to a log entry — never block
                        self.db.append_message("po", f"[auto-resolved] {msg}", self.cycle_n)
                        await self._broadcast_po_message(msg)
                        await self._emit_activity("info", f"Auto-resolved (full_auto): {msg[:80]}")
                        actions_taken.append(action)
                    else:
                        self.db.append_message("po", msg, self.cycle_n)
                        await self._broadcast_po_message(msg)
                        self.status = "blocked"
                        actions_taken.append(action)
                        await self._emit_activity("warn", f"Raised to user: {msg[:80]}")
                elif action_type == "start_ticket":
                    start_tid = action.get("ticket_id", "")
                    if start_tid:
                        try:
                            from claude_hub.routers.tickets import start_ticket
                            await start_ticket(start_tid)
                            t = await redis_client.get_ticket(start_tid)
                            t_title = t.get("title", start_tid[:8]) if t else start_tid[:8]
                            await self._emit_activity("info", f"Started ticket: {t_title}")
                            actions_taken.append(action)
                        except Exception as e:
                            await self._emit_activity("warn", f"Failed to start ticket {start_tid[:8]}: {e}")
                elif action_type == "answer_ticket":
                    ans_tid = action.get("ticket_id", "")
                    ans_text = action.get("answer", "")
                    if ans_tid and ans_text:
                        t = await redis_client.get_ticket(ans_tid)
                        t_title = t.get("title", ans_tid[:8]) if t else ans_tid[:8]
                        t_status = t.get("status", "missing") if t else "not found"
                        if not t or t_status != "blocked":
                            await self._emit_activity("info", f"Skipped answer_ticket: '{t_title}' is {t_status}, not blocked")
                        else:
                            try:
                                from claude_hub.routers.tickets import answer_ticket
                                await answer_ticket(ans_tid, {"answer": ans_text})
                                await self._emit_activity("info", f"Answered blocked ticket: {t_title}")
                                actions_taken.append(action)
                            except Exception as e:
                                await self._emit_activity("warn", f"Failed to answer ticket {ans_tid[:8]}: {e}")
                elif action_type == "merge_ticket":
                    merge_tid = action.get("ticket_id", "")
                    if merge_tid:
                        t = await redis_client.get_ticket(merge_tid)
                        t_title = t.get("title", merge_tid[:8]) if t else merge_tid[:8]
                        t_status = t.get("status") if t else None
                        if t_status != "review":
                            await self._emit_activity("info", f"Skipped merge: '{t_title}' is {t_status or 'not found'}, not in review")
                        else:
                            try:
                                from claude_hub.routers.tickets import merge_ticket
                                await merge_ticket(merge_tid)
                                await self._emit_activity("info", f"Merged ticket: {t_title}")
                                actions_taken.append(action)
                            except Exception as e:
                                await self._emit_activity("warn", f"Failed to merge '{t_title}': {e}")
                elif action_type == "stop_ticket":
                    stop_tid = action.get("ticket_id", "")
                    if stop_tid:
                        try:
                            from claude_hub.routers.tickets import stop_ticket
                            await stop_ticket(stop_tid)
                            t = await redis_client.get_ticket(stop_tid)
                            t_title = t.get("title", stop_tid[:8]) if t else stop_tid[:8]
                            await self._emit_activity("info", f"Stopped ticket: {t_title}")
                            actions_taken.append(action)
                        except Exception as e:
                            await self._emit_activity("warn", f"Failed to stop ticket {stop_tid[:8]}: {e}")
                elif action_type == "retry_ticket":
                    retry_tid = action.get("ticket_id", "")
                    if retry_tid:
                        try:
                            from claude_hub.routers.tickets import retry_ticket
                            await retry_ticket(retry_tid)
                            t = await redis_client.get_ticket(retry_tid)
                            t_title = t.get("title", retry_tid[:8]) if t else retry_tid[:8]
                            await self._emit_activity("info", f"Retried ticket: {t_title}")
                            actions_taken.append(action)
                        except Exception as e:
                            await self._emit_activity("warn", f"Failed to retry ticket {retry_tid[:8]}: {e}")
                elif action_type == "wait":
                    self.consecutive_waits += 1
                    self.status = "waiting"
                    actions_taken.append(action)
                    await self._emit_activity("info", f"Waiting (consecutive: {self.consecutive_waits})")
                    if self.consecutive_waits >= MAX_CONSECUTIVE_WAITS:
                        msg = (
                            f"I've been waiting for {self.consecutive_waits} consecutive cycles. "
                            "Is there anything you'd like me to focus on?"
                        )
                        self.db.append_message("po", msg, self.cycle_n)
                        await self._broadcast_po_message(msg)
                        self.consecutive_waits = 0
                elif action_type == "update_vision":
                    await self._emit_activity("info", "Updating VISION.md PO Memory")
            except Exception as e:
                logger.error("PO action %s failed: %s", action_type, e)
                await self._emit_activity("error", f"Action '{action_type}' failed: {e}")

        if any(a.get("type") != "wait" for a in actions_taken):
            self.consecutive_waits = 0

        # ── STUCK SESSION DETECTION (full_auto only) ─────────────────
        if self.settings.mode == "full_auto":
            await self._detect_stuck_sessions(board_state)

        # ── AUTO-START (full_auto only) ──────────────────────────────
        if self.settings.mode == "full_auto":
            await self._auto_start_todo_tickets()

        # ── RECORD ───────────────────────────────────────────────────
        self.db.record_cycle(
            cycle_n=self.cycle_n,
            triggered_by=trigger,
            observe_summary=observe_summary,
            think_reasoning=think_result.get("reasoning", ""),
            actions_taken=actions_taken,
        )

        # Update VISION.md PO Memory if there's a vision_update action
        vision_update = next(
            (a for a in think_result.get("actions", []) if a.get("type") == "update_vision"),
            None,
        )
        if vision_update:
            await self._update_vision(vision_update.get("content", ""), vision)

        # Check compaction
        if self._should_compact(board_state):
            await self._run_compaction(board_state, git_context)

        # Generate report on timer trigger
        if trigger == "timer":
            await self._generate_report(board_state, observe_summary)

        if self.status not in ("blocked", "waiting"):
            self.status = "idle"
        await self._broadcast_status()
        action_summary = ", ".join(a.get("type", "?") for a in actions_taken) or "none"
        await self._emit_activity("info", f"Cycle {self.cycle_n} complete — actions: {action_summary}, status: {self.status}")

    # ─── Board State ─────────────────────────────────────────────────

    async def _get_board_state(self) -> list[dict]:
        tickets = await redis_client.list_tickets_by_project(self.project_id)
        return [t for t in tickets if not t.get("archived")]

    def _check_constraints(self, board_state: list[dict]) -> dict:
        po_tickets = [t for t in board_state if t.get("po_proposed")]
        active = [
            t for t in po_tickets
            if t.get("status") not in ("merged", "failed")
        ]
        pending = [t for t in po_tickets if t.get("status") == "po_pending"]
        return {
            "can_create": len(active) < self.settings.max_active_tickets,
            "slots_available": self.settings.max_active_tickets - len(active),
            "pending_approval": len(pending),
            "approval_slots": self.settings.max_pending_approval - len(pending),
            "active_count": len(active),
        }

    # ─── VISION.md ───────────────────────────────────────────────────

    async def _read_vision(self) -> str | None:
        if not self._repo_owner or not self._repo_name:
            return None
        url = (
            f"https://api.github.com/repos/{self._repo_owner}/{self._repo_name}"
            f"/contents/VISION.md?ref=kanban-claude-hub"
        )
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self._gh_token:
            headers["Authorization"] = f"token {self._gh_token}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=15)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return content
        except Exception as e:
            logger.warning("Failed to read VISION.md: %s", e)
            return None

    async def _update_vision(self, po_section_content: str, current_vision: str) -> bool:
        if not self._repo_owner or not self._repo_name:
            return False

        # Build new vision: user section unchanged + new PO section
        user_section = _extract_user_section(current_vision)
        if not user_section:
            logger.warning("Cannot update VISION.md: no user section found")
            return False

        new_content = (
            "# VISION.md\n\n"
            f"{user_section}\n\n"
            "<!-- PO_SECTION_START — MAINTAINED BY PO AGENT -->\n\n"
            f"{po_section_content}\n\n"
            "<!-- PO_SECTION_END -->\n"
        )

        if not _validate_po_edit(current_vision, new_content):
            logger.warning("PO edit validation failed — user section was modified")
            return False

        # Get current SHA for optimistic locking
        url = (
            f"https://api.github.com/repos/{self._repo_owner}/{self._repo_name}"
            f"/contents/VISION.md?ref=kanban-claude-hub"
        )
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self._gh_token}",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    return False
                sha = resp.json()["sha"]

                # Write
                put_resp = await client.put(
                    f"https://api.github.com/repos/{self._repo_owner}/{self._repo_name}"
                    f"/contents/VISION.md",
                    headers=headers,
                    json={
                        "message": f"chore(vision): PO memory update — cycle {self.cycle_n}",
                        "content": base64.b64encode(new_content.encode()).decode(),
                        "sha": sha,
                        "branch": "kanban-claude-hub",
                    },
                    timeout=15,
                )
                if put_resp.status_code == 409:
                    logger.warning("VISION.md write conflict — will retry next cycle")
                    return False
                put_resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("Failed to update VISION.md: %s", e)
            return False

    # ─── Git History ─────────────────────────────────────────────────

    def _needs_git_context(self, trigger: str, board_state: list[dict]) -> bool:
        if self.settings.git_history_threshold == 0:
            return False
        if trigger in ("compaction", "vision_changed"):
            return True
        active_count = len([
            t for t in board_state
            if t.get("status") not in ("merged", "failed")
        ])
        return active_count < 3

    async def _get_git_context_if_needed(
        self, trigger: str, board_state: list[dict]
    ) -> str | None:
        if not self._needs_git_context(trigger, board_state):
            return None
        if not self._repo_owner or not self._repo_name:
            return None

        since = (
            datetime.now(timezone.utc)
            - timedelta(days=self.settings.git_history_days)
        ).isoformat()

        url = (
            f"https://api.github.com/repos/{self._repo_owner}/{self._repo_name}"
            f"/commits?sha=main&per_page={self.settings.git_history_threshold}&since={since}"
        )
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self._gh_token:
            headers["Authorization"] = f"token {self._gh_token}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                commits = resp.json()
        except Exception as e:
            logger.warning("Failed to fetch git history: %s", e)
            return None

        if not commits:
            return None

        commit_data = [
            {"message": c["commit"]["message"], "date": c["commit"]["committer"]["date"]}
            for c in commits
        ]

        # Summarize with cheap model
        summary = await self._call_llm(
            model=self.settings.observe_model,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize these recent git commits from the main branch.\n"
                    "Preserve: key changes, rationale from commit messages, unexpected pivots.\n"
                    "Group by theme. Discard: raw file lists, diff details, PR numbers.\n"
                    "Stay under 800 tokens.\n\n"
                    f"Commits:\n{json.dumps(commit_data, indent=2)}"
                ),
            }],
            max_tokens=1000,
        )
        return f"Recent git history (last {len(commits)} commits):\n{summary}"

    # ─── Ticket Creation ─────────────────────────────────────────────

    async def _fix_broken_deps(self, board_state: list[dict]) -> None:
        """Fix tickets with non-UUID dependency references (e.g. 'TICKET-001', seq ints)."""
        id_set = {t["id"] for t in board_state if t.get("id")}

        for ticket in board_state:
            deps = ticket.get("depends_on", [])
            if not deps:
                continue
            # Check if any dep is not a valid UUID in the board
            has_broken = any(d not in id_set for d in deps)
            if not has_broken:
                continue
            resolved = self._resolve_depends_on(deps, board_state)
            if resolved != deps:
                await redis_client.update_ticket_fields(
                    ticket["id"], {"depends_on": json.dumps(resolved)}
                )
                title = ticket.get("title", ticket["id"][:8])
                logger.info("Fixed broken deps for '%s': %s → %s", title, deps, resolved)
                # Update in-memory board_state too
                ticket["depends_on"] = resolved

    def _resolve_depends_on(self, raw_deps: list, board_state: list[dict]) -> list[str]:
        """Resolve dependency references to UUIDs.

        LLM may return UUIDs, seq numbers (int), or labels like "TICKET-001".
        Convert everything to valid UUIDs by matching against the board.
        """
        if not raw_deps:
            return []

        # Build lookup maps from board
        seq_to_id: dict[int, str] = {}
        id_set: set[str] = set()
        for t in board_state:
            tid = t.get("id", "")
            seq = t.get("seq", 0)
            if tid:
                id_set.add(tid)
                if seq:
                    seq_to_id[seq] = tid

        resolved = []
        for dep in raw_deps:
            if isinstance(dep, str) and dep in id_set:
                # Already a valid UUID
                resolved.append(dep)
            elif isinstance(dep, int) and dep in seq_to_id:
                # Seq number → UUID
                resolved.append(seq_to_id[dep])
            elif isinstance(dep, str):
                # Try to extract a number from labels like "TICKET-001", "TICKET-1", "#1"
                import re
                match = re.search(r'\d+', dep)
                if match:
                    seq_num = int(match.group())
                    if seq_num in seq_to_id:
                        resolved.append(seq_to_id[seq_num])
                    else:
                        logger.warning("PO: unresolved dependency '%s' (seq %d not found)", dep, seq_num)
                else:
                    logger.warning("PO: unresolved dependency '%s'", dep)
            else:
                logger.warning("PO: unresolved dependency '%s' (type %s)", dep, type(dep).__name__)
        return resolved

    async def _create_ticket(self, action: dict, board_state: list[dict]) -> None:
        # Semantic dedup
        is_dup = await self._semantic_dedup(action, board_state)
        if is_dup:
            logger.info(
                "PO skipped duplicate ticket: %s", action.get("title", "")
            )
            return

        title = action["title"]
        description = action.get("description", "")
        branch_type = action.get("branch_type", "feature")
        rationale = action.get("rationale", "")

        ticket_id = str(uuid.uuid4())
        seq = await redis_client.next_ticket_seq(self.project_id)

        # In semi_auto, create as PO_PENDING; in full_auto, create as TODO
        status = (
            TicketStatus.PO_PENDING
            if self.settings.mode == "semi_auto"
            else TicketStatus.TODO
        )

        branch = _make_branch(branch_type, title, ticket_id)
        repo_url = self._project.get("repo_url", "") if self._project else ""
        base_branch = self._project.get("base_branch", "main") if self._project else "main"

        ticket_dict = {
            "id": ticket_id,
            "project_id": self.project_id,
            "seq": seq,
            "title": title,
            "description": description,
            "branch_type": branch_type,
            "branch": branch,
            "repo_url": repo_url,
            "base_branch": base_branch,
            "status": status.value,
            "po_proposed": True,
            "po_rationale": rationale,
            "source": "po_agent",
            "priority": action.get("priority", 0),
            "archived": False,
            "has_conflicts": False,
            "agent_cost_usd": 0.0,
            "notes": json.dumps([]),
            "depends_on": json.dumps(self._resolve_depends_on(action.get("depends_on", []), board_state)),
            "metadata": json.dumps({}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await redis_client.save_ticket(ticket_dict)

        # Broadcast
        from claude_hub.routers.ws import broadcast
        await broadcast({
            "type": "ticket_created",
            "ticket_id": ticket_id,
            "data": await redis_client.get_ticket(ticket_id),
        })

        logger.info(
            "PO created ticket #%d '%s' (%s)",
            seq, title, status.value,
        )

    async def _detect_stuck_sessions(self, board_state: list[dict]) -> None:
        """Detect in_progress/blocked tickets with no log activity and stop+retry them."""
        import os
        from claude_hub.services import session_manager

        active_tickets = [
            t for t in board_state
            if t.get("status") in ("in_progress", "blocked")
        ]

        for ticket in active_tickets:
            tid = ticket["id"]
            if not session_manager.has_active_session(tid):
                continue

            info = session_manager._active_sessions.get(tid)
            if not info:
                continue

            log_path = info.get("log_path", "")
            if not log_path or not os.path.exists(log_path):
                continue

            # Check log file modification time
            try:
                mtime = os.path.getmtime(log_path)
                idle_minutes = (time.time() - mtime) / 60
            except OSError:
                continue

            if idle_minutes < STUCK_SESSION_MINUTES:
                continue

            title = ticket.get("title", tid[:8])
            await self._emit_activity(
                "warn",
                f"Stuck session detected: '{title}' — no output for {idle_minutes:.0f}min, stopping",
            )

            try:
                from claude_hub.routers.tickets import stop_ticket
                await stop_ticket(tid)
                await self._emit_activity("info", f"Stopped stuck ticket: {title}")
            except Exception as e:
                await self._emit_activity("warn", f"Failed to stop stuck '{title}': {e}")
                continue

            # Auto-retry after stop
            try:
                # Small delay to let stop settle
                await asyncio.sleep(2)
                from claude_hub.routers.tickets import retry_ticket
                await retry_ticket(tid)
                await self._emit_activity("info", f"Auto-retried stuck ticket: {title}")
            except Exception as e:
                await self._emit_activity("warn", f"Failed to retry '{title}' after stop: {e}")

    async def _auto_start_todo_tickets(self) -> None:
        """In full_auto mode, start todo tickets that have no unmerged dependencies."""
        from claude_hub.services import session_manager
        from claude_hub.config import settings as app_settings

        board = await self._get_board_state()
        todo_tickets = sorted(
            [t for t in board if t.get("status") == "todo"],
            key=lambda t: t.get("priority", 0),
            reverse=True,
        )

        if not todo_tickets:
            return

        for ticket in todo_tickets:
            tid = ticket["id"]

            # Check capacity
            if session_manager.active_session_count() >= app_settings.max_sessions:
                await self._emit_activity(
                    "info",
                    f"Max sessions ({app_settings.max_sessions}) reached, skipping remaining todo tickets",
                )
                break

            if session_manager.has_active_session(tid):
                continue

            # Check dependencies
            deps = ticket.get("depends_on", [])
            deps_met = True
            for dep_id in deps:
                dep = await redis_client.get_ticket(dep_id)
                if not dep or dep.get("status") != "merged":
                    deps_met = False
                    break
            if not deps_met:
                continue

            # Start via the tickets router
            try:
                from claude_hub.routers.tickets import start_ticket
                await start_ticket(tid)
                title = ticket.get("title", tid[:8])
                await self._emit_activity("info", f"Auto-started ticket: {title}")
            except Exception as e:
                title = ticket.get("title", tid[:8])
                await self._emit_activity("warn", f"Failed to auto-start '{title}': {e}")

    async def _semantic_dedup(self, proposed: dict, existing: list[dict]) -> bool:
        if not existing:
            return False
        existing_summary = json.dumps([
            {"title": t["title"], "status": t.get("status")}
            for t in existing
            if t.get("status") not in ("failed",)
        ])
        result_text = await self._call_llm(
            model=self.settings.observe_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Proposed ticket: {proposed.get('title', '')}\n"
                    f"{proposed.get('description', '')}\n\n"
                    f"Existing tickets:\n{existing_summary}\n\n"
                    "Is the proposed ticket semantically equivalent to any existing ticket?\n"
                    'Answer JSON only: {"is_duplicate": true/false}'
                ),
            }],
            max_tokens=100,
        )
        try:
            parsed = json.loads(result_text.strip())
            return parsed.get("is_duplicate", False)
        except (json.JSONDecodeError, AttributeError):
            return False

    # ─── Compaction ──────────────────────────────────────────────────

    def _should_compact(self, board_state: list[dict]) -> bool:
        merged_count = len([t for t in board_state if t.get("status") == "merged"])
        last_compaction_count = self.db.get_state("last_compaction_merged_count")
        if isinstance(last_compaction_count, (int, float)):
            new_merges = merged_count
        else:
            new_merges = merged_count
        return new_merges >= COMPACTION_MERGED_THRESHOLD

    async def _run_compaction(
        self, board_state: list[dict], git_context: str | None = None
    ) -> None:
        newly_merged = [t for t in board_state if t.get("status") == "merged"]
        if not newly_merged:
            return

        vision = await self._read_vision()
        if not vision:
            return

        # Step 1: Compress merged tickets into VISION.md Completed Work Log
        merged_info = json.dumps([
            {"title": t["title"], "description": t.get("description", ""),
             "notes": t.get("notes", [])}
            for t in newly_merged
        ], indent=2)

        compacted_log = await self._call_llm(
            model=self.settings.compaction_model,
            messages=[{
                "role": "user",
                "content": (
                    "Compress these completed tickets into a Completed Work Log entry.\n"
                    "Preserve: surprises, rationale, decisions. Discard: mechanics, file names.\n"
                    "Group by theme. Stay under 340 tokens. Use bullet format.\n\n"
                    f"Tickets:\n{merged_info}\n\n"
                    f"{'Git context:\n' + git_context if git_context else ''}\n\n"
                    "Output ONLY the Completed Work Log section content (no headers)."
                ),
            }],
            max_tokens=500,
        )

        # Build updated PO section with compacted log
        po_content = (
            "## PO Memory\n\n"
            "### Current Phase\n"
            f"Post-compaction — cycle {self.cycle_n}\n\n"
            "## Completed Work Log\n\n"
            f"{compacted_log}\n"
        )

        success = await self._update_vision(po_content, vision)
        if not success:
            logger.error("Compaction Step 1 failed — aborting")
            return

        # Step 2: Archive merged tickets
        for ticket in newly_merged:
            await redis_client.update_ticket_fields(ticket["id"], {"archived": True})

        logger.info("Compacted and archived %d merged tickets", len(newly_merged))
        self.db.set_state("last_compaction_at", datetime.now(timezone.utc).isoformat())
        self.db.set_state("last_compaction_merged_count", 0)

    # ─── Report Generation ───────────────────────────────────────────

    async def _generate_report(
        self, board_state: list[dict], observe_summary: str
    ) -> None:
        status_groups: dict[str, list] = {}
        for t in board_state:
            s = t.get("status", "unknown")
            status_groups.setdefault(s, []).append(t["title"])

        report_lines = [f"**PO Report — Cycle {self.cycle_n}**\n"]
        for status, titles in sorted(status_groups.items()):
            report_lines.append(f"**{status}** ({len(titles)}):")
            for title in titles:
                report_lines.append(f"  - {title}")
        report_lines.append(f"\n{observe_summary}")

        report = "\n".join(report_lines)
        self.db.append_message("report", report, self.cycle_n)

        report_at = datetime.now(timezone.utc)

        # Store in Redis for GET /po/report
        await redis_client.update_project_fields(self.project_id, {
            "po_last_report": report,
            "po_last_report_at": report_at.isoformat(),
        })

        # Push report to kanban-claude-hub branch
        await self._push_report_to_branch(report, report_at)
        await self._emit_activity("info", f"Report generated (cycle {self.cycle_n})")

    async def _push_report_to_branch(self, report: str, report_at: datetime) -> None:
        """Push report as a markdown file to docs/reports/ on kanban-claude-hub branch."""
        if not self._repo_owner or not self._repo_name or not self._gh_token:
            return

        filename = report_at.strftime("%Y-%m-%dT%H-%M") + ".md"
        path = f"docs/reports/{filename}"
        content = (
            f"# PO Report — {report_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"Cycle: {self.cycle_n}\n\n"
            f"{report}\n"
        )

        url = (
            f"https://api.github.com/repos/{self._repo_owner}/{self._repo_name}"
            f"/contents/{path}"
        )
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self._gh_token}",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.put(
                    url,
                    headers=headers,
                    json={
                        "message": f"docs: PO report — cycle {self.cycle_n}",
                        "content": base64.b64encode(content.encode()).decode(),
                        "branch": "kanban-claude-hub",
                    },
                    timeout=15,
                )
                if resp.status_code in (200, 201):
                    logger.info("Pushed report to %s on kanban-claude-hub", path)
                else:
                    logger.warning("Failed to push report: %s %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Failed to push report to branch: %s", e)

    # ─── LLM Calls ──────────────────────────────────────────────────

    async def _llm_observe(self, **inputs) -> str:
        board_summary = json.dumps([
            {"id": t["id"], "seq": t.get("seq", 0), "title": t["title"],
             "status": t.get("status"), "po_proposed": t.get("po_proposed", False),
             **({"blocked_question": t["blocked_question"]} if t.get("blocked_question") else {}),
             **({"started_at": t["started_at"]} if t.get("started_at") else {})}
            for t in inputs["board"]
        ], indent=2)

        prompt = (
            "You are the OBSERVE step of a Product Owner Agent.\n"
            "Compress the following inputs into a structured situation summary.\n"
            "Output: what's done, what's in flight, what's blocked, capacity, "
            "recent user instructions.\n\n"
            f"Trigger: {inputs['trigger']}\n\n"
            f"Board state:\n{board_summary}\n\n"
            f"Constraints: {json.dumps(inputs['constraints'])}\n\n"
            f"VISION.md:\n{inputs['vision']}\n\n"
        )
        if inputs.get("git_context"):
            prompt += f"Git context:\n{inputs['git_context']}\n\n"
        if inputs.get("conversation_tail"):
            prompt += f"Recent conversation:\n{json.dumps(inputs['conversation_tail'][-5:])}\n"

        return await self._call_llm(
            model=self.settings.observe_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )

    async def _llm_think(self, **inputs) -> dict:
        system_prompt = (
            "You are the Product Owner Agent for a software project.\n"
            "Your job is to decide what to do next based on the OBSERVE summary.\n\n"
            "You MUST respond with valid JSON only (no markdown fences):\n"
            "{\n"
            '  "reasoning": "brief explanation of your decision",\n'
            '  "actions": [\n'
            "    {\n"
            '      "type": "create_ticket" | "start_ticket" | "merge_ticket" | "stop_ticket" | "retry_ticket" | "answer_ticket" | "wait" | "raise_to_user" | "update_vision",\n'
            '      "title": "...",           // for create_ticket\n'
            '      "description": "...",     // for create_ticket\n'
            '      "branch_type": "...",     // for create_ticket\n'
            '      "rationale": "...",       // for create_ticket — MUST reference VISION.md\n'
            '      "priority": 0,            // for create_ticket\n'
            '      "depends_on": [],         // for create_ticket — use ticket UUIDs from the board (the "id" field)\n'
            '      "ticket_id": "...",       // for start_ticket / merge_ticket / stop_ticket / retry_ticket / answer_ticket\n'
            '      "answer": "...",          // for answer_ticket — answer to blocked question\n'
            '      "message": "...",         // for raise_to_user\n'
            '      "content": "..."          // for update_vision — PO section content\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Each ticket rationale MUST reference a specific Goal/Scope item from VISION.md\n"
            "- Before choosing 'wait', check: are there features in Goal/Scope not yet addressed?\n"
            f"- Max {self.settings.max_new_per_cycle} new tickets per cycle\n"
            "- Respect capacity constraints provided in OBSERVE summary\n"
            "- Use merge_ticket for tickets in 'review' status — consider dependency order: merge base tickets before dependents\n"
            "- Use stop_ticket for sessions that appear stuck (in_progress too long with no progress)\n"
            "- Use retry_ticket for failed tickets that should be retried\n"
            "- Use answer_ticket to unblock blocked tickets by answering their question\n"
            "- If a ticket is blocked, look at its blocked_question and answer it decisively\n"
            "- In full_auto mode, NEVER use raise_to_user — make autonomous decisions\n"
        )

        prompt = (
            f"OBSERVE summary:\n{inputs['observe_summary']}\n\n"
            f"Full VISION.md:\n{inputs['full_vision']}\n\n"
            f"Constraints: {json.dumps(inputs['constraints'])}\n"
        )

        if inputs.get("conversation"):
            recent = inputs["conversation"][-5:]
            prompt += f"\nRecent conversation:\n{json.dumps(recent)}\n"

        result_text = await self._call_llm(
            model=self.settings.think_model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            system=system_prompt,
            max_tokens=16000,
            thinking=True,
        )

        try:
            # Strip markdown fences if present
            text = result_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            return json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("PO THINK returned invalid JSON: %s", result_text[:200])
            return {"reasoning": "Failed to parse", "actions": [{"type": "wait"}]}

    async def _call_llm(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        system: str | None = None,
        thinking: bool = False,
        max_retries: int = 3,
    ) -> str:
        delay = 5
        for attempt in range(max_retries + 1):
            try:
                kwargs: dict = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system
                if thinking:
                    budget = self.settings.think_budget_tokens
                    kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget,
                    }
                    # max_tokens must be > budget_tokens
                    if kwargs["max_tokens"] <= budget:
                        kwargs["max_tokens"] = budget + 4000
                    # Extended thinking requires temperature=1
                    kwargs["temperature"] = 1

                response = await asyncio.to_thread(
                    self._client.messages.create, **kwargs
                )

                # Extract text from response
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return ""

            except anthropic.APIStatusError as e:
                if e.status_code not in RETRYABLE_STATUS or attempt == max_retries:
                    raise
                logger.warning(
                    "Anthropic API %d on attempt %d/%d, retrying in %ds",
                    e.status_code, attempt + 1, max_retries, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2

            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
                if attempt == max_retries:
                    raise
                logger.warning(
                    "Anthropic connection error attempt %d/%d: %s",
                    attempt + 1, max_retries, e,
                )
                await asyncio.sleep(delay)
                delay *= 2

        return ""

    # ─── Chat ────────────────────────────────────────────────────────

    async def handle_user_message(self, message: str) -> str:
        self.db.append_message("user", message)
        self.enqueue_trigger("user_message")

        # Quick acknowledgment
        response = await self._call_llm(
            model=self.settings.observe_model,
            messages=[
                {"role": "user", "content": (
                    "You are a Product Owner Agent. The user just sent you a message. "
                    "Acknowledge briefly and let them know you'll incorporate their input "
                    "in the next cycle.\n\n"
                    f"User message: {message}"
                )},
            ],
            max_tokens=300,
        )
        self.db.append_message("po", response, self.cycle_n)
        return response

    # ─── Broadcasting ────────────────────────────────────────────────

    async def _emit_activity(self, level: str, message: str) -> None:
        """Emit an activity log entry: broadcast via WS + persist in Redis."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,  # info, warn, error
            "cycle": self.cycle_n,
            "message": message,
        }
        try:
            await redis_client.append_po_activity(self.project_id, entry)
            from claude_hub.routers.ws import broadcast
            await broadcast({
                "type": "po_activity",
                "project_id": self.project_id,
                "entry": entry,
            })
        except Exception:
            pass

    async def _broadcast_status(self) -> None:
        try:
            from claude_hub.routers.ws import broadcast
            await broadcast({
                "type": "po_status",
                "project_id": self.project_id,
                "status": self.status,
                "cycle_n": self.cycle_n,
            })
        except Exception:
            pass

        await redis_client.update_project_fields(self.project_id, {
            "po_status": self.status,
        })

    async def _broadcast_po_message(self, message: str) -> None:
        try:
            from claude_hub.routers.ws import broadcast
            await broadcast({
                "type": "po_message",
                "project_id": self.project_id,
                "message": message,
                "cycle_n": self.cycle_n,
            })
        except Exception:
            pass
