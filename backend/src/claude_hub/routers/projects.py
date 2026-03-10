import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client
from claude_hub.models.ticket import Project, ProjectCreate, ProjectUpdate
from claude_hub.routers.ws import broadcast

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
    updated = await redis_client.get_project(project_id)
    updated["gh_token"] = _mask_token(updated.get("gh_token", ""))
    await broadcast({"type": "project_updated", "data": updated})
    return updated


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    deleted = await redis_client.delete_project(project_id)
    if not deleted:
        raise HTTPException(404, "Project not found")
    await broadcast({"type": "project_deleted", "project_id": project_id})


@router.get("/{project_id}/tickets")
async def list_project_tickets(project_id: str, status: str | None = None):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await redis_client.list_tickets_by_project(project_id, status)
