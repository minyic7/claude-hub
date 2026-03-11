import { Check, Circle, GitMerge, Code, ListTodo } from 'lucide-react'
import type { Ticket } from '../../types/ticket'
import type { ActivityEvent } from '../../types/activity'
import { relativeTime } from '../../utils/relativeTime'

interface StatusTimelineProps {
  ticket: Ticket
  activities: ActivityEvent[]
}

const STAGES = [
  { key: 'todo', label: 'Todo', icon: ListTodo },
  { key: 'in_progress', label: 'In Progress', icon: Code },
  { key: 'review', label: 'Review', icon: Circle },
  { key: 'merged', label: 'Merged', icon: GitMerge },
] as const

type StageKey = (typeof STAGES)[number]['key']

const STATUS_TO_STAGE: Record<string, number> = {
  todo: 0,
  in_progress: 1,
  blocked: 1,
  verifying: 1,
  failed: 1,
  review: 2,
  merging: 2,
  merged: 3,
}

function findReviewTimestamp(activities: ActivityEvent[]): string | null {
  for (const event of activities) {
    if (
      event.type === 'info' &&
      /moved to review|status.*review|pr created|pull request/i.test(event.summary)
    ) {
      return event.timestamp
    }
  }
  return null
}

export function StatusTimeline({ ticket, activities }: StatusTimelineProps) {
  const currentStageIndex = STATUS_TO_STAGE[ticket.status] ?? 0

  const timestamps: Record<StageKey, string | null> = {
    todo: ticket.created_at,
    in_progress: ticket.started_at,
    review: findReviewTimestamp(activities),
    merged: ticket.completed_at,
  }

  return (
    <div className="border-b border-[var(--color-border)] px-3 py-3">
      <div className="flex items-center">
        {STAGES.map((stage, i) => {
          const isCompleted = i < currentStageIndex
          const isCurrent = i === currentStageIndex
          const Icon = isCompleted ? Check : stage.icon
          const ts = timestamps[stage.key]

          return (
            <div key={stage.key} className="flex flex-1 items-center">
              {/* Dot + label */}
              <div className="relative flex flex-col items-center">
                <div
                  className={`flex h-6 w-6 items-center justify-center rounded-full border-2 transition-colors ${
                    isCompleted
                      ? 'border-[var(--color-accent-green)] bg-[var(--color-accent-green)] text-white'
                      : isCurrent
                        ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)] animate-pulse'
                        : 'border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)]'
                  }`}
                >
                  <Icon size={12} />
                </div>
                <span
                  className={`mt-1 text-[10px] font-medium whitespace-nowrap ${
                    isCompleted
                      ? 'text-[var(--color-accent-green)]'
                      : isCurrent
                        ? 'text-[var(--color-accent-blue)]'
                        : 'text-[var(--color-text-muted)]'
                  }`}
                >
                  {stage.label}
                </span>
                {ts && (
                  <span
                    className="text-[9px] text-[var(--color-text-muted)] whitespace-nowrap"
                    title={new Date(ts).toLocaleString()}
                  >
                    {relativeTime(ts)}
                  </span>
                )}
              </div>

              {/* Connector line */}
              {i < STAGES.length - 1 && (
                <div className="mx-1 h-0.5 flex-1">
                  <div
                    className={`h-full rounded-full ${
                      i < currentStageIndex
                        ? 'bg-[var(--color-accent-green)]'
                        : 'bg-[var(--color-border)]'
                    }`}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
