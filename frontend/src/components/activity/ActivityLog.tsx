import { useCallback, useEffect, useRef, useState } from 'react'
import { Brain, FileText, Terminal, MessageSquare, AlertTriangle, CheckCircle, Info, XCircle } from 'lucide-react'
import type { ActivityEvent } from '../../types/activity'
import { relativeTime } from '../../utils/relativeTime'

interface ActivityLogProps {
  events: ActivityEvent[]
}

const typeConfig: Record<string, { icon: typeof Brain; className: string }> = {
  thinking: { icon: Brain, className: 'text-[var(--color-text-muted)]' },
  tool_use: { icon: Terminal, className: 'text-[var(--color-accent-blue)]' },
  tool_result: { icon: FileText, className: 'text-[var(--color-text-muted)]' },
  intervention: { icon: MessageSquare, className: 'text-[var(--color-accent-yellow)]' },
  decision: { icon: CheckCircle, className: 'text-[var(--color-accent-green)]' },
  info: { icon: Info, className: 'text-[var(--color-text-muted)]' },
  warning: { icon: AlertTriangle, className: 'text-[var(--color-accent-yellow)]' },
  error: { icon: XCircle, className: 'text-[var(--color-accent-red)]' },
}

export function ActivityLog({ events }: ActivityLogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [userScrolledUp, setUserScrolledUp] = useState(false)
  const [, setTick] = useState(0)

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

  useEffect(() => {
    if (!userScrolledUp) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [events.length, userScrolledUp])

  if (events.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--color-text-muted)]">
        No activity yet
      </p>
    )
  }

  return (
    <div ref={containerRef} onScroll={handleScroll} className="flex flex-col gap-1 overflow-y-auto">
      {events.map((event, i) => {
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
              {isAgent && <span className="font-medium text-[var(--color-accent-blue)]">Agent: </span>}
              {event.summary}
            </span>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
