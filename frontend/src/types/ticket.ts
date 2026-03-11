export type BranchType = 'feature' | 'bugfix' | 'hotfix' | 'chore' | 'refactor' | 'docs' | 'test'

export type TicketStatus =
  | 'todo'
  | 'in_progress'
  | 'blocked'
  | 'verifying'
  | 'review'
  | 'merging'
  | 'merged'
  | 'failed'

export interface Project {
  id: string
  name: string
  repo_url: string
  gh_token: string  // masked in API responses
  base_branch: string
  created_at: string
}

export interface ProjectCreate {
  name: string
  repo_url: string
  gh_token?: string
  base_branch?: string
}

export interface Ticket {
  id: string
  project_id: string
  title: string
  description: string
  branch_type: BranchType
  branch: string
  repo_url: string
  base_branch: string
  role: string
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
  tmux_session: string | null
  agent_cost_usd: number
  agent_tokens: number
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TicketCreate {
  project_id: string
  title: string
  description?: string
  branch_type?: BranchType
  role?: string
  depends_on?: string[]
}
