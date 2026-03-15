import json
import logging

from fastapi import APIRouter, HTTPException

from claude_hub import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

REDIS_KEY = "settings:global"

# Global-only defaults (agent settings are now per-project)
_DEFAULTS = {
    "max_sessions": 4,
    "max_total_sessions": 12,
    "webhook_url": "",
}


async def get_global_settings() -> dict:
    """Get global settings from Redis, falling back to defaults."""
    r = redis_client.get_pool()
    raw = await r.get(REDIS_KEY)
    if raw:
        try:
            stored = json.loads(raw)
            return {**_DEFAULTS, **stored}
        except json.JSONDecodeError:
            pass

    # Migration: read from old key if new key doesn't exist
    old_raw = await r.get("settings:agent")
    if old_raw:
        try:
            old = json.loads(old_raw)
            return {
                "max_sessions": old.get("max_sessions", 4),
                "max_total_sessions": old.get("max_total_sessions", 12),
                "webhook_url": old.get("webhook_url", ""),
            }
        except json.JSONDecodeError:
            pass

    return {**_DEFAULTS}


# Keep old name as alias for callers that haven't been updated yet
async def get_agent_settings() -> dict:
    """Deprecated: use get_global_settings() or get_agent_settings_for_project()."""
    return await get_global_settings()


async def get_max_sessions() -> int:
    cfg = await get_global_settings()
    return cfg.get("max_sessions", 4)


async def get_gh_token() -> str:
    """Deprecated: gh_token is now per-project only. Returns empty string."""
    return ""


@router.get("/agent")
async def get_settings():
    cfg = await get_global_settings()
    return cfg


@router.put("/agent")
async def update_settings(body: dict):
    current = await get_global_settings()

    if "max_sessions" in body:
        current["max_sessions"] = max(1, min(20, int(body["max_sessions"])))

    if "max_total_sessions" in body:
        current["max_total_sessions"] = max(1, min(50, int(body["max_total_sessions"])))

    old_webhook_url = current.get("webhook_url", "")
    if "webhook_url" in body:
        current["webhook_url"] = body["webhook_url"].strip()

    r = redis_client.get_pool()
    await r.set(REDIS_KEY, json.dumps(current))

    # Auto-register webhooks for all projects when webhook_url changes
    new_webhook_url = current.get("webhook_url", "")
    if new_webhook_url and new_webhook_url != old_webhook_url:
        await _register_webhooks_for_all_projects(new_webhook_url)

    logger.info("Global settings updated: %s", current)
    return current


async def _register_webhooks_for_all_projects(webhook_url: str) -> None:
    """Register webhooks for all existing projects when webhook_url is set/changed."""
    from claude_hub.services.webhook_registration import register_webhook
    projects = await redis_client.list_projects()
    for project in projects:
        gh_token = project.get("gh_token", "")
        repo_url = project.get("repo_url", "")
        if not gh_token or not repo_url:
            continue
        result = register_webhook(repo_url, gh_token, webhook_url_override=webhook_url)
        logger.info("Webhook registration for %s: %s", repo_url, result)
        if result.get("webhook_id"):
            await redis_client.update_project_fields(
                project["id"], {"webhook_id": str(result["webhook_id"])}
            )


@router.post("/agent/test")
async def test_connection(body: dict):
    """Test if an API key works by making a minimal API call."""
    api_key = body.get("api_key", "")
    provider = body.get("provider", "anthropic")
    model = body.get("model", "")
    endpoint_url = body.get("endpoint_url", "")

    if not api_key:
        raise HTTPException(400, "No API key provided")

    # Don't test with masked value
    if "..." in api_key:
        raise HTTPException(400, "Cannot test with masked API key — re-enter the key")

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
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
        if "authentication" in err.lower() or "api key" in err.lower() or "unauthorized" in err.lower():
            raise HTTPException(401, f"Authentication failed: {err[:200]}")
        if "not found" in err.lower() or "does not exist" in err.lower():
            raise HTTPException(404, f"Model not found: {err[:200]}")
        raise HTTPException(502, f"Connection failed: {err[:200]}")
