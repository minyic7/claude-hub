import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useTickets } from './hooks/useTickets'
import { useNotifications } from './hooks/useNotifications'
import { useDeployStatus } from './hooks/useDeployStatus'
import { useVersionPolling } from './hooks/useVersionPolling'
import { AppShell } from './components/layout/AppShell'
import { KanbanBoard } from './components/layout/KanbanBoard'
import { TicketDetail } from './components/kanban/TicketDetail'
import { NotificationToast } from './components/common/NotificationToast'
import { LoginPage } from './components/auth/LoginPage'
import { api, getToken, setApiErrorHandler } from './lib/api'
import type { BranchType, Ticket } from './types/ticket'

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

  // Branch type filter
  const [branchTypeFilter, setBranchTypeFilter] = useState<BranchType | null>(null)

  // Filter tickets by active project and branch type
  const filteredTickets = useMemo(() => {
    let filtered = tickets
    if (activeProjectId) {
      filtered = new Map([...filtered].filter(([, t]) => t.project_id === activeProjectId))
    }
    if (branchTypeFilter) {
      filtered = new Map([...filtered].filter(([, t]) => t.branch_type === branchTypeFilter))
    }
    return filtered
  }, [tickets, activeProjectId, branchTypeFilter])

  // Version polling: detect when a new deploy lands
  const { startFastPolling, newVersionAvailable } = useVersionPolling(
    useCallback(() => {
      addNotification('info', 'New version deployed — click the banner to refresh')
    }, [addNotification]),
  )

  // Merge queue: lock merge buttons while a deploy is in progress
  const [mergeQueueLocked, setMergeQueueLocked] = useState(false)
  const lockTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const onMergeInitiated = useCallback(() => {
    setMergeQueueLocked(true)
    startFastPolling()
    // Safety timeout: unlock after 5 min in case deploy detection fails
    if (lockTimerRef.current) clearTimeout(lockTimerRef.current)
    lockTimerRef.current = setTimeout(() => setMergeQueueLocked(false), 5 * 60_000)
  }, [startFastPolling])

  const onDeployComplete = useCallback((run: { conclusion: string | null; name: string }) => {
    setMergeQueueLocked(false)
    if (lockTimerRef.current) clearTimeout(lockTimerRef.current)
    if (run.conclusion === 'success') {
      addNotification('success', `Deploy complete - safe to merge next ticket`)
    } else {
      addNotification('error', `Deploy failed - check GitHub Actions`)
    }
  }, [addNotification])

  const { runs: deployRuns, state: deployState, deployingBranches } = useDeployStatus(activeProjectId, onDeployComplete)

  // Sync lock with actual deploy state: lock when deploying, unlock when not
  useEffect(() => {
    if (deployState === 'deploying') {
      setMergeQueueLocked(true)
    } else {
      setMergeQueueLocked(false)
      if (lockTimerRef.current) clearTimeout(lockTimerRef.current)
    }
  }, [deployState])

  const columns = useTickets(filteredTickets)
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null)

  const currentTicket = selectedTicket ? filteredTickets.get(selectedTicket.id) || selectedTicket : null

  return (
    <>
    {newVersionAvailable && (
      <div
        onClick={() => window.location.reload()}
        className="fixed top-0 left-0 right-0 z-50 cursor-pointer bg-blue-600 text-white text-center py-2 text-sm font-medium shadow-md hover:bg-blue-700 transition-colors"
      >
        New version deployed — click to refresh
      </div>
    )}
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
        mergeQueueLocked={mergeQueueLocked}
        onMergeInitiated={onMergeInitiated}
        branchTypeFilter={branchTypeFilter}
        onBranchTypeFilter={setBranchTypeFilter}
      />
      {currentTicket && (
        <TicketDetail
          ticket={currentTicket}
          activities={activities.get(currentTicket.id) || []}
          allTickets={filteredTickets}
          onClose={() => setSelectedTicket(null)}
          onDelete={() => setSelectedTicket(null)}
          onTicketClick={setSelectedTicket}
          mergeQueueLocked={mergeQueueLocked}
          onMergeInitiated={onMergeInitiated}
        />
      )}
    </AppShell>
    <NotificationToast notifications={notifications} onDismiss={dismiss} />
  </>
  )
}

export default App
