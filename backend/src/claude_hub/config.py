from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "CLAUDE_HUB_", "env_file": "../.env", "extra": "ignore"}

    # Server
    host: str = "0.0.0.0"
    port: int = 7700
    repo_url: str = ""
    base_branch: str = "main"
    claude_bin: str = "claude"
    log_level: str = "info"
    data_dir: str = "/tmp/claude-hub-data"
    redis_url: str = "redis://localhost:6379/0"
    merged_ttl_days: int = 7

    # Build metadata
    build_sha: str = "dev"

    # Auth
    auth_enabled: bool = True
    auth_username: str = "minyic"
    auth_password: str = "minyic"
    auth_secret: str = "change-this-to-a-random-string"
    auth_token_hours: int = 24
    dev_mode: bool = False  # Enable CORS for dev (frontend on different port)

    # Settings below are managed via Settings UI (stored in Redis).
    # Values here are only used as initial defaults before first UI save.
    max_sessions: int = 4
    max_total_sessions: int = 12
    gh_token: str = ""
    agent_check_interval: int = 5


settings = Settings()
