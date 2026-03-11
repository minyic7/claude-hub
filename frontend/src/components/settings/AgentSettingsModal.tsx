import { useEffect, useState } from 'react'
import { Modal } from '../common/Modal'
import { api, type AgentSettings } from '../../lib/api'

const MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5', cost: '$' },
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6', cost: '$$' },
  { id: 'claude-opus-4-6', label: 'Opus 4.6', cost: '$$$' },
]

interface Props {
  open: boolean
  onClose: () => void
}

export function AgentSettingsModal({ open, onClose }: Props) {
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (open) {
      setError('')
      setSaved(false)
      api.settings.getAgent().then(setSettings).catch(() => setError('Failed to load settings'))
    }
  }, [open])

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const updated = await api.settings.updateAgent(settings)
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      setError('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return (
      <Modal open={open} onClose={onClose} title="TicketAgent Settings">
        <p className="text-sm text-[var(--color-text-muted)]">Loading...</p>
      </Modal>
    )
  }

  return (
    <Modal open={open} onClose={onClose} title="TicketAgent Settings">
      <div className="space-y-4">
        {/* Enabled toggle */}
        <label className="flex items-center justify-between">
          <span className="text-sm text-[var(--color-text-primary)]">Agent Enabled</span>
          <button
            onClick={() => setSettings({ ...settings, enabled: !settings.enabled })}
            className={`relative h-6 w-11 rounded-full transition-colors ${
              settings.enabled ? 'bg-[var(--color-accent-blue)]' : 'bg-[var(--color-border)]'
            }`}
          >
            <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
              settings.enabled ? 'left-[22px]' : 'left-0.5'
            }`} />
          </button>
        </label>

        {/* Model selector */}
        <div>
          <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Model</label>
          <div className="grid grid-cols-3 gap-2">
            {MODELS.map((m) => (
              <button
                key={m.id}
                onClick={() => setSettings({ ...settings, model: m.id })}
                className={`rounded-md border px-3 py-2 text-xs transition-colors ${
                  settings.model === m.id
                    ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]'
                    : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                }`}
              >
                <div className="font-medium">{m.label}</div>
                <div className="mt-0.5 text-[10px]">{m.cost}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Batch size */}
        <div>
          <label className="mb-1 flex items-center justify-between text-sm text-[var(--color-text-primary)]">
            <span>Batch Size</span>
            <span className="font-mono text-xs text-[var(--color-text-muted)]">{settings.batch_size}</span>
          </label>
          <input
            type="range"
            min={1}
            max={30}
            value={settings.batch_size}
            onChange={(e) => setSettings({ ...settings, batch_size: Number(e.target.value) })}
            className="w-full accent-[var(--color-accent-blue)]"
          />
          <div className="flex justify-between text-[10px] text-[var(--color-text-muted)]">
            <span>Responsive (costly)</span>
            <span>Relaxed (cheap)</span>
          </div>
        </div>

        {/* Context messages */}
        <div>
          <label className="mb-1 flex items-center justify-between text-sm text-[var(--color-text-primary)]">
            <span>Context Messages</span>
            <span className="font-mono text-xs text-[var(--color-text-muted)]">{settings.max_context_messages}</span>
          </label>
          <input
            type="range"
            min={5}
            max={100}
            step={5}
            value={settings.max_context_messages}
            onChange={(e) => setSettings({ ...settings, max_context_messages: Number(e.target.value) })}
            className="w-full accent-[var(--color-accent-blue)]"
          />
          <div className="flex justify-between text-[10px] text-[var(--color-text-muted)]">
            <span>Less memory</span>
            <span>More memory</span>
          </div>
        </div>

        {/* Web search toggle */}
        <label className="flex items-center justify-between">
          <span className="text-sm text-[var(--color-text-primary)]">Web Search</span>
          <button
            onClick={() => setSettings({ ...settings, web_search: !settings.web_search })}
            className={`relative h-6 w-11 rounded-full transition-colors ${
              settings.web_search ? 'bg-[var(--color-accent-blue)]' : 'bg-[var(--color-border)]'
            }`}
          >
            <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
              settings.web_search ? 'left-[22px]' : 'left-0.5'
            }`} />
          </button>
        </label>

        {/* Budget */}
        <div>
          <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Budget (USD)</label>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <span className="text-[10px] text-[var(--color-text-muted)]">Per Ticket</span>
              <input
                type="number"
                min={0.1}
                step={0.5}
                value={settings.budget_per_ticket_usd}
                onChange={(e) => setSettings({ ...settings, budget_per_ticket_usd: Number(e.target.value) })}
                className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
              />
            </div>
            <div>
              <span className="text-[10px] text-[var(--color-text-muted)]">Daily</span>
              <input
                type="number"
                min={1}
                step={5}
                value={settings.budget_daily_usd}
                onChange={(e) => setSettings({ ...settings, budget_daily_usd: Number(e.target.value) })}
                className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
              />
            </div>
            <div>
              <span className="text-[10px] text-[var(--color-text-muted)]">Monthly</span>
              <input
                type="number"
                min={1}
                step={50}
                value={settings.budget_monthly_usd}
                onChange={(e) => setSettings({ ...settings, budget_monthly_usd: Number(e.target.value) })}
                className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
              />
            </div>
          </div>
        </div>

        {error && <p className="text-xs text-[var(--color-accent-red)]">{error}</p>}

        <div className="flex items-center justify-end gap-2 pt-2">
          {saved && <span className="text-xs text-[var(--color-accent-green)]">Saved!</span>}
          <button
            onClick={onClose}
            className="rounded px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded bg-[var(--color-accent-blue)] px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
