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
  const visible = notifications.filter((n) => n.bannerVisible)
  if (visible.length === 0) return null

  return (
    <div className="fixed bottom-8 left-8 z-50 flex flex-col gap-1.5 max-w-[260px]">
      {visible.map((n) => {
        const Icon = icons[n.type]
        return (
          <div
            key={n.id}
            className={`flex items-start gap-1.5 rounded-md border px-2 py-1.5 shadow-md backdrop-blur-md bg-[var(--color-bg-panel)]/70 animate-in slide-in-from-left ${colors[n.type]}`}
          >
            <Icon size={13} className="mt-0.5 shrink-0" />
            <p className="flex-1 text-xs leading-snug">{n.message}</p>
            <button onClick={() => onDismiss(n.id)} className="shrink-0 opacity-50 hover:opacity-100">
              <X size={12} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
