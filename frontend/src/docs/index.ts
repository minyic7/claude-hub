import gettingStarted from './getting-started.md?raw'
import projectManagement from './project-management.md?raw'
import kanbanBoard from './kanban-board.md?raw'
import ticketDetail from './ticket-detail.md?raw'
import terminal from './terminal.md?raw'
import notificationsAndDeploy from './notifications-and-deploy.md?raw'
import ticketAgent from './ticket-agent.md?raw'
import settings from './settings.md?raw'

export interface DocPage {
  id: string
  title: string
  content: string
}

export interface DocSection {
  id: string
  title: string
  pages: DocPage[]
}

export const docSections: DocSection[] = [
  {
    id: 'getting-started',
    title: 'Getting Started',
    pages: [
      { id: 'getting-started', title: 'Getting Started', content: gettingStarted },
    ],
  },
  {
    id: 'board',
    title: 'Board',
    pages: [
      { id: 'project-management', title: 'Project Management', content: projectManagement },
      { id: 'kanban-board', title: 'Kanban Board', content: kanbanBoard },
      { id: 'ticket-detail', title: 'Ticket Detail', content: ticketDetail },
    ],
  },
  {
    id: 'features',
    title: 'Features',
    pages: [
      { id: 'terminal', title: 'Terminal', content: terminal },
      { id: 'notifications-and-deploy', title: 'Notifications & Deploy', content: notificationsAndDeploy },
    ],
  },
  {
    id: 'agents',
    title: 'Agents',
    pages: [
      { id: 'ticket-agent', title: 'Ticket Agent', content: ticketAgent },
    ],
  },
  {
    id: 'config',
    title: 'Config',
    pages: [
      { id: 'settings', title: 'Settings', content: settings },
    ],
  },
]
