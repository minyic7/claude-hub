import { useEffect, useRef, useState, useCallback } from 'react'
import { Bot, ArrowUpCircle, MessageSquare, Clock, Eye, EyeOff } from 'lucide-react'
import { api } from '../../lib/api'

export interface SupervisorEvent {
  timestamp: string
  cc_summary: string
  cc_asked_for: string | null
  action: 'wait' | 'send' | 'trigger'
  message: string | null
  reason: string
}

interface PilotAgentPanelProps {
  projectId: string
  visible: boolean
}

const ACTION_CONFIG = {
  trigger: { label: 'TRIGGERED', color: 'text-purple-400', bg: 'bg-purple-500/15', icon: ArrowUpCircle },
  send: { label: 'RESPONDED', color: 'text-blue-400', bg: 'bg-blue-500/15', icon: MessageSquare },
  wait: { label: 'WAITING', color: 'text-[var(--color-text-muted)]', bg: 'bg-[var(--color-bg-secondary)]', icon: Clock },
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function SupervisorEventCard({ event }: { event: SupervisorEvent }) {
  const config = ACTION_CONFIG[event.action] || ACTION_CONFIG.wait
  const Icon = config.icon

  return (
    <div className="border-b border-[var(--color-border)]/30 px-3 py-2.5">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-mono text-[var(--color-text-muted)]">{formatTime(event.timestamp)}</span>
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${config.color} ${config.bg}`}>
          <Icon size={10} />
          {config.label}
        </span>
      </div>

      <p className="text-xs text-[var(--color-text-primary)] leading-relaxed">
        {event.cc_summary}
      </p>

      {event.cc_asked_for && (
        <p className="mt-1 text-xs text-[var(--color-accent-yellow)]">
          CC asked for: {event.cc_asked_for}
        </p>
      )}

      {event.action === 'send' && event.message && (
        <div className="mt-1.5 rounded bg-blue-500/10 px-2 py-1 text-xs text-blue-300 font-mono">
          → {event.message}
        </div>
      )}

      <p className="mt-1 text-[10px] text-[var(--color-text-muted)] italic">
        {event.reason}
      </p>
    </div>
  )
}

export function PilotAgentPanel({ projectId, visible }: PilotAgentPanelProps) {
  const [events, setEvents] = useState<SupervisorEvent[]>([])
  const [showWaiting, setShowWaiting] = useState(false)
  const [loading, setLoading] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoScroll = useRef(true)

  // Load initial events
  useEffect(() => {
    if (!visible || !projectId) return
    setLoading(true)
    api.projects.getSupervisorEvents(projectId)
      .then(setEvents)
      .catch(() => setEvents([]))
      .finally(() => setLoading(false))
  }, [projectId, visible])

  // Listen for new events via custom event (dispatched from useWebSocket)
  useEffect(() => {
    if (!visible) return

    const handler = (e: CustomEvent<SupervisorEvent & { project_id: string }>) => {
      if (e.detail.project_id !== projectId) return
      setEvents(prev => [...prev.slice(-199), e.detail])
    }

    window.addEventListener('supervisor_event', handler as EventListener)
    return () => window.removeEventListener('supervisor_event', handler as EventListener)
  }, [projectId, visible])

  // Auto-scroll
  useEffect(() => {
    if (autoScroll.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events])

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    autoScroll.current = scrollHeight - scrollTop - clientHeight < 40
  }, [])

  const filtered = showWaiting ? events : events.filter(e => e.action !== 'wait')

  if (!visible) return null

  return (
    <div className="flex h-full flex-col bg-[#1a1b26]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <Bot size={14} className="text-purple-400" />
          <span className="text-xs font-semibold text-[var(--color-text-muted)]">Pilot Agent</span>
          <span className="text-[10px] text-[var(--color-text-muted)]/60 font-mono">
            {filtered.length} events
          </span>
        </div>
        <button
          onClick={() => setShowWaiting(!showWaiting)}
          className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors ${
            showWaiting
              ? 'bg-[var(--color-accent-blue)]/15 text-[var(--color-accent-blue)]'
              : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
          }`}
          title={showWaiting ? 'Hide waiting events' : 'Show all ticks'}
        >
          {showWaiting ? <EyeOff size={10} /> : <Eye size={10} />}
          {showWaiting ? 'Hide waits' : 'Show all'}
        </button>
      </div>

      {/* Events list */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <span className="text-xs text-[var(--color-text-muted)] animate-pulse">Loading...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <Bot size={24} className="text-[var(--color-text-muted)]/30" />
            <p className="text-xs text-[var(--color-text-muted)]">
              No supervisor events yet.
            </p>
            <p className="text-[10px] text-[var(--color-text-muted)]/60">
              Events will appear when Pilot Mode is active.
            </p>
          </div>
        ) : (
          filtered.map((event, i) => (
            <SupervisorEventCard key={`${event.timestamp}-${i}`} event={event} />
          ))
        )}
      </div>
    </div>
  )
}
