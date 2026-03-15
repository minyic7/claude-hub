import { useEffect, useState } from 'react'
import { LogOut, Server, Bot, User, Crown } from 'lucide-react'
import { Modal } from '../common/Modal'
import { api, clearToken, type GlobalSettings, type ProjectAgentSettings, type AgentProvider, type POSettings } from '../../lib/api'

const PROVIDERS: { id: AgentProvider; label: string; description: string }[] = [
  { id: 'anthropic', label: 'Anthropic', description: 'Claude models via Anthropic API' },
  { id: 'openai', label: 'OpenAI', description: 'GPT models via OpenAI API' },
  { id: 'openai_compatible', label: 'OpenAI Compatible', description: 'Custom endpoint (vLLM, Ollama, etc.)' },
]

const ANTHROPIC_MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5', cost: '$' },
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6', cost: '$$' },
  { id: 'claude-opus-4-6', label: 'Opus 4.6', cost: '$$$' },
]

const OPENAI_MODELS = [
  { id: 'gpt-4o-mini', label: 'GPT-4o mini', cost: '$' },
  { id: 'gpt-4o', label: 'GPT-4o', cost: '$$' },
  { id: 'o3', label: 'o3', cost: '$$$' },
]

type Tab = 'system' | 'agent' | 'po' | 'account'

const TABS: { id: Tab; label: string; icon: typeof Server }[] = [
  { id: 'system', label: 'System', icon: Server },
  { id: 'agent', label: 'TicketAgent', icon: Bot },
  { id: 'po', label: 'PO Agent', icon: Crown },
  { id: 'account', label: 'Account', icon: User },
]

const DEFAULT_AGENT: ProjectAgentSettings = {
  enabled: true,
  provider: 'anthropic',
  api_key: '',
  endpoint_url: '',
  model: 'claude-haiku-4-5-20251001',
  batch_size: 8,
  max_context_messages: 25,
  web_search: false,
  auto_resolve_conversations: false,
  budget_per_ticket_usd: 2.00,
  budget_daily_usd: 50.00,
  budget_monthly_usd: 500.00,
}

const DEFAULT_PO: POSettings = {
  enabled: false,
  mode: 'semi_auto',
  max_active_tickets: 10,
  max_pending_approval: 5,
  max_new_per_cycle: 3,
  report_interval_hours: 1,
  deployment_type: 'auto',
  docs_format: 'auto',
  git_history_threshold: 10,
  git_history_days: 7,
  observe_model: 'claude-sonnet-4-6',
  think_model: 'claude-opus-4-6',
  think_budget_tokens: 8000,
  compaction_model: 'claude-sonnet-4-6',
}

interface Props {
  open: boolean
  onClose: () => void
  initialTab?: Tab
  activeProjectId?: string | null
}

