# Project Management

Projects are the top-level organizational unit in Claude Hub. Each project maps to a GitHub repository and contains its own set of tickets.

## Creating a Project

1. Click the **project dropdown** in the header
2. Select **New Project** at the bottom of the list
3. Fill in:
   - **Project name** — a short, descriptive name
   - **Repository URL** — the full GitHub repository URL
4. Click **Create**

## Switching Projects

Use the **project dropdown** in the header to switch between projects. The board will update to show only tickets for the selected project.

## Project Scope

Each project has its own:
- Kanban board with tickets
- Claude Code terminal session
- PO Chat instance
- Agent settings (TicketAgent, PO Agent)

## GitHub Integration

Projects connect to GitHub repositories for:
- Webhook-driven ticket creation
- Branch management per ticket
- CI/CD status tracking
- Pull request automation
