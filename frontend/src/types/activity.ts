export interface ActivityEvent {
  timestamp: string
  source: 'claude_code' | 'ticket_agent' | 'user'
  type: 'thinking' | 'tool_use' | 'tool_result' | 'intervention' | 'decision' | 'commentary' | 'review' | 'message' | 'info' | 'warning' | 'error'
  summary: string
}
