import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { CheckSquare, ChevronDown, ChevronRight, Loader2, Play, Square, X } from 'lucide-react'
import { KanbanColumn } from '../kanban/KanbanColumn'
import { TicketCard } from '../kanban/TicketCard'
import { SortableTicketCard } from '../kanban/SortableTicketCard'
import { Button } from '../common/Button'
import { api } from '../../lib/api'
import { useIsMobile } from '../../hooks/useIsMobile'

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
  const isMobile = useIsMobile()
  const [mobileTab, setMobileTab] = useState<string>('todo')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [dragSource, setDragSource] = useState<'todo' | 'queue' | null>(null)
  const [todoOrder, setTodoOrder] = useState<string[] | null>(null)
  const [queueOrder, setQueueOrder] = useState<string[] | null>(null)
  const skipSyncRef = useRef(false)
  const skipQueueSyncRef = useRef(false)

  // Multi-select state
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkStarting, setBulkStarting] = useState(false)

  const sensors = useSensors(
    useSensor(SmartMouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
  )

  const todoColumn = columns.find((c) => c.status === 'todo')
  const todoTickets = todoColumn?.tickets || []
  const activeTodoTickets = useMemo(() => todoTickets.filter((t) => !t.archived && t.status === 'todo'), [todoTickets])
  const queuedTodoTickets = useMemo(() => todoTickets.filter((t) => !t.archived && t.status === 'queued'), [todoTickets])
  const archivedTodoTickets = useMemo(() => todoTickets.filter((t) => t.archived), [todoTickets])
  const [todoArchiveExpanded, setTodoArchiveExpanded] = useState(false)

  // Use local order during drag, fall back to column order (active only)
  const orderedTodoIds = todoOrder || activeTodoTickets.map((t) => t.id)
  const todoTicketMap = new Map(activeTodoTickets.map((t) => [t.id, t]))
  const orderedTodo = orderedTodoIds
    .map((id) => todoTicketMap.get(id))
    .filter((t): t is Ticket => !!t)

  // Queue order: local during drag, fall back to column order
  const queueTicketMap = useMemo(() => new Map(queuedTodoTickets.map((t) => [t.id, t])), [queuedTodoTickets])
  const orderedQueueIds = queueOrder || queuedTodoTickets.map((t) => t.id)
  const orderedQueue = orderedQueueIds
    .map((id) => queueTicketMap.get(id))
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

  // Sync external queue order when not dragging
  if (!activeId && !skipQueueSyncRef.current && queueOrder) {
    const externalIds = queuedTodoTickets.map((t) => t.id)
    const orderChanged = queueOrder.length !== externalIds.length ||
      queueOrder.some((id, i) => id !== externalIds[i])
    if (orderChanged) {
      setQueueOrder(null)
    }
  }
  if (skipQueueSyncRef.current && !activeId) {
    skipQueueSyncRef.current = false
  }

  const handleDragStart = useCallback((event: DragStartEvent) => {
    if (selectMode) return // Disable drag in select mode
    const id = event.active.id as string
    setActiveId(id)
    // Determine which section this item belongs to
    if (queueTicketMap.has(id)) {
      setDragSource('queue')
      setQueueOrder(queuedTodoTickets.map((t) => t.id))
    } else {
      setDragSource('todo')
      setTodoOrder(activeTodoTickets.map((t) => t.id))
    }
  }, [activeTodoTickets, queuedTodoTickets, queueTicketMap, selectMode])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    setActiveId(null)
    const source = dragSource
    setDragSource(null)

    if (!over || active.id === over.id) {
      setTodoOrder(null)
      setQueueOrder(null)
      return
    }

    if (source === 'queue' && queueOrder) {
      const oldIndex = queueOrder.indexOf(active.id as string)
      const newIndex = queueOrder.indexOf(over.id as string)
      if (oldIndex === -1 || newIndex === -1) {
        setQueueOrder(null)
        return
      }
      const newOrder = arrayMove(queueOrder, oldIndex, newIndex)
      setQueueOrder(newOrder)
      skipQueueSyncRef.current = true
      api.tickets.reorderQueue(newOrder).catch(() => {
        setQueueOrder(null)
      })
    } else if (source === 'todo' && todoOrder) {
      const oldIndex = todoOrder.indexOf(active.id as string)
      const newIndex = todoOrder.indexOf(over.id as string)
      if (oldIndex === -1 || newIndex === -1) {
        setTodoOrder(null)
        return
      }
      const newOrder = arrayMove(todoOrder, oldIndex, newIndex)
      setTodoOrder(newOrder)
      skipSyncRef.current = true
      if (activeProjectId) {
        api.tickets.reorder(activeProjectId, newOrder).catch(() => {
          setTodoOrder(null)
        })
      }
    }
  }, [todoOrder, queueOrder, dragSource, activeProjectId])

  const handleDragCancel = useCallback(() => {
    setActiveId(null)
    setDragSource(null)
    setTodoOrder(null)
    setQueueOrder(null)
  }, [])

  const activeTicket = activeId ? (todoTicketMap.get(activeId) || queueTicketMap.get(activeId)) : null
  const activeActivity = activeTicket ? activities.get(activeTicket.id) : undefined
  const activeLatest = activeActivity?.[activeActivity.length - 1]

  // Multi-select handlers
  const toggleSelect = useCallback((ticketId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(ticketId)) next.delete(ticketId)
      else next.add(ticketId)
      return next
    })
  }, [])

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(orderedTodo.filter((t) => t.status === 'todo').map((t) => t.id)))
  }, [orderedTodo])

  const exitSelectMode = useCallback(() => {
    setSelectMode(false)
    setSelectedIds(new Set())
  }, [])

  const handleBulkStart = useCallback(async () => {
    if (selectedIds.size === 0) return
    setBulkStarting(true)
    try {
      // Use the ordered list to maintain priority order
      const idsInOrder = orderedTodo
        .filter((t) => selectedIds.has(t.id))
        .map((t) => t.id)
      await api.tickets.bulkStart(idsInOrder)
      exitSelectMode()
    } catch {
      // Error handled by global handler
    } finally {
      setBulkStarting(false)
    }
  }, [selectedIds, orderedTodo, exitSelectMode])

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

        {/* Mobile column tabs */}
        {isMobile && (
          <div className="flex shrink-0 border-b border-[var(--color-border)]">
            {columns.map((col) => {
              const count = col.tickets.filter((t) => !t.archived).length
              return (
                <button
                  key={col.status}
                  onClick={() => setMobileTab(col.status)}
                  className={`flex-1 px-2 py-2 text-xs font-medium transition-colors ${
                    mobileTab === col.status
                      ? 'border-b-2 border-[var(--color-accent-blue)] text-[var(--color-accent-blue)]'
                      : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
                  }`}
                >
                  {col.label}
                  {count > 0 && <span className="ml-1 opacity-60">{count}</span>}
                </button>
              )
            })}
          </div>
        )}

        <div className={`flex flex-1 gap-4 overflow-x-auto p-4 ${isMobile ? 'flex-col' : ''}`}>
        {columns.filter((col) => !isMobile || col.status === mobileTab).map((col) => {
          if (col.status === 'todo') {
            return (
              <div key="todo" className={`flex flex-1 flex-col ${isMobile ? 'min-w-0' : 'min-w-[280px]'}`}>
                <div className="mb-3 flex items-center gap-2 px-1">
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                    {col.label}
                  </h2>
                  <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-bg-secondary)] px-1.5 text-xs text-[var(--color-text-muted)]">
                    {orderedTodo.length + queuedTodoTickets.length}
                  </span>
                  {/* Multi-select toggle */}
                  {activeTodoTickets.length > 0 && !selectMode && (
                    <button
                      onClick={() => setSelectMode(true)}
                      className="ml-auto rounded p-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-accent-blue)] hover:bg-[var(--color-bg-secondary)] transition-colors"
                      title="Select multiple"
                    >
                      <CheckSquare size={14} />
                    </button>
                  )}
                  {selectMode && (
                    <div className="ml-auto flex items-center gap-1">
                      <button
                        onClick={selectAll}
                        className="text-[10px] text-[var(--color-accent-blue)] hover:underline"
                      >
                        All
                      </button>
                      <button
                        onClick={() => setSelectedIds(new Set())}
                        className="text-[10px] text-[var(--color-text-muted)] hover:underline"
                      >
                        None
                      </button>
                      <button
                        onClick={exitSelectMode}
                        className="rounded p-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)] transition-colors"
                        title="Exit select mode"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  )}
                </div>

                {/* Bulk start button */}
                {selectMode && selectedIds.size > 0 && (
                  <div className="mb-2 px-1">
                    <Button
                      size="sm"
                      onClick={handleBulkStart}
                      disabled={bulkStarting}
                      className="w-full"
                    >
                      {bulkStarting ? (
                        <><Loader2 size={12} className="mr-1 animate-spin" /> Starting...</>
                      ) : (
                        <><Play size={12} className="mr-1" /> Start {selectedIds.size} Selected</>
                      )}
                    </Button>
                  </div>
                )}

                <div className="flex flex-col gap-2 overflow-y-auto px-1 pb-4">
                <SortableContext items={selectMode ? [] : orderedTodoIds} strategy={verticalListSortingStrategy}>
                    {orderedTodo.map((ticket) => {
                      const ticketActivities = activities.get(ticket.id)
                      const latest = ticketActivities?.[ticketActivities.length - 1]
                      if (selectMode) {
                        const isSelected = selectedIds.has(ticket.id)
                        return (
                          <div key={ticket.id} className="flex items-start gap-2">
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); toggleSelect(ticket.id) }}
                              className="mt-3 shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-accent-blue)] transition-colors"
                              data-no-dnd
                            >
                              {isSelected ? <CheckSquare size={16} className="text-[var(--color-accent-blue)]" /> : <Square size={16} />}
                            </button>
                            <div className="flex-1">
                              <TicketCard
                                ticket={ticket}
                                latestActivity={latest}
                                activityEvents={ticketActivities}
                                onClick={() => toggleSelect(ticket.id)}
                                onOptimistic={onOptimistic}
                              />
                            </div>
                          </div>
                        )
                      }
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

                {/* Queued tickets (drag-to-reorder) */}
                {orderedQueue.length > 0 && (
                  <div className="border-t border-dashed border-[var(--color-border)] pt-2 mt-1">
                    <span className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-muted)] opacity-60">Queue</span>
                  </div>
                )}
                <SortableContext items={selectMode ? [] : orderedQueueIds} strategy={verticalListSortingStrategy}>
                  {orderedQueue.map((ticket) => {
                    const ticketActivities = activities.get(ticket.id)
                    const latest = ticketActivities?.[ticketActivities.length - 1]
                    if (selectMode) {
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
                    }
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
              compact={isMobile}
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
