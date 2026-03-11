import { useState } from 'react'
import { AlertCircle, Send } from 'lucide-react'
import { Button } from '../common/Button'
import { api } from '../../lib/api'

interface EscalationBannerProps {
  ticketId: string
  question: string
}

const QUICK_ANSWERS = [
  { label: 'Yes', value: 'yes' },
  { label: 'No', value: 'no' },
  { label: 'Continue', value: 'continue with the current approach' },
  { label: 'Skip', value: 'skip this step and move on' },
]

export function EscalationBanner({ ticketId, question }: EscalationBannerProps) {
  const [answer, setAnswer] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sendAnswer = async (text: string) => {
    if (!text.trim() || sending) return
    setSending(true)
    setError(null)
    try {
      await api.tickets.answer(ticketId, text.trim())
      setAnswer('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send answer')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="rounded-lg border border-[var(--color-accent-red)]/30 bg-[var(--color-accent-red)]/5 p-3">
      <div className="mb-2 flex items-start gap-2">
        <AlertCircle size={16} className="mt-0.5 shrink-0 text-[var(--color-accent-red)]" />
        <div>
          <p className="text-xs font-medium text-[var(--color-accent-red)]">Agent needs your input</p>
          <p className="mt-1 text-sm text-[var(--color-text-primary)]">{question}</p>
        </div>
      </div>
      {/* Quick answer buttons */}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUICK_ANSWERS.map((qa) => (
          <button
            key={qa.label}
            onClick={() => sendAnswer(qa.value)}
            disabled={sending}
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1 text-xs font-medium text-[var(--color-text-primary)] transition-all hover:border-[var(--color-accent-blue)]/40 hover:bg-[var(--color-accent-blue)]/5 disabled:opacity-50"
          >
            {qa.label}
          </button>
        ))}
      </div>
      {/* Custom answer */}
      <div className="mt-2 flex gap-2">
        <input
          type="text"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendAnswer(answer)}
          placeholder="Or type a custom answer..."
          className="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
        />
        <Button size="sm" onClick={() => sendAnswer(answer)} disabled={!answer.trim() || sending}>
          <Send size={12} />
        </Button>
      </div>
      {error && (
        <p className="mt-2 rounded bg-[var(--color-accent-red)]/10 px-2 py-1 text-xs text-[var(--color-accent-red)]">
          {error}
        </p>
      )}
    </div>
  )
}
