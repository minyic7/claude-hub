import type { ActivityEvent } from './activity'
import type { Project, Ticket } from './ticket'

export type WSEvent =
  | { type: 'init'; data: { tickets: Ticket[]; projects: Project[]; activities?: Record<string, ActivityEvent[]> } }
  | { type: 'ticket_updated'; ticket_id: string; data: Ticket }
  | { type: 'ticket_deleted'; ticket_id: string }
  | { type: 'activity'; ticket_id: string; data: ActivityEvent }
  | { type: 'escalation'; ticket_id: string; data: { question: string; severity: string } }
  | { type: 'cost_update'; data: { daily: number; monthly: number } }
  | { type: 'project_created'; data: Project }
  | { type: 'project_updated'; data: Project }
  | { type: 'project_deleted'; project_id: string }
  | { type: 'activity_cleared'; ticket_id: string }
  | { type: 'ticket_created'; ticket_id: string; data: Ticket }
