import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from claude_hub import redis_client
from claude_hub.auth import require_auth
from claude_hub.config import settings
from claude_hub.routers import kanban, github_actions, projects, tickets, webhooks, ws
from claude_hub.routers.auth_router import router as auth_router
from claude_hub.routers.settings_router import router as settings_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def _pr_poll_loop() -> None:
    """Background loop: check review ticket PR statuses and session timeouts every 10 seconds."""
    while True:
        try:
            await asyncio.sleep(10)
            await tickets.sync_review_status()
            await _check_session_timeouts()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("PR poll error: %s", e)


async def _check_session_timeouts() -> None:
    """Fail IN_PROGRESS tickets whose sessions have exceeded the timeout."""
    if settings.session_timeout_minutes <= 0:
        return

    from datetime import datetime, timezone, timedelta
    from claude_hub.services import session_manager
    from claude_hub.services.ticket_service import transition
    from claude_hub.models.ticket import TicketStatus

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.session_timeout_minutes)

    for status in ("in_progress", "blocked"):
        tickets_list = await redis_client.list_tickets(status)
        for ticket in tickets_list:
            started = ticket.get("started_at")
            if not started:
                continue
            try:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if started_dt > cutoff:
                continue

            tid = ticket["id"]
            elapsed = int((datetime.now(timezone.utc) - started_dt).total_seconds() / 60)
            logger.warning("Session timeout for ticket %s (%d min > %d min limit)", tid[:8], elapsed, settings.session_timeout_minutes)

            session_manager.stop_session(tid)
            session_manager.update_session_status(tid, "failed")
            try:
                updated = await transition(tid, TicketStatus.FAILED,
                                           failed_reason=f"Session timed out after {elapsed} minutes")
                await ws.broadcast({
                    "type": "ticket_updated",
                    "ticket_id": tid,
                    "data": updated,
                })
                await ws.broadcast({
                    "type": "notification",
                    "data": {
                        "level": "warning",
                        "title": f"Session timeout for #{ticket.get('seq', '?')}",
                        "message": f"Session ran for {elapsed} minutes, exceeding the {settings.session_timeout_minutes}-minute limit.",
                        "ticket_id": tid,
                    },
                })
            except Exception as e:
                logger.error("Failed to timeout ticket %s: %s", tid[:8], e)


