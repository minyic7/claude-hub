import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client
from claude_hub.models.ticket import AgentSettings, Project, ProjectCreate, ProjectUpdate
from claude_hub.routers.ws import broadcast
from claude_hub.services.webhook_registration import delete_webhook, register_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _mask_token(token: str) -> str:
    if not token or len(token) < 8:
        return "***" if token else ""
    return token[:4] + "..." + token[-4:]


@router.get("")
async def list_projects():
    projects = await redis_client.list_projects()
    for p in projects:
        p["gh_token"] = _mask_token(p.get("gh_token", ""))
    return projects


@router.post("", status_code=201)
async def create_project(body: ProjectCreate):
    project_id = str(uuid.uuid4())[:12]
    project = Project(
        id=project_id,
        name=body.name,
        repo_url=body.repo_url,
        gh_token=body.gh_token,
        base_branch=body.base_branch,
        created_at=datetime.now(timezone.utc),
    )

    # Create kanban-claude-hub branch with initial VISION.md
    if body.gh_token and body.repo_url:
        await _init_kanban_branch(project_id, body.name, body.repo_url, body.gh_token, body.base_branch)

    await redis_client.save_project(project.model_dump(mode="json"))

    # Auto-register GitHub webhook
    if body.gh_token and body.repo_url:
        from claude_hub.routers.settings_router import get_global_settings
        cfg = await get_global_settings()
        wh = register_webhook(body.repo_url, body.gh_token, webhook_url_override=cfg.get("webhook_url", ""))
        logger.info("Webhook registration for %s: %s", body.repo_url, wh)
        if wh.get("webhook_id"):
            await redis_client.update_project_fields(project_id, {"webhook_id": str(wh["webhook_id"])})

    response = project.model_dump(mode="json")
    response["gh_token"] = _mask_token(response["gh_token"])

    await broadcast({"type": "project_created", "data": response})
    return response


async def _init_kanban_branch(
    project_id: str, project_name: str, repo_url: str, gh_token: str, base_branch: str,
) -> None:
    """Clone repo, create kanban-claude-hub branch with VISION.md, and push.

    Raises HTTPException if the token lacks push permissions.
    """
    import os
    import subprocess
    import tempfile

    from claude_hub.services.clone_manager import _inject_token

    kanban_branch = "kanban-claude-hub"
    authed_url = _inject_token(repo_url, gh_token)

    # Check remote branches
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", authed_url],
        capture_output=True, text=True,
    )
    remote_output = ls.stdout or ""

    if kanban_branch in remote_output:
        logger.info("Branch '%s' already exists for %s, skipping init", kanban_branch, repo_url)
        return

    # Shallow clone into temp dir (or init empty repo if base_branch doesn't exist)
    tmp = tempfile.mkdtemp(prefix=f"kanban-init-{project_id}-")
    empty_repo = f"refs/heads/{base_branch}" not in remote_output
    try:
        if empty_repo:
            # Empty repo — init locally, add remote, create base branch first
            logger.info("Empty repo detected, creating base branch '%s' for %s", base_branch, repo_url)
            subprocess.run(["git", "init", "-b", base_branch, tmp], capture_output=True, check=True)
            subprocess.run(["git", "remote", "add", "origin", authed_url], cwd=tmp, capture_output=True)
            # Initial commit so base branch exists
            readme_path = os.path.join(tmp, "README.md")
            with open(readme_path, "w") as f:
                f.write(f"# {project_name}\n")
            subprocess.run(["git", "add", "README.md"], cwd=tmp, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"Initial commit for {project_name}"],
                cwd=tmp, capture_output=True,
            )
            # Push base branch first so it becomes the default
            push_base = subprocess.run(
                ["git", "push", "-u", "origin", base_branch],
                cwd=tmp, capture_output=True, text=True,
            )
            if push_base.returncode != 0:
                raise HTTPException(
                    403,
                    f"Cannot push to repo — check that your GitHub token has write access. Error: {push_base.stderr.strip()}"
                )
            logger.info("Created base branch '%s' for %s", base_branch, repo_url)
        else:
            clone_result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", base_branch, authed_url, tmp],
                capture_output=True, text=True,
            )
            if clone_result.returncode != 0:
                raise HTTPException(400, f"Failed to clone repo: {clone_result.stderr.strip()}")

        # Create kanban branch
        subprocess.run(["git", "checkout", "-b", kanban_branch], cwd=tmp, capture_output=True, check=True)

        # Create VISION.md
        vision_path = os.path.join(tmp, "VISION.md")
        if not os.path.exists(vision_path):
            with open(vision_path, "w") as f:
                f.write(
                    f"# {project_name} — Vision\n\n"
                    "<!-- USER_SECTION_START -->\n"
                    "## Goals\n"
                    "- (Add your project goals here)\n\n"
                    "## Scope\n"
                    "- (Define what is in scope and out of scope)\n"
                    "<!-- USER_SECTION_END -->\n"
                )
            subprocess.run(["git", "add", "VISION.md"], cwd=tmp, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initialize VISION.md for Claude Hub kanban"],
                cwd=tmp, capture_output=True,
            )

        # Push — this validates token has write access
        push = subprocess.run(
            ["git", "push", "-u", "origin", kanban_branch],
            cwd=tmp, capture_output=True, text=True,
        )
        if push.returncode != 0:
            raise HTTPException(
                403,
                f"Cannot push to repo — check that your GitHub token has write access. Error: {push.stderr.strip()}"
            )
        logger.info("Created branch '%s' with VISION.md for project %s", kanban_branch, project_id)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@router.get("/{project_id}")
