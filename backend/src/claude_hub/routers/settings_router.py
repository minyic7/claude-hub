import json
import logging

from fastapi import APIRouter

from claude_hub import redis_client
from claude_hub.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

REDIS_KEY = "settings:agent"

# Default values (from env/config as initial defaults)
_DEFAULTS = {
    "enabled": True,
    "model": "claude-haiku-4-5-20251001",
    "batch_size": 8,
    "max_context_messages": 25,
    "web_search": False,
    "budget_per_ticket_usd": 2.00,
    "budget_daily_usd": 50.00,
    "budget_monthly_usd": 500.00,
}

# Valid model choices
VALID_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]


async def get_agent_settings() -> dict:
    """Get agent settings from Redis, falling back to env vars then defaults."""
    r = redis_client.get_pool()
    raw = await r.get(REDIS_KEY)
    if raw:
        try:
            return {**_DEFAULTS, **json.loads(raw)}
        except json.JSONDecodeError:
            pass

    # First time: seed from env vars
    return {
        "enabled": settings.agent_enabled,
        "model": settings.agent_model,
        "batch_size": settings.agent_batch_size,
        "max_context_messages": settings.agent_max_context_messages,
        "web_search": settings.agent_web_search,
        "budget_per_ticket_usd": settings.agent_budget_per_ticket_usd,
        "budget_daily_usd": settings.agent_budget_daily_usd,
        "budget_monthly_usd": settings.agent_budget_monthly_usd,
    }


@router.get("/agent")
async def get_settings():
    return await get_agent_settings()


@router.put("/agent")
async def update_settings(body: dict):
    current = await get_agent_settings()

    # Validate and merge
    if "model" in body:
        if body["model"] not in VALID_MODELS:
            from fastapi import HTTPException
            raise HTTPException(400, f"Invalid model. Choose from: {VALID_MODELS}")
        current["model"] = body["model"]

    if "enabled" in body:
        current["enabled"] = bool(body["enabled"])

    if "batch_size" in body:
        val = int(body["batch_size"])
        current["batch_size"] = max(1, min(50, val))

    if "max_context_messages" in body:
        val = int(body["max_context_messages"])
        current["max_context_messages"] = max(5, min(100, val))

    if "web_search" in body:
        current["web_search"] = bool(body["web_search"])

    if "budget_per_ticket_usd" in body:
        current["budget_per_ticket_usd"] = max(0.1, float(body["budget_per_ticket_usd"]))

    if "budget_daily_usd" in body:
        current["budget_daily_usd"] = max(1.0, float(body["budget_daily_usd"]))

    if "budget_monthly_usd" in body:
        current["budget_monthly_usd"] = max(1.0, float(body["budget_monthly_usd"]))

    r = redis_client.get_pool()
    await r.set(REDIS_KEY, json.dumps(current))

    logger.info("Agent settings updated: %s", current)
    return current
