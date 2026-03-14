import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Brain, Terminal, FileText, MessageSquare, AlertTriangle, CheckCircle,
  Info, XCircle, Eye, User, ClipboardCheck, Send, ChevronUp, ChevronDown,
  MessageCircle, X,
} from 'lucide-react'
import type { ActivityEvent } from '../../types/activity'
import type { Ticket } from '../../types/ticket'
import { relativeTime } from '../../utils/relativeTime'
import { api } from '../../lib/api'

interface MobileChatViewProps {
  tickets: Map<string, Ticket>
  activities: Map<string, ActivityEvent[]>
  activeProjectId: string | null
}

const typeConfig: Record<string, { icon: typeof Brain; className: string; bgClass: string; label: string }> = {
  thinking:    { icon: Brain,          className: 'text-[var(--color-text-muted)]',    bgClass: 'bg-[var(--color-bg-secondary)]',        label: 'Thinking' },
  tool_use:    { icon: Terminal,       className: 'text-[var(--color-accent-blue)]',   bgClass: 'bg-[var(--color-accent-blue)]/5',       label: 'Tool' },
  tool_result: { icon: FileText,       className: 'text-[var(--color-text-muted)]',    bgClass: 'bg-[var(--color-bg-secondary)]',        label: 'Result' },
  commentary:  { icon: Eye,            className: 'text-[var(--color-accent-purple)]', bgClass: 'bg-[var(--color-accent-purple)]/5',     label: 'Commentary' },
  intervention:{ icon: MessageSquare,  className: 'text-[var(--color-accent-yellow)]', bgClass: 'bg-[var(--color-accent-yellow)]/5',     label: 'Intervention' },
  decision:    { icon: CheckCircle,    className: 'text-[var(--color-accent-green)]',  bgClass: 'bg-[var(--color-accent-green)]/5',      label: 'Decision' },
  review:      { icon: ClipboardCheck, className: 'text-[var(--color-accent-purple)]', bgClass: 'bg-[var(--color-accent-purple)]/5',     label: 'Review' },
  message:     { icon: User,           className: 'text-[var(--color-accent-green)]',  bgClass: 'bg-[var(--color-accent-green)]/5',      label: 'Message' },
  info:        { icon: Info,           className: 'text-[var(--color-text-muted)]',    bgClass: 'bg-[var(--color-bg-secondary)]',        label: 'Info' },
  warning:     { icon: AlertTriangle,  className: 'text-[var(--color-accent-yellow)]', bgClass: 'bg-[var(--color-accent-yellow)]/5',     label: 'Warning' },
  error:       { icon: XCircle,        className: 'text-[var(--color-accent-red)]',    bgClass: 'bg-[var(--color-accent-red)]/5',        label: 'Error' },
}

interface ChatEvent {
  ticketId: string
  ticketTitle: string
  event: ActivityEvent
}

function ChatBubble({ item }: { item: ChatEvent }) {
  const config = typeConfig[item.event.type] || typeConfig.info
  const Icon = config.icon
  const isAgent = item.event.source === 'ticket_agent'
  const isUser = item.event.source === 'user'
  const isError = item.event.type === 'error'

  return (
    <div className={`flex gap-2 px-3 py-1.5 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${config.bgClass}`}>
        <Icon size={12} className={config.className} />
      </div>
      <div className={`min-w-0 max-w-[85%] ${isUser ? 'items-end' : ''}`}>
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className="text-[10px] font-medium text-[var(--color-text-muted)]">
            {item.ticketTitle}
          </span>
          <span className="text-[10px] text-[var(--color-text-muted)]/60">
            {relativeTime(item.event.timestamp)}
          </span>
        </div>
        <div className={`rounded-xl px-3 py-2 text-xs ${
          isUser
            ? 'bg-[var(--color-accent-blue)] text-white rounded-br-sm'
            : isError
              ? 'bg-[var(--color-accent-red)]/10 text-[var(--color-accent-red)] border border-[var(--color-accent-red)]/20 rounded-bl-sm'
              : isAgent
                ? 'bg-[var(--color-accent-purple)]/10 text-[var(--color-text-primary)] border border-[var(--color-accent-purple)]/20 rounded-bl-sm'
                : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] rounded-bl-sm'
        }`}>
          {isAgent && item.event.type === 'intervention' && (
            <span className="font-medium text-[var(--color-accent-purple)]">TicketAgent: </span>
          )}
          {item.event.summary}
        </div>
      </div>
    </div>
  )
}

