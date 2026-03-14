import type { Project, ProjectCreate, Ticket, TicketCreate } from '../types/ticket'

const BASE = '/api'

type ErrorHandler = (message: string) => void
let _onError: ErrorHandler | null = null

/** Register a global error handler for API failures (e.g. notification bell) */
export function setApiErrorHandler(handler: ErrorHandler) {
  _onError = handler
}

// --- Token management ---
const TOKEN_KEY = 'claude-hub-token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options?.headers as Record<string, string>,
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const text = await res.text()
    let detail: string
    try {
      const json = JSON.parse(text)
      detail = json.detail || `${res.status}: ${text}`
    } catch {
      detail = `${res.status}: ${text}`
    }
    if (_onError) _onError(detail)
    throw new Error(detail)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  auth: {
    check: () => request<{ auth_required: boolean }>('/auth/check'),
    verify: () => request<{ status: string }>('/auth/verify'),
    login: (username: string, password: string) =>
      request<{ token: string; expires_in: number }>('/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
  },
  projects: {
    list: () => request<Project[]>('/projects'),
    create: (data: ProjectCreate) =>
      request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
    get: (id: string) => request<Project>(`/projects/${id}`),
    update: (id: string, data: Partial<ProjectCreate>) =>
      request<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    delete: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),
  },
  tickets: {
    list: (projectId?: string, status?: string) => {
      const params = new URLSearchParams()
      if (projectId) params.set('project_id', projectId)
      if (status) params.set('status', status)
      const qs = params.toString()
      return request<Ticket[]>(`/tickets${qs ? `?${qs}` : ''}`)
    },
    create: (data: TicketCreate) =>
      request<Ticket>('/tickets', { method: 'POST', body: JSON.stringify(data) }),
    get: (id: string) =>
      request<Ticket>(`/tickets/${id}`),
    update: (id: string, data: { title?: string; description?: string; priority?: number; depends_on?: string[] }) =>
      request<Ticket>(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/tickets/${id}`, { method: 'DELETE' }),
    start: (id: string) =>
      request<Ticket>(`/tickets/${id}/start`, { method: 'POST' }),
    stop: (id: string) =>
      request<Ticket>(`/tickets/${id}/stop`, { method: 'POST' }),
    retry: (id: string, guidance?: string) =>
      request<Ticket>(`/tickets/${id}/retry`, {
        method: 'POST',
        body: JSON.stringify({ guidance }),
      }),
    answer: (id: string, answer: string) =>
      request<Ticket>(`/tickets/${id}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer }),
      }),
    message: (id: string, message: string) =>
      request<Ticket>(`/tickets/${id}/message`, {
        method: 'POST',
        body: JSON.stringify({ message }),
      }),
    markReview: (id: string) =>
      request<Ticket>(`/tickets/${id}/mark-review`, { method: 'POST' }),
    merge: (id: string) =>
      request<Ticket>(`/tickets/${id}/merge`, { method: 'POST' }),
    requestChanges: (id: string, feedback: string) =>
      request<Ticket>(`/tickets/${id}/request-changes`, {
        method: 'POST',
        body: JSON.stringify({ feedback }),
      }),
    resolveConflicts: (id: string) =>
      request<Ticket>(`/tickets/${id}/resolve-conflicts`, { method: 'POST' }),
    archive: (id: string) =>
      request<Ticket>(`/tickets/${id}/archive`, { method: 'POST' }),
    bulkStart: (ticketIds: string[]) =>
      request<{ started: string[]; queued: string[] }>('/tickets/bulk-start', {
        method: 'POST',
        body: JSON.stringify({ ticket_ids: ticketIds }),
      }),
    dequeue: (id: string) =>
      request<Ticket>(`/tickets/queue/${id}`, { method: 'DELETE' }),
    reorder: (projectId: string, ticketIds: string[]) =>
      request<void>('/tickets/reorder', {
        method: 'POST',
        body: JSON.stringify({ project_id: projectId, ticket_ids: ticketIds }),
      }),
    reorderQueue: (ticketIds: string[]) =>
      request<void>('/tickets/queue/reorder', {
        method: 'POST',
        body: JSON.stringify({ ticket_ids: ticketIds }),
      }),
    activity: (id: string, since = 0) =>
      request<Record<string, unknown>[]>(`/tickets/${id}/activity?since=${since}`),
    syncReviewStatus: () =>
      request<{ synced: string[] }>('/tickets/sync-review-status', { method: 'POST' }),
    syncReviews: (id: string) =>
      request<{ synced: number }>(`/tickets/${id}/sync-reviews`, { method: 'POST' }),
    ciStatus: (id: string) =>
      request<CIStatus>(`/tickets/${id}/ci-status`),
    addNote: (id: string, content: string, type: string = 'comment') =>
      request<Ticket>(`/tickets/${id}/notes`, {
        method: 'POST',
        body: JSON.stringify({ content, type }),
      }),
    revert: (id: string) =>
      request<Ticket>(`/tickets/${id}/revert`, { method: 'POST' }),
    duplicate: (id: string) =>
      request<Ticket>(`/tickets/${id}/duplicate`, { method: 'POST' }),
  },
  settings: {
    getAgent: () => request<AgentSettings>('/settings/agent'),
    updateAgent: (data: Partial<AgentSettings>) =>
      request<AgentSettings>('/settings/agent', { method: 'PUT', body: JSON.stringify(data) }),
    testConnection: () =>
      request<{ ok: boolean; model: string; message: string }>('/settings/agent/test', { method: 'POST' }),
  },
  kanban: {
    start: (projectId: string) =>
      request<KanbanStatus>(`/projects/${projectId}/kanban/start`, { method: 'POST' }),
    restart: (projectId: string) =>
      request<KanbanStatus>(`/projects/${projectId}/kanban/restart`, { method: 'POST' }),
    status: (projectId: string) =>
      request<KanbanStatus>(`/projects/${projectId}/kanban/status`),
  },
  github: {
    actions: (projectId: string) =>
      request<{ runs: WorkflowRun[] }>(`/github/actions?project_id=${encodeURIComponent(projectId)}`),
  },
  version: () => request<{ sha: string }>('/version'),
  health: () => request<{ status: string; redis: boolean }>('/health'),
  cost: () => request<{ daily: number; monthly: number }>('/cost'),
}

export interface KanbanStatus {
  alive: boolean
  session_name: string
  ssh_command: string
}

export interface WorkflowRun {
  id: number
  status: string
  conclusion: string | null
  created_at: string
  html_url: string
  head_branch: string
  name: string
}

export interface CICheck {
  name: string
  status?: string
  state?: string
  conclusion?: string | null
  bucket?: string
  html_url?: string
  detailsUrl?: string
  link?: string
}

export interface CIStatus {
  status: 'passed' | 'failed' | 'pending' | 'no_ci'
  checks: CICheck[]
  summary: string
}

export type AgentProvider = 'anthropic' | 'openai' | 'openai_compatible'

export interface AgentSettings {
  // System
  max_sessions: number
  gh_token: string
  webhook_url: string
  // Agent
  enabled: boolean
  provider: AgentProvider
  api_key: string
  endpoint_url: string
  model: string
  batch_size: number
  max_context_messages: number
  web_search: boolean
  budget_per_ticket_usd: number
  budget_daily_usd: number
  budget_monthly_usd: number
}
