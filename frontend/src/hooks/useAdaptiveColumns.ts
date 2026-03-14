import { useCallback, useMemo, useRef, useState } from 'react'
import type { KanbanColumn } from './useTickets'
import type { TicketStatus } from '../types/ticket'

const COLUMN_MIN_WIDTH = 260
const STORAGE_KEY = 'kanban-active-tab'

// Priority order: kept visible longest → folded first
// todo (highest priority to keep) → in_progress → review → merged (first to fold)
const COLUMN_PRIORITY: TicketStatus[] = ['todo', 'in_progress', 'review', 'merged']

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function useAdaptiveColumns(columns: KanbanColumn[], containerWidth: number, isMobile = false) {
  const visibleCount = isMobile ? 1 : clamp(Math.floor(containerWidth / COLUMN_MIN_WIDTH), 1, 4)

  // Active tab: the folded column currently swapped into view
  const [activeTab, setActiveTabRaw] = useState<TicketStatus | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored && COLUMN_PRIORITY.includes(stored as TicketStatus)) {
        return stored as TicketStatus
      }
      return null
    } catch {
      return null
    }
  })

  const prevVisibleCountRef = useRef(visibleCount)

  // Persist active tab
  const setActiveTab = useCallback((tab: TicketStatus | null) => {
    setActiveTabRaw(tab)
    try {
      if (tab) {
        localStorage.setItem(STORAGE_KEY, tab)
      } else {
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch {
      // localStorage unavailable
    }
  }, [])

  // When visibleCount increases, clear activeTab if that column is now naturally visible.
  // This effect uses a state updater so clearance is applied before the next render's
  // memoization, preventing the same column from appearing in both board and tab bar.
  const currentVisibleCount = visibleCount
  if (currentVisibleCount > prevVisibleCountRef.current) {
    const naturallyVisible = COLUMN_PRIORITY.slice(0, currentVisibleCount)
    setActiveTabRaw((prev) => {
      if (prev && naturallyVisible.includes(prev)) {
        try { localStorage.removeItem(STORAGE_KEY) } catch { /* */ }
        return null
      }
      return prev
    })
  }
  prevVisibleCountRef.current = currentVisibleCount

  // Invariant: exactly one column can be swapped in via activeTab.
  // When activeTab is set and it's a folded column, it replaces the lowest-priority
  // visible column (the last one in the visibleByPriority list).
  const { visibleColumns, foldedColumns } = useMemo(() => {
    if (visibleCount >= columns.length) {
      return { visibleColumns: columns, foldedColumns: [] }
    }

    const visibleStatuses = new Set(COLUMN_PRIORITY.slice(0, visibleCount))
    const foldedStatuses = new Set(COLUMN_PRIORITY.slice(visibleCount))

    // Swap activeTab into visible set if it's currently folded
    if (activeTab && foldedStatuses.has(activeTab)) {
      // Displace the lowest-priority visible column (rightmost in priority order)
      const visibleByPriority = COLUMN_PRIORITY.filter((s) => visibleStatuses.has(s))
      const displaced = visibleByPriority[visibleByPriority.length - 1]
      visibleStatuses.delete(displaced)
      visibleStatuses.add(activeTab)
      foldedStatuses.delete(activeTab)
      foldedStatuses.add(displaced)
    }

    // Maintain original column order for display
    const visible = columns.filter((c) => visibleStatuses.has(c.status))
    const folded = columns.filter((c) => foldedStatuses.has(c.status))

    return { visibleColumns: visible, foldedColumns: folded }
  }, [columns, visibleCount, activeTab])

  // Clicking a tab always activates it (no toggle). This ensures the user can
  // always see the column they clicked on.
  const handleTabClick = useCallback((status: TicketStatus) => {
    setActiveTab(status)
  }, [setActiveTab])

  return {
    visibleColumns,
    foldedColumns,
    activeTab,
    onTabClick: handleTabClick,
  }
}
