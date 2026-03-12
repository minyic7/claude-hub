"""Advisor endpoints for persistent project advisor sessions."""

import logging

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client
from claude_hub.services import advisor_manager

router = APIRouter(prefix="/api/projects", tags=["advisor"])
logger = logging.getLogger(__name__)


async def _get_project_and_token(project_id: str) -> tuple[dict, str]:
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    gh_token = project.get("gh_token", "")
    return project, gh_token


@router.post("/{project_id}/advisor/start")
async def start_advisor(project_id: str):
    """Create a persistent advisor tmux session for the project."""
    project, gh_token = await _get_project_and_token(project_id)

    try:
        session_name = advisor_manager.start_advisor(project, gh_token)
    except Exception as e:
        logger.error("Failed to start advisor for %s: %s", project_id, e)
        raise HTTPException(500, f"Failed to start advisor: {e}")

    return {
        "session_name": session_name,
        **advisor_manager.get_status(project_id),
    }


@router.post("/{project_id}/advisor/restart")
async def restart_advisor(project_id: str):
    """Kill and recreate the advisor session."""
    project, gh_token = await _get_project_and_token(project_id)

    try:
        session_name = advisor_manager.restart_advisor(project, gh_token)
    except Exception as e:
        logger.error("Failed to restart advisor for %s: %s", project_id, e)
        raise HTTPException(500, f"Failed to restart advisor: {e}")

    return {
        "session_name": session_name,
        **advisor_manager.get_status(project_id),
    }


@router.get("/{project_id}/advisor/status")
async def advisor_status(project_id: str):
    """Get advisor session status."""
    project = await redis_client.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    return advisor_manager.get_status(project_id)
