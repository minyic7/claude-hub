# Ticket Agent

The TicketAgent is an AI supervisor that monitors and guides Claude Code sessions in real time. It follows a **trust-but-verify** model: Claude Code works autonomously while the agent watches for problems and intervenes only when needed.

## Supervision Loop

The agent runs a continuous loop for each active ticket:

1. **Tail** — reads Claude Code's terminal output via tmux
2. **Buffer** — accumulates events until the configured **batch size** is reached
3. **Call LLM** — sends the batch to the configured provider for evaluation
4. **Act** — executes any tool calls returned by the model (intervene, wait, escalate, etc.)

### Critical Events

Some events bypass the batch buffer and trigger an immediate LLM call:

- Dangerous commands: `rm -rf`, `drop table`, `drop database`, `mkfs`, `dd if=`
- Sensitive file writes: `.env`, `credentials`, `secret`, `private_key`, `id_rsa`

## Agent Tools

The TicketAgent has access to the following tools during supervision:

| Tool | Description |
|------|-------------|
| **tmux_send** | Send corrections or suggestions to the Claude Code terminal |
| **file_read** | Read files from the ticket's clone directory |
| **git_status** | Check the working tree status |
| **escalate** | Block the ticket and surface a question to the user |
| **pause_session** | Send Ctrl+C to pause Claude Code |
| **wait** | Continue monitoring without action |
| **web_search** | Search the web for context (only when enabled in settings) |

## Provider Selection

The TicketAgent supports three LLM providers:

| Provider | Description |
|----------|-------------|
| **Anthropic** | Claude models via the Anthropic API |
| **OpenAI** | GPT models via the OpenAI API |
| **OpenAI-compatible** | Any endpoint following the OpenAI API spec (vLLM, Ollama, etc.) |

Select a provider in **Settings > TicketAgent**. When using an OpenAI-compatible provider, you must also set the **Endpoint URL** (e.g. `https://your-endpoint.com/v1`).

## Model Selection

Available model presets depend on the selected provider:

**Anthropic:**
| Model | Cost Tier |
|-------|-----------|
| claude-haiku-4-5 | $ |
| claude-sonnet-4-6 | $$ |
| claude-opus-4-6 | $$$ |

**OpenAI:**
| Model | Cost Tier |
|-------|-----------|
| gpt-4o-mini | $ |
| gpt-4o | $$ |
| o3 | $$$ |

For OpenAI-compatible providers, enter any model name as free text.

## Batch Size

Controls how many terminal events are buffered before making an LLM call.

- **Range:** 1 – 50
- **Default:** 8
- Lower values = more responsive supervision (higher cost)
- Higher values = more relaxed supervision (lower cost)

## Context Messages

The maximum number of messages retained in the agent's conversation history.

- **Range:** 5 – 100 (step 5)
- **Default:** 25
- More context = better awareness of earlier work, but higher token usage

## Web Search

When enabled, the agent gains a `web_search` tool it can call during supervision. This uses:

- **Anthropic provider:** `web_search_20250305` tool
- **OpenAI providers:** `web_search_preview` tool

Useful when tickets involve third-party APIs, libraries, or documentation the model may not have in its training data.

## Auto-resolve Conversations

When enabled, the agent can automatically resolve GitHub PR review threads after it has addressed the reviewer's feedback. The agent marks conversations as resolved once it confirms the code has been fixed.

- **Default:** off
- Only applies to PR review threads, not top-level comments

## Budget Limits

Three tiers of spending limits prevent runaway costs:

| Limit | Default | Minimum | Description |
|-------|---------|---------|-------------|
| **Per Ticket** | $2.00 | $0.10 | Maximum spend for a single ticket's supervision |
| **Daily** | $50.00 | $1.00 | Total spend across all tickets per day |
| **Monthly** | $500.00 | $1.00 | Total spend across all tickets per month |

When a budget limit is reached, the agent stops making LLM calls for the affected scope. The ticket continues running without supervision until the limit resets or is raised.

### Cost Tracking

Costs are calculated using per-model pricing and tracked in Redis with automatic TTLs:

- Per-ticket costs accumulate for the ticket's lifetime
- Daily costs reset at midnight (2-day TTL)
- Monthly costs reset at the start of each month (35-day TTL)

Cost data is visible on each ticket and updates in real time via WebSocket.

## Agent Review

After a Claude Code session completes, the TicketAgent performs a code review of the resulting PR diff (up to 50KB):

1. The ticket transitions to **Reviewing** status
2. The agent evaluates the diff against the ticket requirements
3. It returns a structured verdict with scores (1–10) for:
   - Correctness
   - Security
   - Code quality
   - Completeness
4. Issues are listed with severity, file, line number, and description

### Review Outcomes

- **Approve** — the ticket moves to **Review** for human sign-off
- **Reject** — a new session starts with the agent's feedback included

A maximum of **3 review rounds** prevents infinite loops. After 3 rejections, the ticket moves to Review regardless.

## Enabling the Agent

The TicketAgent requires two things to be active:

1. **Enabled** toggle set to on in Settings > TicketAgent
2. A valid **API key** for the selected provider

If either condition is not met, tickets run in simple mode (terminal output is tailed but no LLM supervision occurs).
