import { useEffect, useRef, useState } from 'react'
import { AlertCircle, ArrowLeft, Check, CircleDot, Copy, ExternalLink, GitBranch, GitMerge, Loader2, MessageSquareWarning, Pencil, RefreshCw, RotateCcw, Send, Square, StickyNote, Trash2, Undo2, X } from 'lucide-react'
import { useIsMobile } from '../../hooks/useIsMobile'
import type { Ticket, TicketNote, TicketStatus } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { ActivityLog } from '../activity/ActivityLog'
import { StatusTimeline } from './StatusTimeline'
import { EscalationBanner } from '../activity/EscalationBanner'
import { api, type CIStatus } from '../../lib/api'
import { ConfirmationDialog } from '../common/ConfirmationDialog'
import { AgentReviewReport } from './AgentReviewReport'

interface TicketDetailProps {
  ticket: Ticket
  activities: ActivityEvent[]
  allTickets: Map<string, Ticket>
  onClose: () => void
  onDelete: () => void
  onTicketClick: (ticket: Ticket) => void
  mergeQueueLocked?: boolean
  onMergeInitiated?: () => void
}

function depStatusIcon(status: TicketStatus) {
  switch (status) {
    case 'merged': return <Check size={12} className="text-[var(--color-accent-green)]" />
    case 'in_progress': return <CircleDot size={12} className="text-[var(--color-accent-blue)] animate-pulse" />
    case 'blocked': return <AlertCircle size={12} className="text-[var(--color-accent-red)]" />
    case 'verifying': return <Loader2 size={12} className="text-[var(--color-accent-yellow)] animate-spin" />
    case 'reviewing': return <Loader2 size={12} className="text-[var(--color-accent-yellow)] animate-spin" />
    case 'review': return <CircleDot size={12} className="text-[var(--color-accent-yellow)]" />
    case 'merging': return <Loader2 size={12} className="text-[var(--color-accent-green)] animate-spin" />
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

export function TicketDetail({ ticket, activities, allTickets, onClose, onDelete, onTicketClick, mergeQueueLocked, onMergeInitiated }: TicketDetailProps) {
  const isMobile = useIsMobile()
  const sheetRef = useRef<HTMLDivElement>(null)
  const dragStartY = useRef<number | null>(null)
  const [showChangesForm, setShowChangesForm] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmStop, setConfirmStop] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(ticket.title)
  const [editDescription, setEditDescription] = useState(ticket.description)
  const [editDependsOn, setEditDependsOn] = useState<string[]>(ticket.depends_on)
  const [saving, setSaving] = useState(false)
  const [ciStatus, setCiStatus] = useState<CIStatus | null>(null)
  const [confirmRevert, setConfirmRevert] = useState(false)
  const [reverting, setReverting] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [syncingReviews, setSyncingReviews] = useState(false)
  const [noteText, setNoteText] = useState('')
  const [addingNote, setAddingNote] = useState(false)

  // Poll CI status when ticket is merging or in review
  useEffect(() => {
    if (ticket.status !== 'merging' && ticket.status !== 'review') {
      setCiStatus(null)
      return
    }
    let cancelled = false
    const poll = async () => {
      try {
        const status = await api.tickets.ciStatus(ticket.id)
        if (!cancelled) setCiStatus(status)
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 10_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [ticket.id, ticket.status])

  const handleStop = async () => {
    setStopping(true)
    try {
      await api.tickets.stop(ticket.id)
    } catch { /* global handler */ } finally {
      setStopping(false)
      setConfirmStop(false)
    }
  }

  const handleRetry = async () => {
    try { await api.tickets.retry(ticket.id) } catch { /* global handler */ }
  }

  const handleMarkReview = async () => {
    try { await api.tickets.markReview(ticket.id) } catch { /* global handler */ }
  }

  const handleSyncReviews = async () => {
    setSyncingReviews(true)
    try { await api.tickets.syncReviews(ticket.id) } catch { /* global handler */ }
    finally { setSyncingReviews(false) }
  }

  const handleMerge = async () => {
    onMergeInitiated?.()
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

  const handleRevert = async () => {
    setReverting(true)
    try {
      await api.tickets.revert(ticket.id)
    } catch { /* global handler */ } finally {
      setReverting(false)
      setConfirmRevert(false)
    }
  }

  const handleDuplicate = async () => {
    setDuplicating(true)
    try {
      await api.tickets.duplicate(ticket.id)
    } catch { /* global handler */ } finally {
      setDuplicating(false)
    }
  }

  const handleAddNote = async () => {
    if (!noteText.trim() || addingNote) return
    setAddingNote(true)
    try {
      await api.tickets.addNote(ticket.id, noteText.trim())
      setNoteText('')
    } catch { /* global handler */ } finally {
      setAddingNote(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.tickets.delete(ticket.id)
      onDelete()
    } catch { /* global handler */ } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  const handleStartEdit = () => {
    setEditTitle(ticket.title)
    setEditDescription(ticket.description)
    setEditDependsOn([...ticket.depends_on])
    setEditing(true)
  }

  const handleCancelEdit = () => {
    setEditing(false)
  }

  const handleSaveEdit = async () => {
    setSaving(true)
    try {
      await api.tickets.update(ticket.id, {
        title: editTitle.trim() || ticket.title,
        description: editDescription.trim(),
        depends_on: editDependsOn,
      })
      setEditing(false)
    } catch { /* global handler */ } finally {
      setSaving(false)
    }
  }

  const toggleEditDep = (id: string) => {
    setEditDependsOn((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const isRunning = ticket.status === 'in_progress' || ticket.status === 'verifying' || ticket.status === 'reviewing'

  // Idle detection for stuck IN_PROGRESS tickets (no activity for 2+ minutes)
  const [isIdle, setIsIdle] = useState(false)
  useEffect(() => {
    if (ticket.status !== 'in_progress' || activities.length === 0) {
      setIsIdle(false)
      return
    }
    const checkIdle = () => {
      const last = activities[activities.length - 1]
      if (last) {
        const lastTime = new Date(last.timestamp).getTime()
        setIsIdle(Date.now() - lastTime > 120_000)
      }
    }
    checkIdle()
    const timer = setInterval(checkIdle, 10_000)
    return () => clearInterval(timer)
  }, [ticket.status, activities])

  // Resolve dependencies
  const deps = ticket.depends_on.map((depId) => {
    const dep = allTickets.get(depId)
    return { id: depId, ticket: dep }
  })

  // Reverse dependencies: tickets that depend on this one
  const reverseDeps = [...allTickets.values()].filter(
    (t) => t.depends_on.includes(ticket.id)
  )

  // Available deps for picker (other tickets in same project, not this ticket)
  const availableDeps = [...allTickets.values()]
    .filter((t) => t.project_id === ticket.project_id && t.id !== ticket.id)
    .sort((a, b) => a.title.localeCompare(b.title))

  // Mobile swipe-to-close
  const handleTouchStart = (e: React.TouchEvent) => {
    if (!isMobile) return
    const el = sheetRef.current
    if (el && el.scrollTop <= 0) {
      dragStartY.current = e.touches[0].clientY
    }
  }
  const handleTouchEnd = (e: React.TouchEvent) => {
    if (!isMobile || dragStartY.current === null) return
    const delta = e.changedTouches[0].clientY - dragStartY.current
    dragStartY.current = null
    if (delta > 120) onClose()
  }

  return (
    <div
      ref={sheetRef}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      className={
        isMobile
          ? 'fixed inset-0 z-50 flex flex-col overflow-hidden bg-[var(--color-bg-panel)] animate-slide-up'
          : 'detail-panel flex w-[420px] shrink-0 flex-col overflow-hidden border-l border-[var(--color-border)] bg-[var(--color-bg-panel)]'
      }
    >
      {/* Mobile drag handle */}
      {isMobile && (
        <div className="flex justify-center py-2 shrink-0">
          <div className="h-1 w-10 rounded-full bg-[var(--color-text-muted)]/30" />
        </div>
      )}
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
            <Button size="sm" variant="danger" onClick={() => setConfirmStop(true)}>
              <Square size={12} className="mr-1" /> Stop
            </Button>
          )}
          {ticket.status === 'in_progress' && isIdle && (
            <Button size="sm" variant="secondary" onClick={handleRetry}>
              <RotateCcw size={12} className="mr-1" /> Retry
            </Button>
          )}
          {ticket.status === 'failed' && (
            <>
              <Button size="sm" variant="secondary" onClick={() => setConfirmRevert(true)}>
                <Undo2 size={12} className="mr-1" /> Revert
              </Button>
              <Button size="sm" variant="secondary" onClick={handleMarkReview}>
                Mark Review
              </Button>
              {ticket.pr_number && (
                <Button size="sm" variant="secondary" onClick={handleSyncReviews} disabled={syncingReviews}>
                  <RefreshCw size={12} className={`mr-1 ${syncingReviews ? 'animate-spin' : ''}`} /> Sync
                </Button>
              )}
              <Button size="sm" onClick={handleRetry}>
                <RotateCcw size={12} className="mr-1" /> Retry
              </Button>
            </>
          )}
          {ticket.status === 'review' && (
            <>
              <Button size="sm" variant="secondary" onClick={() => setConfirmRevert(true)}>
                <Undo2 size={12} className="mr-1" /> Revert
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setShowChangesForm(!showChangesForm)}>
                <MessageSquareWarning size={12} className="mr-1" /> Changes
              </Button>
              <Button size="sm" variant="secondary" onClick={handleSyncReviews} disabled={syncingReviews}>
                <RefreshCw size={12} className={`mr-1 ${syncingReviews ? 'animate-spin' : ''}`} /> Sync
              </Button>
              <Button size="sm" onClick={handleMerge} disabled={ticket.has_conflicts || mergeQueueLocked}>
                <GitMerge size={12} className="mr-1" /> Merge
              </Button>
            </>
          )}
          {ticket.status === 'merging' && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--color-accent-green)]">
              <Loader2 size={12} className="animate-spin" /> Waiting for CI...
            </span>
          )}
          {ticket.status === 'merged' && (
            <Button size="sm" variant="secondary" onClick={handleDuplicate} disabled={duplicating}>
              <Copy size={12} className="mr-1" /> {duplicating ? 'Duplicating...' : 'Re-run as New'}
            </Button>
          )}
          {ticket.status === 'todo' && !editing && (
            <Button size="sm" variant="secondary" onClick={handleStartEdit}>
              <Pencil size={12} className="mr-1" /> Edit
            </Button>
          )}
          <button
            onClick={() => setConfirmDelete(true)}
            className="rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-accent-red)]/10 hover:text-[var(--color-accent-red)]"
            title="Delete ticket"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Scrollable content area */}
      <div className="flex-1 overflow-y-auto min-h-0">

      {/* Deploy queue banner */}
      {mergeQueueLocked && ticket.status === 'review' && (
        <div className="border-b border-[var(--color-border)] p-3">
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-accent-yellow)]/30 bg-[var(--color-accent-yellow)]/5 px-3 py-2 text-xs text-[var(--color-accent-yellow)]">
            <Loader2 size={14} className="animate-spin shrink-0" />
            <span>Deploy in progress — merge is queued until current deploy completes</span>
          </div>
        </div>
      )}

      {/* Edit form (TODO only) */}
      {editing && ticket.status === 'todo' && (
        <div className="border-b border-[var(--color-border)] p-3 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">Title</label>
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-blue)] focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">Description</label>
            <textarea
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              rows={3}
              className="w-full resize-none rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-blue)] focus:outline-none"
            />
          </div>
          {/* Dependency picker */}
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
              Depends on
            </label>
            {/* Selected deps as chips */}
            {editDependsOn.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1">
                {editDependsOn.map((depId) => {
                  const dep = allTickets.get(depId)
                  return (
                    <span
                      key={depId}
                      className="inline-flex items-center gap-1 rounded-full border border-[var(--color-accent-blue)]/30 bg-[var(--color-accent-blue)]/10 px-2 py-0.5 text-xs text-[var(--color-accent-blue)]"
                    >
                      <span className="max-w-[120px] truncate" title={dep?.title}>{dep?.seq ? `#${dep.seq}` : dep?.title || `#${depId.slice(0, 6)}`}</span>
                      <button
                        type="button"
                        onClick={() => toggleEditDep(depId)}
                        className="shrink-0 hover:text-[var(--color-accent-red)]"
                      >
                        <X size={10} />
                      </button>
                    </span>
                  )
                })}
              </div>
            )}
            {availableDeps.length > 0 && (
              <div className="max-h-32 overflow-y-auto rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)]">
                {availableDeps.map((dep) => {
                  const selected = editDependsOn.includes(dep.id)
                  return (
                    <button
                      key={dep.id}
                      type="button"
                      onClick={() => toggleEditDep(dep.id)}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--color-bg-secondary)] ${selected ? 'bg-[var(--color-accent-blue)]/5' : ''}`}
                    >
                      <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                        selected
                          ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)] text-white'
                          : 'border-[var(--color-border)]'
                      }`}>
                        {selected && <Check size={10} />}
                      </span>
                      <span className="flex-1 truncate text-[var(--color-text-primary)]">{dep.seq > 0 && <span className="text-[var(--color-text-muted)] mr-1">#{dep.seq}</span>}{dep.title}</span>
                      <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
                        {dep.status.replace('_', ' ')}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="secondary" onClick={handleCancelEdit}>Cancel</Button>
            <Button size="sm" onClick={handleSaveEdit} disabled={saving || !editTitle.trim()}>
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </div>
      )}

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

      {/* CI Status panel */}
      {ciStatus && ciStatus.status !== 'no_ci' && (
        <div className="border-b border-[var(--color-border)] p-3">
          <div className={`rounded-lg border p-3 ${
            ciStatus.status === 'passed' ? 'border-[var(--color-accent-green)]/30 bg-[var(--color-accent-green)]/5' :
            ciStatus.status === 'failed' ? 'border-[var(--color-accent-red)]/30 bg-[var(--color-accent-red)]/5' :
            'border-[var(--color-accent-blue)]/30 bg-[var(--color-accent-blue)]/5'
          }`}>
            <div className="flex items-center gap-2 text-xs font-medium">
              {ciStatus.status === 'passed' && <Check size={14} className="text-[var(--color-accent-green)]" />}
              {ciStatus.status === 'failed' && <AlertCircle size={14} className="text-[var(--color-accent-red)]" />}
              {ciStatus.status === 'pending' && <Loader2 size={14} className="text-[var(--color-accent-blue)] animate-spin" />}
              <span className={
                ciStatus.status === 'passed' ? 'text-[var(--color-accent-green)]' :
                ciStatus.status === 'failed' ? 'text-[var(--color-accent-red)]' :
                'text-[var(--color-accent-blue)]'
              }>
                {ciStatus.summary}
              </span>
            </div>
            {ciStatus.checks.length > 0 && (
              <div className="mt-2 space-y-1">
                {ciStatus.checks.map((check, i) => {
                  const bucket = (check.bucket || '').toUpperCase()
                  const conclusion = (check.conclusion || '').toUpperCase()
                  const state = (check.state || check.status || '').toUpperCase()
                  const isPassed = bucket === 'PASS' || conclusion === 'SUCCESS' || state === 'SUCCESS' || state === 'PASS'
                  const isFailed = bucket === 'FAIL' || conclusion === 'FAILURE' || conclusion === 'TIMED_OUT' || conclusion === 'CANCELLED'
                  const url = check.html_url || check.detailsUrl || check.link
                  return (
                    <div key={i} className="flex items-center gap-2 text-[11px] text-[var(--color-text-secondary)]">
                      {isPassed && <Check size={11} className="text-[var(--color-accent-green)]" />}
                      {isFailed && <X size={11} className="text-[var(--color-accent-red)]" />}
                      {!isPassed && !isFailed && <Loader2 size={11} className="text-[var(--color-accent-blue)] animate-spin" />}
                      <span>{check.name}</span>
                      {url && (
                        <a href={url} target="_blank" rel="noopener noreferrer" className="ml-auto text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
                          <ExternalLink size={10} />
                        </a>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Ticket info */}
      <div className="border-b border-[var(--color-border)] p-3">
        <h2 className="mb-2 text-sm font-semibold text-[var(--color-text-primary)]">
          {ticket.seq > 0 && <span className="text-[var(--color-text-muted)] mr-1.5">#{ticket.seq}</span>}
          {ticket.title}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge color="blue">{ticket.branch_type}</Badge>
          <span className="flex items-center gap-1 text-[var(--color-text-muted)]">
            <GitBranch size={11} /> {ticket.branch}
          </span>
          {ticket.pr_url && (
            <a
              href={ticket.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[var(--color-accent-blue)] hover:underline"
            >
              PR #{ticket.pr_number} <ExternalLink size={10} />
            </a>
          )}
        </div>
        {ticket.description && (
          <p className="mt-2 text-xs text-[var(--color-text-secondary)]">{ticket.description}</p>
        )}
        <div className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--color-text-muted)]">
          {ticket.agent_cost_usd > 0 && <span>Cost: ~${ticket.agent_cost_usd.toFixed(2)}{ticket.agent_tokens > 0 && ` (${ticket.agent_tokens >= 1_000_000 ? `${(ticket.agent_tokens / 1_000_000).toFixed(1)}M` : ticket.agent_tokens >= 1_000 ? `${(ticket.agent_tokens / 1_000).toFixed(0)}k` : ticket.agent_tokens} tokens)`}</span>}
          {ticket.tmux_session && <span>tmux: {ticket.tmux_session}</span>}
        </div>
      </div>

      {/* Status Timeline */}
      <StatusTimeline ticket={ticket} activities={activities} />

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
            {ticket.tmux_session && (
              <div className="mt-2">
                <p className="text-xs text-[var(--color-text-muted)]">Session preserved — inspect directly:</p>
                <pre className="mt-1 rounded bg-[var(--color-bg-secondary)] px-2 py-1.5 text-xs font-mono text-[var(--color-text-secondary)] select-all">
                  docker exec -it claude-hub bash{'\n'}tmux attach -t {ticket.tmux_session}
                </pre>
              </div>
            )}
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
                title={dep?.title || 'Unknown ticket'}
              >
                {depStatusIcon((dep?.status || 'todo') as TicketStatus)}
                <span className="font-semibold text-[var(--color-text-primary)]">
                  #{dep?.seq || id.slice(0, 6)}
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

      {/* Reverse dependencies */}
      {reverseDeps.length > 0 && (
        <div className="border-b border-[var(--color-border)] p-3">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Required by
          </h3>
          <div className="space-y-1">
            {reverseDeps.map((rdep) => (
              <button
                key={rdep.id}
                onClick={() => onTicketClick(rdep)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-[var(--color-bg-secondary)]"
                title={rdep.title}
              >
                {depStatusIcon(rdep.status as TicketStatus)}
                <span className="font-semibold text-[var(--color-text-primary)]">
                  #{rdep.seq || rdep.id.slice(0, 6)}
                </span>
                <span className="flex-1 truncate text-[var(--color-text-secondary)]">
                  {rdep.title}
                </span>
                <span className={`text-[10px] ${depStatusColor(rdep.status as TicketStatus)}`}>
                  {rdep.status.replace('_', ' ')}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Agent Review Report */}
      {ticket.agent_review && (
        <div className="border-b border-[var(--color-border)] px-3 py-2">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Agent Review
          </h3>
          <AgentReviewReport reviewJson={ticket.agent_review} />
        </div>
      )}

      {/* Notes */}
      <NotesSection
        notes={parseNotes(ticket.notes)}
        noteText={noteText}
        onNoteTextChange={setNoteText}
        onAddNote={handleAddNote}
        addingNote={addingNote}
      />

      {/* Activity log */}
      <div className="border-b border-[var(--color-border)] p-3">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Activity
        </h3>
        <ActivityLog events={activities} />
      </div>

      </div>{/* end scrollable content */}

      {/* Message input for active sessions */}
      {(ticket.status === 'in_progress' || ticket.status === 'blocked') && (
        <MessageInput ticketId={ticket.id} isBlocked={ticket.status === 'blocked'} hasSession={!!ticket.tmux_session} />
      )}

      {/* Footer */}
      {ticket.tmux_session && (
        <div className="border-t border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
          <p className="font-mono">tmux attach -t {ticket.tmux_session}</p>
        </div>
      )}

      <ConfirmationDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={handleDelete}
        title="Delete Ticket"
        description="This will permanently delete this ticket and cannot be undone."
        ticketTitle={ticket.title}
        confirmLabel="Delete"
        loading={deleting}
      />

      <ConfirmationDialog
        open={confirmStop}
        onClose={() => setConfirmStop(false)}
        onConfirm={handleStop}
        title="Stop Ticket"
        description="This will stop the running Claude Code session for this ticket."
        ticketTitle={ticket.title}
        confirmLabel="Stop"
        loading={stopping}
      />

      <ConfirmationDialog
        open={confirmRevert}
        onClose={() => setConfirmRevert(false)}
        onConfirm={handleRevert}
        title="Revert to TODO"
        description="This will reset the ticket back to TODO status. Branch and PR info will be preserved."
        ticketTitle={ticket.title}
        confirmLabel="Revert"
        loading={reverting}
      />
    </div>
  )
}

/** Parse notes from Redis (may be JSON string or already an array) */
function parseNotes(raw: TicketNote[] | string | undefined): TicketNote[] {
  if (!raw) return []
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return [] }
  }
  return raw
}

const NOTE_TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  comment: { bg: 'bg-[var(--color-accent-blue)]/10', text: 'text-[var(--color-accent-blue)]', label: 'Comment' },
  progress: { bg: 'bg-[var(--color-accent-green)]/10', text: 'text-[var(--color-accent-green)]', label: 'Progress' },
  blocker: { bg: 'bg-[var(--color-accent-red)]/10', text: 'text-[var(--color-accent-red)]', label: 'Blocker' },
  review: { bg: 'bg-[var(--color-accent-yellow)]/10', text: 'text-[var(--color-accent-yellow)]', label: 'Review' },
  system: { bg: 'bg-[var(--color-bg-secondary)]', text: 'text-[var(--color-text-muted)]', label: 'System' },
}

function NotesSection({
  notes, noteText, onNoteTextChange, onAddNote, addingNote,
}: {
  notes: TicketNote[]
  noteText: string
  onNoteTextChange: (v: string) => void
  onAddNote: () => void
  addingNote: boolean
}) {
  return (
    <div className="border-b border-[var(--color-border)] p-3">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
        <StickyNote size={12} /> Notes {notes.length > 0 && `(${notes.length})`}
      </h3>

      {/* Existing notes */}
      {notes.length > 0 && (
        <div className="mb-2 max-h-40 space-y-1.5 overflow-y-auto">
          {notes.map((note, i) => {
            const style = NOTE_TYPE_STYLES[note.type] || NOTE_TYPE_STYLES.comment
            return (
              <div key={i} className="rounded-md border border-[var(--color-border)]/50 px-2.5 py-1.5">
                <div className="flex items-center gap-2 text-[10px]">
                  <span className={`rounded px-1.5 py-0.5 font-medium ${style.bg} ${style.text}`}>
                    {style.label}
                  </span>
                  <span className="text-[var(--color-text-muted)]">
                    {note.author} · {new Date(note.timestamp).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap">{note.content}</p>
              </div>
            )
          })}
        </div>
      )}

      {/* Add note input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={noteText}
          onChange={(e) => onNoteTextChange(e.target.value)}
          placeholder="Add a note..."
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onAddNote() } }}
          className="flex-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-1.5 text-xs text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
        />
        <button
          onClick={onAddNote}
          disabled={!noteText.trim() || addingNote}
          className="rounded bg-[var(--color-accent-blue)] px-2.5 py-1.5 text-xs text-white transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {addingNote ? '...' : 'Add'}
        </button>
      </div>
    </div>
  )
}

function MessageInput({ ticketId, isBlocked, hasSession }: { ticketId: string; isBlocked: boolean; hasSession: boolean }) {
  const [msg, setMsg] = useState('')
  const [sending, setSending] = useState(false)

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!msg.trim() || sending) return
    setSending(true)
    try {
      await api.tickets.message(ticketId, msg.trim())
      setMsg('')
    } catch { /* global error handler */ } finally {
      setSending(false)
    }
  }

  return (
    <div className="border-t border-[var(--color-border)] px-3 py-2">
      <form onSubmit={handleSend} className="flex items-center gap-2">
        <input
          type="text"
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          placeholder={hasSession ? (isBlocked ? 'Answer or message...' : 'Message Claude Code...') : 'No active session'}
          disabled={!hasSession}
          className="flex-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-1.5 text-xs text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!msg.trim() || sending || !hasSession}
          className="rounded bg-[var(--color-accent-blue)] p-1.5 text-white transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          <Send size={14} />
        </button>
      </form>
    </div>
  )
}
