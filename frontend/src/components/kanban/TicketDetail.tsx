import { useState } from 'react'
import { AlertCircle, ArrowLeft, Check, CircleDot, ExternalLink, GitBranch, GitMerge, Loader2, MessageSquareWarning, RefreshCw, RotateCcw, Square } from 'lucide-react'
import type { Ticket, TicketStatus } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { ActivityLog } from '../activity/ActivityLog'
import { EscalationBanner } from '../activity/EscalationBanner'
import { api } from '../../lib/api'

interface TicketDetailProps {
  ticket: Ticket
  activities: ActivityEvent[]
  allTickets: Map<string, Ticket>
  onClose: () => void
  onTicketClick: (ticket: Ticket) => void
}

function depStatusIcon(status: TicketStatus) {
  switch (status) {
    case 'merged': return <Check size={12} className="text-[var(--color-accent-green)]" />
    case 'in_progress': return <CircleDot size={12} className="text-[var(--color-accent-blue)] animate-pulse" />
    case 'blocked': return <AlertCircle size={12} className="text-[var(--color-accent-red)]" />
    case 'verifying': return <Loader2 size={12} className="text-[var(--color-accent-yellow)] animate-spin" />
    case 'review': return <CircleDot size={12} className="text-[var(--color-accent-yellow)]" />
    case 'failed': return <AlertCircle size={12} className="text-[var(--color-accent-red)]" />
    default: return <CircleDot size={12} className="text-[var(--color-text-muted)]" />
  }
}

function depStatusColor(status: TicketStatus): string {
  switch (status) {
    case 'merged': return 'text-[var(--color-accent-green)]'
    case 'in_progress': return 'text-[var(--color-accent-blue)]'
    case 'blocked': case 'failed': return 'text-[var(--color-accent-red)]'
    case 'review': return 'text-[var(--color-accent-yellow)]'
    default: return 'text-[var(--color-text-muted)]'
  }
}

