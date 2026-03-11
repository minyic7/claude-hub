import { useCallback, useEffect, useMemo, useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useTickets } from './hooks/useTickets'
import { useNotifications } from './hooks/useNotifications'
import { useDeployStatus } from './hooks/useDeployStatus'
import { AppShell } from './components/layout/AppShell'
import { KanbanBoard } from './components/layout/KanbanBoard'
import { TicketDetail } from './components/kanban/TicketDetail'
import { NotificationToast } from './components/common/NotificationToast'
import { LoginPage } from './components/auth/LoginPage'
import { api, getToken, setApiErrorHandler } from './lib/api'
import type { Ticket } from './types/ticket'

function App() {
  const [authed, setAuthed] = useState<boolean | null>(null) // null = checking

  useEffect(() => {
    // Check if auth is required and if we have a valid token
    api.auth.check().then(({ auth_required }) => {
      if (!auth_required) {
        setAuthed(true)
        return
      }
      // Auth required — verify token via protected endpoint
      if (getToken()) {
        api.auth.verify().then(() => setAuthed(true)).catch(() => setAuthed(false))
      } else {
        setAuthed(false)
      }
    }).catch(() => {
      // Can't reach backend — show app anyway (will show disconnected state)
      setAuthed(true)
    })
  }, [])

  if (authed === null) return null // loading
  if (authed === false) return <LoginPage onLogin={() => setAuthed(true)} />
  return <AuthedApp />
}

function AuthedApp() {
  // Build WebSocket URL dynamically from current location + token
  const wsUrl = useMemo(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const token = getToken()
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${proto}//${window.location.host}/ws${qs}`
  }, [])

  const { projects, tickets, activities, connected, lastEscalation, patchTicket } = useWebSocket(wsUrl)
  const { notifications, addNotification, dismiss } = useNotifications()

  // Wire API errors → notification bell
  useEffect(() => {
    setApiErrorHandler((msg) => addNotification('error', msg))
  }, [addNotification])

  // Show notification on escalation events
  useEffect(() => {
    if (lastEscalation) {
      const ticket = tickets.get(lastEscalation.ticketId)
      const title = ticket?.title || lastEscalation.ticketId.slice(0, 8)
      addNotification('warning', `Blocked: ${title} — ${lastEscalation.question}`)
    }
  }, [lastEscalation])

  const [activeProjectId, setActiveProjectId] = useState<string | null>(
    () => localStorage.getItem('claude-hub-active-project'),
  )

  const handleProjectChange = (id: string | null) => {
    setActiveProjectId(id)
    if (id) {
      localStorage.setItem('claude-hub-active-project', id)
    } else {
      localStorage.removeItem('claude-hub-active-project')
    }
    setSelectedTicket(null)
  }

  // Filter tickets by active project
  const filteredTickets = useMemo(() => {
    if (!activeProjectId) return tickets
    return new Map([...tickets].filter(([, t]) => t.project_id === activeProjectId))
  }, [tickets, activeProjectId])

  const onDeployComplete = useCallback((run: { conclusion: string | null; name: string }) => {
    const label = run.conclusion === 'success' ? 'Deploy complete' : 'Deploy failed'
    addNotification(run.conclusion === 'success' ? 'success' : 'error', `${label}: ${run.name}`)
  }, [addNotification])

  const { runs: deployRuns, state: deployState, deployingBranches } = useDeployStatus(activeProjectId, onDeployComplete)

  const columns = useTickets(filteredTickets)
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null)

  const currentTicket = selectedTicket ? filteredTickets.get(selectedTicket.id) || selectedTicket : null

  return (
    <>
    <AppShell
      connected={connected}
      projects={projects}
      tickets={tickets}
      activeProjectId={activeProjectId}
      onProjectChange={handleProjectChange}
      notifications={notifications}
      onDismissNotification={dismiss}
      deployState={deployState}
      deployRuns={deployRuns}
    >
      <KanbanBoard
        columns={columns}
        activities={activities}
        allTickets={filteredTickets}
        activeProjectId={activeProjectId}
        onTicketClick={setSelectedTicket}
        onOptimistic={patchTicket}
        deployingBranches={deployingBranches}
      />
      {currentTicket && (
        <TicketDetail
          ticket={currentTicket}
          activities={activities.get(currentTicket.id) || []}
          allTickets={filteredTickets}
          onClose={() => setSelectedTicket(null)}
          onDelete={() => setSelectedTicket(null)}
          onTicketClick={setSelectedTicket}
        />
      )}
    </AppShell>
    <NotificationToast notifications={notifications} onDismiss={dismiss} />
  </>
  )
}

export default App
