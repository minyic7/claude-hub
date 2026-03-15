# Settings

Access settings via the **gear icon** in the header. Settings are organized into tabs.

## System Settings

General application configuration:

- **Backend URL** — API endpoint (auto-configured in production)
- **WebSocket URL** — Real-time connection endpoint
- **Theme** — Light, Dark, or System preference

## TicketAgent Settings

Configure the AI supervisor per project:

| Setting | Description |
|---------|-------------|
| **Model** | Anthropic model for the agent (e.g., claude-sonnet-4-20250514) |
| **Supervision Interval** | How often the agent checks progress |
| **Auto-approve** | Whether to auto-approve passing reviews |
| **System Prompt** | Custom instructions for the agent |
| **Max Retries** | Maximum retry attempts before escalating |

## PO Agent Settings

Configure the Product Owner chat agent:

| Setting | Description |
|---------|-------------|
| **Model** | Anthropic model for PO chat |
| **System Prompt** | Custom personality and instructions |
| **Context Depth** | How much board context to include |

## Account Settings

Manage your authentication:

- **API Key** — Your Anthropic API key (used for agent features)
- **JWT Token** — Current session token info
- **Logout** — End current session

## Environment Variables

For production deployment, settings are configured via environment variables with the `CLAUDE_HUB_` prefix:

```bash
CLAUDE_HUB_JWT_SECRET=your-secret-key
CLAUDE_HUB_ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_HUB_GITHUB_WEBHOOK_SECRET=whsec_...
CLAUDE_HUB_DEV_MODE=false
```

See `.env.example` for the full list of available settings.
