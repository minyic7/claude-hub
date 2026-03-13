import json
import logging

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

REDIS_KEY = "settings:agent"

VALID_PROVIDERS = ["anthropic", "openai", "openai_compatible"]

# Default values — all settings managed via UI, stored in Redis
_DEFAULTS = {
    # System
    "max_sessions": 4,
    "gh_token": "",
    # Agent
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
    """Get all settings from Redis, falling back to defaults."""
    r = redis_client.get_pool()
    raw = await r.get(REDIS_KEY)
    if raw:
        try:
            stored = json.loads(raw)
            result = {**_DEFAULTS, **stored}
            return result
        except json.JSONDecodeError:
            pass

    # First time: return defaults (all settings managed via UI)
    return {**_DEFAULTS}


async def get_max_sessions() -> int:
    """Get max_sessions from settings (convenience for ticket router)."""
    cfg = await get_agent_settings()
    return cfg.get("max_sessions", 4)


async def get_gh_token() -> str:
    """Get global GitHub token from settings."""
    cfg = await get_agent_settings()
    return cfg.get("gh_token", "")


@router.get("/agent")
async def get_settings():
    cfg = await get_agent_settings()
    # Mask secrets in response
    return {
        **cfg,
        "api_key": _mask_key(cfg.get("api_key", "")),
        "gh_token": _mask_key(cfg.get("gh_token", "")),
    }


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

    # System settings
    if "max_sessions" in body:
        current["max_sessions"] = max(1, min(20, int(body["max_sessions"])))

    if "gh_token" in body:
        token = body["gh_token"]
        if token and "..." not in token:
            current["gh_token"] = token

    r = redis_client.get_pool()
    await r.set(REDIS_KEY, json.dumps(current))

    # Log without exposing secrets
    log_cfg = {
        **current,
        "api_key": _mask_key(current.get("api_key", "")),
        "gh_token": _mask_key(current.get("gh_token", "")),
    }
    logger.info("Settings updated: %s", log_cfg)

    return {
        **current,
        "api_key": _mask_key(current.get("api_key", "")),
        "gh_token": _mask_key(current.get("gh_token", "")),
    }


@router.post("/agent/test")
async def test_connection():
    """Test if the configured API key works by making a minimal API call."""
    cfg = await get_agent_settings()
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise HTTPException(400, "No API key configured")

    provider = cfg.get("provider", "anthropic")
    model = cfg.get("model", "")
    endpoint_url = cfg.get("endpoint_url", "")

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            # Always use cheapest model for test — just verifying the key works
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            return {"ok": True, "model": model or resp.model, "message": "Connection successful"}
        else:
            import openai
            kwargs = {"api_key": api_key}
            if endpoint_url:
                kwargs["base_url"] = endpoint_url
            client = openai.OpenAI(**kwargs)
            resp = client.chat.completions.create(
                model=model or "gpt-4o-mini",
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            return {"ok": True, "model": model or resp.model, "message": "Connection successful"}
    except Exception as e:
        err = str(e)
        # Extract useful part of error
        if "authentication" in err.lower() or "api key" in err.lower() or "unauthorized" in err.lower():
            raise HTTPException(401, f"Authentication failed: {err[:200]}")
        if "not found" in err.lower() or "does not exist" in err.lower():
            raise HTTPException(404, f"Model not found: {err[:200]}")
        raise HTTPException(502, f"Connection failed: {err[:200]}")
