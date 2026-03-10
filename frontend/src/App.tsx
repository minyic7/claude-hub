import { useMemo, useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useTickets } from './hooks/useTickets'
import { AppShell } from './components/layout/AppShell'
import { KanbanBoard } from './components/layout/KanbanBoard'
import { TicketDetail } from './components/kanban/TicketDetail'
import type { Ticket } from './types/ticket'

function App() {
  const wsUrl = `ws://${window.location.host}/ws`
  const { projects, tickets, activities, connected } = useWebSocket(wsUrl)

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

  const columns = useTickets(filteredTickets)
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null)

  const currentTicket = selectedTicket ? tickets.get(selectedTicket.id) || selectedTicket : null

  return (
    <AppShell
      connected={connected}
      projects={projects}
      activeProjectId={activeProjectId}
      onProjectChange={handleProjectChange}
    >
      <KanbanBoard
        columns={columns}
        activities={activities}
        onTicketClick={setSelectedTicket}
      />
      {currentTicket && (
        <TicketDetail
          ticket={currentTicket}
          activities={activities.get(currentTicket.id) || []}
          onClose={() => setSelectedTicket(null)}
        />
      )}
    </AppShell>
  )
}

export default App
