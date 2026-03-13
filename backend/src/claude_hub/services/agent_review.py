"""Agent code review: TicketAgent reviews the PR diff before marking ready for human review."""

import json
import logging
import os
import subprocess

import anthropic
import openai

from claude_hub import redis_client
from claude_hub.routers.ws import broadcast
from claude_hub.services import cost_tracker

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = """You are a senior engineer doing a code review on a PR.
You will be given the PR diff and the original ticket description.

Review the code for:
1. **Correctness** — Does it do what the ticket asks? Any bugs?
2. **Security** — Any vulnerabilities (injection, auth bypass, secrets in code)?
3. **Quality** — Clean code, good naming, no dead code?
4. **Completeness** — All requirements addressed? Edge cases handled?

Respond with a JSON object (and NOTHING else):
{
  "verdict": "approve" | "reject",
  "scores": {
    "correctness": 1-10,
    "security": 1-10,
    "quality": 1-10,
    "completeness": 1-10
  },
  "summary": "1-2 sentence overall assessment",
  "issues": [
    {"severity": "critical|major|minor", "file": "path", "line": 0, "description": "..."}
  ],
  "feedback": "If rejected, specific instructions for what to fix (used as task for new session)"
}

Rules:
- Only reject for critical or major issues. Minor issues = approve with notes.
- Be concise. The feedback field is sent directly to Claude Code as instructions.
- If approving, feedback can be empty string.
- If the diff is truncated, note this in your summary and lower confidence in completeness score.
  You can only review what you can see — do NOT reject based on what might be in the truncated portion.
- ONLY output valid JSON. No markdown fences, no explanation."""


def _get_diff(clone_path: str, base_branch: str) -> str:
    """Get the diff between current branch and base branch."""
    try:
        # Fetch to make sure we have latest
        subprocess.run(["git", "fetch", "origin"], cwd=clone_path, capture_output=True)
        result = subprocess.run(
            ["git", "diff", f"origin/{base_branch}...HEAD", "--stat"],
            cwd=clone_path, capture_output=True, text=True,
        )
        stat = result.stdout

        result = subprocess.run(
            ["git", "diff", f"origin/{base_branch}...HEAD"],
            cwd=clone_path, capture_output=True, text=True,
        )
        diff = result.stdout

        # Truncate very large diffs
        if len(diff) > 50000:
            diff = diff[:50000] + "\n\n... (diff truncated at 50KB) ..."

        return f"## Diff Stats\n{stat}\n\n## Full Diff\n{diff}"
    except Exception as e:
        return f"Error getting diff: {e}"


