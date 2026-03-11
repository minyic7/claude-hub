import { useState } from 'react'
import { CheckCircle, ExternalLink, Loader2, XCircle } from 'lucide-react'
import type { DeployState } from '../../hooks/useDeployStatus'
import type { WorkflowRun } from '../../lib/api'

interface DeployStatusWidgetProps {
  state: DeployState
  runs: WorkflowRun[]
}

export function DeployStatusWidget({ state, runs }: DeployStatusWidgetProps) {
  const [showDropdown, setShowDropdown] = useState(false)

  if (state === 'idle' && runs.length === 0) return null

  return (
    <div className="relative">
      <button
        onClick={() => setShowDropdown(!showDropdown)}
        className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs hover:bg-[var(--color-bg-secondary)] transition-colors"
      >
        {state === 'deploying' && (
          <>
            <Loader2 size={12} className="text-[var(--color-accent-blue)] animate-spin" />
            <span className="text-[var(--color-accent-blue)]">Deploying...</span>
          </>
        )}
        {state === 'success' && (
          <CheckCircle size={12} className="text-[var(--color-accent-green)]" />
        )}
        {state === 'failure' && (
          <XCircle size={12} className="text-[var(--color-accent-red)]" />
        )}
        {state === 'idle' && runs.length > 0 && (
          <CheckCircle size={12} className="text-[var(--color-text-muted)]" />
        )}
      </button>

      {showDropdown && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowDropdown(false)} />
          <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] shadow-lg">
            <div className="border-b border-[var(--color-border)] px-3 py-2">
              <span className="text-xs font-semibold text-[var(--color-text-primary)]">Workflow Runs</span>
            </div>
            <div className="max-h-64 overflow-y-auto">
              {runs.length === 0 ? (
                <p className="px-3 py-4 text-center text-xs text-[var(--color-text-muted)]">No recent runs</p>
              ) : (
                runs.map((run) => (
                  <a
                    key={run.id}
                    href={run.html_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-3 py-2 hover:bg-[var(--color-bg-secondary)] border-b border-[var(--color-border)]/50 last:border-b-0"
                    onClick={() => setShowDropdown(false)}
                  >
                    <RunStatusIcon status={run.status} conclusion={run.conclusion} />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-[var(--color-text-primary)] truncate">{run.name || 'Workflow'}</p>
                      <p className="text-[10px] text-[var(--color-text-muted)]">
                        {run.head_branch} &middot; {new Date(run.created_at).toLocaleString()}
                      </p>
                    </div>
                    <ExternalLink size={10} className="shrink-0 text-[var(--color-text-muted)]" />
                  </a>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function RunStatusIcon({ status, conclusion }: { status: string; conclusion: string | null }) {
  if (status === 'in_progress' || status === 'queued') {
    return <Loader2 size={12} className="shrink-0 text-[var(--color-accent-blue)] animate-spin" />
  }
  if (conclusion === 'success') {
    return <CheckCircle size={12} className="shrink-0 text-[var(--color-accent-green)]" />
  }
  if (conclusion === 'failure') {
    return <XCircle size={12} className="shrink-0 text-[var(--color-accent-red)]" />
  }
  return <CheckCircle size={12} className="shrink-0 text-[var(--color-text-muted)]" />
}
