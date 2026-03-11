import json
import logging

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client
from claude_hub.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

REDIS_KEY = "settings:agent"

VALID_PROVIDERS = ["anthropic", "openai", "openai_compatible"]

# Default values
_DEFAULTS = {
    "enabled": True,
    "provider": "anthropic",
    "api_key": "",
    "endpoint_url": "",
    "model": "claude-haiku-4-5-20251001",
    "batch_size": 8,
    "max_context_messages": 25,
    "web_search": False,
    "budget_per_ticket_usd": 2.00,
    "budget_daily_usd": 50.00,
    "budget_monthly_usd": 500.00,
}


def _mask_key(key: str) -> str:
    """Mask API key for display: show first 8 and last 4 chars."""
    if not key or len(key) < 16:
        return "***" if key else ""
    return key[:8] + "..." + key[-4:]


async def get_agent_settings() -> dict:
    """Get agent settings from Redis, falling back to env vars then defaults."""
    r = redis_client.get_pool()
    raw = await r.get(REDIS_KEY)
    if raw:
        try:
            stored = json.loads(raw)
            result = {**_DEFAULTS, **stored}
            # If no API key in Redis, fall back to env
            if not result.get("api_key"):
                result["api_key"] = settings.anthropic_api_key
            return result
        except json.JSONDecodeError:
            pass

    # First time: seed from env vars
    return {
        **_DEFAULTS,
        "enabled": settings.agent_enabled,
        "api_key": settings.anthropic_api_key,
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
    cfg = await get_agent_settings()
    # Mask API key in response
    return {**cfg, "api_key": _mask_key(cfg.get("api_key", ""))}


@router.put("/agent")
async def update_settings(body: dict):
    current = await get_agent_settings()

    if "provider" in body:
        if body["provider"] not in VALID_PROVIDERS:
            raise HTTPException(400, f"Invalid provider. Choose from: {VALID_PROVIDERS}")
        current["provider"] = body["provider"]

    if "api_key" in body:
        key = body["api_key"]
        # Don't overwrite with masked value
        if key and "..." not in key:
            current["api_key"] = key

    if "endpoint_url" in body:
        current["endpoint_url"] = body["endpoint_url"].strip()

    if "model" in body:
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

    # Log without exposing full key
    log_cfg = {**current, "api_key": _mask_key(current.get("api_key", ""))}
    logger.info("Agent settings updated: %s", log_cfg)

    # Return with masked key
    return {**current, "api_key": _mask_key(current.get("api_key", ""))}
