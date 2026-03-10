import { useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { Button } from '../common/Button'
import { api } from '../../lib/api'

interface EscalationBannerProps {
  ticketId: string
  question: string
}

export function EscalationBanner({ ticketId, question }: EscalationBannerProps) {
  const [answer, setAnswer] = useState('')
  const [sending, setSending] = useState(false)

  const handleSend = async () => {
    if (!answer.trim()) return
    setSending(true)
    try {
      await api.tickets.answer(ticketId, answer.trim())
      setAnswer('')
    } catch (err) {
      console.error('Failed to send answer:', err)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="rounded-lg border border-[var(--color-accent-red)]/30 bg-[var(--color-accent-red)]/5 p-3">
      <div className="mb-2 flex items-start gap-2">
        <AlertCircle size={16} className="mt-0.5 shrink-0 text-[var(--color-accent-red)]" />
        <div>
          <p className="text-xs font-medium text-[var(--color-accent-red)]">Agent Escalation</p>
          <p className="mt-1 text-sm text-[var(--color-text-primary)]">{question}</p>
        </div>
      </div>
      <div className="mt-2 flex gap-2">
        <input
          type="text"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Type your answer..."
          className="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
        />
        <Button size="sm" onClick={handleSend} disabled={!answer.trim() || sending}>
          Send
        </Button>
      </div>
    </div>
  )
}
