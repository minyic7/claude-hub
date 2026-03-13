import { useCallback, useState } from 'react'

export interface NotificationAction {
  label: string
  callback: () => void
}

export interface Notification {
  id: string
  type: 'error' | 'warning' | 'info' | 'success'
  message: string
  timestamp: number
  bannerVisible: boolean
  read: boolean
  action?: NotificationAction
}

let nextId = 0

export function useNotifications() {
  const [notifications, setNotifications] = useState<Notification[]>([])

  const addNotification = useCallback((type: Notification['type'], message: string, action?: NotificationAction) => {
    const id = `n-${++nextId}`
    const notification: Notification = { id, type, message, timestamp: Date.now(), bannerVisible: true, read: false, action }
    setNotifications((prev) => [...prev.slice(-49), notification])

    // Auto-hide banner after 6 seconds (notification stays in list)
    setTimeout(() => {
      setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, bannerVisible: false } : n))
    }, 6000)
  }, [])

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const markRead = useCallback((id: string) => {
    setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, read: true } : n))
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
  }, [])

  const clearAll = useCallback(() => {
    setNotifications([])
  }, [])

  return { notifications, addNotification, dismiss, markRead, markAllRead, clearAll }
}
