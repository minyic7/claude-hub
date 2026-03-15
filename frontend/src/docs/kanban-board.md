# Kanban Board

The Kanban board is the primary interface for managing tickets across their lifecycle.

## Columns

Tickets flow through these status columns:

| Column | Description |
|--------|-------------|
| **To Do** | Queued work, not yet started |
| **In Progress** | Claude Code is actively working |
| **Blocked** | Agent hit an issue and needs input |
| **Verifying** | Work complete, running verification |
| **Review** | Ready for human review |
| **Merged** | PR merged, ticket complete |
| **Failed** | Terminal failure state |

## Ticket Cards

Each card displays:
- Ticket title and branch type badge
- Current status with color indicator
- Time since last status change
- Dependency indicators (if any)

### Card Interactions

- **Click** a card to open the ticket detail panel
- **Drag & drop** cards to reorder within a column
- Cards with active Claude sessions show a pulsing blue dot
- Blocked cards have a red pulse animation

## Filtering & Stats

The header shows real-time stats:
- Total ticket count
- Running sessions count
- Blocked tickets count
- Archived tickets count

## Archiving

Completed or abandoned tickets can be archived to keep the board clean. Archived tickets are hidden from the main view but preserved in the system.
