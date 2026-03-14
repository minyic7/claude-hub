import { useEffect, useRef, useState } from 'react'
import { Crown, FileText, Play, Zap } from 'lucide-react'
import { api, type POSettings, type POStatus } from '../../lib/api'
import type { Ticket } from '../../types/ticket'

interface POBarProps {
  projectId: string
  tickets: Map<string, Ticket>
}

export function POBar({ projectId, tickets }: POBarProps) {
  const [status, setStatus] = useState<POStatus | null>(null)
  const [settings, setSettings] = useState<POSettings | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [togglingMode, setTogglingMode] = useState(false)
  const [showReport, setShowReport] = useState(false)
  const [report, setReport] = useState<{ report: string; generated_at: string | null } | null>(null)
  const [loadingReport, setLoadingReport] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined)

  useEffect(() => {
    api.po.status(projectId).then(setStatus).catch(() => {})
    api.po.getSettings(projectId).then(setSettings).catch(() => {})
    pollRef.current = setInterval(() => {
      api.po.status(projectId).then(setStatus).catch(() => {})
    }, 10000)
    return () => clearInterval(pollRef.current)
  }, [projectId])

  // Don't render if PO is not running
  if (!status?.running) return null

  const pendingCount = [...tickets.values()].filter(
    (t) => t.project_id === projectId && t.status === 'po_pending'
  ).length

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

  const handleToggleMode = async () => {
    if (!settings) return
    setTogglingMode(true)
    try {
      const newMode = settings.mode === 'semi_auto' ? 'full_auto' : 'semi_auto'
      const updated = await api.po.updateSettings(projectId, { ...settings, mode: newMode })
      setSettings(updated)
    } catch {
      // handled by global
    } finally {
      setTogglingMode(false)
    }
  }

  const handleShowReport = async () => {
    if (showReport) {
      setShowReport(false)
      return
    }
    setLoadingReport(true)
    setShowReport(true)
    try {
      const r = await api.po.report(projectId)
      setReport(r)
    } catch {
      setReport({ report: 'No report available yet.', generated_at: null })
    } finally {
      setLoadingReport(false)
    }
  }

  return (
    <>
      <div className="flex items-center gap-3 border-b border-purple-500/20 bg-purple-500/5 px-5 py-1.5 shrink-0">
        <div className="flex items-center gap-1.5">
          <Crown size={12} className="text-purple-400" />
          <span className="text-[11px] font-medium text-purple-400">PO Agent</span>
        </div>
        <span className="text-[11px] text-[var(--color-text-muted)]">
          {status.status} · cycle {status.cycle_n}
        </span>

        {/* Mode toggle */}
        {settings && (
          <button
            onClick={handleToggleMode}
            disabled={togglingMode}
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-purple-400 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
            title={`Switch to ${settings.mode === 'semi_auto' ? 'Full Auto' : 'Semi Auto'}`}
          >
            <Zap size={10} />
            {settings.mode === 'semi_auto' ? 'Semi' : 'Full'}
          </button>
        )}

        {/* Pending count (semi-auto only) */}
        {settings?.mode === 'semi_auto' && pendingCount > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-purple-500/15 px-2 py-0.5 text-[10px] font-medium text-purple-400">
            {pendingCount} pending
          </span>
        )}

        {/* Run Now */}
        <button
          onClick={handleTrigger}
          disabled={triggering}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-purple-400 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
        >
          <Play size={10} />
          {triggering ? 'Running...' : 'Run Now'}
        </button>

        {/* Report */}
        <button
          onClick={handleShowReport}
          className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors ${
            showReport ? 'text-purple-400 bg-purple-500/10' : 'text-[var(--color-text-muted)] hover:text-purple-400 hover:bg-purple-500/10'
          }`}
        >
          <FileText size={10} />
          Report
        </button>
      </div>

      {/* Report panel */}
      {showReport && (
        <div className="border-b border-purple-500/20 bg-purple-500/5 px-5 py-3 shrink-0">
          {loadingReport ? (
            <p className="text-xs text-[var(--color-text-muted)]">Loading report...</p>
          ) : report ? (
            <div>
              {report.generated_at && (
                <p className="mb-1 text-[10px] text-[var(--color-text-muted)]">
                  Generated {new Date(report.generated_at).toLocaleString()}
                </p>
              )}
              <pre className="whitespace-pre-wrap text-xs text-[var(--color-text-primary)] leading-relaxed max-h-48 overflow-y-auto">
                {report.report}
              </pre>
            </div>
          ) : (
            <p className="text-xs text-[var(--color-text-muted)]">No report available.</p>
          )}
        </div>
      )}
    </>
  )
}
