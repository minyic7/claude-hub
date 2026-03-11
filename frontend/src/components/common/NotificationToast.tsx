import { AlertCircle, CheckCircle, Info, X, AlertTriangle } from 'lucide-react'
import type { Notification } from '../../hooks/useNotifications'

interface NotificationToastProps {
  notifications: Notification[]
  onDismiss: (id: string) => void
}

const icons = {
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  success: CheckCircle,
}

const colors = {
  error: 'border-[var(--color-accent-red)]/40 bg-[var(--color-accent-red)]/10 text-[var(--color-accent-red)]',
  warning: 'border-[var(--color-accent-yellow)]/40 bg-[var(--color-accent-yellow)]/10 text-[var(--color-accent-yellow)]',
  info: 'border-[var(--color-accent-blue)]/40 bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]',
  success: 'border-[var(--color-accent-green)]/40 bg-[var(--color-accent-green)]/10 text-[var(--color-accent-green)]',
}

export function NotificationToast({ notifications, onDismiss }: NotificationToastProps) {
  if (notifications.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {notifications.map((n) => {
        const Icon = icons[n.type]
        return (
          <div
            key={n.id}
            className={`flex items-start gap-2 rounded-lg border px-3 py-2 shadow-lg backdrop-blur-sm animate-in slide-in-from-right ${colors[n.type]}`}
          >
            <Icon size={16} className="mt-0.5 shrink-0" />
            <p className="flex-1 text-sm">{n.message}</p>
            <button onClick={() => onDismiss(n.id)} className="shrink-0 opacity-60 hover:opacity-100">
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
