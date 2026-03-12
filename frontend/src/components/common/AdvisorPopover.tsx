import { useCallback, useEffect, useState } from 'react'
import { MessageSquare, RefreshCw, Terminal } from 'lucide-react'
import { api } from '../../lib/api'
import type { AdvisorStatus } from '../../lib/api'
import { Button } from './Button'
interface AdvisorPopoverProps {
  projectId: string
  onClose: () => void
  onOpenTerminal: () => void
}

export function AdvisorPopover({ projectId, onClose, onOpenTerminal }: AdvisorPopoverProps) {
  const [status, setStatus] = useState<AdvisorStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [showRestartConfirm, setShowRestartConfirm] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.advisor.status(projectId)
      setStatus(s)
    } catch {
      setStatus(null)
    }
  }, [projectId])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const handleStart = async () => {
    setLoading(true)
    try {
      const s = await api.advisor.start(projectId)
      setStatus(s)
      // Auto-open terminal after starting
      onOpenTerminal()
      onClose()
    } catch {
      // error handled by global handler
    } finally {
      setLoading(false)
    }
  }

  const handleRestart = async () => {
    setRestarting(true)
    setShowRestartConfirm(false)
    try {
      const s = await api.advisor.restart(projectId)
      setStatus(s)
    } catch {
      // error handled by global handler
    } finally {
      setRestarting(false)
    }
  }

  const handleOpenTerminal = () => {
    onOpenTerminal()
    onClose()
  }

  const alive = status?.alive ?? false

  return (
    <>
      {/* Popover backdrop */}
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] shadow-lg">
        <div className="border-b border-[var(--color-border)] px-3 py-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare size={14} className="text-[var(--color-accent-blue)]" />
            <span className="text-xs font-semibold text-[var(--color-text-primary)]">Project Advisor</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                alive
                  ? 'bg-[var(--color-accent-green)]'
                  : 'bg-[var(--color-accent-red)]'
              }`}
            />
            <span className="text-[10px] text-[var(--color-text-muted)]">
              {alive ? 'Running' : 'Stopped'}
            </span>
          </div>
        </div>

        <div className="p-3 space-y-3">
          {status === null ? (
            <p className="text-xs text-[var(--color-text-muted)]">Loading status...</p>
          ) : !alive ? (
            <div className="space-y-2">
              <p className="text-xs text-[var(--color-text-secondary)]">
                The advisor helps you refine requirements and create structured tickets.
              </p>
              <Button size="sm" onClick={handleStart} disabled={loading} className="w-full">
                {loading ? 'Starting...' : 'Start Advisor Session'}
              </Button>
            </div>
          ) : (
            <>
              <Button size="sm" onClick={handleOpenTerminal} className="w-full flex items-center justify-center gap-1.5">
                <Terminal size={14} />
                Open Terminal
              </Button>

              <div className="border-t border-[var(--color-border)] pt-2">
                {showRestartConfirm ? (
                  <div className="space-y-2">
                    <p className="text-xs text-[var(--color-accent-red)]">
                      Kill current session and start fresh? Conversation history will be lost.
                    </p>
                    <div className="flex gap-2">
                      <Button size="sm" variant="secondary" onClick={() => setShowRestartConfirm(false)} className="flex-1">
                        Cancel
                      </Button>
                      <Button size="sm" variant="danger" onClick={handleRestart} disabled={restarting} className="flex-1">
                        {restarting ? 'Restarting...' : 'Confirm'}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowRestartConfirm(true)}
                    className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors"
                  >
                    <RefreshCw size={12} />
                    Restart Advisor
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>

    </>
  )
}
