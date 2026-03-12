import { useRef } from 'react'
import { useSortable, defaultAnimateLayoutChanges } from '@dnd-kit/sortable'
import type { AnimateLayoutChanges } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { TicketCard } from './TicketCard'

interface SortableTicketCardProps {
  ticket: Ticket
  latestActivity?: ActivityEvent
  activityEvents?: ActivityEvent[]
  allTickets: Map<string, Ticket>
  onClick: () => void
  onOptimistic?: (ticketId: string, patch: Partial<Ticket>) => void
  onTicketClick?: (ticket: Ticket) => void
}

export function SortableTicketCard({
  ticket, latestActivity, activityEvents, allTickets, onClick, onOptimistic, onTicketClick,
}: SortableTicketCardProps) {
  // Prevent layout animation flash after drop
  const skipPostDrop: AnimateLayoutChanges = (args) =>
    args.active ? defaultAnimateLayoutChanges(args) : false

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: ticket.id, animateLayoutChanges: skipPostDrop })

  // Prevent flash when drop completes
  const wasDragging = useRef(false)
  const justDropped = wasDragging.current && !isDragging
  wasDragging.current = isDragging

  const style: React.CSSProperties = {
    transform: (isDragging || justDropped)
      ? 'translate3d(0, 0, 0)'
      : (transform ? CSS.Transform.toString(transform) : undefined),
    transition: justDropped ? 'none' : transition ?? undefined,
    opacity: isDragging ? 0 : 1,
    willChange: 'transform',
  }

  // Check dependencies
  const depsBlocked = ticket.depends_on.length > 0 && ticket.depends_on.some((depId) => {
    const dep = allTickets.get(depId)
    return !dep || dep.status !== 'merged'
  })

  const depLabels = ticket.depends_on.length > 0 ? ticket.depends_on.map((depId) => {
    const dep = allTickets.get(depId)
    return { id: depId, seq: dep?.seq, title: dep?.title, status: dep?.status || 'unknown' }
  }) : []

  const handleDepClick = (depId: string) => {
    const dep = allTickets.get(depId)
    if (dep && onTicketClick) onTicketClick(dep)
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <TicketCard
        ticket={ticket}
        latestActivity={latestActivity}
        activityEvents={activityEvents}
        onClick={onClick}
        onOptimistic={onOptimistic}
        depsBlocked={depsBlocked}
        depLabels={depLabels}
        onDepClick={handleDepClick}
      />
    </div>
  )
}
