import { useCallback, useEffect, useRef, useState } from 'react'
import { Crown, Loader2, PanelRightClose, Play, Send } from 'lucide-react'
import { api, type POMessage, type POStatus } from '../../lib/api'

const MIN_WIDTH = 300
const MAX_WIDTH_VW = 70
const DEFAULT_WIDTH = 600
const STORAGE_KEY = 'kanban-terminal-flex-basis'

function loadPersistedWidth(): number {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const val = parseInt(stored, 10)
      if (val >= MIN_WIDTH) return val
    }
  } catch {
    // ignore
  }
  return DEFAULT_WIDTH
}

interface POChatPanelProps {
  projectId: string
  onClose: () => void
  tabBar?: React.ReactNode
}

export function POChatPanel({ projectId, onClose, tabBar }: POChatPanelProps) {
  const [messages, setMessages] = useState<POMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState<POStatus | null>(null)
  const [triggering, setTriggering] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined)
  const [flexBasis, setFlexBasis] = useState(loadPersistedWidth)
  const draggingRef = useRef(false)

  // Load chat history and status on mount
  useEffect(() => {
    api.po.chatHistory(projectId).then((r) => setMessages(r.messages)).catch(() => {})
    api.po.status(projectId).then(setStatus).catch(() => {})

    // Poll status every 10s
    pollRef.current = setInterval(() => {
      api.po.status(projectId).then(setStatus).catch(() => {})
    }, 10000)

    return () => clearInterval(pollRef.current)
  }, [projectId])

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || sending) return

    // Optimistic append
    const userMsg: POMessage = { role: 'user', content: text, timestamp: new Date().toISOString() }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setSending(true)

    try {
      const { response } = await api.po.chat(projectId, text)
      const poMsg: POMessage = { role: 'assistant', content: response, timestamp: new Date().toISOString() }
      setMessages((prev) => [...prev, poMsg])
    } catch {
      const errMsg: POMessage = { role: 'system', content: 'Failed to send message', timestamp: new Date().toISOString() }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setSending(false)
    }
  }, [input, sending, projectId])

  const handleTrigger = useCallback(async () => {
    setTriggering(true)
    try {
      await api.po.run(projectId)
    } catch {
      // handled by global
    } finally {
      setTriggering(false)
    }
  }, [projectId])

  // Drag resize handler (mirrors KanbanTerminal)
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    draggingRef.current = true

    const startX = e.clientX
    const startBasis = flexBasis
    const maxWidth = window.innerWidth * MAX_WIDTH_VW / 100

    const onMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return
      const delta = startX - ev.clientX
      const newBasis = Math.min(Math.max(startBasis + delta, MIN_WIDTH), maxWidth)
      setFlexBasis(newBasis)
    }

    const onUp = () => {
      draggingRef.current = false
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setFlexBasis((current) => {
        try { localStorage.setItem(STORAGE_KEY, String(current)) } catch { /* ignore */ }
        return current
      })
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [flexBasis])

  const statusColor = status?.running
    ? status.status === 'waiting' ? 'text-[var(--color-accent-yellow)]' : 'text-[var(--color-accent-green)]'
    : 'text-[var(--color-text-muted)]'

  const statusLabel = status?.running
    ? `${status.status} (cycle ${status.cycle_n})`
    : 'Not running'

  return (
    <div
      className="flex shrink-0 transition-[flex-basis] duration-200 overflow-hidden"
      style={{ flexBasis }}
    >
      {/* Drag handle */}
      <div
        onMouseDown={handleDragStart}
        className="w-1 cursor-col-resize bg-[var(--color-border)] hover:bg-purple-400 transition-colors shrink-0"
      />

      {/* Panel */}
      <div className="flex flex-1 flex-col bg-[var(--color-bg-primary)] border-l border-[var(--color-border)] overflow-hidden min-w-0">
        {tabBar}

        {/* Status bar + close */}
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-1.5 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${status?.running ? 'bg-[var(--color-accent-green)] animate-pulse' : 'bg-[var(--color-text-muted)]/40'}`} />
            <span className={`text-[11px] ${statusColor}`}>{statusLabel}</span>
          </div>
          <div className="flex items-center gap-1.5">
            {status?.running && (
              <button
                onClick={handleTrigger}
                disabled={triggering}
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors disabled:opacity-50"
                title="Trigger PO cycle now"
              >
                <Play size={10} />
                {triggering ? 'Running...' : 'Run Now'}
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
              title="Hide panel (Shift+Esc)"
            >
              <PanelRightClose size={14} />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-3 min-h-0">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-[var(--color-text-muted)]">
              <Crown size={24} className="opacity-40" />
              <p className="text-xs">PO Chat</p>
              <p className="text-[10px] opacity-60">Send instructions to the PO Agent</p>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-[var(--color-accent-blue)]/15 text-[var(--color-text-primary)]'
                    : msg.role === 'system'
                    ? 'bg-[var(--color-accent-red)]/10 text-[var(--color-accent-red)]'
                    : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]'
                }`}>
                  {msg.role === 'assistant' && (
                    <div className="flex items-center gap-1 mb-1 text-[10px] text-purple-400">
                      <Crown size={10} /> PO Agent
                    </div>
                  )}
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  <span className="block mt-1 text-[9px] opacity-40">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ))
          )}
          {sending && (
            <div className="flex justify-start">
              <div className="flex items-center gap-1.5 rounded-lg bg-[var(--color-bg-secondary)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
                <Loader2 size={12} className="animate-spin" /> Thinking...
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <form
          onSubmit={(e) => { e.preventDefault(); handleSend() }}
          className="flex items-center gap-2 border-t border-[var(--color-border)] px-3 py-2 shrink-0"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={status?.running ? 'Message PO Agent...' : 'PO not running — enable in Settings'}
            disabled={!status?.running || sending}
            className="flex-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-1.5 text-xs text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || !status?.running || sending}
            className="rounded bg-purple-500 p-1.5 text-white hover:opacity-90 disabled:opacity-30 transition-opacity"
          >
            <Send size={14} />
          </button>
        </form>
      </div>
    </div>
  )
}
