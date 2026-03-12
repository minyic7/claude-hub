import json
from datetime import datetime

import redis.asyncio as redis

from claude_hub.config import settings

pool: redis.Redis | None = None


async def connect() -> None:
    global pool
    pool = redis.from_url(settings.redis_url, decode_responses=True)
    await pool.ping()


async def disconnect() -> None:
    global pool
    if pool:
        await pool.aclose()
        pool = None


def _r() -> redis.Redis:
    assert pool is not None, "Redis not connected"
    return pool


async def ping() -> bool:
    return await _r().ping()


def get_pool() -> redis.Redis:
    """Public access to Redis pool for services that need direct commands."""
    return _r()


# ─── Project helpers ─────────────────────────────────────────────────────────

async def save_project(project_dict: dict) -> None:
    r = _r()
    pid = project_dict["id"]
    await r.hset(f"project:{pid}", mapping={
        k: str(v) if v is not None else ""
        for k, v in project_dict.items()
    })
    await r.sadd("projects:all", pid)


async def get_project(project_id: str) -> dict | None:
    r = _r()
    data = await r.hgetall(f"project:{project_id}")
    if not data:
        return None
    return data


async def list_projects() -> list[dict]:
    r = _r()
    ids = await r.smembers("projects:all")
    projects = []
    for pid in ids:
        p = await get_project(pid)
        if p:
            projects.append(p)
    return projects


async def update_project_fields(project_id: str, fields: dict) -> None:
    r = _r()
    mapping = {k: str(v) if v is not None else "" for k, v in fields.items()}
    await r.hset(f"project:{project_id}", mapping=mapping)


async def delete_project(project_id: str) -> bool:
    r = _r()
    if not await r.exists(f"project:{project_id}"):
        return False
    # Delete all project tickets
    ticket_ids = await r.smembers(f"project:{project_id}:tickets")
    for tid in ticket_ids:
        await delete_ticket(tid)
    await r.delete(f"project:{project_id}")
    await r.delete(f"project:{project_id}:tickets")
    await r.srem("projects:all", project_id)
    return True


# ─── Ticket helpers ──────────────────────────────────────────────────────────

async def save_ticket(ticket_dict: dict) -> None:
    r = _r()
    ticket_id = ticket_dict["id"]
    await r.hset(f"ticket:{ticket_id}", mapping={
        k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) if v is not None else ""
        for k, v in ticket_dict.items()
    })
    await r.sadd("tickets:all", ticket_id)
    status = ticket_dict.get("status", "todo")
    await r.sadd(f"tickets:by_status:{status}", ticket_id)
    # Track ticket under its project
    project_id = ticket_dict.get("project_id")
    if project_id:
        await r.sadd(f"project:{project_id}:tickets", ticket_id)


async def get_ticket(ticket_id: str) -> dict | None:
    r = _r()
    data = await r.hgetall(f"ticket:{ticket_id}")
    if not data:
        return None
    return _deserialize_ticket(data)


async def list_tickets(status: str | None = None) -> list[dict]:
    r = _r()
    if status:
        ids = await r.smembers(f"tickets:by_status:{status}")
    else:
        ids = await r.smembers("tickets:all")

    tickets = []
    for ticket_id in ids:
        t = await get_ticket(ticket_id)
        if t:
            tickets.append(t)
    return tickets


async def delete_ticket(ticket_id: str) -> bool:
    r = _r()
    data = await r.hgetall(f"ticket:{ticket_id}")
    if not data:
        return False
    status = data.get("status", "todo")
    project_id = data.get("project_id")
    await r.srem(f"tickets:by_status:{status}", ticket_id)
    await r.srem("tickets:all", ticket_id)
    if project_id:
        await r.srem(f"project:{project_id}:tickets", ticket_id)
    await r.delete(f"ticket:{ticket_id}")
    await r.delete(f"ticket:{ticket_id}:activity")
    return True


async def list_tickets_by_project(project_id: str, status: str | None = None) -> list[dict]:
    r = _r()
    ids = await r.smembers(f"project:{project_id}:tickets")
    tickets = []
    for ticket_id in ids:
        t = await get_ticket(ticket_id)
        if t and (status is None or t.get("status") == status):
            tickets.append(t)
    return tickets


async def update_ticket_status(ticket_id: str, old_status: str, new_status: str) -> None:
    r = _r()
    await r.srem(f"tickets:by_status:{old_status}", ticket_id)
    await r.sadd(f"tickets:by_status:{new_status}", ticket_id)
    await r.hset(f"ticket:{ticket_id}", "status", new_status)


async def update_ticket_fields(ticket_id: str, fields: dict) -> None:
    r = _r()
    mapping = {
        k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) if v is not None else ""
        for k, v in fields.items()
    }
    await r.hset(f"ticket:{ticket_id}", mapping=mapping)


# ─── Ticket sequence helpers ─────────────────────────────────────────────────

