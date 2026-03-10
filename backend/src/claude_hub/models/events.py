from pydantic import BaseModel


class ActivityEvent(BaseModel):
    timestamp: str
    source: str  # "claude_code" | "ticket_agent"
    type: str  # "thinking" | "tool_use" | "tool_result" | "intervention" | "decision" | "info" | "warning" | "error"
    summary: str


class WSEvent(BaseModel):
    type: str
    ticket_id: str | None = None
    data: dict
