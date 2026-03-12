import hashlib
import logging
import os
import shutil
import subprocess

from claude_hub.config import settings

logger = logging.getLogger(__name__)


def _reference_dir() -> str:
    return os.path.join(settings.data_dir, "references")


def _clones_dir() -> str:
    return os.path.join(settings.data_dir, "clones")


def _repo_hash(repo_url: str) -> str:
    return hashlib.sha256(repo_url.encode()).hexdigest()[:12]


def _inject_token(repo_url: str, token: str = "") -> str:
    token = token or settings.gh_token
    if not token:
        return repo_url
    if repo_url.startswith("https://github.com/"):
        return repo_url.replace(
            "https://github.com/",
            f"https://x-access-token:{token}@github.com/",
        )
    return repo_url


def ensure_reference(repo_url: str, gh_token: str = "") -> str:
    ref_dir = _reference_dir()
    os.makedirs(ref_dir, exist_ok=True)

    bare_path = os.path.join(ref_dir, f"{_repo_hash(repo_url)}.git")
    authed_url = _inject_token(repo_url, gh_token)

    if os.path.exists(bare_path):
        logger.info("Updating reference clone: %s", bare_path)
        subprocess.run(
            ["git", "fetch", "--all"],
            cwd=bare_path, check=True, capture_output=True,
        )
    else:
        logger.info("Creating reference clone: %s → %s", repo_url, bare_path)
        subprocess.run(
            ["git", "clone", "--bare", authed_url, bare_path],
            check=True, capture_output=True,
        )

    return bare_path


def clone_for_ticket(
    repo_url: str,
    ticket_id: str,
    branch: str,
    base_branch: str = "main",
    gh_token: str = "",
) -> str:
    clone_dir = os.path.join(_clones_dir(), ticket_id[:12])
    authed_url = _inject_token(repo_url, gh_token)

    if os.path.exists(clone_dir):
        logger.info("Reusing existing clone: %s", clone_dir)
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=clone_dir, check=True, capture_output=True,
        )
    else:
        os.makedirs(os.path.dirname(clone_dir), exist_ok=True)

        # Try reference clone first
        ref_path = os.path.join(_reference_dir(), f"{_repo_hash(repo_url)}.git")
        if os.path.exists(ref_path):
            logger.info("Cloning with reference: %s", ref_path)
            subprocess.run(
                ["git", "clone", "--reference", ref_path, authed_url, clone_dir],
                check=True, capture_output=True,
            )
        else:
            logger.info("Cloning fresh: %s", repo_url)
            subprocess.run(
                ["git", "clone", authed_url, clone_dir],
                check=True, capture_output=True,
            )

    # Checkout branch
    # Check if remote branch exists
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch],
        cwd=clone_dir, capture_output=True, text=True,
    )
    if branch in result.stdout:
        logger.info("Checking out existing remote branch: %s", branch)
        subprocess.run(
            ["git", "checkout", "-B", branch, f"origin/{branch}"],
            cwd=clone_dir, check=True, capture_output=True,
        )
    else:
        logger.info("Creating new branch: %s from origin/%s", branch, base_branch)
        subprocess.run(
            ["git", "checkout", "-B", branch, f"origin/{base_branch}"],
            cwd=clone_dir, check=True, capture_output=True,
        )

    # Ensure token in push URL
    subprocess.run(
        ["git", "remote", "set-url", "origin", authed_url],
        cwd=clone_dir, check=True, capture_output=True,
    )

    # Push branch to reserve it on remote (even if empty)
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=clone_dir, capture_output=True,
    )

    return clone_dir


def cleanup_clone(ticket_id: str) -> None:
    clone_dir = os.path.join(_clones_dir(), ticket_id[:12])
    if os.path.exists(clone_dir):
        shutil.rmtree(clone_dir)
        logger.info("Cleaned up clone: %s", clone_dir)
