import { useCallback, useEffect, useRef, useState } from 'react'
import type { Project, Ticket, TicketStatus } from '../types/ticket'
import type { ActivityEvent } from '../types/activity'
import type { WSEvent } from '../types/ws'
import type { Notification } from './useNotifications'
import { api } from '../lib/api'

export interface TicketNotification {
  ticketId: string
  ticketTitle: string
  notificationType: Notification['type']
  message: string
  _seq: number
}

let notifSeq = 0

const statusLabels: Partial<Record<TicketStatus, string>> = {
  in_progress: 'started',
  review: 'ready for review',
  merging: 'merging',
  merged: 'merged',
  failed: 'failed',
  blocked: 'blocked',
  verifying: 'verifying',
}

const statusNotifType: Partial<Record<TicketStatus, Notification['type']>> = {
  merged: 'success',
  failed: 'error',
  blocked: 'warning',
}

interface UseWebSocketReturn {
  projects: Map<string, Project>
  tickets: Map<string, Ticket>
  activities: Map<string, ActivityEvent[]>
  connected: boolean
  lastEscalation: { ticketId: string; question: string } | null
  lastTicketNotification: TicketNotification | null
  patchTicket: (ticketId: string, patch: Partial<Ticket>) => void
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [projects, setProjects] = useState<Map<string, Project>>(new Map())
  const [tickets, setTickets] = useState<Map<string, Ticket>>(new Map())
  const [activities, setActivities] = useState<Map<string, ActivityEvent[]>>(new Map())
  const [connected, setConnected] = useState(false)
  const [lastEscalation, setLastEscalation] = useState<{ ticketId: string; question: string } | null>(null)
  const [lastTicketNotification, setLastTicketNotification] = useState<TicketNotification | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const prevTicketsRef = useRef<Map<string, Ticket>>(new Map())
  const initDone = useRef(false)

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

  const emitNotification = useCallback((
    ticketId: string,
    ticketTitle: string,
    notificationType: Notification['type'],
    message: string,
  ) => {
    setLastTicketNotification({ ticketId, ticketTitle, notificationType, message, _seq: ++notifSeq })
  }, [])

  const handleMessage = useCallback((msg: WSEvent) => {
    switch (msg.type) {
      case 'init':
        setProjects(new Map((msg.data.projects || []).map((p) => [p.id, p])))
        setTickets(new Map(msg.data.tickets.map((t) => [t.id, t])))
        // Snapshot for diff detection (no notifications on init)
        prevTicketsRef.current = new Map(msg.data.tickets.map((t) => [t.id, t]))
        initDone.current = true
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

      case 'ticket_updated': {
        const newTicket = msg.data
        const oldTicket = prevTicketsRef.current.get(msg.ticket_id)
        const title = newTicket.title || msg.ticket_id.slice(0, 8)

        setTickets((prev) => {
          const next = new Map(prev)
          next.set(msg.ticket_id, newTicket)
          return next
        })
        prevTicketsRef.current.set(msg.ticket_id, newTicket)

        if (!initDone.current) break

        // Status change notification
        if (oldTicket && oldTicket.status !== newTicket.status) {
          const label = statusLabels[newTicket.status]
          if (label) {
            const type = statusNotifType[newTicket.status] || 'info'
            let detail = `${title} — ${label}`
            if (newTicket.status === 'failed' && newTicket.failed_reason) {
              detail += `: ${newTicket.failed_reason}`
            }
            emitNotification(msg.ticket_id, title, type, detail)
          }
        }

        // PR created notification
        if (oldTicket && !oldTicket.pr_url && newTicket.pr_url) {
          emitNotification(msg.ticket_id, title, 'info', `${title} — PR created: ${newTicket.pr_url}`)
        }
        break
      }

      case 'ticket_deleted':
        setTickets((prev) => {
          const next = new Map(prev)
          next.delete(msg.ticket_id)
          return next
        })
        prevTicketsRef.current.delete(msg.ticket_id)
        setActivities((prev) => {
          const next = new Map(prev)
          next.delete(msg.ticket_id)
          return next
        })
        break

      case 'activity': {
        setActivities((prev) => {
          const next = new Map(prev)
          const existing = next.get(msg.ticket_id) || []
          next.set(msg.ticket_id, [...existing.slice(-499), msg.data])
          return next
        })

        if (!initDone.current) break

        const ev = msg.data
        const ticket = prevTicketsRef.current.get(msg.ticket_id)
        const evTitle = ticket?.title || msg.ticket_id.slice(0, 8)

        // Review result notifications (from TicketAgent)
        if (ev.source === 'ticket_agent' && ev.type === 'decision') {
          if (/review.*(pass|approv|lgtm)/i.test(ev.summary)) {
            emitNotification(msg.ticket_id, evTitle, 'success', `${evTitle} — review passed`)
          } else if (/review.*(fail|reject|change|fix)/i.test(ev.summary)) {
            emitNotification(msg.ticket_id, evTitle, 'warning', `${evTitle} — changes requested`)
          }
        }

        // Session completed notifications (from TicketAgent info events)
        if (ev.source === 'ticket_agent' && ev.type === 'info' && /session.*(?:complet|finish|end|exit)/i.test(ev.summary)) {
          emitNotification(msg.ticket_id, evTitle, 'info', `${evTitle} — session completed`)
        }
        break
      }

      case 'escalation':
        setLastEscalation({ ticketId: msg.ticket_id, question: msg.data.question })
        break
      case 'cost_update':
        break
    }
  }, [emitNotification])

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

  return { projects, tickets, activities, connected, lastEscalation, lastTicketNotification, patchTicket }
}
