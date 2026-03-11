import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Query

from claude_hub import redis_client
from claude_hub.config import settings

router = APIRouter(prefix="/api/github", tags=["github"])
logger = logging.getLogger(__name__)


def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract owner/repo from a GitHub URL like https://github.com/owner/repo."""
    match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)", repo_url)
    if not match:
        raise ValueError(f"Cannot parse owner/repo from: {repo_url}")
    return match.group(1), match.group(2)


@router.get("/actions")
async def get_actions(project_id: str = Query(...)):
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    repo_url = project.get("repo_url", "")
    token = project.get("gh_token", "") or settings.gh_token
    if not token:
        raise HTTPException(400, "No GitHub token configured for this project")

    try:
        owner, repo = _parse_owner_repo(repo_url)
    except ValueError:
        raise HTTPException(400, f"Cannot parse owner/repo from: {repo_url}")

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers, params={"per_page": 5})

    if resp.status_code != 200:
        logger.warning("GitHub Actions API returned %s: %s", resp.status_code, resp.text[:200])
        raise HTTPException(502, "Failed to fetch workflow runs from GitHub")

    data = resp.json()
    runs = []
    for run in data.get("workflow_runs", []):
        runs.append({
            "id": run["id"],
            "status": run["status"],
            "conclusion": run.get("conclusion"),
            "created_at": run["created_at"],
            "html_url": run["html_url"],
            "head_branch": run["head_branch"],
            "name": run.get("name", ""),
        })

    return {"runs": runs}
