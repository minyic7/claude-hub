import { useState, type FormEvent } from 'react'
import { Check } from 'lucide-react'
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

  return (
    <Modal open={open} onClose={onClose} title="New Ticket">
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
    </Modal>
  )
}
