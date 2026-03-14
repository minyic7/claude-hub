import { useEffect, useRef, useState } from 'react'
import { Crown, Play } from 'lucide-react'
import { api, type POStatus } from '../../lib/api'

interface POBarProps {
  projectId: string
}

export function POBar({ projectId }: POBarProps) {
  const [status, setStatus] = useState<POStatus | null>(null)
  const [triggering, setTriggering] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined)

  useEffect(() => {
    api.po.status(projectId).then(setStatus).catch(() => {})
    pollRef.current = setInterval(() => {
      api.po.status(projectId).then(setStatus).catch(() => {})
    }, 10000)
    return () => clearInterval(pollRef.current)
  }, [projectId])

  // Don't render if PO is not running
  if (!status?.running) return null

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      await api.po.run(projectId)
    } catch {
      // handled by global
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className="flex items-center gap-3 border-b border-purple-500/20 bg-purple-500/5 px-5 py-1.5 shrink-0">
      <div className="flex items-center gap-1.5">
        <Crown size={12} className="text-purple-400" />
        <span className="text-[11px] font-medium text-purple-400">PO Agent</span>
      </div>
      <span className="text-[11px] text-[var(--color-text-muted)]">
        {status.status} · cycle {status.cycle_n}
      </span>
      <button
        onClick={handleTrigger}
        disabled={triggering}
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-purple-400 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
      >
        <Play size={10} />
        {triggering ? 'Running...' : 'Run Now'}
      </button>
    </div>
  )
}
