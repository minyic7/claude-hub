import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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

export function useAdaptiveColumns(columns: KanbanColumn[], containerWidth: number) {
  const visibleCount = clamp(Math.floor(containerWidth / COLUMN_MIN_WIDTH), 1, 4)

  // Active tab: the folded column currently swapped into view
  const [activeTab, setActiveTabRaw] = useState<TicketStatus | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      return stored as TicketStatus | null
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

  // When visibleCount increases, check if active tab column is now naturally visible
  useEffect(() => {
    if (visibleCount > prevVisibleCountRef.current && activeTab) {
      // Determine which columns would be visible without the tab swap
      const prioritized = [...COLUMN_PRIORITY]
      const naturallyVisible = prioritized.slice(0, visibleCount)
      if (naturallyVisible.includes(activeTab)) {
        setActiveTab(null)
      }
    }
    prevVisibleCountRef.current = visibleCount
  }, [visibleCount, activeTab, setActiveTab])

  const { visibleColumns, foldedColumns } = useMemo(() => {
    if (visibleCount >= columns.length) {
      return { visibleColumns: columns, foldedColumns: [] }
    }

    // Columns sorted by priority (highest priority first = kept visible longest)
    const prioritized = [...COLUMN_PRIORITY]

    // Pick the top `visibleCount` columns by priority
    const visibleStatuses = new Set(prioritized.slice(0, visibleCount))
    const foldedStatuses = new Set(prioritized.slice(visibleCount))

    // If there's an active tab, swap it in: add active tab to visible, remove the lowest-priority visible column
    if (activeTab && foldedStatuses.has(activeTab)) {
      // Find the lowest-priority column among visible ones (last in priority order that's visible)
      const visibleByPriority = prioritized.filter((s) => visibleStatuses.has(s))
      const displaced = visibleByPriority[visibleByPriority.length - 1]
      visibleStatuses.delete(displaced)
      visibleStatuses.add(activeTab)
      foldedStatuses.delete(activeTab)
      foldedStatuses.add(displaced)
    } else if (activeTab && visibleStatuses.has(activeTab)) {
      // Active tab is already visible naturally, clear it
      // (handled via effect above, but also handle here for safety)
    }

    // Maintain original column order for display
    const visible = columns.filter((c) => visibleStatuses.has(c.status))
    const folded = columns.filter((c) => foldedStatuses.has(c.status))

    return { visibleColumns: visible, foldedColumns: folded }
  }, [columns, visibleCount, activeTab])

  const handleTabClick = useCallback((status: TicketStatus) => {
    setActiveTab(activeTab === status ? null : status)
  }, [activeTab, setActiveTab])

  return {
    visibleColumns,
    foldedColumns,
    activeTab,
    onTabClick: handleTabClick,
  }
}
