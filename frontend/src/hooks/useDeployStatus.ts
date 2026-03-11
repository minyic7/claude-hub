import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type WorkflowRun } from '../lib/api'

export type DeployState = 'idle' | 'deploying' | 'success' | 'failure'

interface UseDeployStatusReturn {
  runs: WorkflowRun[]
  state: DeployState
  deployingBranches: Set<string>
}

export function useDeployStatus(
  projectId: string | null,
  onDeployComplete?: (run: WorkflowRun) => void,
): UseDeployStatusReturn {
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [state, setState] = useState<DeployState>('idle')
  const [deployingBranches, setDeployingBranches] = useState<Set<string>>(new Set())
  const prevStateRef = useRef<DeployState>('idle')
  const prevRunsRef = useRef<WorkflowRun[]>([])

  const fetchRuns = useCallback(async () => {
    if (!projectId) return
    try {
      const { runs: newRuns } = await api.github.actions(projectId)
      setRuns(newRuns)

      const hasInProgress = newRuns.some((r) => r.status === 'in_progress' || r.status === 'queued')
      const deploying = new Set<string>()
      for (const r of newRuns) {
        if (r.status === 'in_progress' || r.status === 'queued') {
          deploying.add(r.head_branch)
        }
      }
      setDeployingBranches(deploying)

      const newState: DeployState = hasInProgress
        ? 'deploying'
        : newRuns.length > 0
          ? newRuns[0].conclusion === 'success'
            ? 'success'
            : newRuns[0].conclusion === 'failure'
              ? 'failure'
              : 'idle'
          : 'idle'

      // Detect transition from deploying -> completed
      if (prevStateRef.current === 'deploying' && newState !== 'deploying' && onDeployComplete) {
        // Find runs that were in_progress but are now complete
        for (const run of newRuns) {
          const prev = prevRunsRef.current.find((r) => r.id === run.id)
          if (prev && (prev.status === 'in_progress' || prev.status === 'queued') && run.status === 'completed') {
            onDeployComplete(run)
          }
        }
      }

      prevStateRef.current = newState
      prevRunsRef.current = newRuns
      setState(newState)
    } catch {
      // Silently fail - don't spam errors for missing tokens etc.
    }
  }, [projectId, onDeployComplete])

  useEffect(() => {
    if (!projectId) {
      setRuns([])
      setState('idle')
      setDeployingBranches(new Set())
      return
    }

    fetchRuns()
    const getInterval = () => (prevStateRef.current === 'deploying' ? 15_000 : 120_000)

    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      timer = setTimeout(async () => {
        await fetchRuns()
        schedule()
      }, getInterval())
    }
    schedule()

    return () => clearTimeout(timer)
  }, [projectId, fetchRuns])

  return { runs, state, deployingBranches }
}
