import { useCallback, useEffect, useRef, useState } from 'react'
import type { Project, Ticket } from '../types/ticket'
import type { ActivityEvent } from '../types/activity'
import type { WSEvent } from '../types/ws'
import { api } from '../lib/api'

interface UseWebSocketReturn {
  projects: Map<string, Project>
  tickets: Map<string, Ticket>
  activities: Map<string, ActivityEvent[]>
  connected: boolean
  lastEscalation: { ticketId: string; question: string } | null
  patchTicket: (ticketId: string, patch: Partial<Ticket>) => void
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [projects, setProjects] = useState<Map<string, Project>>(new Map())
  const [tickets, setTickets] = useState<Map<string, Ticket>>(new Map())
  const [activities, setActivities] = useState<Map<string, ActivityEvent[]>>(new Map())
  const [connected, setConnected] = useState(false)
  const [lastEscalation, setLastEscalation] = useState<{ ticketId: string; question: string } | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      // Sync review ticket PR statuses with GitHub on (re)connect
      api.tickets.syncReviewStatus().catch(() => {})
    }

    ws.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 2000)
    }

    ws.onerror = () => {
      ws.close()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSEvent
        handleMessage(msg)
      } catch {
        // ignore parse errors
      }
    }
  }, [url])

  const handleMessage = useCallback((msg: WSEvent) => {
    switch (msg.type) {
      case 'init':
        setProjects(new Map((msg.data.projects || []).map((p) => [p.id, p])))
        setTickets(new Map(msg.data.tickets.map((t) => [t.id, t])))
        // Restore activities for active tickets on (re)connect
        if (msg.data.activities) {
          setActivities(new Map(
            Object.entries(msg.data.activities).filter(([, events]) => events.length > 0)
          ))
        }
        break

      case 'project_created':
      case 'project_updated':
        setProjects((prev) => {
          const next = new Map(prev)
          next.set(msg.data.id, msg.data)
          return next
        })
        break

      case 'project_deleted':
        setProjects((prev) => {
          const next = new Map(prev)
          next.delete(msg.project_id)
          return next
        })
        break

      case 'ticket_updated':
        setTickets((prev) => {
          const next = new Map(prev)
          next.set(msg.ticket_id, msg.data)
          return next
        })
        break

      case 'ticket_deleted':
        setTickets((prev) => {
          const next = new Map(prev)
          next.delete(msg.ticket_id)
          return next
        })
        setActivities((prev) => {
          const next = new Map(prev)
          next.delete(msg.ticket_id)
          return next
        })
        break

      case 'activity':
        setActivities((prev) => {
          const next = new Map(prev)
          const existing = next.get(msg.ticket_id) || []
          next.set(msg.ticket_id, [...existing.slice(-499), msg.data])
          return next
        })
        break

      case 'escalation':
        setLastEscalation({ ticketId: msg.ticket_id, question: msg.data.question })
        break
      case 'cost_update':
        break
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const patchTicket = useCallback((ticketId: string, patch: Partial<Ticket>) => {
    setTickets((prev) => {
      const existing = prev.get(ticketId)
      if (!existing) return prev
      const next = new Map(prev)
      next.set(ticketId, { ...existing, ...patch })
      return next
    })
  }, [])

  return { projects, tickets, activities, connected, lastEscalation, patchTicket }
}