async def review_pr(ticket_id: str, ticket: dict, agent_settings: dict | None = None) -> dict:
    """Run agent code review on a ticket's PR. Returns the review result dict."""
    cfg = agent_settings or {}
    provider = cfg.get("provider", "anthropic")
    model = cfg.get("model", "claude-haiku-4-5-20251001")
    api_key = cfg.get("api_key", "")

    clone_path = ticket.get("clone_path", "")
    base_branch = ticket.get("base_branch", "main")
    diff = _get_diff(clone_path, base_branch)

    if not diff or "Error getting diff" in diff:
        return {
            "verdict": "approve",
            "scores": {"correctness": 5, "security": 5, "quality": 5, "completeness": 5},
            "summary": "Could not retrieve diff, auto-approving for human review.",
            "issues": [],
            "feedback": "",
        }

    user_message = (
        f"## Ticket\n"
        f"**Title:** {ticket.get('title', '')}\n"
        f"**Description:** {ticket.get('description', '')}\n\n"
        f"{diff}"
    )

    # Record activity: review started
    await _record_activity(ticket_id, "review", "Starting automated code review...")

    # Budget check
    ok, reason = await cost_tracker.can_spend(ticket_id, 0.01)
    if not ok:
        logger.warning("Budget exceeded for review %s: %s", ticket_id, reason)
        return {
            "verdict": "approve",
            "scores": {"correctness": 5, "security": 5, "quality": 5, "completeness": 5},
            "summary": f"Budget exceeded ({reason}), auto-approving for human review.",
            "issues": [],
            "feedback": "",
        }

    try:
        if provider == "anthropic":
            result = await _call_anthropic(api_key, model, user_message, ticket_id)
        else:
            endpoint_url = cfg.get("endpoint_url", "")
            result = await _call_openai(api_key, model, endpoint_url, user_message, ticket_id)
    except Exception as e:
        logger.error("Agent review failed for %s: %s", ticket_id, e)
        return {
            "verdict": "approve",
            "scores": {"correctness": 5, "security": 5, "quality": 5, "completeness": 5},
            "summary": f"Review error: {e}. Auto-approving for human review.",
            "issues": [],
            "feedback": "",
        }

    # Append review round to history array
    from datetime import datetime, timezone
    ticket_current = await redis_client.get_ticket(ticket_id)
    history = ticket_current.get("agent_review") or []
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            history = []
    if not isinstance(history, list):
        # Migrate legacy single-object to array
        history = [history]
    round_number = len(history) + 1
    entry = {
        "round": round_number,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    history.append(entry)
    await redis_client.update_ticket_fields(ticket_id, {
        "agent_review": json.dumps(history),
    })

    # Record activity
    verdict = result.get("verdict", "approve")
    summary = result.get("summary", "")
    issues = result.get("issues", [])
    critical = sum(1 for i in issues if i.get("severity") == "critical")
    major = sum(1 for i in issues if i.get("severity") == "major")

    if verdict == "approve":
        await _record_activity(ticket_id, "review",
                               f"Review APPROVED: {summary} (issues: {critical} critical, {major} major)")
    else:
        await _record_activity(ticket_id, "review",
                               f"Review REJECTED: {summary} (issues: {critical} critical, {major} major)")

    return result


async def _call_anthropic(api_key: str, model: str, user_message: str, ticket_id: str) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=REVIEW_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # Record cost
    usage = response.usage
    cost = cost_tracker.calculate_cost({
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }, model)
    await cost_tracker.record_spend(ticket_id, cost, tokens=usage.input_tokens + usage.output_tokens)

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    return _parse_review(text)


async def _call_openai(api_key: str, model: str, endpoint_url: str,
                       user_message: str, ticket_id: str) -> dict:
    kwargs = {"api_key": api_key}
    if endpoint_url:
        kwargs["base_url"] = endpoint_url
    client = openai.OpenAI(**kwargs)

    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    usage = response.usage
    cost = cost_tracker.calculate_cost({
        "input_tokens": usage.prompt_tokens or 0,
        "output_tokens": usage.completion_tokens or 0,
        "cache_read_input_tokens": 0,
    }, model)
    await cost_tracker.record_spend(ticket_id, cost, tokens=(usage.prompt_tokens or 0) + (usage.completion_tokens or 0))

    text = response.choices[0].message.content or ""
    return _parse_review(text)


def _parse_review(text: str) -> dict:
    """Parse LLM response into review dict, with fallback."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines)

    try:
        result = json.loads(text)
        # Validate required fields
        if "verdict" not in result:
            result["verdict"] = "approve"
        if "scores" not in result:
            result["scores"] = {"correctness": 5, "security": 5, "quality": 5, "completeness": 5}
        if "summary" not in result:
            result["summary"] = ""
        if "issues" not in result:
            result["issues"] = []
        if "feedback" not in result:
            result["feedback"] = ""
        return result
    except json.JSONDecodeError:
        logger.warning("Failed to parse review JSON: %s", text[:200])
        return {
            "verdict": "approve",
            "scores": {"correctness": 5, "security": 5, "quality": 5, "completeness": 5},
            "summary": f"Could not parse review response. Auto-approving. Raw: {text[:200]}",
            "issues": [],
            "feedback": "",
        }


async def _record_activity(ticket_id: str, event_type: str, summary: str) -> None:
    from datetime import datetime, timezone
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "ticket_agent",
        "type": event_type,
        "summary": summary,
    }
    await redis_client.append_activity(ticket_id, event)
    await broadcast({
        "type": "activity",
        "ticket_id": ticket_id,
        "data": event,
    })
