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

      // Track which branches have in-progress runs (for per-branch indicators)
      const deploying = new Set<string>()
      for (const r of newRuns) {
        if (r.status === 'in_progress' || r.status === 'queued') {
          deploying.add(r.head_branch)
        }
      }
      setDeployingBranches(deploying)

      // Deploy state: only consider CD workflows on main/master (push events).
      // CI runs on feature branches should NOT block merges — CI is per-branch,
      // only the merge endpoint checks per-PR CI status.
      const CD_KEYWORDS = ['deploy', 'cd', 'release', 'publish', 'production']
      const mainBranches = new Set(['main', 'master'])
      const cdRuns = newRuns.filter(
        (r) =>
          mainBranches.has(r.head_branch) &&
          CD_KEYWORDS.some((kw) => r.name.toLowerCase().includes(kw)),
      )

      const hasCdInProgress = cdRuns.some(
        (r) => r.status === 'in_progress' || r.status === 'queued',
      )

      const newState: DeployState = hasCdInProgress
        ? 'deploying'
        : cdRuns.length > 0
          ? cdRuns[0].conclusion === 'success'
            ? 'success'
            : cdRuns[0].conclusion === 'failure'
              ? 'failure'
              : 'idle'
          : 'idle'

      // Detect transition from deploying -> completed
      if (prevStateRef.current === 'deploying' && newState !== 'deploying' && onDeployComplete) {
        // Find CD runs that were in_progress but are now complete
        for (const run of cdRuns) {
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