async def get_project(project_id: str):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project["gh_token"] = _mask_token(project.get("gh_token", ""))
    return project


@router.patch("/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")

    await redis_client.update_project_fields(project_id, updates)

    # Re-register webhook if gh_token or repo_url changed
    if "gh_token" in updates or "repo_url" in updates:
        # Delete old webhook if we have one
        old_wh_id = project.get("webhook_id")
        if old_wh_id and project.get("gh_token") and project.get("repo_url"):
            delete_webhook(project["repo_url"], project["gh_token"], int(old_wh_id))

        full = await redis_client.get_project(project_id)
        if full and full.get("gh_token") and full.get("repo_url"):
            from claude_hub.routers.settings_router import get_global_settings
            cfg = await get_global_settings()
            wh = register_webhook(full["repo_url"], full["gh_token"], webhook_url_override=cfg.get("webhook_url", ""))
            logger.info("Webhook re-registration for %s: %s", full["repo_url"], wh)
            if wh.get("webhook_id"):
                await redis_client.update_project_fields(project_id, {"webhook_id": str(wh["webhook_id"])})

    # Rebuild CLAUDE.md + notify session if pilot-related fields changed
    pilot_fields = {"pilot_mode", "max_board_tickets", "max_tickets_per_cycle", "vision_mode"}
    if pilot_fields & updates.keys():
        from claude_hub.services.kanban_manager import rebuild_claude_md, send_pilot_trigger, is_alive
        full_project = await redis_client.get_project(project_id)
        if full_project:
            rebuild_claude_md(project_id, full_project)
            # Only send trigger if pilot mode is ON (don't trigger when disabling)
            if full_project.get("pilot_mode") and is_alive(project_id):
                send_pilot_trigger(project_id, "config_changed")

    updated = await redis_client.get_project(project_id)
    updated["gh_token"] = _mask_token(updated.get("gh_token", ""))
    await broadcast({"type": "project_updated", "data": updated})
    return updated


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    # Clean up webhook before deleting
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    wh_id = project.get("webhook_id")
    if wh_id and project.get("gh_token") and project.get("repo_url"):
        delete_webhook(project["repo_url"], project["gh_token"], int(wh_id))

    await redis_client.delete_project(project_id)
    await broadcast({"type": "project_deleted", "project_id": project_id})


def _mask_key(key: str) -> str:
    if not key or len(key) < 16:
        return "***" if key else ""
    return key[:8] + "..." + key[-4:]


@router.get("/{project_id}/agent/settings")
async def get_project_agent_settings(project_id: str):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    raw = project.get("agent_settings", "")
    try:
        cfg = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    result = AgentSettings(**cfg).model_dump()
    result["api_key"] = _mask_key(result.get("api_key", ""))
    result["pilot_api_key"] = _mask_key(result.get("pilot_api_key", ""))
    return result


@router.put("/{project_id}/agent/settings")
async def update_project_agent_settings(project_id: str, body: AgentSettings):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Don't overwrite api keys with masked values
    raw = project.get("agent_settings", "")
    try:
        old = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (json.JSONDecodeError, TypeError):
        old = {}
    if body.api_key and "..." in body.api_key:
        body.api_key = old.get("api_key", "")
    if body.pilot_api_key and "..." in body.pilot_api_key:
        body.pilot_api_key = old.get("pilot_api_key", "")

    await redis_client.update_project_fields(project_id, {
        "agent_settings": json.dumps(body.model_dump()),
    })

    result = body.model_dump()
    result["api_key"] = _mask_key(result.get("api_key", ""))
    result["pilot_api_key"] = _mask_key(result.get("pilot_api_key", ""))
    return result


@router.get("/{project_id}/tickets")
async def list_project_tickets(project_id: str, status: str | None = None):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await redis_client.backfill_ticket_seqs(project_id)
    return await redis_client.list_tickets_by_project(project_id, status)


@router.get("/{project_id}/supervisor/events")
async def get_supervisor_events(project_id: str, limit: int = 50):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    from claude_hub.services.pilot_agent import get_supervisor_events as _get_events
    return await _get_events(project_id, limit=limit)


@router.post("/{project_id}/supervisor/nudge")
async def nudge_supervisor(project_id: str):
    """Frontend calls this when it detects CC has gone idle. Triggers an immediate PilotAgent tick."""
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.get("pilot_mode"):
        return {"status": "ignored", "reason": "pilot mode not active"}
    from claude_hub.services.pilot_agent import nudge
    event = await nudge(project_id)
    return {"status": "nudged", "event": event}
