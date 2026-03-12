import { useCallback, useMemo, useRef, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  closestCenter,
  defaultDropAnimationSideEffects,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, arrayMove } from '@dnd-kit/sortable'
import type { BranchType, Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import type { KanbanColumn as KanbanColumnType } from '../../hooks/useTickets'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { KanbanColumn } from '../kanban/KanbanColumn'
import { TicketCard } from '../kanban/TicketCard'
import { SortableTicketCard } from '../kanban/SortableTicketCard'
import { api } from '../../lib/api'

// Prevent drag from starting on buttons or interactive elements
class SmartMouseSensor extends MouseSensor {
  static activators = [
    {
      eventName: 'onMouseDown' as const,
      handler: ({ nativeEvent: e }: { nativeEvent: MouseEvent }) => {
        return e.button === 0 && !(e.target as HTMLElement).closest('button, a, input, [data-no-dnd]')
      },
    },
  ]
}

interface KanbanBoardProps {
  columns: KanbanColumnType[]
  activities: Map<string, ActivityEvent[]>
  allTickets: Map<string, Ticket>
  activeProjectId: string | null
  onTicketClick: (ticket: Ticket) => void
  onOptimistic?: (ticketId: string, patch: Partial<Ticket>) => void
  deployingBranches?: Set<string>
  mergeQueueLocked?: boolean
  onMergeInitiated?: () => void
  branchTypeFilter?: BranchType | null
  onBranchTypeFilter?: (type: BranchType | null) => void
}

const BRANCH_TYPES: BranchType[] = ['feature', 'bugfix', 'hotfix', 'chore', 'refactor', 'docs', 'test']

export function KanbanBoard({
  columns, activities, allTickets, activeProjectId, onTicketClick, onOptimistic, deployingBranches, mergeQueueLocked, onMergeInitiated, branchTypeFilter, onBranchTypeFilter,
}: KanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [todoOrder, setTodoOrder] = useState<string[] | null>(null)
  const skipSyncRef = useRef(false)

  const sensors = useSensors(
    useSensor(SmartMouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
  )

  const todoColumn = columns.find((c) => c.status === 'todo')
  const todoTickets = todoColumn?.tickets || []
  const activeTodoTickets = useMemo(() => todoTickets.filter((t) => !t.archived), [todoTickets])
  const archivedTodoTickets = useMemo(() => todoTickets.filter((t) => t.archived), [todoTickets])
  const [todoArchiveExpanded, setTodoArchiveExpanded] = useState(false)

  // Use local order during drag, fall back to column order (active only)
  const orderedTodoIds = todoOrder || activeTodoTickets.map((t) => t.id)
  const todoTicketMap = new Map(activeTodoTickets.map((t) => [t.id, t]))
  const orderedTodo = orderedTodoIds
    .map((id) => todoTicketMap.get(id))
    .filter((t): t is Ticket => !!t)

  // Sync external order when not dragging
  if (!activeId && !skipSyncRef.current && todoOrder) {
    const externalIds = activeTodoTickets.map((t) => t.id)
    const orderChanged = todoOrder.length !== externalIds.length ||
      todoOrder.some((id, i) => id !== externalIds[i])
    if (orderChanged) {
      // Server pushed new order, accept it
      setTodoOrder(null)
    }
  }
  if (skipSyncRef.current && !activeId) {
    skipSyncRef.current = false
  }

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(event.active.id as string)
    // Initialize local order from current
    setTodoOrder(activeTodoTickets.map((t) => t.id))
  }, [activeTodoTickets])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    setActiveId(null)

    if (!over || active.id === over.id || !todoOrder) {
      setTodoOrder(null)
      return
    }

    const oldIndex = todoOrder.indexOf(active.id as string)
    const newIndex = todoOrder.indexOf(over.id as string)
    if (oldIndex === -1 || newIndex === -1) {
      setTodoOrder(null)
      return
    }

    const newOrder = arrayMove(todoOrder, oldIndex, newIndex)
    setTodoOrder(newOrder)
    skipSyncRef.current = true

    // Persist to backend
    if (activeProjectId) {
      api.tickets.reorder(activeProjectId, newOrder).catch(() => {
        setTodoOrder(null)
      })
    }
  }, [todoOrder, activeProjectId])

  const handleDragCancel = useCallback(() => {
    setActiveId(null)
    setTodoOrder(null)
  }, [])

  const activeTicket = activeId ? todoTicketMap.get(activeId) : null
  const activeActivity = activeTicket ? activities.get(activeTicket.id) : undefined
  const activeLatest = activeActivity?.[activeActivity.length - 1]

  // Compute branch type counts from all tickets for filter chips
  const branchTypeCounts = useMemo(() => {
    const counts = new Map<BranchType, number>()
    allTickets.forEach((t) => {
      counts.set(t.branch_type, (counts.get(t.branch_type) || 0) + 1)
    })
    return counts
  }, [allTickets])

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Branch type filter bar */}
        {onBranchTypeFilter && (
          <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-[var(--color-border)] px-5 py-2">
            <span className="mr-1 text-xs text-[var(--color-text-muted)]">Filter:</span>
            {BRANCH_TYPES.filter((bt) => branchTypeCounts.has(bt)).map((bt) => {
              const active = branchTypeFilter === bt
              return (
                <button
                  key={bt}
                  onClick={() => onBranchTypeFilter(active ? null : bt)}
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                    active
                      ? 'bg-[var(--color-accent-blue)] text-white'
                      : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
                  }`}
                >
                  {bt}
                  <span className="ml-1 opacity-60">{branchTypeCounts.get(bt)}</span>
                </button>
              )
            })}
            {branchTypeFilter && (
              <button
                onClick={() => onBranchTypeFilter(null)}
                className="ml-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
              >
                Clear
              </button>
            )}
          </div>
        )}

        <div className="flex flex-1 gap-4 overflow-x-auto p-4">
        {columns.map((col) => {
          if (col.status === 'todo') {
            return (
              <div key="todo" className="flex min-w-[280px] flex-1 flex-col">
                <div className="mb-3 flex items-center gap-2 px-1">
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                    {col.label}
                  </h2>
                  <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-bg-secondary)] px-1.5 text-xs text-[var(--color-text-muted)]">
                    {orderedTodo.length}
                  </span>
                </div>
                <div className="flex flex-col gap-2 overflow-y-auto px-1 pb-4">
                <SortableContext items={orderedTodoIds} strategy={verticalListSortingStrategy}>
                    {orderedTodo.map((ticket) => {
                      const ticketActivities = activities.get(ticket.id)
                      const latest = ticketActivities?.[ticketActivities.length - 1]
                      return (
                        <SortableTicketCard
                          key={ticket.id}
                          ticket={ticket}
                          latestActivity={latest}
                          activityEvents={ticketActivities}
                          allTickets={allTickets}
                          onClick={() => onTicketClick(ticket)}
                          onOptimistic={onOptimistic}
                          onTicketClick={onTicketClick}
                        />
                      )
                    })}
                </SortableContext>

                {archivedTodoTickets.length > 0 && (
                  <>
                    <button
                      onClick={() => setTodoArchiveExpanded(!todoArchiveExpanded)}
                      className="flex items-center gap-1.5 rounded px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
                    >
                      {todoArchiveExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      <span>{todoArchiveExpanded ? 'Hide' : 'Show'} {archivedTodoTickets.length} archived</span>
                    </button>
                    {todoArchiveExpanded && archivedTodoTickets.map((ticket) => {
                      const ticketActivities = activities.get(ticket.id)
                      const latest = ticketActivities?.[ticketActivities.length - 1]
                      return (
                        <TicketCard
                          key={ticket.id}
                          ticket={ticket}
                          latestActivity={latest}
                          activityEvents={ticketActivities}
                          onClick={() => onTicketClick(ticket)}
                          onOptimistic={onOptimistic}
                        />
                      )
                    })}
                  </>
                )}
              </div>
              </div>
            )
          }
          return (
            <KanbanColumn
              key={col.status}
              label={col.label}
              tickets={col.tickets}
              activities={activities}
              onTicketClick={onTicketClick}
              onOptimistic={onOptimistic}
              deployingBranches={deployingBranches}
              mergeQueueLocked={mergeQueueLocked}
              onMergeInitiated={onMergeInitiated}
            />
          )
        })}
        </div>
      </div>

      <DragOverlay
        dropAnimation={{
          duration: 180,
          easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
          sideEffects: defaultDropAnimationSideEffects({
            styles: { active: { opacity: '0' } },
          }),
        }}
      >
        {activeTicket && (
          <div className="rotate-[2deg] scale-[1.02] opacity-95">
            <TicketCard
              ticket={activeTicket}
              latestActivity={activeLatest}
              activityEvents={activeActivity}
              onClick={() => {}}
              onOptimistic={onOptimistic}
            />
          </div>
        )}
      </DragOverlay>
    </DndContext>
  )
}
