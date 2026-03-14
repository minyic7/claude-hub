"""Check CI (GitHub Actions) status on a branch before merging."""

import asyncio
import json
import logging
import os
import subprocess

from claude_hub import redis_client
from claude_hub.models.ticket import TicketStatus
from claude_hub.services.ticket_service import transition

logger = logging.getLogger(__name__)

# How long to wait for CI to complete before giving up
CI_POLL_TIMEOUT = 600  # 10 minutes
CI_POLL_INTERVAL = 15  # seconds


def _run_gh(args: list[str], cwd: str, gh_token: str = "") -> subprocess.CompletedProcess:
    env = None
    if gh_token:
        env = {**os.environ, "GH_TOKEN": gh_token}
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)


def get_ci_status(clone_path: str, branch: str, gh_token: str = "", pr_number: int = 0) -> dict:
    """Get CI check status for a branch.

    Returns:
        {
            "status": "passed" | "failed" | "pending" | "no_ci",
            "checks": [...],
            "summary": "human readable summary"
        }
    """
    pr_ref = str(pr_number) if pr_number else branch

    # gh pr checks --json fields vary by gh version; use the modern field names
    result = _run_gh(
        ["gh", "pr", "checks", pr_ref, "--json", "name,state,bucket,link"],
        cwd=clone_path, gh_token=gh_token,
    )

    if result.returncode != 0:
        # No PR or no checks configured — try commit status API (REST, stable fields)
        result2 = _run_gh(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{branch}/check-runs",
             "--jq", ".check_runs | map({name, status, conclusion, html_url})"],
            cwd=clone_path, gh_token=gh_token,
        )
        if result2.returncode != 0 or not result2.stdout.strip():
            return {"status": "no_ci", "checks": [], "summary": "No CI checks configured"}

        try:
            checks = json.loads(result2.stdout)
        except json.JSONDecodeError:
            return {"status": "no_ci", "checks": [], "summary": "No CI checks configured"}

        if not checks:
            return {"status": "no_ci", "checks": [], "summary": "No CI checks configured"}

        return _evaluate_checks(checks, key_status="status", key_conclusion="conclusion")

    # Parse PR checks output
    try:
        checks = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "no_ci", "checks": [], "summary": "Could not parse CI status"}

    if not checks:
        return {"status": "no_ci", "checks": [], "summary": "No CI checks configured"}

    # gh pr checks uses "state" for status and "bucket" for pass/fail/pending
    return _evaluate_checks(checks, key_status="state", key_conclusion="bucket")


def _evaluate_checks(checks: list[dict], key_status: str, key_conclusion: str) -> dict:
    """Evaluate a list of checks and return overall status."""
    pending = []
    failed = []
    passed = []

    for check in checks:
        status = (check.get(key_status) or "").upper()
        conclusion = (check.get(key_conclusion) or "").upper()
        name = check.get("name", "unknown")

        # "bucket" field from `gh pr checks` uses PASS/FAIL/PENDING
        # "conclusion" from REST API uses SUCCESS/FAILURE/etc.
        # "status" from REST API uses COMPLETED/IN_PROGRESS/etc.
        if conclusion in ("PASS", "SUCCESS"):
            passed.append(name)
        elif conclusion in ("FAIL", "FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"):
            failed.append(name)
        elif conclusion in ("PENDING",) or status in ("IN_PROGRESS", "QUEUED", "PENDING", "WAITING", "REQUESTED"):
            pending.append(name)
        elif status in ("COMPLETED", "SUCCESS", "PASS"):
            passed.append(name)
        else:
            pending.append(name)

    if failed:
        summary = f"CI failed: {', '.join(failed)}"
        return {"status": "failed", "checks": checks, "summary": summary}
    if pending:
        summary = f"CI running: {', '.join(pending)}"
        return {"status": "pending", "checks": checks, "summary": summary}

    summary = f"All {len(passed)} check(s) passed"
    return {"status": "passed", "checks": checks, "summary": summary}


