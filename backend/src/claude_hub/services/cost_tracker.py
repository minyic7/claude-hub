import logging
from datetime import datetime

from claude_hub import redis_client
from claude_hub.config import settings

logger = logging.getLogger(__name__)

# Approximate costs per 1M tokens (March 2026)
MODEL_COSTS = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.50},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_read": 0.08},
}


def calculate_cost(usage: dict, model: str) -> float:
    costs = MODEL_COSTS.get(model, MODEL_COSTS["claude-sonnet-4-6"])
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)

    cost = (
        (input_tokens / 1_000_000) * costs["input"]
        + (output_tokens / 1_000_000) * costs["output"]
        + (cache_read / 1_000_000) * costs["cache_read"]
    )
    return round(cost, 6)


async def can_spend(ticket_id: str, estimated: float) -> tuple[bool, str]:
    r = redis_client.get_pool()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    ticket_cost = await r.get(f"agent:cost:ticket:{ticket_id}")
    ticket_cost = float(ticket_cost) if ticket_cost else 0.0
    if ticket_cost + estimated > settings.agent_budget_per_ticket_usd:
        return False, f"Ticket budget exceeded (${ticket_cost:.2f}/${settings.agent_budget_per_ticket_usd:.2f})"

    daily_cost = await r.get(f"agent:cost:daily:{today}")
    daily_cost = float(daily_cost) if daily_cost else 0.0
    if daily_cost + estimated > settings.agent_budget_daily_usd:
        return False, f"Daily budget exceeded (${daily_cost:.2f}/${settings.agent_budget_daily_usd:.2f})"

    monthly_cost = await r.get(f"agent:cost:monthly:{month}")
    monthly_cost = float(monthly_cost) if monthly_cost else 0.0
    if monthly_cost + estimated > settings.agent_budget_monthly_usd:
        return False, f"Monthly budget exceeded (${monthly_cost:.2f}/${settings.agent_budget_monthly_usd:.2f})"

    return True, ""


async def record_spend(ticket_id: str, cost: float) -> None:
    r = redis_client.get_pool()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    await r.incrbyfloat(f"agent:cost:ticket:{ticket_id}", cost)
    await r.incrbyfloat(f"agent:cost:daily:{today}", cost)
    await r.incrbyfloat(f"agent:cost:monthly:{month}", cost)

    # Set TTLs
    await r.expire(f"agent:cost:daily:{today}", 2 * 86400)
    await r.expire(f"agent:cost:monthly:{month}", 35 * 86400)

    # Update ticket's agent_cost_usd
    ticket_total = await r.get(f"agent:cost:ticket:{ticket_id}")
    await redis_client.update_ticket_fields(ticket_id, {
        "agent_cost_usd": float(ticket_total) if ticket_total else cost,
    })

    logger.debug("Recorded $%.4f for ticket %s (today: $%.2f)",
                 cost, ticket_id,
                 float(await r.get(f"agent:cost:daily:{today}") or 0))
