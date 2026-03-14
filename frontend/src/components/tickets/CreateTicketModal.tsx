import { useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, Check } from 'lucide-react'
import { useIsMobile } from '../../hooks/useIsMobile'
import { useVisualViewport } from '../../hooks/useVisualViewport'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { api } from '../../lib/api'
import type { BranchType, Ticket } from '../../types/ticket'

interface CreateTicketModalProps {
  open: boolean
  onClose: () => void
  projectId: string
  tickets: Map<string, Ticket>
}

const BRANCH_TYPES: { value: BranchType; label: string }[] = [
  { value: 'feature', label: 'Feature' },
  { value: 'bugfix', label: 'Bug Fix' },
  { value: 'hotfix', label: 'Hot Fix' },
  { value: 'chore', label: 'Chore' },
  { value: 'refactor', label: 'Refactor' },
  { value: 'docs', label: 'Docs' },
  { value: 'test', label: 'Test' },
]

export function CreateTicketModal({ open, onClose, projectId, tickets }: CreateTicketModalProps) {
  const isMobile = useIsMobile()
  const keyboardOffset = useVisualViewport(isMobile && open)
  const sheetRef = useRef<HTMLDivElement>(null)
  const dragStartY = useRef<number | null>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [branchType, setBranchType] = useState<BranchType>('feature')
  const [dependsOn, setDependsOn] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  // Filter tickets for the same project that are not yet merged
  const availableDeps = [...tickets.values()]
    .filter((t) => t.project_id === projectId && t.status !== 'merged')
    .sort((a, b) => a.title.localeCompare(b.title))

  const toggleDep = (id: string) => {
    setDependsOn((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return

    setLoading(true)
    try {
      await api.tickets.create({
        project_id: projectId,
        title: title.trim(),
        description: description.trim(),
        branch_type: branchType,
        depends_on: dependsOn.length > 0 ? dependsOn : undefined,
      })
      setTitle('')
      setDescription('')
      setBranchType('feature')
      setDependsOn([])
      onClose()
    } catch (err) {
      console.error('Failed to create ticket:', err)
    } finally {
      setLoading(false)
    }
  }

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

  if (!open) return null

  const formContent = (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add user authentication"
          className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
          autoFocus
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Detailed task description..."
          rows={4}
          className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none resize-none"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">Branch Type</label>
        <select
          value={branchType}
          onChange={(e) => setBranchType(e.target.value as BranchType)}
          className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-blue)] focus:outline-none"
        >
          {BRANCH_TYPES.map((bt) => (
            <option key={bt.value} value={bt.value}>{bt.label}</option>
          ))}
        </select>
      </div>

      {/* Dependency picker */}
      {availableDeps.length > 0 && (
        <div>
          <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">
            Depends on
          </label>
          <div className="max-h-36 overflow-y-auto rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)]">
            {availableDeps.map((dep) => {
              const selected = dependsOn.includes(dep.id)
              return (
                <button
                  key={dep.id}
                  type="button"
                  onClick={() => toggleDep(dep.id)}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-[var(--color-bg-secondary)] ${
                    selected ? 'bg-[var(--color-accent-blue)]/5' : ''
                  }`}
                >
                  <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                    selected
                      ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)] text-white'
                      : 'border-[var(--color-border)]'
                  }`}>
                    {selected && <Check size={10} />}
                  </span>
                  <span className="flex-1 truncate text-[var(--color-text-primary)]">
                    {dep.seq > 0 && <span className="text-[var(--color-text-muted)] mr-1">#{dep.seq}</span>}
                    {dep.title}
                  </span>
                  <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
                    {dep.status.replace('_', ' ')}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={!title.trim() || loading}>
          {loading ? 'Creating...' : 'Create Ticket'}
        </Button>
      </div>
    </form>
  )

  // Mobile: render as full-screen bottom sheet
  if (isMobile) {
    return (
      <div
        ref={sheetRef}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-[var(--color-bg-panel)] animate-slide-up"
        style={keyboardOffset > 0 ? { height: `calc(100% - ${keyboardOffset}px)`, top: 0 } : undefined}
      >
        {/* Drag handle */}
        <div className="flex justify-center py-2 shrink-0">
          <div className="h-1 w-10 rounded-full bg-[var(--color-text-muted)]/30" />
        </div>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 pb-3">
          <button
            onClick={onClose}
            className="flex items-center gap-1 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
          >
            <ArrowLeft size={14} /> Back
          </button>
          <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">New Ticket</h2>
          <div className="w-12" /> {/* spacer for centering */}
        </div>
        {/* Scrollable form */}
        <div className="flex-1 overflow-y-auto p-4">
          {formContent}
        </div>
      </div>
    )
  }

  // Desktop: render as centered modal
  return (
    <Modal open={open} onClose={onClose} title="New Ticket">
      {formContent}
    </Modal>
  )
}