async def _kanban_sync_loop() -> None:
    """Background loop: sync kanban branches with main every 30 seconds."""
    while True:
        try:
            await asyncio.sleep(30)
            from claude_hub.services.kanban_manager import sync_kanban_branch, is_alive
            from claude_hub import redis_client as rc
            projects = await rc.list_projects()
            for project in projects:
                if is_alive(project["id"]):
                    result = sync_kanban_branch(project["id"], project.get("gh_token", ""), project.get("base_branch", "main"))
                    if result["status"] == "updated":
                        logger.info("Kanban sync for %s: %s", project["id"], result["message"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Kanban sync error: %s", e)


PILOT_TICK_SECONDS = int(os.environ.get("CLAUDE_HUB_PILOT_TICK_SECONDS", "10"))


async def _pilot_agent_loop() -> None:
    """Background loop: tick all active PilotAgents every N seconds."""
    while True:
        try:
            await asyncio.sleep(PILOT_TICK_SECONDS)
            from claude_hub.services.pilot_agent import tick_all_pilots
            await tick_all_pilots()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Pilot agent loop error: %s", e)


async def _migrate_review_to_awaiting_merge() -> None:
    """One-time migration: rename 'review' status to 'awaiting_merge' in Redis."""
    r = redis_client.get_pool()

    # Move tickets from old status set to new
    old_key = "tickets:by_status:review"
    new_key = "tickets:by_status:awaiting_merge"
    old_members = await r.smembers(old_key)
    if old_members:
        for tid in old_members:
            await r.sadd(new_key, tid)
            await r.hset(f"ticket:{tid}", "status", "awaiting_merge")
        await r.delete(old_key)
        logger.info("Migrated %d tickets from 'review' to 'awaiting_merge'", len(old_members))


async def _recover_orphaned_tickets() -> None:
    """On startup, recover orphaned tickets:
    - IN_PROGRESS/BLOCKED/VERIFYING with dead sessions → auto-restart
    - MERGING → fallback to AWAITING_MERGE (background task lost on restart)
    """
    from claude_hub.services import session_manager, clone_manager
    from claude_hub.services.ticket_service import transition
    from claude_hub.models.ticket import TicketStatus

    # Recover MERGING tickets: background wait_for_ci task was lost on restart
    merging_tickets = await redis_client.list_tickets("merging")
    for ticket in merging_tickets:
        tid = ticket["id"]
        try:
            updated = await transition(tid, TicketStatus.AWAITING_MERGE)
            await ws.broadcast({
                "type": "ticket_updated",
                "ticket_id": tid,
                "data": updated,
            })
            logger.info("Recovered MERGING ticket %s → AWAITING_MERGE (retry merge manually)", tid[:8])
        except Exception as e:
            logger.error("Failed to recover MERGING ticket %s: %s", tid[:8], e)

    # Recover session-based tickets
    from claude_hub.routers.settings_router import get_max_sessions
    max_sess = await get_max_sessions()
    for status in ("in_progress", "blocked", "verifying"):
        tickets_list = await redis_client.list_tickets(status)
        for ticket in tickets_list:
            tid = ticket["id"]
            if session_manager.is_alive(tid):
                continue
            if session_manager.active_session_count() >= max_sess:
                logger.warning("Max sessions reached, skipping recovery for %s", tid[:8])
                break

            try:
                project = await redis_client.get_project(ticket.get("project_id", ""))
                gh_token = project.get("gh_token", "") if project else ""

                clone_path = ticket.get("clone_path", "")
                if not clone_path or not os.path.exists(clone_path):
                    clone_manager.ensure_reference(ticket["repo_url"], gh_token=gh_token)
                    clone_path = clone_manager.clone_for_ticket(
                        ticket["repo_url"], tid,
                        ticket["branch"], ticket["base_branch"],
                        gh_token=gh_token,
                    )
                    await redis_client.update_ticket_fields(tid, {"clone_path": clone_path})

                task = ticket.get("description") or ticket["title"]
                session_name, log_path = session_manager.start_session(
                    tid, clone_path, task, gh_token=gh_token,
                    model="claude-opus-4-6",
                )
                await redis_client.update_ticket_fields(tid, {"tmux_session": session_name})
                asyncio.create_task(
                    tickets._tail_and_broadcast(tid, log_path)
                )
                await ws.broadcast({
                    "type": "ticket_updated",
                    "ticket_id": tid,
                    "data": await redis_client.get_ticket(tid),
                })
                logger.info("Auto-restarted orphaned ticket %s (was %s)", tid[:8], status)
            except Exception as e:
                logger.error("Failed to recover orphan %s: %s", tid[:8], e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to Redis at %s", settings.redis_url)
    await redis_client.connect()
    logger.info("Redis connected")
    await _migrate_review_to_awaiting_merge()
    await _recover_orphaned_tickets()
    poll_task = asyncio.create_task(_pr_poll_loop())
    kanban_sync_task = asyncio.create_task(_kanban_sync_loop())
    pilot_task = asyncio.create_task(_pilot_agent_loop())
    yield
    poll_task.cancel()
    kanban_sync_task.cancel()
    pilot_task.cancel()
    for task in (poll_task, kanban_sync_task, pilot_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await redis_client.disconnect()
    logger.info("Redis disconnected")


app = FastAPI(title="Claude Hub", lifespan=lifespan)

# CORS: only needed in dev mode (frontend on different port)
if settings.dev_mode:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Auth-free routes
app.include_router(auth_router)
app.include_router(webhooks.router)

# Auth-protected routes (using Depends at router level)
auth_dep = [Depends(require_auth)] if settings.auth_enabled else []
app.include_router(projects.router, dependencies=auth_dep)
app.include_router(tickets.router, dependencies=auth_dep)
app.include_router(settings_router, dependencies=auth_dep)
app.include_router(github_actions.router, dependencies=auth_dep)
app.include_router(kanban.router, dependencies=auth_dep)
# WS auth is handled inside the endpoint (query param), not via router dependency
app.include_router(ws.router)
app.include_router(kanban.ws_router)


@app.get("/api/version")
async def version():
    return {"sha": settings.build_sha}


@app.get("/api/health")
async def health():
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok" if redis_ok else "degraded", "redis": redis_ok}


@app.get("/api/cost", dependencies=auth_dep)
async def cost_summary():
    return await redis_client.get_cost_summary()


# Serve frontend build output (must be LAST — fallback route)
# Docker: static files at /app/backend/static (copied in Dockerfile)
# Local dev: won't exist (frontend runs its own dev server)
_static_dir = Path(os.environ.get("CLAUDE_HUB_STATIC_DIR", "/app/backend/static"))
if not _static_dir.exists():
    # Fallback: relative to main.py for local dev
    _static_dir = Path(__file__).parent.parent.parent / "static"
if _static_dir.exists() and not settings.dev_mode:
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("claude_hub.main:app", host=settings.host, port=settings.port, reload=True)
