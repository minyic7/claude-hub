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

    # Check if branch already exists on remote
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", authed_url, kanban_branch],
        capture_output=True, text=True,
    )
    if kanban_branch in (ls.stdout or ""):
        logger.info("Branch '%s' already exists for %s, skipping init", kanban_branch, repo_url)
        return

    # Shallow clone into temp dir
    tmp = tempfile.mkdtemp(prefix=f"kanban-init-{project_id}-")
    try:
        clone_result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", base_branch, authed_url, tmp],
            capture_output=True, text=True,
        )
        if clone_result.returncode != 0:
            raise HTTPException(400, f"Failed to clone repo: {clone_result.stderr.strip()}")

        # Create branch
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
