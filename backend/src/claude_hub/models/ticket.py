from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ─── Project ─────────────────────────────────────────────────────────────────

class Project(BaseModel):
    id: str
    name: str
    repo_url: str
    gh_token: str = ""
    base_branch: str = "main"
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str
    repo_url: str
    gh_token: str = ""
    base_branch: str = "main"


class ProjectUpdate(BaseModel):
    name: str | None = None
    repo_url: str | None = None
    gh_token: str | None = None
    base_branch: str | None = None


# ─── Ticket ──────────────────────────────────────────────────────────────────

class BranchType(str, Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    HOTFIX = "hotfix"
    CHORE = "chore"
    REFACTOR = "refactor"
    DOCS = "docs"
    TEST = "test"


class TicketStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    REVIEW = "review"
    MERGING = "merging"
    MERGED = "merged"
    FAILED = "failed"


class Ticket(BaseModel):
    id: str
    project_id: str
    title: str
    description: str = ""
    branch_type: BranchType
    branch: str
    repo_url: str
    base_branch: str = "main"
    status: TicketStatus = TicketStatus.TODO

    # Escalation
    blocked_question: str | None = None
    failed_reason: str | None = None

    # Source
    source: str = "ui"
    external_id: str | None = None
    metadata: dict = Field(default_factory=dict)

    # Dependencies
    depends_on: list[str] = Field(default_factory=list)

    # Git/PR
    clone_path: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    has_conflicts: bool = False

    # Session
    tmux_session: str | None = None

    # Priority (lower = higher priority)
    priority: int = 0
    archived: bool = False

    # Cost
    agent_cost_usd: float = 0.0

    # Timestamps
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status_changed_at: datetime | None = None


class TicketCreate(BaseModel):
    project_id: str
    title: str
    description: str = ""
    branch_type: BranchType = BranchType.FEATURE
    source: str = "ui"
    external_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class TicketUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    depends_on: list[str] | None = None
