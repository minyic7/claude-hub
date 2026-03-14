from datetime import datetime
from enum import Enum
from typing import Literal

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


# ─── PO Settings ─────────────────────────────────────────────────────────────

class POSettings(BaseModel):
    enabled: bool = False
    mode: Literal["full_auto", "semi_auto"] = "semi_auto"

    # Capacity controls
    max_active_tickets: int = 10
    max_pending_approval: int = 5
    max_new_per_cycle: int = 3

    # Timing
    report_interval_hours: int = 1

    # Scope
    deployment_type: Literal[
        "auto", "github_pages", "docker", "docs_only", "none"
    ] = "auto"
    docs_format: Literal["html", "md", "auto"] = "auto"

    # Git history context
    git_history_threshold: int = 10
    git_history_days: int = 7

    # LLM model configuration
    observe_model: str = "claude-sonnet-4-6"
    think_model: str = "claude-opus-4-6"
    think_budget_tokens: int = 8000
    compaction_model: str = "claude-sonnet-4-6"


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
    PO_PENDING = "po_pending"
    TODO = "todo"
    QUEUED = "queued"
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
    seq: int = 0  # Per-project sequential number (1, 2, 3...)
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

    # PO Agent
    po_proposed: bool = False
    po_rationale: str = ""

    # Cost
    agent_cost_usd: float = 0.0

    # Notes (append-only structured notes)
    notes: list[dict] = Field(default_factory=list)

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
