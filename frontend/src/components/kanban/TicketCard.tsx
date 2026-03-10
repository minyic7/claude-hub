import type { MouseEvent } from 'react'
import { AlertCircle, Check, CircleDot, Loader2, Play, RotateCcw, ExternalLink } from 'lucide-react'
import type { Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { api } from '../../lib/api'

interface TicketCardProps {
  ticket: Ticket
  latestActivity?: ActivityEvent
  onClick: () => void
}

export function TicketCard({ ticket, latestActivity, onClick }: TicketCardProps) {
  const handleStart = async (e: MouseEvent) => {
    e.stopPropagation()
    await api.tickets.start(ticket.id)
  }

  const handleRetry = async (e: MouseEvent) => {
    e.stopPropagation()
    await api.tickets.retry(ticket.id)
  }

  return (
    <div
      onClick={onClick}
      className="cursor-pointer rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-3 transition-all hover:border-[var(--color-accent-blue)]/40 hover:shadow-sm"
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
      </div>

      <p className="mb-2 truncate text-xs text-[var(--color-text-muted)]">
        {ticket.branch}
      </p>

      {/* Status-specific content */}
      {ticket.status === 'todo' && (
        <Button size="sm" onClick={handleStart} className="w-full">
          <Play size={12} className="mr-1" /> Start
        </Button>
      )}

      {(ticket.status === 'in_progress' || ticket.status === 'verifying') && latestActivity && (
        <p className="truncate text-xs text-[var(--color-text-muted)]">
          {latestActivity.summary}
        </p>
      )}

      {ticket.status === 'blocked' && ticket.blocked_question && (
        <p className="truncate text-xs text-[var(--color-accent-red)]">
          {ticket.blocked_question}
        </p>
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

      {ticket.status === 'review' && ticket.pr_url && (
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

      {ticket.agent_cost_usd > 0 && (
        <p className="mt-1 text-right text-xs text-[var(--color-text-muted)]">
          ${ticket.agent_cost_usd.toFixed(2)}
        </p>
      )}
    </div>
  )
}

function StatusIndicator({ status }: { status: string }) {
  switch (status) {
    case 'in_progress':
      return <CircleDot size={14} className="shrink-0 text-[var(--color-accent-blue)] animate-pulse" />
    case 'blocked':
      return <AlertCircle size={14} className="shrink-0 text-[var(--color-accent-red)]" />
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
