import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_roles_cache: dict | None = None


def _load_roles() -> dict:
    global _roles_cache
    if _roles_cache is not None:
        return _roles_cache

    roles_path = Path(__file__).parent.parent / "templates" / "roles.yaml"
    if not roles_path.exists():
        logger.warning("roles.yaml not found at %s", roles_path)
        return {}

    with open(roles_path) as f:
        data = yaml.safe_load(f)

    _roles_cache = data.get("roles", {})
    return _roles_cache


def get_role_prompt(role: str, branch: str) -> str:
    roles = _load_roles()
    role_def = roles.get(role)
    if not role_def:
        return ""
    prompt = role_def.get("system_prompt", "")
    return prompt.replace("{branch}", branch)


def get_role_info(role: str) -> dict | None:
    roles = _load_roles()
    return roles.get(role)
