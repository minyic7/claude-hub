import type { ActivityEvent } from './activity'
import type { Project, Ticket } from './ticket'

export type WSEvent =
  | { type: 'init'; data: { tickets: Ticket[]; projects: Project[] } }
  | { type: 'ticket_updated'; ticket_id: string; data: Ticket }
  | { type: 'ticket_deleted'; ticket_id: string }
  | { type: 'activity'; ticket_id: string; data: ActivityEvent }
  | { type: 'escalation'; ticket_id: string; data: { question: string; severity: string } }
  | { type: 'cost_update'; data: { daily: number; monthly: number } }
  | { type: 'project_created'; data: Project }
  | { type: 'project_updated'; data: Project }
  | { type: 'project_deleted'; project_id: string }
