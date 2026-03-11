import { type FormEvent, type MouseEvent, useEffect, useRef, useState } from 'react'
import { AlertCircle, Check, CircleDot, GitMerge, Link, Loader2, Lock, MessageCircleQuestion, Play, RotateCcw, ExternalLink, Send } from 'lucide-react'
import type { Ticket, TicketStatus } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { api } from '../../lib/api'

interface DepLabel {
  id: string
  title?: string
  status: string
}

interface TicketCardProps {
  ticket: Ticket
  latestActivity?: ActivityEvent
  onClick: () => void
  onOptimistic?: (ticketId: string, patch: Partial<Ticket>) => void
  depsBlocked?: boolean
  depLabels?: DepLabel[]
}

export function TicketCard({ ticket, latestActivity, onClick, onOptimistic, depsBlocked, depLabels }: TicketCardProps) {
  const [actionError, setActionError] = useState<string | null>(null)
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
  const handleRetry = safeAction(
    () => api.tickets.retry(ticket.id),
    { status: 'in_progress', failed_reason: null },
    { status: 'failed', failed_reason: ticket.failed_reason },
  )
  const handleMerge = safeAction(
    () => api.tickets.merge(ticket.id),
    { status: 'merged' },
    { status: 'review' },
  )

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

  const isBlocked = ticket.status === 'blocked'

  return (
    <div
      onClick={onClick}
      data-blocked={isBlocked || undefined}
      className={`ticket-card cursor-pointer rounded-lg border p-3 ${
        isBlocked
          ? 'border-[var(--color-accent-red)]/60 bg-[var(--color-accent-red)]/5 hover:border-[var(--color-accent-red)]'
          : 'border-[var(--color-border)] bg-[var(--color-bg-panel)] hover:border-[var(--color-accent-blue)]/40'
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-[var(--color-text-primary)] line-clamp-2">
          {ticket.title}
        </h3>
        <StatusIndicator status={ticket.status} />
      </div>

      <div className="mb-2 flex items-center gap-1.5">
        <Badge color="blue">{ticket.branch_type}</Badge>
        {ticket.status === 'blocked' && <Badge color="red">ESCALATION</Badge>}
        {ticket.status === 'failed' && <Badge color="red">FAILED</Badge>}
        {ticket.status === 'verifying' && <Badge color="yellow">VERIFYING</Badge>}
        {isIdle && <Badge color="gray">IDLE</Badge>}
      </div>

      <p className="mb-2 truncate text-xs text-[var(--color-text-muted)]">
        {ticket.branch}
      </p>

      {/* Dependency labels for TODO tickets */}
      {ticket.status === 'todo' && depLabels && depLabels.length > 0 && depLabels.some((d) => d.status !== 'merged') && (
        <div className="mb-2 flex flex-wrap items-center gap-1 text-[11px] text-[var(--color-text-muted)]">
          <Link size={10} className="shrink-0" />
          {depLabels.filter((d) => d.status !== 'merged').map((d) => (
            <span key={d.id} className="inline-flex items-center gap-0.5">
              <span className="font-semibold">#{d.id.slice(0, 6)}</span>
              <span className={statusColor(d.status as TicketStatus)}>({d.status.replace('_', ' ')})</span>
            </span>
          ))}
        </div>
      )}

      {/* Status-specific content */}
      {ticket.status === 'todo' && (
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
      )}

      {(ticket.status === 'in_progress' || ticket.status === 'verifying') && latestActivity && (
        <p className="truncate text-xs text-[var(--color-text-muted)]">
          {latestActivity.summary}
        </p>
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
            <Button size="sm" onClick={handleMerge} disabled={ticket.has_conflicts}>
              <GitMerge size={12} className="mr-1" /> Merge
            </Button>
          </div>
        </div>
      )}

      {actionError && (
        <p className="mt-1 rounded bg-[var(--color-accent-red)]/10 px-2 py-1 text-xs text-[var(--color-accent-red)]">
          {actionError}
        </p>
      )}

      {ticket.agent_cost_usd > 0 && (
        <p className="mt-1 text-right text-xs text-[var(--color-text-muted)]">
          ~${ticket.agent_cost_usd.toFixed(2)}
        </p>
      )}
    </div>
  )
}

function statusColor(status: TicketStatus): string {
  switch (status) {
    case 'in_progress': return 'text-[var(--color-accent-blue)]'
    case 'blocked': return 'text-[var(--color-accent-red)]'
    case 'review': return 'text-[var(--color-accent-yellow)]'
    case 'merged': return 'text-[var(--color-accent-green)]'
    case 'failed': return 'text-[var(--color-accent-red)]'
    default: return 'text-[var(--color-text-muted)]'
  }
}

function StatusIndicator({ status }: { status: string }) {
  switch (status) {
    case 'in_progress':
      return <CircleDot size={14} className="shrink-0 text-[var(--color-accent-blue)] animate-pulse" />
    case 'blocked':
      return <AlertCircle size={14} className="shrink-0 text-[var(--color-accent-red)] animate-pulse" />
    case 'verifying':
      return <Loader2 size={14} className="shrink-0 text-[var(--color-accent-yellow)] animate-spin" />
    case 'failed':
      return <AlertCircle size={14} className="shrink-0 text-[var(--color-accent-red)]" />
    case 'review':
      return <CircleDot size={14} className="shrink-0 text-[var(--color-accent-yellow)]" />
    case 'merged':
      return <Check size={14} className="shrink-0 text-[var(--color-accent-green)]" />
    default:
      return null
  }
}
