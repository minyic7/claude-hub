import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Crown, FileText, Loader2, MessageSquare, PanelRightClose, Play, Send, Zap } from 'lucide-react'
import { api, type POActivityEntry, type POMessage, type POSettings, type POStatus } from '../../lib/api'

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

type SubTab = 'activity' | 'chat'

interface POChatPanelProps {
  projectId: string
  onClose: () => void
  tabBar?: React.ReactNode
}

// ─── Activity Log Entry ─────────────────────────────────────────────────────

function ActivityEntry({ entry }: { entry: POActivityEntry }) {
  const levelStyles: Record<string, string> = {
    info: 'text-[var(--color-text-muted)]',
    warn: 'text-[var(--color-accent-yellow)]',
    error: 'text-[var(--color-accent-red)]',
  }
  const levelIcons: Record<string, string> = {
    info: '\u2022',
    warn: '\u26A0',
    error: '\u2717',
  }

  const time = new Date(entry.ts).toLocaleTimeString()

  return (
    <div className={`flex gap-2 text-[11px] leading-relaxed ${levelStyles[entry.level] || levelStyles.info}`}>
      <span className="shrink-0 w-[52px] opacity-50 tabular-nums">{time}</span>
      <span className="shrink-0 w-3 text-center">{levelIcons[entry.level] || '\u2022'}</span>
      <span className="break-words min-w-0">{entry.message}</span>
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function POChatPanel({ projectId, onClose, tabBar }: POChatPanelProps) {
  const [subTab, setSubTab] = useState<SubTab>('activity')

  // Chat state
  const [messages, setMessages] = useState<POMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)

  // Activity state
  const [activities, setActivities] = useState<POActivityEntry[]>([])

  // Shared state
  const [status, setStatus] = useState<POStatus | null>(null)
  const [settings, setSettings] = useState<POSettings | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [togglingMode, setTogglingMode] = useState(false)
  const [report, setReport] = useState<{ report: string; generated_at: string | null } | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [loadingReport, setLoadingReport] = useState(false)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const activityScrollRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined)
  const [flexBasis, setFlexBasis] = useState(loadPersistedWidth)
  const draggingRef = useRef(false)

  // Load data on mount
  useEffect(() => {
    api.po.chatHistory(projectId).then((r) => setMessages(r.messages)).catch(() => {})
    api.po.activity(projectId).then((r) => setActivities(r.entries)).catch(() => {})
    api.po.status(projectId).then(setStatus).catch(() => {})
    api.po.getSettings(projectId).then(setSettings).catch(() => {})

    pollRef.current = setInterval(() => {
      api.po.status(projectId).then(setStatus).catch(() => {})
    }, 10000)

    return () => clearInterval(pollRef.current)
  }, [projectId])

  // Listen for WS po_activity events
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.type === 'po_activity' && detail.project_id === projectId) {
        setActivities((prev) => [...prev.slice(-99), detail.entry])
      }
    }
    window.addEventListener('ws:po_activity', handler)
    return () => window.removeEventListener('ws:po_activity', handler)
  }, [projectId])

  // Auto-scroll
  useEffect(() => {
    if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
  }, [messages])
  useEffect(() => {
    if (activityScrollRef.current) activityScrollRef.current.scrollTop = activityScrollRef.current.scrollHeight
  }, [activities])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || sending) return

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

  const handleToggleMode = useCallback(async () => {
    if (!settings) return
    setTogglingMode(true)
    try {
      const newMode = settings.mode === 'semi_auto' ? 'full_auto' : 'semi_auto'
      const updated = await api.po.updateSettings(projectId, { ...settings, mode: newMode })
      setSettings(updated)
    } catch {
      // handled by global
    } finally {
      setTogglingMode(false)
    }
  }, [settings, projectId])

  const handleShowReport = useCallback(async () => {
    if (showReport) { setShowReport(false); return }
    setLoadingReport(true)
    setShowReport(true)
    try {
      const r = await api.po.report(projectId)
      setReport(r)
    } catch {
      setReport({ report: 'No report available yet.', generated_at: null })
    } finally {
      setLoadingReport(false)
    }
  }, [showReport, projectId])

  // Drag resize
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
      className="flex shrink-0 overflow-hidden"
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

        {/* Sub-tabs + status + actions — single compact row */}
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-1 shrink-0">
          <div className="flex items-center">
            <button
              onClick={() => setSubTab('activity')}
              className={`flex items-center gap-1 px-2.5 py-1.5 text-[11px] transition-colors ${
                subTab === 'activity'
                  ? 'text-purple-400 border-b-2 border-purple-400'
                  : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
              }`}
            >
              <Activity size={11} />
              Activity
            </button>
            <button
              onClick={() => setSubTab('chat')}
              className={`flex items-center gap-1 px-2.5 py-1.5 text-[11px] transition-colors ${
                subTab === 'chat'
                  ? 'text-purple-400 border-b-2 border-purple-400'
                  : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
              }`}
            >
              <MessageSquare size={11} />
              Chat
            </button>
            <span className="mx-1.5 h-3 w-px bg-[var(--color-border)]" />
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${status?.running ? 'bg-[var(--color-accent-green)] animate-pulse' : 'bg-[var(--color-text-muted)]/40'}`} />
            <span className={`ml-1 text-[10px] ${statusColor}`}>{statusLabel}</span>
          </div>
          <div className="flex items-center gap-0.5">
            {status?.running && settings && (
              <button
                onClick={handleToggleMode}
                disabled={togglingMode}
                className="flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] text-purple-400 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
                title={`Switch to ${settings.mode === 'semi_auto' ? 'Full Auto' : 'Semi Auto'}`}
              >
                <Zap size={9} />
                {settings.mode === 'semi_auto' ? 'Semi' : 'Full'}
              </button>
            )}
            {status?.running && (
              <>
                <button
                  onClick={handleTrigger}
                  disabled={triggering}
                  className="flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors disabled:opacity-50"
                  title="Trigger PO cycle now"
                >
                  <Play size={9} />
                  {triggering ? '...' : 'Run'}
                </button>
                <button
                  onClick={handleShowReport}
                  className={`flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] transition-colors ${
                    showReport ? 'text-purple-400 bg-purple-500/10' : 'text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]'
                  }`}
                  title="View report"
                >
                  <FileText size={9} />
                </button>
              </>
            )}
            <button
              onClick={onClose}
              className="rounded p-0.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
              title="Hide panel (Shift+Esc)"
            >
              <PanelRightClose size={13} />
            </button>
          </div>
        </div>

        {/* Report panel (collapsible) */}
        {showReport && (
          <div className="border-b border-purple-500/20 bg-purple-500/5 px-3 py-2 shrink-0 max-h-48 overflow-y-auto">
            {loadingReport ? (
              <p className="text-[11px] text-[var(--color-text-muted)]">Loading report...</p>
            ) : report ? (
              <div>
                {report.generated_at && (
                  <p className="mb-1 text-[10px] text-[var(--color-text-muted)]">
                    Generated {new Date(report.generated_at).toLocaleString()}
                  </p>
                )}
                <pre className="whitespace-pre-wrap text-[11px] text-[var(--color-text-primary)] leading-relaxed">
                  {report.report}
                </pre>
              </div>
            ) : (
              <p className="text-[11px] text-[var(--color-text-muted)]">No report available.</p>
            )}
          </div>
        )}

        {/* Activity tab */}
        {subTab === 'activity' && (
          <div ref={activityScrollRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-1 min-h-0">
            {activities.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-[var(--color-text-muted)]">
                <Activity size={24} className="opacity-40" />
                <p className="text-xs">No activity yet</p>
                <p className="text-[10px] opacity-60">PO Agent events will appear here</p>
              </div>
            ) : (
              activities.map((entry, i) => <ActivityEntry key={i} entry={entry} />)
            )}
          </div>
        )}

        {/* Chat tab */}
        {subTab === 'chat' && (
          <>
            <div ref={chatScrollRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-3 min-h-0">
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
          </>
        )}
      </div>
    </div>
  )
}