def get_failed_log(clone_path: str, gh_token: str = "", max_lines: int = 80) -> str:
    """Fetch the failed CI run log for the most recent failed workflow run."""
    # Find the most recent failed run
    result = _run_gh(
        ["gh", "run", "list", "--status", "failure", "--limit", "1",
         "--json", "databaseId,name", "--jq", ".[0].databaseId"],
        cwd=clone_path, gh_token=gh_token,
    )
    run_id = result.stdout.strip()
    if not run_id:
        return ""

    # Get the failed log
    result = _run_gh(
        ["gh", "run", "view", run_id, "--log-failed"],
        cwd=clone_path, gh_token=gh_token,
    )
    if result.returncode != 0:
        return ""

    log = result.stdout.strip()
    # Truncate to last N lines (the error is usually at the end)
    lines = log.split("\n")
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


async def merge_pr(ticket_id: str, clone_path: str, pr_number: int, gh_token: str = "") -> None:
    """Actually merge the PR on GitHub."""
    env = None
    if gh_token:
        env = {**os.environ, "GH_TOKEN": gh_token}

    # Mark PR as ready (in case it's a draft)
    subprocess.run(
        ["gh", "pr", "ready", str(pr_number)],
        cwd=clone_path, capture_output=True, text=True, env=env,
    )
    # Merge PR
    result = subprocess.run(
        ["gh", "pr", "merge", str(pr_number), "--squash", "--delete-branch"],
        cwd=clone_path, capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GitHub merge failed: {result.stderr.strip()}")


async def wait_for_ci_and_merge(
    ticket_id: str,
    clone_path: str,
    branch: str,
    pr_number: int,
    gh_token: str = "",
) -> None:
    """Background task: poll CI status and merge when passed."""
    from datetime import datetime, timezone
    from claude_hub.routers.ws import broadcast
    from claude_hub.services import clone_manager

    logger.info("Waiting for CI on ticket %s (branch: %s)", ticket_id, branch)

    elapsed = 0
    while elapsed < CI_POLL_TIMEOUT:
        await asyncio.sleep(CI_POLL_INTERVAL)
        elapsed += CI_POLL_INTERVAL

        ci = get_ci_status(clone_path, branch, gh_token, pr_number=pr_number)
        logger.info("CI status for %s: %s", ticket_id, ci["summary"])

        if ci["status"] == "passed":
            try:
                from claude_hub.services import session_manager
                from claude_hub.routers.tickets import process_queue
                await merge_pr(ticket_id, clone_path, pr_number, gh_token)
                updated = await transition(
                    ticket_id, TicketStatus.MERGED,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                session_manager.cleanup_session(ticket_id)
                clone_manager.cleanup_clone(ticket_id)
                await redis_client.update_ticket_fields(ticket_id, {"clone_path": "", "tmux_session": ""})
                updated = await redis_client.get_ticket(ticket_id)
                await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
                logger.info("CI passed, merged ticket %s", ticket_id)
                await process_queue()
            except Exception as e:
                logger.error("Merge failed for %s: %s", ticket_id, e)
                updated = await transition(ticket_id, TicketStatus.FAILED, failed_reason=str(e))
                await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
                await process_queue()
            return

        if ci["status"] == "failed":
            from claude_hub.routers.tickets import process_queue
            # Fetch detailed failure logs
            fail_log = get_failed_log(clone_path, gh_token)
            reason = ci["summary"]
            if fail_log:
                reason = f"{reason}\n\n--- CI Log (last 80 lines) ---\n{fail_log}"
            updated = await transition(ticket_id, TicketStatus.FAILED, failed_reason=reason)
            await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
            logger.warning("CI failed for %s: %s", ticket_id, ci["summary"])
            await process_queue()
            return

    # Timeout
    from claude_hub.routers.tickets import process_queue
    reason = f"CI did not complete within {CI_POLL_TIMEOUT}s"
    updated = await transition(ticket_id, TicketStatus.FAILED, failed_reason=reason)
    await broadcast({"type": "ticket_updated", "ticket_id": ticket_id, "data": updated})
    logger.warning("CI timeout for %s", ticket_id)
    await process_queue()
