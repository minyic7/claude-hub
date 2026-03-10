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


def verify_agent_work(
    clone_path: str,
    branch: str,
    base_branch: str,
) -> VerifyResult:
    """Verify that the agent produced commits and a PR on the expected branch."""

    # 1. Check remote branch exists
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch],
        cwd=clone_path, capture_output=True, text=True,
    )
    if branch not in result.stdout:
        return VerifyResult(
            passed=False,
            reason=f"Branch '{branch}' not found on remote",
        )

    # 2. Check commits ahead of base
    result = subprocess.run(
        ["git", "log", f"origin/{base_branch}..origin/{branch}", "--oneline"],
        cwd=clone_path, capture_output=True, text=True,
    )
    commits = [line for line in result.stdout.strip().split("\n") if line]
    if not commits:
        return VerifyResult(
            passed=False,
            reason=f"No commits ahead of {base_branch}",
        )

    # 3. Check for PR
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
