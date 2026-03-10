import { useState, type FormEvent } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { api } from '../../lib/api'
import type { BranchType } from '../../types/ticket'

interface CreateTicketModalProps {
  open: boolean
  onClose: () => void
  projectId: string
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

export function CreateTicketModal({ open, onClose, projectId }: CreateTicketModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [branchType, setBranchType] = useState<BranchType>('feature')
  const [role, setRole] = useState('builder')
  const [loading, setLoading] = useState(false)

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
        role,
      })
      setTitle('')
      setDescription('')
      setBranchType('feature')
      setRole('builder')
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

        <div className="flex gap-4">
          <div className="flex-1">
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

          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-blue)] focus:outline-none"
            >
              <option value="builder">Builder</option>
              <option value="reviewer">Reviewer</option>
              <option value="tester">Tester</option>
            </select>
          </div>
        </div>

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
