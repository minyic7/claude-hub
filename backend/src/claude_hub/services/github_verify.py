import json
import logging
import subprocess

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class VerifyResult(BaseModel):
    passed: bool
    reason: str
    pr_url: str | None = None
    pr_number: int | None = None
    commits_count: int = 0


def ensure_pushed(
    clone_path: str,
    branch: str,
    base_branch: str,
    gh_token: str = "",
) -> list[str]:
    """Safety net: commit any uncommitted changes, push, and create PR if missing.

    Returns list of actions taken (for logging).
    """
    actions: list[str] = []
    env = None
    if gh_token:
        import os
        env = {**os.environ, "GH_TOKEN": gh_token}

    # 1. Stage + commit any uncommitted changes
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=clone_path, capture_output=True, text=True,
    )
    if status.stdout.strip():
        subprocess.run(["git", "add", "-A"], cwd=clone_path, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", "chore: auto-commit remaining changes"],
            cwd=clone_path, capture_output=True, text=True,
        )
        if result.returncode == 0:
            actions.append("committed uncommitted changes")

    # 2. Check if local is ahead of remote and push
    ahead = subprocess.run(
        ["git", "log", f"origin/{branch}..{branch}", "--oneline"],
        cwd=clone_path, capture_output=True, text=True,
    )
    unpushed = [l for l in ahead.stdout.strip().split("\n") if l]
    if unpushed:
        result = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=clone_path, capture_output=True, text=True,
        )
        if result.returncode == 0:
            actions.append(f"pushed {len(unpushed)} unpushed commit(s)")
        else:
            actions.append(f"push failed: {result.stderr.strip()}")

    # 3. Create PR if none exists
    pr_check = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--json", "number", "--limit", "1"],
        cwd=clone_path, capture_output=True, text=True, env=env,
    )
    has_pr = False
    if pr_check.returncode == 0:
        try:
            prs = json.loads(pr_check.stdout)
            has_pr = len(prs) > 0
        except json.JSONDecodeError:
            pass

    if not has_pr:
        # Check we actually have commits to make a PR for
        diff = subprocess.run(
            ["git", "log", f"origin/{base_branch}..origin/{branch}", "--oneline"],
            cwd=clone_path, capture_output=True, text=True,
        )
        if diff.stdout.strip():
            # Get first commit message as PR title
            first_msg = subprocess.run(
                ["git", "log", f"origin/{base_branch}..origin/{branch}",
                 "--reverse", "--format=%s", "-1"],
                cwd=clone_path, capture_output=True, text=True,
            )
            title = first_msg.stdout.strip() or branch
            result = subprocess.run(
                ["gh", "pr", "create", "--base", base_branch, "--head", branch,
                 "--title", title, "--body", "Auto-created by Claude Hub"],
                cwd=clone_path, capture_output=True, text=True, env=env,
            )
            if result.returncode == 0:
                actions.append(f"created PR: {result.stdout.strip()}")
            else:
                actions.append(f"PR creation failed: {result.stderr.strip()}")

    return actions


def verify_agent_work(
    clone_path: str,
    branch: str,
    base_branch: str,
) -> VerifyResult:
    """Verify that the agent produced commits and a PR on the expected branch."""

    # 1. Check commits ahead of base
    result = subprocess.run(
        ["git", "log", f"origin/{base_branch}..origin/{branch}", "--oneline"],
        cwd=clone_path, capture_output=True, text=True,
    )
    commits = [line for line in result.stdout.strip().split("\n") if line]
    if not commits:
        return VerifyResult(
            passed=False,
            reason=f"No commits ahead of {base_branch} — agent did not make changes",
        )

    # 2. Check for PR
    pr_url = None
    pr_number = None
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--json", "number,url,state", "--limit", "1"],
            cwd=clone_path, capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            prs = json.loads(result.stdout)
            if prs:
                pr_url = prs[0].get("url")
                pr_number = prs[0].get("number")
    except Exception as e:
        logger.warning("Could not check PRs: %s", e)

    if not pr_url:
        return VerifyResult(
            passed=False,
            reason=f"Branch has {len(commits)} commit(s) but no PR found",
            commits_count=len(commits),
        )

    return VerifyResult(
        passed=True,
        reason=f"{len(commits)} commit(s), PR #{pr_number}",
        pr_url=pr_url,
        pr_number=pr_number,
        commits_count=len(commits),
    )
