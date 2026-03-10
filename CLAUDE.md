# Claude Hub

Kanban board that orchestrates Claude Code CLI sessions with TicketAgent supervision.

## Quick Start

```bash
# Redis
docker compose up -d

# Backend (from backend/)
uv sync
uv run python -m claude_hub.main

# Frontend (from frontend/)
pnpm install
pnpm run dev
```

## Package Managers

- **Backend:** uv ONLY (never pip)
- **Frontend:** pnpm ONLY (never npm/yarn)

## Architecture

- Backend: Python 3.13+, FastAPI, Redis
- Frontend: React 19, TypeScript, Vite 7, Tailwind CSS 4
- Claude Code runs in tmux with `--output-format stream-json --verbose --dangerously-skip-permissions`
- TicketAgent supervises via Anthropic API (trust-but-verify model)
- All state in Redis, real-time updates via WebSocket

## Key Files

- `backend/src/claude_hub/main.py` — FastAPI app entry
- `backend/src/claude_hub/config.py` — All settings (CLAUDE_HUB_ prefix)
- `backend/src/claude_hub/services/session_manager.py` — tmux + Claude Code
- `backend/src/claude_hub/services/ticket_agent.py` — TicketAgent ReAct loop
- `frontend/src/App.tsx` — React entry
- `.env` — Local config (not committed)
