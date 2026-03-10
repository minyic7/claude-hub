import { ArrowLeft, ExternalLink, GitBranch, Square, RotateCcw, CheckCircle } from 'lucide-react'
import type { Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { ActivityLog } from '../activity/ActivityLog'
import { EscalationBanner } from '../activity/EscalationBanner'
import { api } from '../../lib/api'

interface TicketDetailProps {
  ticket: Ticket
  activities: ActivityEvent[]
  onClose: () => void
}

export function TicketDetail({ ticket, activities, onClose }: TicketDetailProps) {
  const handleStop = async () => {
    await api.tickets.stop(ticket.id)
  }

  const handleRetry = async () => {
    await api.tickets.retry(ticket.id)
  }

  const handleMarkReview = async () => {
    await api.tickets.markReview(ticket.id)
  }

  const handleMerge = async () => {
    await api.tickets.merge(ticket.id)
  }

  const isRunning = ticket.status === 'in_progress' || ticket.status === 'verifying'

  return (
    <div className="flex w-[420px] shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-panel)]">
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
            <Button size="sm" onClick={handleMerge}>
              <CheckCircle size={12} className="mr-1" /> Mark Merged
            </Button>
          )}
        </div>
      </div>

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
          {ticket.agent_cost_usd > 0 && <span>Cost: ${ticket.agent_cost_usd.toFixed(2)}</span>}
          {ticket.tmux_session && <span>tmux: {ticket.tmux_session}</span>}
        </div>
      </div>

      {/* Escalation */}
      {ticket.status === 'blocked' && ticket.blocked_question && (
        <div className="border-b border-[var(--color-border)] p-3">
          <EscalationBanner ticketId={ticket.id} question={ticket.blocked_question} />
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
