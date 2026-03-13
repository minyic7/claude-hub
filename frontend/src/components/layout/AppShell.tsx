import { useState, useEffect, useMemo } from 'react'
import { Bell, ChevronDown, FolderPlus, LogOut, Plus, Settings, TerminalSquare, Wifi, WifiOff } from 'lucide-react'
import { DeployStatusWidget } from '../common/DeployStatusWidget'
import { ThemeToggle } from '../common/ThemeToggle'
import { Button } from '../common/Button'
import { CreateTicketModal } from '../tickets/CreateTicketModal'
import { CreateProjectModal } from '../projects/CreateProjectModal'
import { AgentSettingsModal } from '../settings/AgentSettingsModal'
import { AdvisorTerminal } from '../common/AdvisorTerminal'
import { clearToken, getToken } from '../../lib/api'
import type { DeployState } from '../../hooks/useDeployStatus'
import type { WorkflowRun } from '../../lib/api'
import type { Notification } from '../../hooks/useNotifications'
import type { ReactNode } from 'react'
import type { Project, Ticket } from '../../types/ticket'

interface AppShellProps {
  connected: boolean
  projects: Map<string, Project>
  tickets: Map<string, Ticket>
  activeProjectId: string | null
  onProjectChange: (id: string | null) => void
  notifications: Notification[]
  onDismissNotification: (id: string) => void
  deployState: DeployState
  deployRuns: WorkflowRun[]
  children: ReactNode
}

export function AppShell({
  connected, projects, tickets, activeProjectId, onProjectChange,
  notifications, onDismissNotification, deployState, deployRuns, children,
}: AppShellProps) {
  const [showCreateTicket, setShowCreateTicket] = useState(false)
  const [showCreateProject, setShowCreateProject] = useState(false)
  const [showProjectMenu, setShowProjectMenu] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showAdvisorTerminal, setShowAdvisorTerminal] = useState(false)

  const activeProject = activeProjectId ? projects.get(activeProjectId) : null

  // Compute ticket stats
  const stats = useMemo(() => {
    let running = 0
    let blocked = 0
    let total = 0
    let archived = 0
    for (const [, t] of tickets) {
      if (activeProjectId && t.project_id !== activeProjectId) continue
      if (t.archived) {
        archived++
      } else {
        total++
        if (t.status === 'in_progress' || t.status === 'verifying') running++
        if (t.status === 'blocked') blocked++
      }
    }
    return { running, blocked, total, archived }
  }, [tickets, activeProjectId])

  const unreadCount = notifications.filter((n) => n.type === 'error' || n.type === 'warning').length

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

          <span className="flex items-center gap-1 text-xs">
            {connected ? (
              <Wifi size={12} className="text-[var(--color-accent-green)]" />
            ) : (
              <>
                <WifiOff size={12} className="text-[var(--color-accent-red)] animate-pulse" />
                <span className="text-[var(--color-accent-red)] animate-pulse">Reconnecting...</span>
              </>
            )}
          </span>

          <DeployStatusWidget state={deployState} runs={deployRuns} />

          {/* Stats */}
          <div className="flex items-center gap-2 text-xs font-mono text-[var(--color-text-muted)]">
            <span>{stats.total} tickets{stats.archived > 0 && <> · {stats.archived} archived</>}</span>
            {stats.running > 0 && (
              <span className="flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-accent-blue)] animate-pulse" />
                {stats.running} running
              </span>
            )}
            {stats.blocked > 0 && (
              <span className="flex items-center gap-1 text-[var(--color-accent-red)]">
                <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-accent-red)]" />
                {stats.blocked} blocked
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Notification bell */}
          <div className="relative">
            <button
              onClick={() => setShowNotifications(!showNotifications)}
              className="relative rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
            >
              <Bell size={16} />
              {unreadCount > 0 && (
                <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--color-accent-red)] px-1 text-[10px] font-bold text-white">
                  {unreadCount}
                </span>
              )}
            </button>

            {showNotifications && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowNotifications(false)} />
                <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] shadow-lg">
                  <div className="border-b border-[var(--color-border)] px-3 py-2">
                    <span className="text-xs font-semibold text-[var(--color-text-primary)]">Notifications</span>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <p className="px-3 py-4 text-center text-xs text-[var(--color-text-muted)]">No notifications</p>
                    ) : (
                      notifications.slice().reverse().map((n) => (
                        <button
                          key={n.id}
                          onClick={() => {
                            onDismissNotification(n.id)
                            setShowNotifications(false)
                          }}
                          className="flex w-full items-start gap-2 border-b border-[var(--color-border)]/50 px-3 py-2 text-left hover:bg-[var(--color-bg-secondary)]"
                        >
                          <span className={`mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full ${
                            n.type === 'error' ? 'bg-[var(--color-accent-red)]' :
                            n.type === 'warning' ? 'bg-[var(--color-accent-yellow)]' :
                            n.type === 'success' ? 'bg-[var(--color-accent-green)]' :
                            'bg-[var(--color-accent-blue)]'
                          }`} />
                          <div className="min-w-0 flex-1">
                            <p className="text-xs text-[var(--color-text-primary)] line-clamp-2">{n.message}</p>
                            <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
                              {new Date(n.timestamp).toLocaleTimeString()}
                            </p>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Kanban Claude Code */}
          {activeProjectId && (
            <button
              onClick={() => setShowAdvisorTerminal(true)}
              className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
              title="Kanban Claude Code"
            >
              <TerminalSquare size={16} />
            </button>
          )}

          <Button size="sm" onClick={() => setShowCreateTicket(true)} disabled={!activeProjectId}>
            <Plus size={14} className="mr-1" /> New Ticket
          </Button>
          <button
            onClick={() => setShowSettings(true)}
            className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
            title="Agent Settings"
          >
            <Settings size={16} />
          </button>
          <ThemeToggle />
          {getToken() && (
            <button
              onClick={() => { clearToken(); window.location.reload() }}
              className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
              title="Logout"
            >
              <LogOut size={16} />
            </button>
          )}
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
          tickets={tickets}
        />
      )}
      <CreateProjectModal open={showCreateProject} onClose={() => setShowCreateProject(false)} />
      <AgentSettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
      {showAdvisorTerminal && activeProjectId && (
        <AdvisorTerminal
          projectId={activeProjectId}
          onClose={() => setShowAdvisorTerminal(false)}
        />
      )}
    </div>
  )
}
