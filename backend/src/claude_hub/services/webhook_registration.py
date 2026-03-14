"""Auto-register GitHub webhooks for projects."""

import json
import logging
import os
import re
import subprocess

from claude_hub.config import settings

logger = logging.getLogger(__name__)

# Events we want to receive
WEBHOOK_EVENTS = ["pull_request", "pull_request_review"]


def _parse_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """Extract owner/repo from a GitHub URL."""
    match = re.match(
        r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/.]+?)(?:\.git)?$",
        repo_url,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def delete_webhook(repo_url: str, gh_token: str, webhook_id: int) -> bool:
    """Delete a GitHub webhook by ID. Returns True on success."""
    parsed = _parse_owner_repo(repo_url)
    if not parsed or not gh_token:
        return False

    owner, repo = parsed
    env = {**os.environ, "GH_TOKEN": gh_token}
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/hooks/{webhook_id}",
         "--method", "DELETE"],
        capture_output=True, text=True, env=env,
    )
    if result.returncode == 0:
        logger.info("Deleted webhook %d for %s/%s", webhook_id, owner, repo)
        return True
    logger.warning("Failed to delete webhook %d for %s/%s: %s", webhook_id, owner, repo, result.stderr.strip())
    return False


def get_webhook_url() -> str:
    """Get webhook URL from Redis settings, falling back to env var."""
    # Try Redis settings first (async -> sync via run_in_executor not practical here)
    # So we read from env var / config as fallback
    return settings.webhook_url


def register_webhook(repo_url: str, gh_token: str, webhook_url_override: str = "") -> dict:
    """Register or update a GitHub webhook for the given repo.

    Returns:
        {"status": "created" | "exists" | "updated" | "skipped" | "error",
         "message": str, "webhook_id": int | None}
    """
    webhook_url = webhook_url_override or get_webhook_url()
    if not webhook_url:
        return {"status": "skipped", "message": "No webhook_url configured", "webhook_id": None}

    parsed = _parse_owner_repo(repo_url)
    if not parsed:
        return {"status": "error", "message": f"Cannot parse repo URL: {repo_url}", "webhook_id": None}

    owner, repo = parsed

    if not gh_token:
        return {"status": "skipped", "message": "No gh_token available", "webhook_id": None}

    env = {**os.environ, "GH_TOKEN": gh_token}

    # Check existing webhooks
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/hooks",
         "--jq", f'[.[] | select(.config.url == "{webhook_url}") | {{id: .id, events: .events, active: .active}}]'],
        capture_output=True, text=True, env=env,
    )

    if result.returncode == 0 and result.stdout.strip():
        try:
            existing = json.loads(result.stdout)
        except json.JSONDecodeError:
            existing = []

        if existing:
            hook = existing[0]
            hook_id = hook["id"]
            current_events = set(hook.get("events", []))
            needed_events = set(WEBHOOK_EVENTS)

            if needed_events.issubset(current_events) and hook.get("active"):
                return {"status": "exists", "message": f"Webhook already registered (id: {hook_id})", "webhook_id": hook_id}

            # Update to add missing events
            all_events = list(current_events | needed_events)
            events_json = ",".join(f'"{e}"' for e in all_events)
            update_result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/hooks/{hook_id}",
                 "--method", "PATCH",
                 "--input", "-"],
                input=f'{{"events": [{events_json}], "active": true}}',
                capture_output=True, text=True, env=env,
            )
            if update_result.returncode == 0:
                return {"status": "updated", "message": f"Webhook updated with events: {all_events}", "webhook_id": hook_id}
            return {"status": "error", "message": f"Failed to update webhook: {update_result.stderr.strip()}", "webhook_id": None}

    # Create new webhook
    payload = json.dumps({
        "name": "web",
        "active": True,
        "events": WEBHOOK_EVENTS,
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "insecure_ssl": "0",
        },
    })

    create_result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/hooks",
         "--method", "POST", "--input", "-"],
        input=payload,
        capture_output=True, text=True, env=env,
    )

    if create_result.returncode == 0:
        logger.info("Webhook registered for %s/%s -> %s", owner, repo, webhook_url)
        # Parse webhook ID from response
        created_id = None
        try:
            created_id = json.loads(create_result.stdout).get("id")
        except (json.JSONDecodeError, AttributeError):
            pass
        return {"status": "created", "message": f"Webhook created for {owner}/{repo}", "webhook_id": created_id}

    error = create_result.stderr.strip()
    # GitHub returns 422 if webhook already exists (race condition)
    if "already exists" in error.lower() or "Hook already exists" in error:
        return {"status": "exists", "message": "Webhook already registered", "webhook_id": None}

    logger.error("Failed to register webhook for %s/%s: %s", owner, repo, error)
    return {"status": "error", "message": f"Failed to create webhook: {error}", "webhook_id": None}
