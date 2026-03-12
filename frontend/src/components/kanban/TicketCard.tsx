import { type FormEvent, type MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Archive, ArchiveRestore, Check, CircleDot, ClipboardCheck, Clock, GitMerge, Loader2, Lock, MessageCircleQuestion, Pencil, Play, Plug, Rocket, RotateCcw, ExternalLink, Send, X } from 'lucide-react'
import type { Ticket, TicketStatus } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { api } from '../../lib/api'
import { formatElapsed } from '../../utils/relativeTime'

function derivePhase(summary: string): string {
  const lower = summary.toLowerCase()
  if (/clone|cloning|checkout|setup|install|initializ/.test(lower)) return 'Setup'
  if (/read|reading|analyz|review|understand|examin|inspect|explor/.test(lower)) return 'Analyzing'
  if (/writ|writing|edit|creat|implement|add|modif|refactor|cod/.test(lower)) return 'Coding'
  if (/test|testing|run.*test|spec|assert|verify|check/.test(lower)) return 'Testing'
  if (/pr\b|pull request|creating pr|push|commit|finaliz/.test(lower)) return 'Finalizing'
  return 'Working'
}

interface DepLabel {
  id: string
  seq?: number
  title?: string
  status: string
}

interface TicketCardProps {
  ticket: Ticket
  latestActivity?: ActivityEvent
  activityEvents?: ActivityEvent[]
  onClick: () => void
  onOptimistic?: (ticketId: string, patch: Partial<Ticket>) => void
  depsBlocked?: boolean
  depLabels?: DepLabel[]
  onDepClick?: (depId: string) => void
  deploying?: boolean
  mergeQueueLocked?: boolean
  onMergeInitiated?: () => void
}

