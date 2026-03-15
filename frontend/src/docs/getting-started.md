# Getting Started

Welcome to **Claude Hub** — a Kanban board that orchestrates Claude Code CLI sessions with TicketAgent supervision. This guide covers setup, authentication, and the core architecture.

## Prerequisites

- **Docker & Docker Compose** — required for Redis (and production deployment)
- **Python 3.13+** with [uv](https://docs.astral.sh/uv/) — backend package manager
- **Node.js 20+** with [pnpm](https://pnpm.io/) — frontend package manager
- **tmux** — used to run Claude Code CLI sessions
- **Claude Code CLI** — the `claude` command must be available on `$PATH`
- **GitHub CLI (`gh`)** — used for PR operations, CI checks, and merging

> **Important:** Never use `pip` for the backend or `npm`/`yarn` for the frontend.

## Quick Start (Development)

### 1. Start Redis

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This starts Redis on port `6379` with data persistence enabled.

### 2. Configure Authentication

Copy the example environment file and set your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
CLAUDE_HUB_AUTH_USERNAME=admin
CLAUDE_HUB_AUTH_PASSWORD=changeme
CLAUDE_HUB_AUTH_SECRET=replace-with-a-random-string
```

Generate a secure secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Start the Backend

```bash
cd backend
uv sync
CLAUDE_HUB_DEV_MODE=true uv run python -m claude_hub.main
```

The backend runs on `http://localhost:7700`. Setting `DEV_MODE=true` enables CORS so the frontend dev server can communicate with it.

### 4. Start the Frontend

```bash
cd frontend
pnpm install
pnpm run dev
```

The frontend runs on `http://localhost:3000`. Vite automatically proxies `/api` and `/ws` requests to the backend.

## Quick Start (Production)

Production runs everything in a single Docker container — FastAPI serves both the API and the built frontend (same-origin, no CORS needed).

```bash
cp .env.example .env   # Edit with real values
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The app is available on port `7700`. The production compose file includes:
- The Claude Hub app container (FastAPI + static frontend)
- Redis with AOF persistence
- Watchtower for automatic container updates

## Authentication

Claude Hub uses a **shared login** model — all users authenticate with the same username and password.

### Login Flow

1. Open the app in your browser
2. If authentication is enabled (default), you'll see the **login page**
3. Enter the username and password configured in `.env`
4. On success, a JWT token is stored in your browser's `localStorage`
5. The token is included in all API requests and WebSocket connections

### Token Details

| Setting | Env Variable | Default |
|---------|-------------|---------|
| Username | `CLAUDE_HUB_AUTH_USERNAME` | `admin` |
| Password | `CLAUDE_HUB_AUTH_PASSWORD` | `changeme` |
| JWT Secret | `CLAUDE_HUB_AUTH_SECRET` | *(must be set)* |
| Token Lifetime | `CLAUDE_HUB_AUTH_TOKEN_HOURS` | `24` hours |

When your token expires, the app automatically redirects you to the login page.

### WebSocket Authentication

WebSocket connections pass the JWT token as a query parameter (`?token=...`) since WebSocket connections don't support custom headers in all browsers. The token is verified inside each WebSocket endpoint.

## Architecture Overview

```
┌──────────────┐     ┌──────────────────┐     ┌─────────┐
│   Browser    │◄───►│  FastAPI Backend  │◄───►│  Redis  │
│  (React +    │ WS  │  (Python 3.13+)  │     │ (State) │
│   xterm.js)  │     │                  │     └─────────┘
└──────────────┘     │  ┌────────────┐  │
                     │  │  tmux      │  │
                     │  │  sessions  │  │
                     │  │ (Claude    │  │
                     │  │   Code)    │  │
                     │  └────────────┘  │
                     └──────────────────┘
```

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | React 19, TypeScript, Vite 7, Tailwind CSS 4 | UI, Kanban board, xterm.js terminal |
| Backend | Python 3.13+, FastAPI | API, WebSocket, session orchestration |
| Auth | JWT via FastAPI `Depends()` | Token-based authentication |
| Sessions | tmux + Claude Code CLI | Code generation in isolated sessions |
| Agents | Anthropic API | TicketAgent supervision, code review, PO agent |
| State | Redis | All persistent state, real-time pub/sub |
| Real-time | WebSocket | Live updates for tickets, activity, terminal |

### Key Design Decisions

- **All state lives in Redis** — no SQL database, no file-based state
- **Real-time first** — WebSocket broadcasts ticket changes, activity events, and terminal output to all connected clients
- **Claude Code runs in tmux** with `--output-format stream-json --verbose --dangerously-skip-permissions` for full automation
- **Same-origin in production** — FastAPI serves the built frontend, eliminating CORS complexity
- **Dev mode** — Vite proxy handles API/WS forwarding; backend enables CORS

## First Steps After Setup

1. **Configure settings** — click the gear icon in the header to set your GitHub token, max concurrent sessions, and TicketAgent API key
2. **Create a project** — use the project dropdown in the header to create your first project linked to a GitHub repository
3. **Create a ticket** — click the "+" button to create a ticket with a title and description
4. **Start the ticket** — click "Start" to launch a Claude Code session that works on the ticket
5. **Watch it work** — open the terminal panel to see Claude Code in action