export function TicketDetail({ ticket, activities, allTickets, onClose, onTicketClick }: TicketDetailProps) {
  const [showChangesForm, setShowChangesForm] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleStop = async () => {
    try { await api.tickets.stop(ticket.id) } catch { /* global handler */ }
  }

  const handleRetry = async () => {
    try { await api.tickets.retry(ticket.id) } catch { /* global handler */ }
  }

  const handleMarkReview = async () => {
    try { await api.tickets.markReview(ticket.id) } catch { /* global handler */ }
  }

  const handleMerge = async () => {
    try { await api.tickets.merge(ticket.id) } catch { /* global handler */ }
  }

  const handleRequestChanges = async () => {
    if (!feedback.trim()) return
    setSubmitting(true)
    try {
      await api.tickets.requestChanges(ticket.id, feedback.trim())
      setFeedback('')
      setShowChangesForm(false)
    } catch { /* global handler */ } finally {
      setSubmitting(false)
    }
  }

  const [resolving, setResolving] = useState(false)
  const handleResolveConflicts = async () => {
    setResolving(true)
    try { await api.tickets.resolveConflicts(ticket.id) } catch { /* global handler */ } finally {
      setResolving(false)
    }
  }

  const isRunning = ticket.status === 'in_progress' || ticket.status === 'verifying'

  // Resolve dependencies
  const deps = ticket.depends_on.map((depId) => {
    const dep = allTickets.get(depId)
    return { id: depId, ticket: dep }
  })

  return (
    <div className="detail-panel flex w-[420px] shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-panel)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] p-3">
        <button
          onClick={onClose}
          className="flex items-center gap-1 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div className="flex gap-2">
          {isRunning && (
            <Button size="sm" variant="danger" onClick={handleStop}>
              <Square size={12} className="mr-1" /> Stop
            </Button>
          )}
          {ticket.status === 'failed' && (
            <>
              <Button size="sm" variant="secondary" onClick={handleMarkReview}>
                Mark Review
              </Button>
              <Button size="sm" onClick={handleRetry}>
                <RotateCcw size={12} className="mr-1" /> Retry
              </Button>
            </>
          )}
          {ticket.status === 'review' && (
            <>
              <Button size="sm" variant="secondary" onClick={() => setShowChangesForm(!showChangesForm)}>
                <MessageSquareWarning size={12} className="mr-1" /> Changes
              </Button>
              <Button size="sm" onClick={handleMerge} disabled={ticket.has_conflicts}>
                <GitMerge size={12} className="mr-1" /> Merge
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Request Changes form */}
      {showChangesForm && ticket.status === 'review' && (
        <div className="border-b border-[var(--color-border)] p-3">
          <div className="rounded-lg border border-[var(--color-accent-yellow)]/30 bg-[var(--color-accent-yellow)]/5 p-3">
            <p className="mb-2 text-xs font-medium text-[var(--color-accent-yellow)]">Request Changes</p>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="What needs to be fixed?"
              rows={3}
              className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
            />
            <div className="mt-2 flex justify-end gap-2">
              <Button size="sm" variant="secondary" onClick={() => setShowChangesForm(false)}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleRequestChanges} disabled={!feedback.trim() || submitting}>
                Submit
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Conflict banner for review tickets */}
      {ticket.status === 'review' && ticket.has_conflicts && (
        <div className="border-b border-[var(--color-border)] p-3">
          <div className="rounded-lg border border-[var(--color-accent-yellow)]/30 bg-[var(--color-accent-yellow)]/5 p-3">
            <div className="flex items-start gap-2">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-[var(--color-accent-yellow)]" />
              <div>
                <p className="text-xs font-medium text-[var(--color-accent-yellow)]">PR has merge conflicts</p>
                <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                  Base branch has diverged since this PR was created.
                </p>
              </div>
            </div>
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={handleResolveConflicts} disabled={resolving}>
                <RefreshCw size={12} className={`mr-1 ${resolving ? 'animate-spin' : ''}`} /> {resolving ? 'Resolving...' : 'Resolve Conflicts'}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setShowChangesForm(true)}>
                Request Changes
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Ticket info */}
      <div className="border-b border-[var(--color-border)] p-3">
        <h2 className="mb-2 text-sm font-semibold text-[var(--color-text-primary)]">
          {ticket.title}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge color="blue">{ticket.branch_type}</Badge>
          <Badge>{ticket.role}</Badge>
          <span className="flex items-center gap-1 text-[var(--color-text-muted)]">
            <GitBranch size={11} /> {ticket.branch}
          </span>
        </div>
        {ticket.description && (
          <p className="mt-2 text-xs text-[var(--color-text-secondary)]">{ticket.description}</p>
        )}
        <div className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--color-text-muted)]">
          {ticket.agent_cost_usd > 0 && <span>Cost: ~${ticket.agent_cost_usd.toFixed(2)}{ticket.agent_tokens > 0 && ` (${ticket.agent_tokens >= 1_000_000 ? `${(ticket.agent_tokens / 1_000_000).toFixed(1)}M` : ticket.agent_tokens >= 1_000 ? `${(ticket.agent_tokens / 1_000).toFixed(0)}k` : ticket.agent_tokens} tokens)`}</span>}
          {ticket.tmux_session && <span>tmux: {ticket.tmux_session}</span>}
        </div>
      </div>

      {/* Escalation */}
      {ticket.status === 'blocked' && ticket.blocked_question && (
        <div className="border-b border-[var(--color-border)] p-3">
          <EscalationBanner ticketId={ticket.id} question={ticket.blocked_question} />
        </div>
      )}

      {/* Failed reason banner */}
      {ticket.status === 'failed' && ticket.failed_reason && (
        <div className="border-b border-[var(--color-border)] p-3">
          <div className="rounded-lg border border-[var(--color-accent-red)]/30 bg-[var(--color-accent-red)]/5 p-3">
            <p className="text-xs font-medium text-[var(--color-accent-red)]">Failed</p>
            <p className="mt-1 text-sm text-[var(--color-text-primary)]">{ticket.failed_reason}</p>
          </div>
        </div>
      )}

      {/* Dependencies */}
      {deps.length > 0 && (
        <div className="border-b border-[var(--color-border)] p-3">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Dependencies
          </h3>
          <div className="space-y-1">
            {deps.map(({ id, ticket: dep }) => (
              <button
                key={id}
                onClick={() => dep && onTicketClick(dep)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-[var(--color-bg-secondary)]"
              >
                {depStatusIcon((dep?.status || 'todo') as TicketStatus)}
                <span className="font-semibold text-[var(--color-text-primary)]">
                  #{id.slice(0, 6)}
                </span>
                <span className="flex-1 truncate text-[var(--color-text-secondary)]">
                  {dep?.title || 'Unknown ticket'}
                </span>
                <span className={`text-[10px] ${depStatusColor((dep?.status || 'todo') as TicketStatus)}`}>
                  {dep?.status?.replace('_', ' ') || 'missing'}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Activity log */}
      <div className="flex flex-1 flex-col overflow-hidden p-3">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Activity
        </h3>
        <div className="flex-1 overflow-y-auto">
          <ActivityLog events={activities} />
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-[var(--color-border)] p-3 text-xs text-[var(--color-text-muted)]">
        {ticket.tmux_session && (
          <p className="font-mono">tmux attach -t {ticket.tmux_session}</p>
        )}
        {ticket.pr_url && (
          <a
            href={ticket.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 flex items-center gap-1 text-[var(--color-accent-blue)] hover:underline"
          >
            PR #{ticket.pr_number} <ExternalLink size={10} />
          </a>
        )}
      </div>
    </div>
  )
}
