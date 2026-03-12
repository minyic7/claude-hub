import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Brain, FileText, Terminal, MessageSquare, AlertTriangle, CheckCircle, Info, XCircle, Eye, User, ClipboardCheck, Search } from 'lucide-react'
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

const filterableTypes = ['thinking', 'tool_use', 'tool_result', 'commentary', 'review', 'message', 'intervention'] as const

export function ActivityLog({ events }: ActivityLogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [userScrolledUp, setUserScrolledUp] = useState(false)
  const [, setTick] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [disabledTypes, setDisabledTypes] = useState<Set<string>>(new Set())

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
    const query = searchQuery.toLowerCase()
    return events.filter((event) => {
      if (disabledTypes.has(event.type)) return false
      if (query && !event.summary.toLowerCase().includes(query)) return false
      return true
    })
  }, [events, searchQuery, disabledTypes])

  useEffect(() => {
    if (!userScrolledUp) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [filteredEvents.length, userScrolledUp])

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
        {filteredEvents.map((event, i) => {
          const config = typeConfig[event.type] || typeConfig.info
          const Icon = config.icon
          const fullTime = new Date(event.timestamp).toLocaleString()
          const time = relativeTime(event.timestamp)
          const isAgent = event.source === 'ticket_agent'

          return (
            <div key={i} className={`flex items-start gap-2 rounded px-2 py-1 text-xs ${isAgent ? 'bg-[var(--color-accent-blue)]/5' : ''}`}>
              <Icon size={12} className={`mt-0.5 shrink-0 ${config.className}`} />
              <span className="shrink-0 cursor-default text-[var(--color-text-muted)]" title={fullTime}>{time}</span>
              <span className={`min-w-0 break-words ${event.type === 'error' ? 'text-[var(--color-accent-red)]' : 'text-[var(--color-text-secondary)]'}`}>
                {isAgent && event.type === 'commentary' && <span className="font-medium text-[var(--color-accent-purple)]">Tech Lead: </span>}
                {isAgent && event.type === 'intervention' && <span className="font-medium text-[var(--color-accent-yellow)]">Agent → CC: </span>}
                {isAgent && event.type === 'review' && <span className="font-medium text-[var(--color-accent-purple)]">Review: </span>}
                {isAgent && event.type !== 'commentary' && event.type !== 'intervention' && event.type !== 'review' && <span className="font-medium text-[var(--color-accent-blue)]">Agent: </span>}
                {event.source === 'user' && <span className="font-medium text-[var(--color-accent-green)]">You: </span>}
                {event.summary}
              </span>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
