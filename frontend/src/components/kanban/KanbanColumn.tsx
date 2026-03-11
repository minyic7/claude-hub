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
}

export function KanbanColumn({ label, tickets, activities, onTicketClick, onOptimistic, deployingBranches, mergeQueueLocked, onMergeInitiated }: KanbanColumnProps) {
  return (
    <div className="flex min-w-[280px] flex-1 flex-col">
      <div className="mb-3 flex items-center gap-2 px-1">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {label}
        </h2>
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-bg-secondary)] px-1.5 text-xs text-[var(--color-text-muted)]">
          {tickets.length}
        </span>
      </div>
      <div className="flex flex-col gap-2 overflow-y-auto px-1 pb-4">
        {tickets.map((ticket, index) => {
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
                deploying={ticket.status === 'merged' && deployingBranches ? deployingBranches.has(ticket.branch) ? true : false : undefined}
                mergeQueueLocked={mergeQueueLocked}
                onMergeInitiated={onMergeInitiated}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
