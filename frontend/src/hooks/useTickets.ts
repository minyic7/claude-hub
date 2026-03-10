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

    // Sort: newest first in TODO, oldest first elsewhere
    columns.todo.sort((a, b) => b.created_at.localeCompare(a.created_at))
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
