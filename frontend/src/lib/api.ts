import type { Project, ProjectCreate, Ticket, TicketCreate } from '../types/ticket'

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
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
    update: (id: string, data: { title?: string; description?: string }) =>
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
    markReview: (id: string) =>
      request<Ticket>(`/tickets/${id}/mark-review`, { method: 'POST' }),
    merge: (id: string) =>
      request<Ticket>(`/tickets/${id}/merge`, { method: 'POST' }),
    activity: (id: string, since = 0) =>
      request<Record<string, unknown>[]>(`/tickets/${id}/activity?since=${since}`),
  },
  health: () => request<{ status: string; redis: boolean }>('/health'),
  cost: () => request<{ daily: number; monthly: number }>('/cost'),
  roles: () => request<Record<string, unknown>>('/roles'),
}
