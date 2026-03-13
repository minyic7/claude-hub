import { useCallback, useState } from 'react'

export interface Notification {
  id: string
  type: 'error' | 'warning' | 'info' | 'success'
  message: string
  timestamp: number
  bannerVisible: boolean
  read: boolean
}

let nextId = 0

export function useNotifications() {
  const [notifications, setNotifications] = useState<Notification[]>([])

  const addNotification = useCallback((type: Notification['type'], message: string) => {
    const id = `n-${++nextId}`
    const notification: Notification = { id, type, message, timestamp: Date.now(), bannerVisible: true, read: false }
    setNotifications((prev) => [...prev.slice(-49), notification])

    // Auto-hide banner after 6 seconds (notification stays in list)
    setTimeout(() => {
      setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, bannerVisible: false } : n))
    }, 6000)
  }, [])

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
  }, [])

  const clearAll = useCallback(() => {
    setNotifications([])
  }, [])

  return { notifications, addNotification, dismiss, markAllRead, clearAll }
}
