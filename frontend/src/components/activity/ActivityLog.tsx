import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Brain, FileText, Terminal, MessageSquare, AlertTriangle, CheckCircle, Info, XCircle, Eye, User, ClipboardCheck, Search, ChevronRight, ChevronDown } from 'lucide-react'
import type { ActivityEvent } from '../../types/activity'
import { relativeTime } from '../../utils/relativeTime'

interface ActivityLogProps {
  events: ActivityEvent[]
}

const typeConfig: Record<string, { icon: typeof Brain; className: string; label: string }> = {
  thinking: { icon: Brain, className: 'text-[var(--color-text-muted)]', label: 'thinking' },
  tool_use: { icon: Terminal, className: 'text-[var(--color-accent-blue)]', label: 'tool_use' },
  tool_result: { icon: FileText, className: 'text-[var(--color-text-muted)]', label: 'tool_result' },
  commentary: { icon: Eye, className: 'text-[var(--color-accent-purple)]', label: 'commentary' },
  intervention: { icon: MessageSquare, className: 'text-[var(--color-accent-yellow)]', label: 'intervention' },
  decision: { icon: CheckCircle, className: 'text-[var(--color-accent-green)]', label: 'decision' },
  review: { icon: ClipboardCheck, className: 'text-[var(--color-accent-purple)]', label: 'review' },
  message: { icon: User, className: 'text-[var(--color-accent-green)]', label: 'message' },
  info: { icon: Info, className: 'text-[var(--color-text-muted)]', label: 'info' },
  warning: { icon: AlertTriangle, className: 'text-[var(--color-accent-yellow)]', label: 'warning' },
  error: { icon: XCircle, className: 'text-[var(--color-accent-red)]', label: 'error' },
}

const typeLabels: Record<string, { singular: string; plural: string }> = {
  thinking: { singular: 'thinking event', plural: 'thinking events' },
  tool_use: { singular: 'tool call', plural: 'tool calls' },
  tool_result: { singular: 'tool result', plural: 'tool results' },
  commentary: { singular: 'commentary', plural: 'commentaries' },
  intervention: { singular: 'intervention', plural: 'interventions' },
  decision: { singular: 'decision', plural: 'decisions' },
  review: { singular: 'review', plural: 'reviews' },
  message: { singular: 'message', plural: 'messages' },
  info: { singular: 'info event', plural: 'info events' },
  warning: { singular: 'warning', plural: 'warnings' },
  error: { singular: 'error', plural: 'errors' },
}

const COLLAPSE_THRESHOLD = 3

const filterableTypes = ['thinking', 'tool_use', 'tool_result', 'commentary', 'review', 'message', 'intervention'] as const

type GroupedItem =
  | { kind: 'single'; event: ActivityEvent; index: number }
  | { kind: 'group'; type: string; events: ActivityEvent[]; startIndex: number }

function groupConsecutive(events: ActivityEvent[]): GroupedItem[] {
  const result: GroupedItem[] = []
  let i = 0
  while (i < events.length) {
    let j = i + 1
    while (j < events.length && events[j].type === events[i].type) j++
    const runLength = j - i
    if (runLength >= COLLAPSE_THRESHOLD) {
      result.push({ kind: 'group', type: events[i].type, events: events.slice(i, j), startIndex: i })
    } else {
      for (let k = i; k < j; k++) {
        result.push({ kind: 'single', event: events[k], index: k })
      }
    }
    i = j
  }
  return result
}

function EventRow({ event, isAgent }: { event: ActivityEvent; isAgent: boolean }) {
  const config = typeConfig[event.type] || typeConfig.info
  const Icon = config.icon
  const fullTime = new Date(event.timestamp).toLocaleString()
  const time = relativeTime(event.timestamp)

  return (
    <div className={`flex items-start gap-2 rounded px-2 py-1 text-xs ${isAgent ? 'bg-[var(--color-accent-blue)]/5' : ''}`}>
      <Icon size={12} className={`mt-0.5 shrink-0 ${config.className}`} />
      <span className="shrink-0 cursor-default text-[var(--color-text-muted)]" title={fullTime}>{time}</span>
      <span className={`min-w-0 break-words ${event.type === 'error' ? 'text-[var(--color-accent-red)]' : 'text-[var(--color-text-secondary)]'}`}>
        {isAgent && event.type === 'intervention' && <span className="font-medium text-[var(--color-accent-purple)]">TicketAgent → CC: </span>}
        {isAgent && event.type !== 'intervention' && <span className="font-medium text-[var(--color-accent-purple)]">TicketAgent: </span>}
        {event.source === 'user' && <span className="font-medium text-[var(--color-accent-green)]">You: </span>}
        {event.summary}
      </span>
    </div>
  )
}

