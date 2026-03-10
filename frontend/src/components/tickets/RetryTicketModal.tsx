import { useState } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { api } from '../../lib/api'

interface RetryTicketModalProps {
  open: boolean
  onClose: () => void
  ticketId: string
}

export function RetryTicketModal({ open, onClose, ticketId }: RetryTicketModalProps) {
  const [guidance, setGuidance] = useState('')
  const [loading, setLoading] = useState(false)

  const handleRetry = async () => {
    setLoading(true)
    try {
      await api.tickets.retry(ticketId, guidance.trim() || undefined)
      setGuidance('')
      onClose()
    } catch (err) {
      console.error('Failed to retry:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Retry Ticket">
      <div className="flex flex-col gap-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">
            Additional guidance (optional)
          </label>
          <textarea
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            placeholder="Any additional instructions for the retry..."
            rows={3}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none resize-none"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleRetry} disabled={loading}>
            {loading ? 'Retrying...' : 'Retry'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
