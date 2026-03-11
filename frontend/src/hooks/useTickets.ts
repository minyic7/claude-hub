import { useMemo } from 'react'
import type { Ticket, TicketStatus } from '../types/ticket'

const COLUMN_ORDER: TicketStatus[] = ['todo', 'in_progress', 'review', 'merged']

// These statuses are shown within their parent column
const STATUS_MAPPING: Record<TicketStatus, TicketStatus> = {
  todo: 'todo',
  in_progress: 'in_progress',
  blocked: 'in_progress',
  verifying: 'in_progress',
  review: 'review',
  merging: 'review',
  merged: 'merged',
  failed: 'in_progress',
}

export interface KanbanColumn {
  status: TicketStatus
  label: string
  tickets: Ticket[]
}

export function useTickets(ticketMap: Map<string, Ticket>): KanbanColumn[] {
  return useMemo(() => {
    const columns: Record<string, Ticket[]> = {
      todo: [],
      in_progress: [],
      review: [],
      merged: [],
    }

    for (const ticket of ticketMap.values()) {
      const col = STATUS_MAPPING[ticket.status] || 'in_progress'
      columns[col]?.push(ticket)
    }

    // Sort TODO: by priority, then group dependent tickets adjacently
    columns.todo.sort((a, b) => {
      const pa = a.priority ?? 0
      const pb = b.priority ?? 0
      if (pa !== pb) return pa - pb
      return b.created_at.localeCompare(a.created_at)
    })

    // Group dependent tickets: place tickets right after their dependencies
    const todoIds = new Set(columns.todo.map((t) => t.id))
    const sorted: Ticket[] = []
    const placed = new Set<string>()

    const place = (ticket: Ticket) => {
      if (placed.has(ticket.id)) return
      placed.add(ticket.id)
      sorted.push(ticket)
      // Find tickets that depend on this one and place them next
      for (const t of columns.todo) {
        if (!placed.has(t.id) && t.depends_on.includes(ticket.id)) {
          place(t)
        }
      }
    }

    // Start with tickets that have no TODO-column dependencies (roots)
    for (const t of columns.todo) {
      const hasTodoDep = t.depends_on.some((depId) => todoIds.has(depId))
      if (!hasTodoDep) place(t)
    }
    // Place any remaining (circular deps, etc.)
    for (const t of columns.todo) {
      place(t)
    }
    columns.todo = sorted
    columns.in_progress.sort((a, b) => (a.started_at || a.created_at).localeCompare(b.started_at || b.created_at))
    columns.review.sort((a, b) => (a.started_at || a.created_at).localeCompare(b.started_at || b.created_at))
    columns.merged.sort((a, b) => (b.completed_at || b.created_at).localeCompare(a.completed_at || a.created_at))

    const labels: Record<string, string> = {
      todo: 'TODO',
      in_progress: 'IN PROGRESS',
      review: 'REVIEW',
      merged: 'MERGED',
    }

    return COLUMN_ORDER.map((status) => ({
      status,
      label: labels[status],
      tickets: columns[status],
    }))
  }, [ticketMap])
}