export function ActivityLog({ events }: ActivityLogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [userScrolledUp, setUserScrolledUp] = useState(false)
  const [, setTick] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [disabledTypes, setDisabledTypes] = useState<Set<string>>(new Set())
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(new Set())

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000)
    return () => clearInterval(id)
  }, [])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setUserScrolledUp(!atBottom)
  }, [])

  const filteredEvents = useMemo(() => {
    return events.filter((event) => {
      if (disabledTypes.has(event.type)) return false
      return true
    })
  }, [events, disabledTypes])

  const query = searchQuery.toLowerCase()

  const grouped = useMemo(() => groupConsecutive(filteredEvents), [filteredEvents])

  // Determine which groups should auto-expand due to search matches
  const searchExpandedGroups = useMemo(() => {
    if (!query) return new Set<number>()
    const set = new Set<number>()
    for (const item of grouped) {
      if (item.kind === 'group' && item.events.some((e) => e.summary.toLowerCase().includes(query))) {
        set.add(item.startIndex)
      }
    }
    return set
  }, [grouped, query])

  // Filter out single events that don't match search, and track visible groups
  const visibleItems = useMemo(() => {
    if (!query) return grouped
    return grouped.filter((item) => {
      if (item.kind === 'single') return item.event.summary.toLowerCase().includes(query)
      // Groups: show if any event matches
      return item.events.some((e) => e.summary.toLowerCase().includes(query))
    })
  }, [grouped, query])

  useEffect(() => {
    if (!userScrolledUp) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [visibleItems.length, userScrolledUp])

  const toggleType = useCallback((type: string) => {
    setDisabledTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) {
        next.delete(type)
      } else {
        next.add(type)
      }
      return next
    })
  }, [])

  const toggleGroup = useCallback((startIndex: number) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(startIndex)) {
        next.delete(startIndex)
      } else {
        next.add(startIndex)
      }
      return next
    })
  }, [])

  if (events.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--color-text-muted)]">
        No activity yet
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2 overflow-hidden">
      {/* Search box */}
      <div className="relative shrink-0">
        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
        <input
          type="text"
          placeholder="Search activity..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] py-1 pl-7 pr-2 text-xs text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)] outline-none focus:border-[var(--color-accent-blue)]"
        />
      </div>

      {/* Type filter chips */}
      <div className="flex shrink-0 flex-wrap gap-1">
        {filterableTypes.map((type) => {
          const config = typeConfig[type]
          const Icon = config.icon
          const active = !disabledTypes.has(type)
          return (
            <button
              key={type}
              onClick={() => toggleType(type)}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-opacity ${
                active
                  ? `border-[var(--color-border)] ${config.className} opacity-100`
                  : 'border-transparent text-[var(--color-text-muted)] opacity-40'
              }`}
              title={`${active ? 'Hide' : 'Show'} ${type} events`}
            >
              <Icon size={10} />
              {type}
            </button>
          )
        })}
      </div>

      {/* Event list */}
      <div ref={containerRef} onScroll={handleScroll} className="flex flex-col gap-1 overflow-y-auto">
        {visibleItems.map((item) => {
          if (item.kind === 'single') {
            return <EventRow key={`e-${item.index}`} event={item.event} isAgent={item.event.source === 'ticket_agent'} />
          }

          const { type, events: groupEvents, startIndex } = item
          const isExpanded = expandedGroups.has(startIndex) || searchExpandedGroups.has(startIndex)
          const config = typeConfig[type] || typeConfig.info
          const Icon = config.icon
          const count = groupEvents.length
          const labels = typeLabels[type] || { singular: type, plural: `${type}s` }
          const label = count === 1 ? labels.singular : labels.plural
          const firstTime = relativeTime(groupEvents[0].timestamp)
          const lastTime = relativeTime(groupEvents[groupEvents.length - 1].timestamp)
          const timeRange = firstTime === lastTime ? firstTime : `${firstTime} .. ${lastTime}`

          return (
            <div key={`g-${startIndex}`}>
              <button
                onClick={() => toggleGroup(startIndex)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-xs hover:bg-[var(--color-bg-secondary)] transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown size={12} className="shrink-0 text-[var(--color-text-muted)]" />
                ) : (
                  <ChevronRight size={12} className="shrink-0 text-[var(--color-text-muted)]" />
                )}
                <Icon size={12} className={`shrink-0 ${config.className}`} />
                <span className="shrink-0 text-[var(--color-text-muted)]">{timeRange}</span>
                <span className="text-[var(--color-text-secondary)]">
                  {count} {label}
                </span>
              </button>
              {isExpanded && (
                <div className="ml-4 flex flex-col gap-1 border-l border-[var(--color-border)] pl-1">
                  {groupEvents.map((event, i) => (
                    <EventRow key={`g-${startIndex}-${i}`} event={event} isAgent={event.source === 'ticket_agent'} />
                  ))}
                </div>
              )}
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
