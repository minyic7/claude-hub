export interface TicketNote {
  type: 'comment' | 'progress' | 'blocker' | 'review' | 'system'
  content: string
  author: string
  timestamp: string
}

export type BranchType = 'feature' | 'bugfix' | 'hotfix' | 'chore' | 'refactor' | 'docs' | 'test'

export type TicketStatus =
  | 'todo'
  | 'queued'
  | 'in_progress'
  | 'blocked'
  | 'verifying'
  | 'reviewing'
  | 'awaiting_merge'
  | 'merging'
  | 'merged'
  | 'failed'

export interface Project {
  id: string
  name: string
  repo_url: string
  gh_token: string  // masked in API responses
  base_branch: string
  pilot_mode: false | 'semi' | 'auto'
  max_board_tickets: number
  max_tickets_per_cycle: number
  vision_mode: 'readonly' | 'writable'
  created_at: string
}

export interface ProjectCreate {
  name: string
  repo_url: string
  gh_token?: string
  base_branch?: string
  pilot_mode?: false | 'semi' | 'auto'
  max_board_tickets?: number
  max_tickets_per_cycle?: number
  vision_mode?: 'readonly' | 'writable'
}

export interface Ticket {
  id: string
  project_id: string
  seq: number
  title: string
  description: string
  branch_type: BranchType
  branch: string
  repo_url: string
  base_branch: string
  status: TicketStatus
  blocked_question: string | null
  failed_reason: string | null
  source: string
  external_id: string | null
  metadata: Record<string, unknown>
  depends_on: string[]
  clone_path: string | null
  pr_url: string | null
  pr_number: number | null
  has_conflicts?: boolean
  priority: number
  archived: boolean
  pilot: boolean
  tmux_session: string | null
  agent_cost_usd: number
  agent_tokens: number
  agent_review?: string | null
  review_status?: string | null
  reviewer?: string | null
  unresolved_thread_count?: number
  notes?: TicketNote[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  status_changed_at: string | null
}

export interface TicketCreate {
  project_id: string
  title: string
  description?: string
  branch_type?: BranchType
  depends_on?: string[]
  pilot?: boolean
}
