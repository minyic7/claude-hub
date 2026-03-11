import { useCallback, useState } from 'react'

export interface Notification {
  id: string
  type: 'error' | 'warning' | 'info' | 'success'
  message: string
  timestamp: number
}

let nextId = 0

export function useNotifications() {
  const [notifications, setNotifications] = useState<Notification[]>([])

  const addNotification = useCallback((type: Notification['type'], message: string) => {
    const id = `n-${++nextId}`
    const notification: Notification = { id, type, message, timestamp: Date.now() }
    setNotifications((prev) => [...prev.slice(-19), notification])

    // Auto-dismiss after 6 seconds
    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n.id !== id))
    }, 6000)
  }, [])

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
  }, [])

  return { notifications, addNotification, dismiss }
}
