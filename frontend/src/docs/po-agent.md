# PO Agent

The PO (Product Owner) Agent is an autonomous planning agent that observes your project board, reasons about what work to do next, and creates tickets. It follows an **Observe-Think-Act** cycle powered by Claude models with extended thinking.

## Modes

### Semi-Auto (default)

Tickets created by the PO Agent start in **PO Pending** status. You must explicitly approve or reject each one before it enters the board.

- Pending tickets show a purple "PO PENDING" badge on the kanban card
- The card displays the agent's **rationale** explaining why it proposed the ticket
- Approve (green checkmark) transitions the ticket to **To Do**
- Reject (red X) archives the ticket with a note

### Full Auto

Tickets are created directly in **To Do** status and can be picked up immediately. No approval step is required.

Use full auto when the PO Agent has a well-defined VISION.md and you trust its judgment. Switch back to semi-auto when you want tighter control.

## The OTA Cycle

Each PO cycle runs three phases:

### 1. Observe

The agent collects context:

- Current board state (all tickets and their statuses)
- VISION.md content from the `kanban-claude-hub` branch
- Recent conversation history
- Constraint checks (active ticket count, pending approvals, available slots)
- Git commit history (when configured and conditions are met)

### 2. Think

Using extended thinking, the agent reasons about the project state and decides on actions. The think phase uses a more powerful model (default: claude-opus-4-6) with a configurable token budget.

The agent can produce four action types:

| Action | Description |
|--------|-------------|
| **create_ticket** | Define a new ticket with title, description, branch type, priority, and dependencies |
| **wait** | Idle until the next cycle trigger |
| **raise_to_user** | Send a message to the user and block until answered |
| **update_vision** | Update the PO section of VISION.md |

### 3. Act

Actions are executed in order. Created tickets go through semantic deduplication to avoid duplicates. If the agent waits for 3 consecutive cycles, it escalates with a message to the user.

## Chat Panel

The PO Chat panel is a resizable right-side panel for direct conversation with the agent.

- Open the right panel and select the **PO Chat** tab
- Messages are persisted in a per-project SQLite database (up to 50 messages)
- Sending a message triggers a new PO cycle with a "user_message" trigger
- The agent acknowledges your message and factors it into its next OTA cycle
- Panel width is saved to localStorage

### Chat Controls

- **Run Now** — manually trigger an OTA cycle without sending a message
- Status indicator shows the current cycle state (idle, analyzing, planning, waiting, blocked)
- Cycle counter tracks how many cycles have run

## PO Bar

When the PO Agent is running, a status bar appears above the board showing:

- Current status and cycle number
- **Mode toggle** — switch between Semi and Full auto
- **Pending count** — number of tickets awaiting approval (semi-auto only)
- **Run Now** button
- **Report** button — view the latest PO report

## Reports

The PO Agent generates periodic reports summarizing project state. Reports group tickets by status and are stored with a timestamp.

- Reports are generated on a configurable interval (default: every 1 hour)
- Click "Report" in the PO Bar to view the latest report
- Use the API to request an on-demand report

## VISION.md

The PO Agent reads and updates a `VISION.md` file stored on the `kanban-claude-hub` branch of your repository. This file has two sections:

```markdown
<!-- USER_SECTION_START ... -->
Your project goals, scope, and constraints go here.
Edit this section to guide the PO Agent's planning.
<!-- USER_SECTION_END -->

<!-- PO_SECTION_START — MAINTAINED BY PO AGENT -->
The agent maintains its own memory, current phase,
and completed work log in this section.
<!-- PO_SECTION_END -->
```

The user section is never modified by the agent. The PO section is updated via the `update_vision` action.

## Compaction

After **5 tickets** reach merged status, the agent runs a compaction cycle:

1. Summarizes merged tickets into a "Completed Work Log" in VISION.md
2. Archives the merged tickets from the board
3. This keeps the board clean and VISION.md focused on current work

## Capacity Limits

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Max Active Tickets** | 10 | 1–20 | Total PO-created tickets in active statuses (todo through merging) |
| **Max New Per Cycle** | 3 | 1–10 | Maximum tickets created in a single OTA cycle |
| **Max Pending Approval** | 5 | 1–20 | Maximum tickets in PO Pending status (semi-auto only) |

The agent checks these constraints during the Observe phase and includes available slot counts in its context.

## Deployment Scope

Tells the PO Agent what kind of deployment the project uses:

| Option | Description |
|--------|-------------|
| **Auto** | Agent infers from the repository |
| **GitHub Pages** | Static site deployment |
| **Docker** | Container-based deployment |
| **Docs Only** | Documentation-only project |
| **None** | No deployment pipeline |

## Git History Context

The agent can fetch recent git commits for additional context:

- **Max Commits** (default: 10, range: 0–50) — set to 0 to disable
- **Days Window** (default: 7, range: 1–30) — how far back to look

Git history is fetched when:
- The trigger is "compaction" or "vision_changed", or
- There are fewer than 3 active tickets

The commit history is summarized by the observe model before being passed to the think phase.

## LLM Model Configuration

The PO Agent uses separate models for different phases to balance cost and capability:

| Phase | Setting | Default | Purpose |
|-------|---------|---------|---------|
| **Observe** | observe_model | claude-sonnet-4-6 | Fast summarization, deduplication, git history |
| **Think** | think_model | claude-opus-4-6 | Deep reasoning with extended thinking |
| **Compaction** | compaction_model | claude-sonnet-4-6 | Compressing merged ticket summaries |

### Think Budget

Controls the extended thinking token budget for the Think phase:

- **Range:** 2,000 – 16,000 tokens (step 1,000)
- **Default:** 8,000 tokens
- Higher budget = deeper reasoning (more costly)

## Watchdog

A background watchdog monitors cycle frequency. If no cycle runs for **1 hour**, it sends a `po_alert` via WebSocket. The watchdog checks every 5 minutes.

## Enabling the PO Agent

1. Go to **Settings > PO Agent**
2. Toggle **Enabled** to on
3. Configure mode, capacity, and model settings
4. The agent starts automatically when settings are saved with enabled=true

The PO Agent requires the TicketAgent's API key to be configured (it uses the same Anthropic credentials).
