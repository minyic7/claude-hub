# Claude Hub

Kanban board that orchestrates Claude Code CLI sessions with TicketAgent supervision.

## Quick Start (Dev)

```bash
# Redis (dev mode — exposes port 6379)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Backend (from backend/)
uv sync
CLAUDE_HUB_DEV_MODE=true uv run python -m claude_hub.main

# Frontend (from frontend/)
pnpm install
pnpm run dev
```

## Quick Start (Production)

```bash
cp .env.example .env  # edit with real values
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Package Managers

- **Backend:** uv ONLY (never pip)
- **Frontend:** pnpm ONLY (never npm/yarn)

## Architecture

- Backend: Python 3.13+, FastAPI, Redis
- Frontend: React 19, TypeScript, Vite 7, Tailwind CSS 4
- Auth: JWT via FastAPI Depends() (NOT BaseHTTPMiddleware — WS incompatible)
- WebSocket auth: query param `?token=...` verified inside endpoint
- Claude Code runs in tmux with `--output-format stream-json --verbose --dangerously-skip-permissions`
- TicketAgent supervises via Anthropic API (trust-but-verify model)
- All state in Redis, real-time updates via WebSocket
- Production: FastAPI serves static frontend (same-origin, no CORS needed)
- Dev: Vite proxy forwards /api and /ws to backend, CORS enabled via DEV_MODE

## Key Files

- `backend/src/claude_hub/main.py` — FastAPI app entry, lifespan, static serving
- `backend/src/claude_hub/config.py` — All settings (CLAUDE_HUB_ prefix)
- `backend/src/claude_hub/auth.py` — JWT auth, Depends(), WS auth
- `backend/src/claude_hub/services/session_manager.py` — tmux + Claude Code
- `backend/src/claude_hub/services/ticket_agent.py` — TicketAgent ReAct loop
- `frontend/src/App.tsx` — React entry with auth gate
- `Dockerfile` — Multi-stage build (pnpm frontend + Python runtime)
- `docker-compose.yml` — Base (Redis only)
- `docker-compose.dev.yml` — Dev overlay (Redis port exposed)
- `docker-compose.prod.yml` — Prod overlay (app + watchtower)
- `.env` — Local config (not committed)