export function TicketCard({ ticket, latestActivity, activityEvents, onClick, onOptimistic, depsBlocked, depLabels, onDepClick, deploying, mergeQueueLocked, onMergeInitiated }: TicketCardProps) {
  const [actionError, setActionError] = useState<string | null>(null)
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Track status changes for transition animations
  const prevStatusRef = useRef(ticket.status)
  const [statusEntering, setStatusEntering] = useState(false)
  const [cardFlash, setCardFlash] = useState(false)

  useEffect(() => {
    if (prevStatusRef.current !== ticket.status) {
      prevStatusRef.current = ticket.status
      // Trigger icon enter animation
      setStatusEntering(true)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setStatusEntering(false))
      })
      // Trigger card border flash
      setCardFlash(true)
      const t = setTimeout(() => setCardFlash(false), 600)
      return () => clearTimeout(t)
    }
  }, [ticket.status])

  useEffect(() => {
    return () => {
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current)
    }
  }, [])

  const safeAction = (fn: () => Promise<unknown>, optimisticPatch?: Partial<Ticket>, revertPatch?: Partial<Ticket>) => async (e: MouseEvent) => {
    e.stopPropagation()
    setActionError(null)
    if (optimisticPatch && onOptimistic) onOptimistic(ticket.id, optimisticPatch)
    try {
      await fn()
    } catch (err) {
      if (revertPatch && onOptimistic) onOptimistic(ticket.id, revertPatch)
      const msg = err instanceof Error ? err.message : 'Action failed'
      setActionError(msg)
      const t = setTimeout(() => setActionError(null), 5000)
      errorTimerRef.current = t
    }
  }

  const handleStart = safeAction(
    () => api.tickets.start(ticket.id),
    { status: 'in_progress' },
    { status: 'todo' },
  )
  const handleDequeue = safeAction(
    () => api.tickets.dequeue(ticket.id),
    { status: 'todo' },
    { status: 'queued' },
  )
  const handleRetry = safeAction(
    () => api.tickets.retry(ticket.id),
    { status: 'in_progress', failed_reason: null },
    { status: 'failed', failed_reason: ticket.failed_reason },
  )
  const handleMerge = safeAction(
    () => {
      onMergeInitiated?.()
      return api.tickets.merge(ticket.id)
    },
    { status: 'merged' },
    { status: 'review' },
  )
  const handleArchive = safeAction(
    () => api.tickets.archive(ticket.id),
    { archived: !ticket.archived },
    { archived: ticket.archived },
  )

  // Inline edit state (TODO tickets only)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(ticket.title)
  const [editDesc, setEditDesc] = useState(ticket.description || '')
  const [saving, setSaving] = useState(false)

  const handleEditClick = (e: MouseEvent) => {
    e.stopPropagation()
    setEditTitle(ticket.title)
    setEditDesc(ticket.description || '')
    setEditing(true)
  }

  const handleEditCancel = (e: MouseEvent) => {
    e.stopPropagation()
    setEditing(false)
  }

  const handleEditSave = async (e: MouseEvent | FormEvent) => {
    e.stopPropagation()
    e.preventDefault()
    if (!editTitle.trim()) return
    setSaving(true)
    try {
      await api.tickets.update(ticket.id, {
        title: editTitle.trim(),
        description: editDesc.trim(),
      })
      setEditing(false)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Save failed'
      setActionError(msg)
      const t = setTimeout(() => setActionError(null), 5000)
      errorTimerRef.current = t
    } finally {
      setSaving(false)
    }
  }

  const [answer, setAnswer] = useState('')
  const [answering, setAnswering] = useState(false)
  const handleAnswer = async (e: MouseEvent | FormEvent) => {
    e.stopPropagation()
    e.preventDefault()
    if (!answer.trim()) return
    setAnswering(true)
    try {
      await api.tickets.answer(ticket.id, answer.trim())
      setAnswer('')
    } finally {
      setAnswering(false)
    }
  }

  // Idle detection: no activity for 2+ minutes on in_progress ticket
  const [isIdle, setIsIdle] = useState(false)
  useEffect(() => {
    if (ticket.status !== 'in_progress' || !latestActivity) {
      setIsIdle(false)
      return
    }
    const checkIdle = () => {
      const lastTime = new Date(latestActivity.timestamp).getTime()
      setIsIdle(Date.now() - lastTime > 120_000)
    }
    checkIdle()
    const timer = setInterval(checkIdle, 10_000)
    return () => clearInterval(timer)
  }, [ticket.status, latestActivity])

  // Elapsed time since ticket entered current status, refreshes every 30s
  const getElapsedTimestamp = useCallback(() => {
    if (ticket.status === 'todo') return null
    if (ticket.status === 'in_progress' && ticket.started_at) return ticket.started_at
    if (ticket.status_changed_at) return ticket.status_changed_at
    // Fallback for tickets without status_changed_at
    if (ticket.started_at) return ticket.started_at
    return ticket.created_at
  }, [ticket.status, ticket.started_at, ticket.status_changed_at, ticket.created_at])

  const [elapsed, setElapsed] = useState<string | null>(() => {
    const ts = getElapsedTimestamp()
    return ts ? formatElapsed(ts) : null
  })

  useEffect(() => {
    const ts = getElapsedTimestamp()
    if (!ts) { setElapsed(null); return }
    setElapsed(formatElapsed(ts))
    const timer = setInterval(() => setElapsed(formatElapsed(ts)), 30_000)
    return () => clearInterval(timer)
  }, [getElapsedTimestamp])

  const stepInfo = useMemo(() => {
    if (ticket.status !== 'in_progress' || !latestActivity) return null
    const stepCount = activityEvents
      ? activityEvents.filter((e) => e.type === 'tool_use').length
      : 0
    const phase = derivePhase(latestActivity.summary)
    return { stepCount, phase }
  }, [ticket.status, latestActivity, activityEvents])

  const isBlocked = ticket.status === 'blocked'

  return (
    <div
      onClick={onClick}
      data-blocked={isBlocked || undefined}
      className={`ticket-card cursor-pointer rounded-lg border p-3 ${
        isBlocked
          ? 'border-[var(--color-accent-red)]/60 bg-[var(--color-accent-red)]/5 hover:border-[var(--color-accent-red)]'
          : 'border-[var(--color-border)] bg-[var(--color-bg-panel)] hover:border-[var(--color-accent-blue)]/40'
      }${cardFlash ? ' ticket-card--flash' : ''}`}
      style={cardFlash ? { '--flash-color': statusFlashColor(ticket.status) } as React.CSSProperties : undefined}
    >
      {editing ? (
        <form onClick={(e) => e.stopPropagation()} onSubmit={handleEditSave} className="space-y-2">
          <input
            type="text"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            placeholder="Title"
            autoFocus
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2 py-1 text-sm font-medium text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
          />
          <textarea
            value={editDesc}
            onChange={(e) => setEditDesc(e.target.value)}
            placeholder="Description (markdown)"
            rows={3}
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2 py-1 text-xs text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none resize-y"
          />
          <div className="flex items-center gap-1.5">
            <Button size="sm" onClick={handleEditSave} disabled={saving || !editTitle.trim()}>
              {saving ? <Loader2 size={12} className="mr-1 animate-spin" /> : <Check size={12} className="mr-1" />}
              Save
            </Button>
            <Button size="sm" variant="secondary" onClick={handleEditCancel} disabled={saving}>
              <X size={12} className="mr-1" /> Cancel
            </Button>
          </div>
        </form>
      ) : (
        <>
          <div className="mb-2 flex items-start justify-between gap-2">
            <h3 className="text-sm font-medium text-[var(--color-text-primary)] line-clamp-2">
              {ticket.seq > 0 && <span className="text-[var(--color-text-muted)] mr-1">#{ticket.seq}</span>}
              {ticket.title}
            </h3>
            <div className="flex items-center gap-1 shrink-0">
              {ticket.status === 'todo' && (
                <button
                  type="button"
                  onClick={handleEditClick}
                  className="rounded p-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-accent-blue)] hover:bg-[var(--color-bg-secondary)] transition-colors"
                  title="Edit ticket"
                >
                  <Pencil size={13} />
                </button>
              )}
              <button
                type="button"
                onClick={handleArchive}
                className="rounded p-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-accent-blue)] hover:bg-[var(--color-bg-secondary)] transition-colors"
                title={ticket.archived ? 'Unarchive' : 'Archive'}
              >
                {ticket.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
              </button>
              <StatusIndicator status={ticket.status} entering={statusEntering} />
            </div>
          </div>

          <div className="mb-2 flex items-center gap-1.5">
            <Badge color="blue">{ticket.branch_type}</Badge>
            {ticket.status === 'queued' && <Badge color="yellow">QUEUED</Badge>}
            {ticket.status === 'queued' && ticket.priority >= 0 && (
              <span className="inline-flex items-center rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-muted)]" title={`Priority ${ticket.priority}`}>
                P{ticket.priority}
              </span>
            )}
            {ticket.status === 'blocked' && <Badge color="red">ESCALATION</Badge>}
            {ticket.status === 'failed' && <Badge color="red">FAILED</Badge>}
            {ticket.status === 'verifying' && <Badge color="yellow">VERIFYING</Badge>}
            {ticket.status === 'reviewing' && <Badge color="yellow">REVIEWING</Badge>}
            {isIdle && <Badge color="gray">IDLE</Badge>}
            {ticket.tmux_session && ticket.status !== 'in_progress' && ticket.status !== 'verifying' && ticket.status !== 'reviewing' && (
              <span className="flex items-center gap-0.5 text-[10px] text-[var(--color-accent-blue)]" title="Live tmux session">
                <Plug size={10} /> Session
              </span>
            )}
          </div>

          <div className="mb-2 flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
            <p className="truncate">{ticket.branch}</p>
            {elapsed && (
              <span className="shrink-0 opacity-60" title={`In ${ticket.status} for ${elapsed}`}>{elapsed}</span>
            )}
          </div>
        </>
      )}

      {/* Dependency labels for TODO tickets */}
      {!editing && ticket.status === 'todo' && depLabels && depLabels.length > 0 && (
        <div className="mb-2 space-y-0.5 text-[11px]">
          {depLabels.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={(e) => { e.stopPropagation(); onDepClick?.(d.id) }}
              className="flex w-full items-center gap-1.5 rounded px-0.5 text-left hover:bg-[var(--color-bg-secondary)] transition-colors"
            >
              <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${depDotColor(d.status as TicketStatus)}`} />
              <span className="text-[var(--color-text-muted)]">Depends on:</span>
              <span
                className={`truncate font-medium ${d.status === 'merged' ? 'text-[var(--color-text-muted)] line-through opacity-60' : 'text-[var(--color-text-secondary)]'}`}
                title={d.title}
              >
                {d.seq ? `#${d.seq}` : d.title || `#${d.id.slice(0, 6)}`}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Status-specific content */}
      {!editing && ticket.status === 'todo' && (
        <div className="relative group/start">
          <Button
            size="sm"
            onClick={depsBlocked ? undefined : handleStart}
            disabled={depsBlocked}
            className="w-full"
          >
            {depsBlocked ? (
              <><Lock size={12} className="mr-1" /> Waiting</>
            ) : (
              <><Play size={12} className="mr-1" /> Start</>
            )}
          </Button>
          {depsBlocked && depLabels && (
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover/start:block z-10">
              <div className="whitespace-nowrap rounded bg-[var(--color-bg-secondary)] border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] shadow-lg">
                Waiting for {depLabels.filter((d) => d.status !== 'merged').map((d) => d.seq ? `#${d.seq}` : d.title || `#${d.id.slice(0, 6)}`).join(', ')} to be merged
              </div>
            </div>
          )}
        </div>
      )}

      {!editing && ticket.status === 'queued' && (
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs text-[var(--color-accent-yellow)]">
            <Clock size={12} />
            <span>Queued — waiting for slot</span>
          </div>
          <Button size="sm" variant="secondary" onClick={handleDequeue}>
            <X size={12} className="mr-1" /> Cancel
          </Button>
        </div>
      )}

      {(ticket.status === 'in_progress' || ticket.status === 'verifying' || ticket.status === 'reviewing') && latestActivity && (
        <div className="space-y-0.5">
          {stepInfo && (
            <div className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-muted)]">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-accent-blue)] animate-pulse" />
              <span>Step {stepInfo.stepCount || 1}</span>
              <span className="opacity-50">&middot;</span>
              <span>{stepInfo.phase}</span>
            </div>
          )}
          <p className="truncate text-xs text-[var(--color-text-muted)]">
            {latestActivity.summary}
          </p>
        </div>
      )}

      {isBlocked && ticket.blocked_question && (
        <div className="space-y-2">
          <div className="flex gap-1.5 rounded bg-[var(--color-accent-red)]/10 p-2">
            <MessageCircleQuestion size={14} className="mt-0.5 shrink-0 text-[var(--color-accent-red)]" />
            <p className="text-xs leading-relaxed text-[var(--color-accent-red)] line-clamp-3">
              {ticket.blocked_question}
            </p>
          </div>
          <form onSubmit={handleAnswer} onClick={(e) => e.stopPropagation()} className="flex gap-1">
            <input
              type="text"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type answer..."
              className="flex-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2 py-1 text-xs text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
            />
            <Button size="sm" onClick={handleAnswer} disabled={answering || !answer.trim()}>
              <Send size={12} />
            </Button>
          </form>
        </div>
      )}

      {ticket.status === 'failed' && (
        <div className="flex items-center gap-2">
          <p className="flex-1 truncate text-xs text-[var(--color-accent-red)]">
            {ticket.failed_reason}
          </p>
          <Button size="sm" variant="secondary" onClick={handleRetry}>
            <RotateCcw size={12} className="mr-1" /> Retry
          </Button>
        </div>
      )}

      {ticket.status === 'review' && (
        <div className="space-y-1.5">
          {ticket.has_conflicts && (
            <div className="flex items-center gap-1 rounded bg-[var(--color-accent-red)]/10 px-2 py-1 text-xs text-[var(--color-accent-red)]">
              <AlertCircle size={12} className="shrink-0" /> Merge conflicts detected
            </div>
          )}
          {mergeQueueLocked && (
            <div className="flex items-center gap-1.5 rounded bg-[var(--color-accent-yellow)]/10 px-2 py-1 text-xs text-[var(--color-accent-yellow)]">
              <Loader2 size={12} className="animate-spin shrink-0" />
              <span>Deploy in progress — merge queued</span>
            </div>
          )}
          <div className="flex items-center justify-between gap-2">
            {ticket.pr_url && (
              <a
                href={ticket.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1 text-xs text-[var(--color-accent-blue)] hover:underline"
              >
                PR #{ticket.pr_number} <ExternalLink size={10} />
              </a>
            )}
            <Button size="sm" onClick={handleMerge} disabled={ticket.has_conflicts || mergeQueueLocked}>
              <GitMerge size={12} className="mr-1" /> Merge
            </Button>
          </div>
        </div>
      )}

      {ticket.status === 'merging' && (
        <div className="flex items-center gap-1.5 text-xs text-[var(--color-accent-blue)]">
          <Loader2 size={12} className="animate-spin" />
          <span>Waiting for CI checks...</span>
          {ticket.pr_url && (
            <a
              href={ticket.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="ml-auto text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
            >
              <ExternalLink size={10} />
            </a>
          )}
        </div>
      )}

      {ticket.status === 'merged' && deploying !== undefined && (
        <div className="flex items-center gap-1.5 text-xs">
          {deploying ? (
            <>
              <Loader2 size={12} className="text-[var(--color-accent-blue)] animate-spin" />
              <span className="text-[var(--color-accent-blue)]">Deploying...</span>
            </>
          ) : (
            <>
              <Rocket size={12} className="text-[var(--color-accent-green)]" />
              <span className="text-[var(--color-accent-green)]">Deployed</span>
            </>
          )}
        </div>
      )}

      {actionError && (
        <p className="mt-1 rounded bg-[var(--color-accent-red)]/10 px-2 py-1 text-xs text-[var(--color-accent-red)]">
          {actionError}
        </p>
      )}

      {ticket.agent_cost_usd > 0 && (
        <p className="mt-1 text-right text-xs text-[var(--color-text-muted)]">
          ~${ticket.agent_cost_usd.toFixed(2)}{ticket.agent_tokens > 0 && ` (${ticket.agent_tokens >= 1_000_000 ? `${(ticket.agent_tokens / 1_000_000).toFixed(1)}M` : ticket.agent_tokens >= 1_000 ? `${(ticket.agent_tokens / 1_000).toFixed(0)}k` : ticket.agent_tokens} tokens)`}
        </p>
      )}
    </div>
  )
}

function depDotColor(status: TicketStatus): string {
  switch (status) {
    case 'merged': return 'bg-[var(--color-accent-green)]'
    case 'review': case 'merging': return 'bg-[var(--color-accent-yellow)]'
    case 'in_progress': case 'verifying': case 'reviewing': return 'bg-[var(--color-accent-blue)]'
    case 'blocked': case 'failed': return 'bg-[var(--color-accent-red)]'
    default: return 'bg-[var(--color-accent-red)]/60'
  }
}

function statusFlashColor(status: string): string {
  switch (status) {
    case 'in_progress': return 'var(--color-accent-blue)'
    case 'blocked': case 'failed': return 'var(--color-accent-red)'
    case 'queued': case 'review': case 'verifying': case 'reviewing': return 'var(--color-accent-yellow)'
    case 'merging': case 'merged': return 'var(--color-accent-green)'
    default: return 'var(--color-accent-blue)'
  }
}

function StatusIndicator({ status, entering }: { status: string; entering?: boolean }) {
  const cls = `shrink-0 status-icon${entering ? ' status-icon--enter' : ''}`
  switch (status) {
    case 'queued':
      return <Clock size={14} className={`${cls} text-[var(--color-accent-yellow)]`} />
    case 'in_progress':
      return <CircleDot size={14} className={`${cls} text-[var(--color-accent-blue)] animate-pulse`} />
    case 'blocked':
      return <AlertCircle size={14} className={`${cls} text-[var(--color-accent-red)] animate-pulse`} />
    case 'verifying':
      return <Loader2 size={14} className={`${cls} text-[var(--color-accent-yellow)] animate-spin`} />
    case 'reviewing':
      return <ClipboardCheck size={14} className={`${cls} text-[var(--color-accent-yellow)] animate-pulse`} />
    case 'failed':
      return <AlertCircle size={14} className={`${cls} text-[var(--color-accent-red)]`} />
    case 'review':
      return <CircleDot size={14} className={`${cls} text-[var(--color-accent-yellow)]`} />
    case 'merging':
      return <Loader2 size={14} className={`${cls} text-[var(--color-accent-green)] animate-spin`} />
    case 'merged':
      return <Check size={14} className={`${cls} text-[var(--color-accent-green)]`} />
    default:
      return null
  }
}
