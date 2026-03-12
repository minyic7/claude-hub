import { Modal } from './Modal'
import { Button } from './Button'

interface ConfirmationDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description: string
  ticketTitle: string
  confirmLabel: string
  loading?: boolean
}

export function ConfirmationDialog({ open, onClose, onConfirm, title, description, ticketTitle, confirmLabel, loading }: ConfirmationDialogProps) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="space-y-3">
        <p className="text-sm text-[var(--color-text-secondary)]">{description}</p>
        <div className="rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2">
          <p className="text-sm font-medium text-[var(--color-text-primary)]">{ticketTitle}</p>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button size="sm" variant="secondary" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button size="sm" variant="danger" onClick={onConfirm} disabled={loading}>
            {loading ? 'Processing...' : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
