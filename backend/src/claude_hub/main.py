import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from claude_hub import redis_client
from claude_hub.auth import require_auth
from claude_hub.config import settings
from claude_hub.routers import github_actions, projects, tickets, webhooks, ws
from claude_hub.routers.auth_router import router as auth_router
from claude_hub.routers.settings_router import router as settings_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def _pr_poll_loop() -> None:
    """Background loop: check review ticket PR statuses every 30 seconds."""
    while True:
        try:
            await asyncio.sleep(30)
            await tickets.sync_review_status()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("PR poll error: %s", e)


async def _recover_orphaned_tickets() -> None:
    """On startup, find IN_PROGRESS/BLOCKED tickets with dead tmux sessions → auto-restart."""
    from claude_hub.services import session_manager, clone_manager

    for status in ("in_progress", "blocked", "verifying"):
        tickets_list = await redis_client.list_tickets(status)
        for ticket in tickets_list:
            tid = ticket["id"]
            if session_manager.is_alive(tid):
                continue
            if session_manager.active_session_count() >= settings.max_sessions:
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
    await _recover_orphaned_tickets()
    poll_task = asyncio.create_task(_pr_poll_loop())
    yield
    poll_task.cancel()
    try:
        await poll_task
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
# WS auth is handled inside the endpoint (query param), not via router dependency
app.include_router(ws.router)


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
