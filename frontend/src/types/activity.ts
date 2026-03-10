export interface ActivityEvent {
  timestamp: string
  source: 'claude_code' | 'ticket_agent'
  type: 'thinking' | 'tool_use' | 'tool_result' | 'intervention' | 'decision' | 'info' | 'warning' | 'error'
  summary: string
}
