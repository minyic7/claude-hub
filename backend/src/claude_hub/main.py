import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from claude_hub import redis_client
from claude_hub.config import settings
from claude_hub.routers import projects, tickets, webhooks, ws

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to Redis at %s", settings.redis_url)
    await redis_client.connect()
    logger.info("Redis connected")
    yield
    await redis_client.disconnect()
    logger.info("Redis disconnected")


app = FastAPI(title="Claude Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(tickets.router)
app.include_router(ws.router)
app.include_router(webhooks.router)


@app.get("/api/health")
async def health():
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok" if redis_ok else "degraded", "redis": redis_ok}


@app.get("/api/cost")
async def cost_summary():
    return await redis_client.get_cost_summary()


@app.get("/api/roles")
async def list_roles():
    import yaml
    from pathlib import Path
    roles_path = Path(__file__).parent / "templates" / "roles.yaml"
    if not roles_path.exists():
        return {}
    with open(roles_path) as f:
        data = yaml.safe_load(f)
    return data.get("roles", {})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("claude_hub.main:app", host=settings.host, port=settings.port, reload=True)
