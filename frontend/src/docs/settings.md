# Settings

Access settings via the **gear icon** in the header. The modal is organized into four tabs: System, TicketAgent, PO Agent, and Account.

All settings (except Account) are stored in Redis and take effect immediately. API keys and tokens are masked in the UI after saving.

## System

Global application settings that apply to all projects.

### Max Concurrent Sessions

How many Claude Code sessions can run simultaneously.

- **Range:** 1 – 20
- **Default:** 4

Each session uses a tmux pane and consumes system resources. Increase this if your server has capacity for more parallel work.

### GitHub Token

A fallback GitHub personal access token used when a project does not have its own token configured.

- Used for GitHub API calls (webhooks, PR operations, Actions status)
- Enter a token with `repo` scope

### Webhook URL

The public URL where GitHub delivers webhook events.

- Must be reachable from the internet (e.g., via Tailscale Funnel or a reverse proxy)
- Format: `https://your-server.com/api/webhooks/github`
- When changed, webhooks are automatically re-registered for all existing projects

## TicketAgent

Global AI supervisor settings used by all tickets. See the [Ticket Agent docs](#) for detailed feature explanations.

### Enabled

Master toggle for TicketAgent supervision. When off, tickets run without LLM oversight (simple terminal tailing only).

- **Default:** on

### Provider

Which LLM provider to use for supervision.

| Provider | Description |
|----------|-------------|
| **Anthropic** | Claude models via the Anthropic API |
| **OpenAI** | GPT models via the OpenAI API |
| **OpenAI-compatible** | Custom endpoint (vLLM, Ollama, etc.) |

### API Key

The API key for the selected provider. Required for the agent to function.

- Keys are masked after saving (first 8 + last 4 characters shown)
- Use the **Test Connection** button to verify the key works
- A successful test shows the model name; failures show the specific error

### Endpoint URL

Only shown when the provider is **OpenAI-compatible**. Enter the base URL of your API endpoint (e.g., `https://your-endpoint.com/v1`).

### Model

The LLM model used for supervision. Preset options vary by provider:

**Anthropic:** claude-haiku-4-5 ($), claude-sonnet-4-6 ($$), claude-opus-4-6 ($$$)

**OpenAI:** gpt-4o-mini ($), gpt-4o ($$), o3 ($$$)

**OpenAI-compatible:** free text input for any model name.

- **Default:** claude-haiku-4-5-20251001

### Batch Size

Number of terminal events buffered before making an LLM call.

- **Range:** 1 – 30 (slider)
- **Default:** 8
- Left = "Responsive (costly)", Right = "Relaxed (cheap)"

### Context Messages

Maximum messages retained in the agent's conversation history.

- **Range:** 5 – 100 (step 5)
- **Default:** 25
- Left = "Less memory", Right = "More memory"

### Web Search

Toggle to give the agent web search capabilities during supervision.

- **Default:** off

### Auto-resolve Conversations

Allow the agent to automatically resolve GitHub PR review threads after addressing feedback.

- **Default:** off

### Budget (USD)

Three spending limits to control costs:

| Field | Default | Min | Step |
|-------|---------|-----|------|
| **Per Ticket** | $2.00 | $0.10 | $0.50 |
| **Daily** | $50.00 | $1.00 | $5.00 |
| **Monthly** | $500.00 | $1.00 | $50.00 |

## PO Agent

Per-project Product Owner agent settings. These configure the autonomous planning agent for the currently selected project. See the [PO Agent docs](#) for detailed feature explanations.

### Enabled

Master toggle. Saving with enabled=true starts the agent; saving with enabled=false stops it.

- **Default:** off

### Approval Mode

| Mode | Behavior |
|------|----------|
| **Semi-Auto** | Created tickets require user approval (PO Pending status) |
| **Full Auto** | Tickets are created directly in To Do status |

- **Default:** Semi-Auto

### Report Interval

How often the agent generates a project status report.

- **Range:** 1 – 24 hours (slider)
- **Default:** 1 hour
- Left = "Frequent (1 hr)", Right = "Relaxed (24 hr)"

### Capacity Limits

| Field | Default | Range | Description |
|-------|---------|-------|-------------|
| **Max Active** | 10 | 1–20 | Total PO-created tickets in active statuses |
| **Max New/Cycle** | 3 | 1–10 | Max tickets created per OTA cycle |
| **Max Pending** | 5 | 1–20 | Max tickets awaiting approval (semi-auto only) |

### Deployment Scope

Informs the agent about the project's deployment model: **Auto**, **GitHub Pages**, **Docker**, **Docs Only**, or **None**.

- **Default:** Auto

### Git History Context

| Field | Default | Range | Description |
|-------|---------|-------|-------------|
| **Max Commits** | 10 | 0–50 | Commits to fetch for context (0 = disabled) |
| **Days Window** | 7 | 1–30 | How far back to look |

### LLM Models

| Phase | Default | Purpose |
|-------|---------|---------|
| **Observe (fast)** | claude-sonnet-4-6 | Summarization, deduplication, git history |
| **Think (reasoning)** | claude-opus-4-6 | Deep planning with extended thinking |

Each has a dropdown with Haiku, Sonnet, and Opus options.

### Think Budget

Extended thinking token budget for the Think phase.

- **Range:** 2,000 – 16,000 tokens (step 1,000)
- **Default:** 8,000
- Left = "Quick (cheap)", Right = "Deep (costly)"

## Account

Authentication management for the current session.

### Logout

Clears the JWT token and reloads the page, returning to the login screen.

## Environment Variables

Only three settings are configured via environment variables (in `.env`):

```bash
CLAUDE_HUB_AUTH_USERNAME=your-username
CLAUDE_HUB_AUTH_PASSWORD=your-password
CLAUDE_HUB_AUTH_SECRET=your-jwt-secret
```

All other application settings are managed through the Settings UI and stored in Redis.
