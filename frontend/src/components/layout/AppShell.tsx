import { useState, useEffect } from 'react'
import { ChevronDown, FolderPlus, Plus, Wifi, WifiOff } from 'lucide-react'
import { ThemeToggle } from '../common/ThemeToggle'
import { Button } from '../common/Button'
import { CreateTicketModal } from '../tickets/CreateTicketModal'
import { CreateProjectModal } from '../projects/CreateProjectModal'
import { api } from '../../lib/api'
import type { ReactNode } from 'react'
import type { Project } from '../../types/ticket'

interface AppShellProps {
  connected: boolean
  projects: Map<string, Project>
  activeProjectId: string | null
  onProjectChange: (id: string | null) => void
  children: ReactNode
}

export function AppShell({ connected, projects, activeProjectId, onProjectChange, children }: AppShellProps) {
  const [showCreateTicket, setShowCreateTicket] = useState(false)
  const [showCreateProject, setShowCreateProject] = useState(false)
  const [showProjectMenu, setShowProjectMenu] = useState(false)
  const [dailyCost, setDailyCost] = useState(0)

  const activeProject = activeProjectId ? projects.get(activeProjectId) : null

  useEffect(() => {
    const fetchCost = async () => {
      try {
        const data = await api.cost()
        setDailyCost(data.daily)
      } catch {
        // ignore
      }
    }
    fetchCost()
    const interval = setInterval(fetchCost, 30000)
    return () => clearInterval(interval)
  }, [])

  // Auto-select first project if none selected and projects exist
  useEffect(() => {
    if (!activeProjectId && projects.size > 0) {
      const first = [...projects.values()][0]
      onProjectChange(first.id)
    }
  }, [activeProjectId, projects, onProjectChange])

  return (
    <div className="flex h-screen flex-col bg-[var(--color-bg-secondary)]">
      {/* Top bar */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-bg-panel)] px-4">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-bold text-[var(--color-text-primary)]">Claude Hub</h1>

          {/* Project selector */}
          <div className="relative">
            <button
              onClick={() => setShowProjectMenu(!showProjectMenu)}
              className="flex items-center gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 py-1 text-xs text-[var(--color-text-primary)] hover:border-[var(--color-accent-blue)]/40 transition-colors"
            >
              {activeProject ? (
                <>
                  <span className="max-w-[160px] truncate font-medium">{activeProject.name}</span>
                  <span className="max-w-[120px] truncate text-[var(--color-text-muted)]">
                    {activeProject.repo_url.replace('https://github.com/', '')}
                  </span>
                </>
              ) : (
                <span className="text-[var(--color-text-muted)]">Select project...</span>
              )}
              <ChevronDown size={12} className="text-[var(--color-text-muted)]" />
            </button>

            {showProjectMenu && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowProjectMenu(false)} />
                <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] py-1 shadow-lg">
                  {[...projects.values()].map((p) => (
                    <button
                      key={p.id}
                      onClick={() => { onProjectChange(p.id); setShowProjectMenu(false) }}
                      className={`flex w-full flex-col px-3 py-2 text-left hover:bg-[var(--color-bg-secondary)] ${p.id === activeProjectId ? 'bg-[var(--color-accent-blue)]/5' : ''}`}
                    >
                      <span className="text-xs font-medium text-[var(--color-text-primary)]">{p.name}</span>
                      <span className="text-xs text-[var(--color-text-muted)] truncate">
                        {p.repo_url.replace('https://github.com/', '')}
                      </span>
                    </button>
                  ))}
                  {projects.size > 0 && <div className="my-1 border-t border-[var(--color-border)]" />}
                  <button
                    onClick={() => { setShowCreateProject(true); setShowProjectMenu(false) }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-[var(--color-accent-blue)] hover:bg-[var(--color-bg-secondary)]"
                  >
                    <FolderPlus size={12} /> New Project
                  </button>
                </div>
              </>
            )}
          </div>

          <span className="flex items-center gap-1 text-xs text-[var(--color-text-muted)]">
            {connected ? (
              <Wifi size={12} className="text-[var(--color-accent-green)]" />
            ) : (
              <WifiOff size={12} className="text-[var(--color-accent-red)]" />
            )}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {dailyCost > 0 && (
            <span className="text-xs text-[var(--color-text-muted)]">
              Today: ${dailyCost.toFixed(2)}
            </span>
          )}
          <Button size="sm" onClick={() => setShowCreateTicket(true)} disabled={!activeProjectId}>
            <Plus size={14} className="mr-1" /> New Ticket
          </Button>
          <ThemeToggle />
        </div>
      </header>

      {/* Main content */}
      <main className="flex flex-1 overflow-hidden">
        {projects.size === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4">
            <p className="text-sm text-[var(--color-text-muted)]">No projects yet. Create one to get started.</p>
            <Button onClick={() => setShowCreateProject(true)}>
              <FolderPlus size={14} className="mr-1" /> New Project
            </Button>
          </div>
        ) : !activeProjectId ? (
          <div className="flex flex-1 items-center justify-center">
            <p className="text-sm text-[var(--color-text-muted)]">Select a project from the dropdown above.</p>
          </div>
        ) : (
          children
        )}
      </main>

      {activeProjectId && (
        <CreateTicketModal
          open={showCreateTicket}
          onClose={() => setShowCreateTicket(false)}
          projectId={activeProjectId}
        />
      )}
      <CreateProjectModal open={showCreateProject} onClose={() => setShowCreateProject(false)} />
    </div>
  )
}
