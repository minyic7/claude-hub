import { useEffect, useRef, useState, useCallback } from 'react'
import { Bot, MessageSquare, Clock, ChevronUp, ChevronDown, Zap, AlertTriangle, Send, User } from 'lucide-react'
import { api } from '../../lib/api'

export interface SupervisorEvent {
  timestamp: string
  cc_summary: string
  action: 'wait' | 'message' | 'user_message' | 'user_relay'
  message: string | null
  reason: string
  wait_seconds?: number
}

interface PilotStatusBarProps {
  projectId: string
  pilotMode: boolean
  onNudge: () => void
}

// ── Helpers ────────────────────────────────────────────────────

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function formatAgo(ts: string): string {
  const seconds = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.floor(minutes / 60)}h ago`
}

function deriveCC(event: SupervisorEvent | null): { label: string; color: string; stale: boolean } {
  if (!event) return { label: 'no data', color: 'text-[var(--color-text-muted)]', stale: false }

  const summary = event.cc_summary.toLowerCase()
  const age = (Date.now() - new Date(event.timestamp).getTime()) / 1000

  // If pilot sent a message, CC is likely processing it
  if (event.action === 'message' && age < 15) {
    return { label: 'processing message', color: 'text-blue-400', stale: false }
  }

  // Detect idle from summary keywords
  if (summary.includes('idle') || summary.includes('waiting for') || summary.includes('prompt')) {
    return { label: 'idle at prompt', color: age > 60 ? 'text-amber-400' : 'text-emerald-400', stale: age > 60 }
  }

  // Detect working
  if (summary.includes('working') || summary.includes('running') || summary.includes('editing') || summary.includes('executing')) {
    return { label: 'working', color: 'text-blue-400', stale: false }
  }

  // Detect started tasks
  if (summary.includes('started') || summary.includes('in_progress') || summary.includes('in progress')) {
    return { label: 'managing tasks', color: 'text-blue-400', stale: false }
  }

  return { label: 'active', color: 'text-emerald-400', stale: false }
}

// ── Event Log Item ─────────────────────────────────────────────

function EventRow({ event, collapsed }: { event: SupervisorEvent; collapsed?: number }) {
  const isMessage = event.action === 'message'
  const isUserMessage = event.action === 'user_message'
  const isUserRelay = event.action === 'user_relay'
  const isHighlighted = isMessage || isUserMessage || isUserRelay

  return (
    <div className={`flex items-start gap-2 px-3 py-1.5 ${isUserMessage || isUserRelay ? 'bg-emerald-500/8' : isMessage ? 'bg-blue-500/5' : ''}`}>
      <span className="shrink-0 mt-0.5 text-[10px] font-mono text-[var(--color-text-muted)]/60 w-[60px]">
        {formatTime(event.timestamp)}
      </span>
      {isUserMessage ? (
        <User size={11} className="shrink-0 mt-0.5 text-emerald-400" />
      ) : isUserRelay ? (
        <Send size={11} className="shrink-0 mt-0.5 text-emerald-400" />
      ) : isMessage ? (
        <MessageSquare size={11} className="shrink-0 mt-0.5 text-blue-400" />
      ) : (
        <Clock size={11} className="shrink-0 mt-0.5 text-[var(--color-text-muted)]/40" />
      )}
      <div className="min-w-0 flex-1">
        {isUserMessage && event.message ? (
          <p className="text-xs text-emerald-300 break-words whitespace-pre-wrap">
            <span className="text-emerald-400/60 text-[10px]">you → pilot: </span>{event.message}
          </p>
        ) : isUserRelay && event.message ? (
          <p className="text-xs text-emerald-300 break-words whitespace-pre-wrap">
            <span className="text-emerald-400/60 text-[10px]">pilot → CC: </span>{event.message}
          </p>
        ) : isHighlighted && event.message ? (
          <p className="text-xs text-blue-300 break-words whitespace-pre-wrap">{event.message}</p>
        ) : (
          <p className="text-xs text-[var(--color-text-muted)]/70 break-words whitespace-pre-wrap">
            {event.cc_summary}
            {collapsed && collapsed > 1 && (
              <span className="ml-1 text-[10px] text-[var(--color-text-muted)]/40">({collapsed}x)</span>
            )}
          </p>
        )}
      </div>
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────

export function PilotStatusBar({ projectId, pilotMode, onNudge }: PilotStatusBarProps) {
  const [events, setEvents] = useState<SupervisorEvent[]>([])
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [nudging, setNudging] = useState(false)
  const [messageText, setMessageText] = useState('')
  const [sending, setSending] = useState(false)
  const [, setTick] = useState(0) // force re-render for "ago" timer
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const autoScroll = useRef(true)

  // Load initial events
  useEffect(() => {
    if (!pilotMode || !projectId) return
    setLoading(true)
    api.projects.getSupervisorEvents(projectId)
      .then(setEvents)
      .catch(() => setEvents([]))
      .finally(() => setLoading(false))
  }, [projectId, pilotMode])

  // Listen for new events
  useEffect(() => {
    if (!pilotMode) return

    const handler = (e: CustomEvent<SupervisorEvent & { project_id: string }>) => {
      if (e.detail.project_id !== projectId) return
      setEvents(prev => [...prev.slice(-199), e.detail])
    }

    window.addEventListener('supervisor_event', handler as EventListener)
    return () => window.removeEventListener('supervisor_event', handler as EventListener)
  }, [projectId, pilotMode])

  // Update "ago" timer every 5s
  useEffect(() => {
    if (!pilotMode) return
    const id = setInterval(() => setTick(t => t + 1), 5000)
    return () => clearInterval(id)
  }, [pilotMode])

  // Auto-scroll when expanded
  useEffect(() => {
    if (expanded && autoScroll.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, expanded])

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    autoScroll.current = scrollHeight - scrollTop - clientHeight < 40
  }, [])

  const handleNudge = useCallback(async () => {
    setNudging(true)
    try {
      await onNudge()
    } finally {
      setTimeout(() => setNudging(false), 2000)
    }
  }, [onNudge])

  const handleSendMessage = useCallback(async () => {
    const text = messageText.trim()
    if (!text || sending) return
    setSending(true)
    try {
      await api.projects.sendPilotMessage(projectId, text)
      setMessageText('')
    } catch {
      // Error will show via supervisor event
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }, [messageText, sending, projectId])

  if (!pilotMode) return null

  const latest = events.length > 0 ? events[events.length - 1] : null
  const ccStatus = deriveCC(latest)

  // Derive pilot status
  const lastMessageEvent = [...events].reverse().find(e => e.action === 'message')
  const lastMessageAgo = lastMessageEvent ? formatAgo(lastMessageEvent.timestamp) : null
  const latestAge = latest ? (Date.now() - new Date(latest.timestamp).getTime()) / 1000 : 0
  const isStalled = latest && latest.action === 'wait' && latestAge > 90

  // Collapse consecutive waits for log view
  const collapsedEvents = collapseWaits(events)

  return (
    <div className="flex flex-col border-t border-[var(--color-border)] bg-[#1e1f2e] shrink-0">
      {/* ── Status Bar (always visible) ── */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-3 px-3 py-1.5 hover:bg-[#252638] transition-colors w-full text-left"
      >
        {/* Pilot indicator */}
        <div className="flex items-center gap-1.5">
          <Bot size={12} className={isStalled ? 'text-amber-400 animate-pulse' : 'text-purple-400'} />
          <span className="text-[10px] font-semibold text-purple-400/80">PILOT</span>
        </div>

        {/* CC Status */}
        <div className="flex items-center gap-1.5">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${
            ccStatus.stale ? 'bg-amber-400 animate-pulse' : ccStatus.color.includes('emerald') ? 'bg-emerald-400' : 'bg-blue-400 animate-pulse'
          }`} />
          <span className={`text-[10px] ${ccStatus.color}`}>
            CC: {ccStatus.label}
          </span>
        </div>

        {/* Divider */}
        <span className="text-[var(--color-border)]">|</span>

        {/* Last action */}
        <div className="flex-1 min-w-0">
          {loading ? (
            <span className="text-[10px] text-[var(--color-text-muted)] animate-pulse">Loading...</span>
          ) : latest ? (
            <span className="text-[10px] text-[var(--color-text-muted)] truncate block">
              {latest.action === 'message' && latest.message ? (
                <>
                  <span className="text-blue-400">sent</span>{' '}
                  <span className="text-[var(--color-text-primary)]/70">"{latest.message.slice(0, 60)}{latest.message.length > 60 ? '...' : ''}"</span>
                </>
              ) : (
                <>
                  <span className="text-[var(--color-text-muted)]/60">watching</span>{' '}
                  <span className="text-[var(--color-text-muted)]/40">— {latest.reason.slice(0, 60)}</span>
                </>
              )}
              <span className="text-[var(--color-text-muted)]/40 ml-1">{formatAgo(latest.timestamp)}</span>
            </span>
          ) : (
            <span className="text-[10px] text-[var(--color-text-muted)]/40">Waiting for first tick...</span>
          )}
        </div>

        {/* Stall warning */}
        {isStalled && (
          <span className="flex items-center gap-1 text-[10px] text-amber-400 shrink-0">
            <AlertTriangle size={10} />
            stalled
          </span>
        )}

        {/* Last message indicator */}
        {lastMessageAgo && !isStalled && (
          <span className="text-[10px] text-[var(--color-text-muted)]/40 shrink-0">
            last msg {lastMessageAgo}
          </span>
        )}

        {/* Expand chevron */}
        {expanded ? <ChevronDown size={12} className="text-[var(--color-text-muted)] shrink-0" /> : <ChevronUp size={12} className="text-[var(--color-text-muted)] shrink-0" />}
      </button>

      {/* ── Expanded Event Log ── */}
      {expanded && (
        <div className="flex flex-col border-t border-[var(--color-border)]/50" style={{ maxHeight: '40vh' }}>
          {/* Log header */}
          <div className="flex items-center justify-between px-3 py-1 bg-[#1a1b26] shrink-0">
            <span className="text-[10px] text-[var(--color-text-muted)]/60 font-mono">
              {events.length} events
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); handleNudge() }}
              disabled={nudging}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-purple-400 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
              title="Force Pilot to check now"
            >
              <Zap size={10} className={nudging ? 'animate-spin' : ''} />
              {nudging ? 'Nudging...' : 'Nudge'}
            </button>
          </div>

          {/* Events */}
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto"
          >
            {collapsedEvents.length === 0 ? (
              <div className="flex items-center justify-center py-6">
                <span className="text-[10px] text-[var(--color-text-muted)]/40">No events yet</span>
              </div>
            ) : (
              collapsedEvents.map((item, i) => (
                <EventRow key={`${item.event.timestamp}-${i}`} event={item.event} collapsed={item.count} />
              ))
            )}
          </div>

          {/* Message input */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1a1b26] border-t border-[var(--color-border)]/50 shrink-0">
            <input
              ref={inputRef}
              type="text"
              value={messageText}
              onChange={(e) => setMessageText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() } }}
              placeholder="Message pilot..."
              disabled={sending}
              className="flex-1 bg-[#252638] text-xs text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)]/40 rounded px-2 py-1 outline-none focus:ring-1 focus:ring-emerald-500/50 disabled:opacity-50"
            />
            <button
              onClick={handleSendMessage}
              disabled={sending || !messageText.trim()}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-emerald-400 hover:bg-emerald-500/10 transition-colors disabled:opacity-30"
              title="Send message to pilot"
            >
              <Send size={10} className={sending ? 'animate-pulse' : ''} />
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Collapse consecutive waits ─────────────────────────────────

function collapseWaits(events: SupervisorEvent[]): { event: SupervisorEvent; count: number }[] {
  const result: { event: SupervisorEvent; count: number }[] = []
  let waitRun = 0

  for (const event of events) {
    if (event.action === 'wait') {
      waitRun++
    } else {
      // Flush accumulated waits as single collapsed entry
      if (waitRun > 0) {
        const lastWait = events[events.indexOf(event) - 1]
        result.push({ event: lastWait, count: waitRun })
        waitRun = 0
      }
      result.push({ event, count: 1 })
    }
  }

  // Flush trailing waits
  if (waitRun > 0) {
    result.push({ event: events[events.length - 1], count: waitRun })
  }

  return result
}
