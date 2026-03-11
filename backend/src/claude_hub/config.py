from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "CLAUDE_HUB_", "env_file": "../.env", "extra": "ignore"}

    # Server
    host: str = "0.0.0.0"
    port: int = 7700
    repo_url: str = ""
    base_branch: str = "main"
    max_sessions: int = 4
    claude_bin: str = "claude"
    log_level: str = "info"
    data_dir: str = "/tmp/claude-hub-data"
    redis_url: str = "redis://localhost:6379/0"
    merged_ttl_days: int = 7
    disallowed_tools: str = "Bash(curl:*),Bash(wget:*),Bash(ssh:*)"

    # Auth
    auth_enabled: bool = True
    auth_username: str = "admin"
    auth_password: str = "changeme"
    auth_secret: str = "change-this-to-a-random-string"
    auth_token_hours: int = 24
    dev_mode: bool = False  # Enable CORS for dev (frontend on different port)

    # GitHub
    gh_token: str = ""

    # TicketAgent
    anthropic_api_key: str = ""
    agent_model: str = "claude-sonnet-4-6"
    agent_enabled: bool = True
    agent_web_search: bool = True
    agent_web_fetch: bool = True
    agent_max_web_searches: int = 10
    agent_check_interval: int = 5
    agent_batch_size: int = 3
    agent_max_context_messages: int = 80
    agent_budget_per_ticket_usd: float = 5.00
    agent_budget_daily_usd: float = 50.00
    agent_budget_monthly_usd: float = 500.00


settings = Settings()
