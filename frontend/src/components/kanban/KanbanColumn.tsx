import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { TicketCard } from './TicketCard'

interface KanbanColumnProps {
  label: string
  tickets: Ticket[]
  activities: Map<string, ActivityEvent[]>
  onTicketClick: (ticket: Ticket) => void
  onOptimistic?: (ticketId: string, patch: Partial<Ticket>) => void
  deployingBranches?: Set<string>
  mergeQueueLocked?: boolean
  onMergeInitiated?: () => void
  compact?: boolean
}

export function KanbanColumn({ label, tickets, activities, onTicketClick, onOptimistic, deployingBranches, mergeQueueLocked, onMergeInitiated, compact }: KanbanColumnProps) {
  const [archiveExpanded, setArchiveExpanded] = useState(false)

  const { active, archived } = useMemo(() => {
    const active: Ticket[] = []
    const archived: Ticket[] = []
    for (const t of tickets) {
      if (t.archived) {
        archived.push(t)
      } else {
        active.push(t)
      }
    }
    // Sort archived by completed_at (or created_at) descending
    archived.sort((a, b) => {
      const ta = a.completed_at || a.created_at
      const tb = b.completed_at || b.created_at
      return tb.localeCompare(ta)
    })
    return { active, archived }
  }, [tickets])

  const renderTicket = (ticket: Ticket, index: number) => {
    const ticketActivities = activities.get(ticket.id)
    const latest = ticketActivities?.[ticketActivities.length - 1]
    return (
      <div
        key={ticket.id}
        className="rise-stagger"
        style={{ animationDelay: `${60 + index * 50}ms` }}
      >
        <TicketCard
          ticket={ticket}
          latestActivity={latest}
          activityEvents={ticketActivities}
          onClick={() => onTicketClick(ticket)}
          onOptimistic={onOptimistic}
          deploying={ticket.status === 'merged' ? deployingBranches?.has(ticket.branch) : undefined}
          mergeQueueLocked={mergeQueueLocked}
          onMergeInitiated={onMergeInitiated}
        />
      </div>
    )
  }

  return (
    <div className={`flex flex-1 flex-col ${compact ? 'min-w-0' : 'min-w-[280px]'}`}>
      <div className="mb-3 flex items-center gap-2 px-1">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {label}
        </h2>
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-bg-secondary)] px-1.5 text-xs text-[var(--color-text-muted)]">
          {active.length}
        </span>
      </div>
      <div className="flex flex-col gap-2 overflow-y-auto px-1 pb-4">
        {active.map(renderTicket)}

        {archived.length > 0 && (
          <>
            <button
              onClick={() => setArchiveExpanded(!archiveExpanded)}
              className="flex items-center gap-1.5 rounded px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
            >
              {archiveExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span>{archiveExpanded ? 'Hide' : 'Show'} {archived.length} archived</span>
            </button>
            {archiveExpanded && archived.map((t, i) => renderTicket(t, i + active.length))}
          </>
        )}
      </div>
    </div>
  )
}
