"""Global PO Agent manager — one POAgent per project, lifecycle tied to FastAPI."""

import asyncio
import logging

from claude_hub import redis_client
from claude_hub.models.ticket import POSettings
from claude_hub.services.po_agent import POAgent

logger = logging.getLogger(__name__)


class POManager:
    """Manages all PO agent processes. One per project, globally."""

    def __init__(self):
        self._agents: dict[str, POAgent] = {}  # project_id → POAgent
        self._tasks: dict[str, asyncio.Task] = {}  # project_id → running task

    async def start_all_enabled(self) -> None:
        """Called at FastAPI lifespan startup — cold start all enabled POs."""
        projects = await redis_client.list_projects()
        count = 0
        for project in projects:
            raw_settings = project.get("po_settings", "")
            if not raw_settings or raw_settings == "{}":
                continue
            try:
                import json
                po_cfg = json.loads(raw_settings) if isinstance(raw_settings, str) else raw_settings
                po_settings = POSettings(**po_cfg)
                if po_settings.enabled:
                    await self.start(project["id"])
                    count += 1
            except Exception as e:
                logger.warning("Failed to parse PO settings for %s: %s", project["id"][:8], e)
        logger.info("POManager: started %d agents on cold start", count)

    async def start(self, project_id: str) -> None:
        """Start PO for a project. Safe to call if already running."""
        if project_id in self._agents:
            return

        project = await redis_client.get_project(project_id)
        if not project:
            logger.warning("POManager: project %s not found", project_id[:8])
            return

        import json
        raw = project.get("po_settings", "")
        try:
            po_cfg = json.loads(raw) if isinstance(raw, str) and raw else {}
        except (json.JSONDecodeError, TypeError):
            po_cfg = {}

        po_settings = POSettings(**po_cfg)

        # Get per-project API key for PO Agent
        agent_raw = project.get("agent_settings", "")
        try:
            agent_cfg = json.loads(agent_raw) if isinstance(agent_raw, str) and agent_raw else {}
        except (json.JSONDecodeError, TypeError):
            agent_cfg = {}
        api_key = agent_cfg.get("api_key", "")

        agent = POAgent(project_id=project_id, po_settings=po_settings, api_key=api_key)
        self._agents[project_id] = agent

        task = asyncio.create_task(
            agent.start(), name=f"po-{project_id[:8]}"
        )
        self._tasks[project_id] = task
        logger.info("POManager: started PO for project %s", project_id[:8])

    async def stop(self, project_id: str) -> None:
        """Stop PO for a project gracefully."""
        agent = self._agents.pop(project_id, None)
        task = self._tasks.pop(project_id, None)
        if agent:
            await agent.stop()
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if agent:
            logger.info("POManager: stopped PO for project %s", project_id[:8])

    async def stop_all(self) -> None:
        """Called at FastAPI lifespan shutdown."""
        for project_id in list(self._agents.keys()):
            await self.stop(project_id)

    def get(self, project_id: str) -> POAgent | None:
        return self._agents.get(project_id)

    def trigger(self, project_id: str, trigger: str) -> None:
        """Fire a trigger to a running PO (non-blocking)."""
        agent = self._agents.get(project_id)
        if agent:
            agent.enqueue_trigger(trigger)

    def is_running(self, project_id: str) -> bool:
        return project_id in self._agents


# Global singleton
po_manager = POManager()
