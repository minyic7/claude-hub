# Kanban Board

The Kanban board is the primary interface for managing tickets across their lifecycle. It provides adaptive columns, drag-and-drop reordering, filtering, multi-select bulk operations, and an archive section.

## Columns

Tickets are grouped into four visual columns based on their status:

| Column | Statuses Included |
|--------|-------------------|
| **To Do** | `todo`, `queued` |
| **In Progress** | `in_progress`, `blocked`, `verifying`, `reviewing`, `failed` |
| **Review** | `review`, `merging` |
| **Merged** | `merged` |

### Sorting

Each column uses a different sort order:

- **To Do** — sorted by priority (lower number = higher priority), then by creation date (newest first). Dependent tickets are grouped adjacently, placed after their dependencies.
- **In Progress** — sorted by `started_at`, then by `created_at`
- **Review** — sorted by `started_at`, then by `created_at`
- **Merged** — sorted by `completed_at` (newest first)

## Adaptive Columns

The board dynamically adjusts its layout based on your viewport width:

- **Desktop** — shows 1 to 4 columns side by side (minimum 260px per column)
- **Mobile** — single column with tab navigation

When there isn't enough space for all columns, lower-priority columns are "folded" into a tab bar at the bottom of the board. The folding order prioritizes keeping **To Do** visible longest and folds **Merged** first.

Your active tab selection is saved and restored between sessions.

## Ticket Lifecycle

Tickets flow through a defined state machine with enforced transitions:

```
                        ┌──── FAILED (retry possible)
                        │
TODO ─► QUEUED ─► IN_PROGRESS ─► VERIFYING ─► REVIEWING ─► REVIEW ─► MERGING ─► MERGED
                     │    ▲                                   │
                     ▼    │                                   │
                   BLOCKED ──────────────────────────────────►┘
                  (answer unblocks)              (reject sends back)
```

Invalid status transitions are rejected by the backend with a `409 Conflict` response.

## Ticket Cards

Each card in a column displays:

- **Title** and **branch type badge** (feature, bugfix, hotfix, chore, refactor, docs, test)
- **Current status** with a color-coded indicator
- **Time** since the last status change
- **Dependency indicators** if the ticket depends on other tickets
- **Pulsing blue dot** for tickets with an active Claude Code session
- **Red pulse animation** for blocked tickets

Click a card to open the **Ticket Detail** panel.

## Drag-and-Drop Reorder

You can reorder tickets within the same column by dragging and dropping:

- **To Do → To Do** — updates ticket priorities via the backend. The new order persists across sessions.
- **Queued → Queued** — reorders the queue position for tickets waiting to start.
- **Cross-column drops** are not supported and will revert silently.

The reorder uses optimistic updates — the UI updates immediately and syncs with the server. If the server detects a conflict (e.g., another user reordered), the server state takes priority.

Drag is disabled on interactive elements like buttons and inputs to prevent accidental drags.

## Branch Type Filter

Filter the board by ticket branch type using the **filter button** at the top of the board.

Available types:
- `feature`, `bugfix`, `hotfix`, `chore`, `refactor`, `docs`, `test`

Filtering is applied client-side on the ticket's `branch_type` field. The filter resets when you switch projects.

## Multi-Select & Bulk Operations

### Enabling Multi-Select

1. Click the **checkbox icon** in the To Do column header to enter select mode
2. Check individual tickets or use the **Select All** checkbox in the column header
3. Selected tickets are highlighted

### Bulk Start

With tickets selected, click **Bulk Start** to start multiple tickets at once:

- Tickets are started up to the configured `max_sessions` limit
- Overflow tickets are automatically transitioned to **Queued** status
- The response shows which tickets were `started` and which were `queued`

Archived tickets are excluded from multi-select operations.

## Archive Section

Tickets can be archived to keep the board clean without deleting them.

- **Archive a ticket** — use the archive toggle on the ticket card or in the detail panel
- **Archived tickets** appear in a collapsible section at the bottom of the To Do column
- **Unarchive** — toggle the archive flag again to restore the ticket to the main board
- Archived tickets are excluded from bulk operations and board statistics

## Header Stats

The board header displays real-time statistics for the active project:

| Stat | Description |
|------|-------------|
| **Running** | Number of active Claude Code sessions |
| **Blocked** | Tickets waiting for human input |
| **Total** | All non-archived tickets |
| **Archived** | Hidden archived tickets |

## Merge Queue & Deploy Lock

When a merge is initiated:

1. All **Merge** buttons across the board are locked to prevent concurrent merges
2. The system polls for deployment completion (via `/api/version` SHA comparison)
3. Once the new version is detected, the lock is released
4. A safety timeout of **5 minutes** auto-unlocks if deploy detection hangs

The deploy status widget in the header shows the current workflow run status (deploying, success, failed).