async def next_ticket_seq(project_id: str) -> int:
    """Atomically increment and return the next per-project ticket sequence number."""
    r = _r()
    return int(await r.incr(f"project:{project_id}:ticket_seq"))


async def backfill_ticket_seqs(project_id: str) -> None:
    """Assign seq numbers to existing tickets that have seq=0, sorted by created_at.

    Also sets the counter so future tickets continue from the max.
    """
    r = _r()
    # Check if backfill already done (counter exists)
    counter = await r.get(f"project:{project_id}:ticket_seq")
    if counter is not None:
        return

    ids = await r.smembers(f"project:{project_id}:tickets")
    if not ids:
        return

    # Load tickets and sort by created_at
    tickets = []
    for tid in ids:
        data = await r.hgetall(f"ticket:{tid}")
        if data:
            tickets.append(data)
    tickets.sort(key=lambda t: t.get("created_at", ""))

    # Assign seq 1, 2, 3... and set counter
    for i, t in enumerate(tickets, start=1):
        await r.hset(f"ticket:{t['id']}", "seq", str(i))

    # Set counter to highest assigned seq
    if tickets:
        await r.set(f"project:{project_id}:ticket_seq", str(len(tickets)))


# ─── Activity helpers ────────────────────────────────────────────────────────

async def append_activity(ticket_id: str, event: dict) -> None:
    r = _r()
    await r.rpush(f"ticket:{ticket_id}:activity", json.dumps(event))
    await r.ltrim(f"ticket:{ticket_id}:activity", -500, -1)


async def get_activity(ticket_id: str, since: int = 0) -> list[dict]:
    r = _r()
    raw = await r.lrange(f"ticket:{ticket_id}:activity", since, -1)
    return [json.loads(item) for item in raw]


async def get_recent_activity(ticket_id: str, count: int = 50) -> list[dict]:
    """Get the most recent N activity events for a ticket."""
    r = _r()
    raw = await r.lrange(f"ticket:{ticket_id}:activity", -count, -1)
    return [json.loads(item) for item in raw]


# ─── Queue helpers ──────────────────────────────────────────────────────────

QUEUE_KEY = "tickets:queue"


async def enqueue_tickets(ticket_ids: list[str]) -> int:
    """Add ticket IDs to the queue sorted set. Score = current max + position."""
    r = _r()
    existing = await r.zrange(QUEUE_KEY, -1, -1, withscores=True)
    base_score = int(existing[0][1]) + 1 if existing else 1
    mapping = {tid: base_score + i for i, tid in enumerate(ticket_ids)}
    await r.zadd(QUEUE_KEY, mapping)  # type: ignore[arg-type]
    return len(mapping)


async def dequeue_ticket() -> str | None:
    """Pop the lowest-score (oldest) ticket from the queue."""
    r = _r()
    result = await r.zpopmin(QUEUE_KEY, count=1)
    if result:
        return result[0][0]
    return None


async def remove_from_queue(ticket_id: str) -> None:
    r = _r()
    await r.zrem(QUEUE_KEY, ticket_id)


async def get_queue() -> list[str]:
    """Get all queued ticket IDs in order."""
    r = _r()
    return await r.zrange(QUEUE_KEY, 0, -1)


async def get_queue_position(ticket_id: str) -> int | None:
    """Get 0-based position in queue, or None if not queued."""
    r = _r()
    rank = await r.zrank(QUEUE_KEY, ticket_id)
    return rank


# ─── Cost helpers ────────────────────────────────────────────────────────────

async def get_cost_summary() -> dict:
    r = _r()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    daily = await r.get(f"agent:cost:daily:{today}")
    monthly = await r.get(f"agent:cost:monthly:{month}")
    return {
        "daily": float(daily) if daily else 0.0,
        "monthly": float(monthly) if monthly else 0.0,
    }


# ─── Internal ────────────────────────────────────────────────────────────────

# Fields that are stored as JSON strings in Redis
_JSON_FIELDS = {"metadata", "depends_on", "agent_review"}
_FLOAT_FIELDS = {"agent_cost_usd"}
_INT_FIELDS = {"pr_number"}
_INT_FIELDS_DEFAULT_ZERO = {"priority", "agent_tokens", "seq"}
_BOOL_FIELDS = {"has_conflicts", "archived"}
_NULLABLE_FIELDS = {
    "blocked_question", "failed_reason", "clone_path", "pr_url",
    "pr_number", "tmux_session", "started_at", "completed_at", "status_changed_at", "external_id",
}


def _deserialize_ticket(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if k in _JSON_FIELDS:
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        elif k in _FLOAT_FIELDS:
            result[k] = float(v) if v else 0.0
        elif k in _INT_FIELDS:
            result[k] = int(v) if v and v != "" else None
        elif k in _INT_FIELDS_DEFAULT_ZERO:
            result[k] = int(v) if v and v != "" else 0
        elif k in _BOOL_FIELDS:
            result[k] = v.lower() in ("true", "1") if v else False
        elif k in _NULLABLE_FIELDS and v == "":
            result[k] = None
        else:
            result[k] = v
    return result
