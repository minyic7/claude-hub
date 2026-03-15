import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client
from claude_hub.models.ticket import Project, ProjectCreate, ProjectUpdate
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


@router.get("/{project_id}/tickets")
async def list_project_tickets(project_id: str, status: str | None = None):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await redis_client.backfill_ticket_seqs(project_id)
    return await redis_client.list_tickets_by_project(project_id, status)