function TicketSelector({
  tickets,
  activeProjectId,
  selectedTicketId,
  onSelect,
}: {
  tickets: Map<string, Ticket>
  activeProjectId: string | null
  selectedTicketId: string | null
  onSelect: (id: string | null) => void
}) {
  const [open, setOpen] = useState(false)

  const activeTickets = [...tickets.values()].filter(
    (t) => activeProjectId && t.project_id === activeProjectId && !t.archived &&
      (t.status === 'in_progress' || t.status === 'blocked' || t.status === 'verifying' || t.status === 'reviewing')
  )

  if (activeTickets.length === 0) return null

  const selected = selectedTicketId ? tickets.get(selectedTicketId) : null

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 py-1 text-xs text-[var(--color-text-primary)]"
      >
        <span className="max-w-[180px] truncate">
          {selected ? `#${selected.seq} ${selected.title}` : 'All active'}
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] py-1 shadow-lg">
            <button
              onClick={() => { onSelect(null); setOpen(false) }}
              className={`w-full px-3 py-2 text-left text-xs hover:bg-[var(--color-bg-secondary)] ${!selectedTicketId ? 'bg-[var(--color-accent-blue)]/5 font-medium' : ''}`}
            >
              All active tickets
            </button>
            {activeTickets.map((t) => (
              <button
                key={t.id}
                onClick={() => { onSelect(t.id); setOpen(false) }}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-[var(--color-bg-secondary)] ${selectedTicketId === t.id ? 'bg-[var(--color-accent-blue)]/5' : ''}`}
              >
                <span className="text-[var(--color-text-muted)]">#{t.seq}</span>
                <span className="flex-1 truncate text-[var(--color-text-primary)]">{t.title}</span>
                <span className={`shrink-0 text-[10px] ${
                  t.status === 'blocked' ? 'text-[var(--color-accent-red)]' : 'text-[var(--color-accent-blue)]'
                }`}>
                  {t.status.replace('_', ' ')}
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export function MobileChatView({ tickets, activities, activeProjectId }: MobileChatViewProps) {
  const [open, setOpen] = useState(false)
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [userScrolledUp, setUserScrolledUp] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [, setTick] = useState(0)

  // Refresh relative timestamps
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000)
    return () => clearInterval(id)
  }, [])

  // Merge activities across active tickets into a chronological feed
  const chatEvents: ChatEvent[] = []
  const activeTickets = [...tickets.values()].filter(
    (t) => activeProjectId && t.project_id === activeProjectId && !t.archived &&
      (t.status === 'in_progress' || t.status === 'blocked' || t.status === 'verifying' || t.status === 'reviewing')
  )

  for (const ticket of activeTickets) {
    if (selectedTicketId && ticket.id !== selectedTicketId) continue
    const events = activities.get(ticket.id) || []
    const title = ticket.seq > 0 ? `#${ticket.seq} ${ticket.title}` : ticket.title
    for (const event of events) {
      chatEvents.push({ ticketId: ticket.id, ticketTitle: title, event })
    }
  }

  // Sort chronologically
  chatEvents.sort((a, b) => new Date(a.event.timestamp).getTime() - new Date(b.event.timestamp).getTime())

  // Keep only last 200 events for performance
  const visibleEvents = chatEvents.slice(-200)

  // Find blocked ticket for escalation input
  const blockedTicket = activeTickets.find((t) => t.status === 'blocked' && t.blocked_question)
  const targetTicket = selectedTicketId
    ? tickets.get(selectedTicketId)
    : blockedTicket || activeTickets[0]

  // Auto-scroll to bottom
  useEffect(() => {
    if (!userScrolledUp && open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [visibleEvents.length, userScrolledUp, open])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setUserScrolledUp(!atBottom)
  }, [])

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!msg.trim() || sending || !targetTicket) return
    setSending(true)
    try {
      if (targetTicket.status === 'blocked' && targetTicket.blocked_question) {
        await api.tickets.answer(targetTicket.id, msg.trim())
      } else {
        await api.tickets.message(targetTicket.id, msg.trim())
      }
      setMsg('')
    } catch { /* global error handler */ } finally {
      setSending(false)
    }
  }

  const hasActivity = activeTickets.length > 0

  if (!hasActivity) return null

  // Unread indicator: count events in the last 60 seconds
  const recentCount = chatEvents.filter(
    (e) => Date.now() - new Date(e.event.timestamp).getTime() < 60_000
  ).length

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-22 right-6 z-30 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-accent-blue)] text-white shadow-lg active:scale-95 transition-transform"
      >
        <MessageCircle size={20} />
        {recentCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-accent-red)] px-1 text-[10px] font-bold text-white">
            {recentCount > 99 ? '99+' : recentCount}
          </span>
        )}
      </button>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--color-bg-panel)] animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <MessageCircle size={16} className="text-[var(--color-accent-blue)] shrink-0" />
          <span className="text-sm font-semibold text-[var(--color-text-primary)]">Agent Chat</span>
        </div>
        <div className="flex items-center gap-2">
          <TicketSelector
            tickets={tickets}
            activeProjectId={activeProjectId}
            selectedTicketId={selectedTicketId}
            onSelect={setSelectedTicketId}
          />
          <button
            onClick={() => setOpen(false)}
            className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Escalation banner */}
      {blockedTicket && blockedTicket.blocked_question && (
        <div className="border-b border-[var(--color-accent-red)]/20 bg-[var(--color-accent-red)]/5 px-3 py-2 shrink-0">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[var(--color-accent-red)]" />
            <div className="min-w-0">
              <p className="text-[10px] font-medium text-[var(--color-accent-red)]">
                #{blockedTicket.seq} needs input
              </p>
              <p className="text-xs text-[var(--color-text-primary)] mt-0.5">
                {blockedTicket.blocked_question}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Chat timeline */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto py-2 min-h-0"
      >
        {visibleEvents.length === 0 ? (
          <p className="py-12 text-center text-sm text-[var(--color-text-muted)]">
            No activity yet
          </p>
        ) : (
          visibleEvents.map((item, i) => (
            <ChatBubble key={`${item.ticketId}-${i}`} item={item} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      {targetTicket && targetTicket.tmux_session && (
        <div className="border-t border-[var(--color-border)] px-3 py-2 shrink-0">
          {blockedTicket && blockedTicket.blocked_question && (
            <div className="flex gap-1.5 mb-2 overflow-x-auto">
              {['Yes', 'No', 'Continue', 'Skip'].map((label) => (
                <button
                  key={label}
                  onClick={async () => {
                    const values: Record<string, string> = {
                      Yes: 'yes', No: 'no',
                      Continue: 'continue with the current approach',
                      Skip: 'skip this step and move on',
                    }
                    setSending(true)
                    try {
                      await api.tickets.answer(blockedTicket.id, values[label])
                    } catch { /* global handler */ } finally {
                      setSending(false)
                    }
                  }}
                  disabled={sending}
                  className="shrink-0 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1 text-xs font-medium text-[var(--color-text-primary)] active:bg-[var(--color-accent-blue)]/10 disabled:opacity-50"
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          <form onSubmit={handleSend} className="flex items-center gap-2">
            <input
              type="text"
              value={msg}
              onChange={(e) => setMsg(e.target.value)}
              placeholder={
                blockedTicket?.blocked_question
                  ? 'Answer or message...'
                  : `Message #${targetTicket.seq || ''}...`
              }
              className="flex-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-4 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={!msg.trim() || sending}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent-blue)] text-white transition-opacity hover:opacity-80 disabled:opacity-40"
            >
              <Send size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
