# Getting Started

Welcome to **Claude Hub** — a Kanban board that orchestrates Claude Code CLI sessions with TicketAgent supervision.

## Quick Start (Development)

### 1. Start Redis

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### 2. Start the Backend

```bash
cd backend
uv sync
CLAUDE_HUB_DEV_MODE=true uv run python -m claude_hub.main
```

### 3. Start the Frontend

```bash
cd frontend
pnpm install
pnpm run dev
```

The app will be available at `http://localhost:3000`.

## Quick Start (Production)

```bash
cp .env.example .env  # Edit with real values
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Package Managers

| Component | Manager | Command |
|-----------|---------|---------|
| Backend | uv | `uv sync`, `uv run ...` |
| Frontend | pnpm | `pnpm install`, `pnpm run dev` |

> **Important:** Never use `pip` for the backend or `npm`/`yarn` for the frontend.

## Architecture Overview

- **Backend:** Python 3.13+, FastAPI, Redis
- **Frontend:** React 19, TypeScript, Vite 7, Tailwind CSS 4
- **Auth:** JWT via FastAPI `Depends()` (not BaseHTTPMiddleware — WebSocket incompatible)
- **Real-time:** WebSocket with query param `?token=...` for auth
- **Claude Code:** Runs in tmux with `--output-format stream-json`
- **State:** All state stored in Redis, real-time updates via WebSocket
- **Production:** FastAPI serves static frontend (same-origin, no CORS needed)
- **Dev:** Vite proxy forwards `/api` and `/ws` to backend