export function AgentSettingsModal({ open, onClose, initialTab, activeProjectId }: Props) {
  const [globalSettings, setGlobalSettings] = useState<GlobalSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>(initialTab || 'system')

  // Per-project agent settings
  const [agentSettings, setAgentSettings] = useState<ProjectAgentSettings>(DEFAULT_AGENT)
  const [agentLoaded, setAgentLoaded] = useState(false)

  // PO settings (per-project)
  const [poSettings, setPoSettings] = useState<POSettings>(DEFAULT_PO)
  const [poLoaded, setPoLoaded] = useState(false)

  // Sync initialTab when modal opens
  useEffect(() => {
    if (open && initialTab) setActiveTab(initialTab)
  }, [open, initialTab])

  useEffect(() => {
    if (open) {
      setError('')
      setSaved(false)
      setTestResult(null)
      api.settings.getGlobal().then(setGlobalSettings).catch(() => setError('Failed to load settings'))
      // Load per-project settings
      if (activeProjectId) {
        setAgentLoaded(false)
        setPoLoaded(false)
        api.settings.getProjectAgent(activeProjectId)
          .then((s) => { setAgentSettings(s); setAgentLoaded(true) })
          .catch(() => { setAgentSettings(DEFAULT_AGENT); setAgentLoaded(true) })
        api.po.getSettings(activeProjectId)
          .then((s) => { setPoSettings(s); setPoLoaded(true) })
          .catch(() => { setPoSettings(DEFAULT_PO); setPoLoaded(true) })
      }
    }
  }, [open, activeProjectId])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      if (activeTab === 'system' && globalSettings) {
        const updated = await api.settings.updateGlobal(globalSettings)
        setGlobalSettings(updated)
      } else if (activeTab === 'agent' && activeProjectId) {
        const updated = await api.settings.updateProjectAgent(activeProjectId, agentSettings)
        setAgentSettings(updated)
      } else if (activeTab === 'po' && activeProjectId) {
        const updated = await api.po.updateSettings(activeProjectId, poSettings)
        setPoSettings(updated)
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      setError('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await api.settings.testConnection({
        api_key: agentSettings.api_key,
        provider: agentSettings.provider,
        model: agentSettings.model,
        endpoint_url: agentSettings.endpoint_url,
      })
      setTestResult({ ok: true, message: `${result.model}` })
    } catch (e) {
      setTestResult({ ok: false, message: e instanceof Error ? e.message : 'Connection failed' })
    } finally {
      setTesting(false)
    }
  }

  if (!globalSettings) {
    return (
      <Modal open={open} onClose={onClose} title="Settings">
        <p className="text-sm text-[var(--color-text-muted)]">Loading...</p>
      </Modal>
    )
  }

  const models = agentSettings.provider === 'anthropic' ? ANTHROPIC_MODELS
    : agentSettings.provider === 'openai' ? OPENAI_MODELS
    : []

  const needsProject = (activeTab === 'agent' || activeTab === 'po') && !activeProjectId
  const agentNotLoaded = activeTab === 'agent' && activeProjectId && !agentLoaded
  const poNotLoaded = activeTab === 'po' && activeProjectId && !poLoaded

  return (
    <Modal open={open} onClose={onClose} title="Settings" wide>
      <div className="flex min-h-[400px]">
        {/* Left tabs */}
        <nav className="flex w-36 shrink-0 flex-col border-r border-[var(--color-border)] pr-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 rounded-md px-2.5 py-2 text-xs transition-colors ${
                activeTab === tab.id
                  ? 'bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)] font-medium'
                  : 'text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]'
              }`}
            >
              <tab.icon size={14} />
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Right content */}
        <div className="flex flex-1 flex-col pl-4 min-w-0">
          <div className="flex-1 overflow-y-auto space-y-4">

            {/* Needs project message */}
            {needsProject && (
              <p className="text-sm text-[var(--color-text-muted)]">Select a project to configure {activeTab === 'agent' ? 'TicketAgent' : 'PO Agent'} settings.</p>
            )}

            {/* Loading */}
            {(agentNotLoaded || poNotLoaded) && (
              <p className="text-sm text-[var(--color-text-muted)]">Loading...</p>
            )}

            {/* ── System Tab ── */}
            {activeTab === 'system' && (
              <>
                <div>
                  <label className="mb-1 flex items-center justify-between text-sm text-[var(--color-text-primary)]">
                    <span>Max Concurrent Sessions</span>
                    <span className="font-mono text-xs text-[var(--color-text-muted)]">{globalSettings.max_sessions}</span>
                  </label>
                  <input
                    type="range"
                    min={1}
                    max={20}
                    value={globalSettings.max_sessions}
                    onChange={(e) => setGlobalSettings({ ...globalSettings, max_sessions: Number(e.target.value) })}
                    className="w-full accent-[var(--color-accent-blue)]"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Webhook URL</label>
                  <input
                    type="url"
                    value={globalSettings.webhook_url}
                    onChange={(e) => setGlobalSettings({ ...globalSettings, webhook_url: e.target.value })}
                    placeholder="https://your-server.com/api/webhooks/github"
                    className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)] font-mono"
                  />
                  <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
                    Public URL for GitHub webhook delivery. Auto-registered when creating/updating projects.
                  </p>
                </div>
              </>
            )}

            {/* ── TicketAgent Tab (per-project) ── */}
            {activeTab === 'agent' && activeProjectId && agentLoaded && (
              <>
                {/* Enabled */}
                <label className="flex items-center justify-between">
                  <span className="text-sm text-[var(--color-text-primary)]">Agent Enabled</span>
                  <button
                    onClick={() => setAgentSettings({ ...agentSettings, enabled: !agentSettings.enabled })}
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      agentSettings.enabled ? 'bg-[var(--color-accent-blue)]' : 'bg-[var(--color-border)]'
                    }`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                      agentSettings.enabled ? 'left-[22px]' : 'left-0.5'
                    }`} />
                  </button>
                </label>

                {/* Provider */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Provider</label>
                  <div className="grid grid-cols-3 gap-2">
                    {PROVIDERS.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => setAgentSettings({ ...agentSettings, provider: p.id })}
                        className={`rounded-md border px-3 py-2 text-xs transition-colors ${
                          agentSettings.provider === p.id
                            ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]'
                            : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                        }`}
                      >
                        <div className="font-medium">{p.label}</div>
                        <div className="mt-0.5 text-[10px] leading-tight">{p.description}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* API Key */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">API Key</label>
                  <input
                    type="password"
                    value={agentSettings.api_key}
                    onChange={(e) => setAgentSettings({ ...agentSettings, api_key: e.target.value })}
                    placeholder="sk-..."
                    className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)] font-mono"
                  />
                  <div className="mt-1.5 flex items-center gap-2">
                    <button
                      onClick={handleTest}
                      disabled={testing}
                      className="rounded border border-[var(--color-border)] px-2.5 py-1 text-[11px] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] disabled:opacity-50"
                    >
                      {testing ? 'Testing...' : 'Test Connection'}
                    </button>
                    {testResult && (
                      <span className={`text-[11px] ${testResult.ok ? 'text-[var(--color-accent-green)]' : 'text-[var(--color-accent-red)]'}`}>
                        {testResult.ok ? `OK (${testResult.message})` : testResult.message}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
                    Required for TicketAgent supervision. Not used by Claude Code CLI.
                  </p>
                </div>

                {/* Endpoint URL */}
                {agentSettings.provider === 'openai_compatible' && (
                  <div>
                    <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Endpoint URL</label>
                    <input
                      type="url"
                      value={agentSettings.endpoint_url}
                      onChange={(e) => setAgentSettings({ ...agentSettings, endpoint_url: e.target.value })}
                      placeholder="https://your-endpoint.com/v1"
                      className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)] font-mono"
                    />
                  </div>
                )}

                {/* Model */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Model</label>
                  {models.length > 0 ? (
                    <div className="grid grid-cols-3 gap-2">
                      {models.map((m) => (
                        <button
                          key={m.id}
                          onClick={() => setAgentSettings({ ...agentSettings, model: m.id })}
                          className={`rounded-md border px-3 py-2 text-xs transition-colors ${
                            agentSettings.model === m.id
                              ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]'
                              : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                          }`}
                        >
                          <div className="font-medium">{m.label}</div>
                          <div className="mt-0.5 text-[10px]">{m.cost}</div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <input
                      type="text"
                      value={agentSettings.model}
                      onChange={(e) => setAgentSettings({ ...agentSettings, model: e.target.value })}
                      placeholder="model-name"
                      className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)] font-mono"
                    />
                  )}
                </div>

                {/* Batch size */}
                <div>
                  <label className="mb-1 flex items-center justify-between text-sm text-[var(--color-text-primary)]">
                    <span>Batch Size</span>
                    <span className="font-mono text-xs text-[var(--color-text-muted)]">{agentSettings.batch_size}</span>
                  </label>
                  <input
                    type="range"
                    min={1}
                    max={30}
                    value={agentSettings.batch_size}
                    onChange={(e) => setAgentSettings({ ...agentSettings, batch_size: Number(e.target.value) })}
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
                    <span className="font-mono text-xs text-[var(--color-text-muted)]">{agentSettings.max_context_messages}</span>
                  </label>
                  <input
                    type="range"
                    min={5}
                    max={100}
                    step={5}
                    value={agentSettings.max_context_messages}
                    onChange={(e) => setAgentSettings({ ...agentSettings, max_context_messages: Number(e.target.value) })}
                    className="w-full accent-[var(--color-accent-blue)]"
                  />
                  <div className="flex justify-between text-[10px] text-[var(--color-text-muted)]">
                    <span>Less memory</span>
                    <span>More memory</span>
                  </div>
                </div>

                {/* Web search */}
                <label className="flex items-center justify-between">
                  <span className="text-sm text-[var(--color-text-primary)]">Web Search</span>
                  <button
                    onClick={() => setAgentSettings({ ...agentSettings, web_search: !agentSettings.web_search })}
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      agentSettings.web_search ? 'bg-[var(--color-accent-blue)]' : 'bg-[var(--color-border)]'
                    }`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                      agentSettings.web_search ? 'left-[22px]' : 'left-0.5'
                    }`} />
                  </button>
                </label>

                {/* Auto-resolve conversations */}
                <label className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-[var(--color-text-primary)]">Auto-resolve Conversations</span>
                    <p className="text-[10px] text-[var(--color-text-muted)]">Allow agent to resolve GitHub review threads after fixing</p>
                  </div>
                  <button
                    onClick={() => setAgentSettings({ ...agentSettings, auto_resolve_conversations: !agentSettings.auto_resolve_conversations })}
                    className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                      agentSettings.auto_resolve_conversations ? 'bg-[var(--color-accent-blue)]' : 'bg-[var(--color-border)]'
                    }`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                      agentSettings.auto_resolve_conversations ? 'left-[22px]' : 'left-0.5'
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
                        value={agentSettings.budget_per_ticket_usd}
                        onChange={(e) => setAgentSettings({ ...agentSettings, budget_per_ticket_usd: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Daily</span>
                      <input
                        type="number"
                        min={1}
                        step={5}
                        value={agentSettings.budget_daily_usd}
                        onChange={(e) => setAgentSettings({ ...agentSettings, budget_daily_usd: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Monthly</span>
                      <input
                        type="number"
                        min={1}
                        step={50}
                        value={agentSettings.budget_monthly_usd}
                        onChange={(e) => setAgentSettings({ ...agentSettings, budget_monthly_usd: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* ── PO Agent Tab ── */}
            {activeTab === 'po' && activeProjectId && poLoaded && (
              <>
                {/* Enabled */}
                <label className="flex items-center justify-between">
                  <span className="text-sm text-[var(--color-text-primary)]">PO Agent Enabled</span>
                  <button
                    onClick={() => setPoSettings({ ...poSettings, enabled: !poSettings.enabled })}
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      poSettings.enabled ? 'bg-[var(--color-accent-blue)]' : 'bg-[var(--color-border)]'
                    }`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                      poSettings.enabled ? 'left-[22px]' : 'left-0.5'
                    }`} />
                  </button>
                </label>

                {/* Mode */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Approval Mode</label>
                  <div className="grid grid-cols-2 gap-2">
                    {(['semi_auto', 'full_auto'] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() => setPoSettings({ ...poSettings, mode: m })}
                        className={`rounded-md border px-3 py-2 text-xs transition-colors ${
                          poSettings.mode === m
                            ? 'border-[var(--color-accent-blue)] bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]'
                            : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                        }`}
                      >
                        <div className="font-medium">{m === 'semi_auto' ? 'Semi-Auto' : 'Full Auto'}</div>
                        <div className="mt-0.5 text-[10px] leading-tight">
                          {m === 'semi_auto' ? 'Tickets require approval' : 'Tickets created directly'}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Report interval */}
                <div>
                  <label className="mb-1 flex items-center justify-between text-sm text-[var(--color-text-primary)]">
                    <span>Report Interval</span>
                    <span className="font-mono text-xs text-[var(--color-text-muted)]">{poSettings.report_interval_hours} hr</span>
                  </label>
                  <input
                    type="range"
                    min={1}
                    max={24}
                    value={poSettings.report_interval_hours}
                    onChange={(e) => setPoSettings({ ...poSettings, report_interval_hours: Number(e.target.value) })}
                    className="w-full accent-[var(--color-accent-blue)]"
                  />
                  <div className="flex justify-between text-[10px] text-[var(--color-text-muted)]">
                    <span>Frequent (1 hr)</span>
                    <span>Relaxed (24 hr)</span>
                  </div>
                </div>

                {/* Capacity */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Capacity Limits</label>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Max Active</span>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={poSettings.max_active_tickets}
                        onChange={(e) => setPoSettings({ ...poSettings, max_active_tickets: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Max New/Cycle</span>
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={poSettings.max_new_per_cycle}
                        onChange={(e) => setPoSettings({ ...poSettings, max_new_per_cycle: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Max Pending</span>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={poSettings.max_pending_approval}
                        onChange={(e) => setPoSettings({ ...poSettings, max_pending_approval: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                      <span className="text-[9px] text-[var(--color-text-muted)]">semi-auto only</span>
                    </div>
                  </div>
                </div>

                {/* Scope */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Deployment Scope</label>
                  <div className="grid grid-cols-3 gap-2">
                    {(['auto', 'github_pages', 'docker', 'docs_only', 'none'] as const).map((dt) => (
                      <button
                        key={dt}
                        onClick={() => setPoSettings({ ...poSettings, deployment_type: dt })}
                        className={`rounded-md border px-2 py-1.5 text-[11px] transition-colors ${
                          poSettings.deployment_type === dt
                            ? 'border-purple-400 bg-purple-500/10 text-purple-400'
                            : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                        }`}
                      >
                        {dt === 'auto' ? 'Auto' : dt === 'github_pages' ? 'GH Pages' : dt === 'docker' ? 'Docker' : dt === 'docs_only' ? 'Docs' : 'None'}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Git history */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">Git History Context</label>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Max Commits</span>
                      <input
                        type="number"
                        min={0}
                        max={50}
                        value={poSettings.git_history_threshold}
                        onChange={(e) => setPoSettings({ ...poSettings, git_history_threshold: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Days Window</span>
                      <input
                        type="number"
                        min={1}
                        max={30}
                        value={poSettings.git_history_days}
                        onChange={(e) => setPoSettings({ ...poSettings, git_history_days: Number(e.target.value) })}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]"
                      />
                    </div>
                  </div>
                </div>

                {/* LLM Models */}
                <div>
                  <label className="mb-1 block text-sm text-[var(--color-text-primary)]">LLM Models</label>
                  <div className="space-y-2">
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Observe (fast, cheap)</span>
                      <div className="grid grid-cols-3 gap-1">
                        {ANTHROPIC_MODELS.map((m) => (
                          <button
                            key={m.id}
                            onClick={() => setPoSettings({ ...poSettings, observe_model: m.id })}
                            className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                              poSettings.observe_model === m.id
                                ? 'border-purple-400 bg-purple-500/10 text-purple-400'
                                : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                            }`}
                          >
                            {m.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--color-text-muted)]">Think (reasoning)</span>
                      <div className="grid grid-cols-3 gap-1">
                        {ANTHROPIC_MODELS.map((m) => (
                          <button
                            key={m.id}
                            onClick={() => setPoSettings({ ...poSettings, think_model: m.id })}
                            className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                              poSettings.think_model === m.id
                                ? 'border-purple-400 bg-purple-500/10 text-purple-400'
                                : 'border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-text-muted)]'
                            }`}
                          >
                            {m.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Think budget */}
                <div>
                  <label className="mb-1 flex items-center justify-between text-sm text-[var(--color-text-primary)]">
                    <span>Think Budget</span>
                    <span className="font-mono text-xs text-[var(--color-text-muted)]">~{poSettings.think_budget_tokens} tokens</span>
                  </label>
                  <input
                    type="range"
                    min={2000}
                    max={16000}
                    step={1000}
                    value={poSettings.think_budget_tokens}
                    onChange={(e) => setPoSettings({ ...poSettings, think_budget_tokens: Number(e.target.value) })}
                    className="w-full accent-[var(--color-accent-blue)]"
                  />
                  <div className="flex justify-between text-[10px] text-[var(--color-text-muted)]">
                    <span>Quick (cheap)</span>
                    <span>Deep (costly)</span>
                  </div>
                </div>
              </>
            )}

            {/* ── Account Tab ── */}
            {activeTab === 'account' && (
              <div className="flex flex-col items-start gap-4">
                <p className="text-sm text-[var(--color-text-muted)]">
                  Logged in as the shared account. Logout will require re-entering credentials.
                </p>
                <button
                  onClick={() => { clearToken(); window.location.reload() }}
                  className="flex items-center gap-2 rounded-md border border-[var(--color-accent-red)]/30 px-3 py-2 text-xs text-[var(--color-accent-red)] hover:bg-[var(--color-accent-red)]/10 transition-colors"
                >
                  <LogOut size={14} />
                  Logout
                </button>
              </div>
            )}
          </div>

          {/* Footer — save/cancel (only for system, agent & po tabs) */}
          {activeTab !== 'account' && !needsProject && (
            <div className="flex items-center justify-end gap-2 border-t border-[var(--color-border)] pt-3 mt-3">
              {error && <span className="text-xs text-[var(--color-accent-red)] mr-auto">{error}</span>}
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
          )}
        </div>
      </div>
    </Modal>
  )
}
