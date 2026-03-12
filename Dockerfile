# ─── Stage 1: Build frontend ─────────────────────────────
FROM node:24-alpine AS frontend-build

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm run build
# Output: /app/frontend/dist/

# ─── Stage 2: Runtime ────────────────────────────────────
FROM python:3.13-slim

# System dependencies: tmux, git, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node.js 24 LTS (required for Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI + pnpm (for frontend projects Claude Code may work on)
RUN npm install -g @anthropic-ai/claude-code pnpm

# Disable corepack strict mode (prevents download prompts in cloned repos)
ENV COREPACK_ENABLE_STRICT=0

# uv (Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ─── Backend setup ────────────────────────────────────────
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./

# ─── Frontend build → served by FastAPI as static files ───
COPY --from=frontend-build /app/frontend/dist /app/backend/static

# ─── Non-root user (Claude Code refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash claude && \
    mkdir -p /data/clones /data/references /data/logs && \
    chown -R claude:claude /data /app

USER claude

# Git identity for Claude Code commits
RUN git config --global user.name "Claude Hub" && \
    git config --global user.email "claude-hub@noreply.github.com"

# ─── Build metadata ───────────────────────────────────────
ARG BUILD_SHA=unknown
ENV CLAUDE_HUB_BUILD_SHA=${BUILD_SHA}

# ─── Environment defaults ─────────────────────────────────
ENV CLAUDE_HUB_HOST=0.0.0.0
ENV CLAUDE_HUB_PORT=7700
ENV CLAUDE_HUB_DATA_DIR=/data
ENV CLAUDE_HUB_REDIS_URL=redis://redis:6379/0

EXPOSE 7700

CMD ["uv", "run", "python", "-m", "claude_hub.main"]
