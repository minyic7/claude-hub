import { useMemo } from 'react'
import { CheckCircle, XCircle, AlertTriangle, Info } from 'lucide-react'

interface ReviewScores {
  correctness: number
  security: number
  quality: number
  completeness: number
}

interface ReviewIssue {
  severity: 'critical' | 'major' | 'minor'
  file: string
  line: number
  description: string
}

interface ReviewData {
  verdict: 'approve' | 'reject'
  scores: ReviewScores
  summary: string
  issues: ReviewIssue[]
  feedback: string
}

interface AgentReviewReportProps {
  reviewJson: string
}

function ScoreRing({ score, label, size = 48 }: { score: number; label: string; size?: number }) {
  const r = (size - 6) / 2
  const circumference = 2 * Math.PI * r
  const pct = score / 10
  const offset = circumference * (1 - pct)
  const color = score >= 8 ? 'var(--color-accent-green)' : score >= 5 ? 'var(--color-accent-yellow)' : 'var(--color-accent-red)'

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="rotate-[-90deg]">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-border)" strokeWidth={3} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={color} strokeWidth={3}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
        <text
          x={size / 2} y={size / 2}
          textAnchor="middle" dominantBaseline="central"
          className="rotate-[90deg] origin-center"
          fill="var(--color-text-primary)" fontSize={size * 0.3} fontWeight="bold"
        >
          {score}
        </text>
      </svg>
      <span className="text-[10px] text-[var(--color-text-muted)]">{label}</span>
    </div>
  )
}

function ScoreRadar({ scores, size = 120 }: { scores: ReviewScores; size?: number }) {
  const cx = size / 2
  const cy = size / 2
  const maxR = size * 0.38
  const labels = ['Correct', 'Security', 'Quality', 'Complete']
  const values = [scores.correctness, scores.security, scores.quality, scores.completeness]
  const n = values.length

  const getPoint = (i: number, r: number) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
  }

  // Grid rings
  const rings = [0.25, 0.5, 0.75, 1.0]

  // Data polygon (minimum 0.5/10 radius so zero scores are still visible)
  const dataPoints = values.map((v, i) => getPoint(i, maxR * (Math.max(v, 0.5) / 10)))
  const dataPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ') + ' Z'

  return (
    <svg width={size} height={size} className="mx-auto">
      {/* Grid */}
      {rings.map((pct) => {
        const pts = Array.from({ length: n }, (_, i) => getPoint(i, maxR * pct))
        const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ') + ' Z'
        return <path key={pct} d={path} fill="none" stroke="var(--color-border)" strokeWidth={0.5} />
      })}
      {/* Axes */}
      {Array.from({ length: n }, (_, i) => {
        const [x, y] = getPoint(i, maxR)
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--color-border)" strokeWidth={0.5} />
      })}
      {/* Data */}
      <path d={dataPath} fill="var(--color-accent-blue)" fillOpacity={0.15} stroke="var(--color-accent-blue)" strokeWidth={1.5} />
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={2.5} fill="var(--color-accent-blue)" />
      ))}
      {/* Labels */}
      {Array.from({ length: n }, (_, i) => {
        const [x, y] = getPoint(i, maxR + 14)
        return (
          <text key={i} x={x} y={y} textAnchor="middle" dominantBaseline="central"
            fill="var(--color-text-muted)" fontSize={9}>
            {labels[i]}
          </text>
        )
      })}
    </svg>
  )
}

const severityConfig = {
  critical: { icon: XCircle, className: 'text-[var(--color-accent-red)]', bg: 'bg-[var(--color-accent-red)]/10' },
  major: { icon: AlertTriangle, className: 'text-[var(--color-accent-yellow)]', bg: 'bg-[var(--color-accent-yellow)]/10' },
  minor: { icon: Info, className: 'text-[var(--color-text-muted)]', bg: 'bg-[var(--color-bg-secondary)]' },
}

export function AgentReviewReport({ reviewJson }: AgentReviewReportProps) {
  const review = useMemo<ReviewData | null>(() => {
    try {
      return JSON.parse(reviewJson)
    } catch {
      return null
    }
  }, [reviewJson])

  if (!review) return null

  const avg = Math.round(
    (review.scores.correctness + review.scores.security + review.scores.quality + review.scores.completeness) / 4 * 10
  ) / 10
  const approved = review.verdict === 'approve'

  return (
    <div className="space-y-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        {approved
          ? <CheckCircle size={16} className="text-[var(--color-accent-green)]" />
          : <XCircle size={16} className="text-[var(--color-accent-red)]" />
        }
        <span className={`text-sm font-semibold ${approved ? 'text-[var(--color-accent-green)]' : 'text-[var(--color-accent-red)]'}`}>
          {approved ? 'APPROVED' : 'REJECTED'}
        </span>
        <span className="ml-auto text-xs text-[var(--color-text-muted)]">Avg: {avg}/10</span>
      </div>

      {/* Summary */}
      <p className="text-xs text-[var(--color-text-secondary)]">{review.summary}</p>

      {/* Scores */}
      <div className="flex items-start gap-4">
        <div className="flex gap-2">
          <ScoreRing score={review.scores.correctness} label="Correct" />
          <ScoreRing score={review.scores.security} label="Security" />
          <ScoreRing score={review.scores.quality} label="Quality" />
          <ScoreRing score={review.scores.completeness} label="Complete" />
        </div>
        <ScoreRadar scores={review.scores} size={100} />
      </div>

      {/* Issues */}
      {review.issues.length > 0 && (
        <div className="space-y-1">
          <span className="text-xs font-medium text-[var(--color-text-muted)]">Issues ({review.issues.length})</span>
          {review.issues.map((issue, i) => {
            const config = severityConfig[issue.severity] || severityConfig.minor
            const Icon = config.icon
            return (
              <div key={i} className={`flex items-start gap-1.5 rounded px-2 py-1 text-xs ${config.bg}`}>
                <Icon size={12} className={`mt-0.5 shrink-0 ${config.className}`} />
                <div className="min-w-0">
                  <span className="font-mono text-[10px] text-[var(--color-text-muted)]">
                    {issue.file}{issue.line > 0 ? `:${issue.line}` : ''}
                  </span>
                  <p className="text-[var(--color-text-secondary)]">{issue.description}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Feedback (if rejected) */}
      {!approved && review.feedback && (
        <div className="rounded border border-[var(--color-accent-red)]/20 bg-[var(--color-accent-red)]/5 px-2 py-1.5">
          <span className="text-[10px] font-medium text-[var(--color-accent-red)]">Feedback sent to Claude Code:</span>
          <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">{review.feedback}</p>
        </div>
      )}
    </div>
  )
}
