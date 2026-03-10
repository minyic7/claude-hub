import type { Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import type { KanbanColumn as KanbanColumnType } from '../../hooks/useTickets'
import { KanbanColumn } from '../kanban/KanbanColumn'

interface KanbanBoardProps {
  columns: KanbanColumnType[]
  activities: Map<string, ActivityEvent[]>
  onTicketClick: (ticket: Ticket) => void
}

export function KanbanBoard({ columns, activities, onTicketClick }: KanbanBoardProps) {
  return (
    <div className="flex flex-1 gap-4 overflow-x-auto p-4">
      {columns.map((col) => (
        <KanbanColumn
          key={col.status}
          label={col.label}
          tickets={col.tickets}
          activities={activities}
          onTicketClick={onTicketClick}
        />
      ))}
    </div>
  )
}
