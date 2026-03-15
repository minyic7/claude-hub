# Project Management

Projects are the top-level organizational unit in Claude Hub. Each project maps to a GitHub repository and contains its own set of tickets, terminal session, and agent configuration.

## Creating a Project

1. Click the **project dropdown** in the header bar
2. Select **New Project** at the bottom of the list
3. Fill in the project details:
   - **Project name** — a short, descriptive name (e.g., "Backend API", "Mobile App")
   - **Repository URL** — the full GitHub repository URL (e.g., `https://github.com/org/repo`)
   - **GitHub Token** *(optional)* — a per-project GitHub token for private repos
   - **Base Branch** *(optional)* — the branch tickets branch from (defaults to `main`)
4. Click **Create**

The project is assigned a unique 12-character ID and immediately becomes the active project.

## Project Settings

### Base Branch

Each project has a configurable **base branch** (default: `main`). This branch is used as:
- The parent branch for all ticket feature branches
- The target branch for pull requests
- The reference point for code reviews and diffs

To change it, edit the project and update the base branch field.

### Per-Project GitHub Token

Each project can have its own GitHub token, which takes priority over the global token configured in Settings. This is useful when:
- Different projects live in different GitHub organizations
- You need fine-grained access control per repository
- Team members have different permission levels

The token is stored securely in Redis and masked in the UI (showing only the first 4 and last 4 characters). If no per-project token is set, the global `gh_token` from Settings is used as a fallback.

### Webhook Auto-Registration

When you create or update a project with both a **repository URL** and a **GitHub token**, Claude Hub automatically registers a GitHub webhook on the repository. The webhook listens for:

- `pull_request` events
- `pull_request_review` events
- `pull_request_review_comment` events

This enables features like automatic PR review status syncing and webhook-driven ticket updates. The webhook URL is configured via the `CLAUDE_HUB_WEBHOOK_URL` setting.

**Webhook lifecycle:**
- **Created** when a project is first set up with valid credentials
- **Updated** if the webhook URL changes
- **Deleted** if the project is deleted or the token is removed
- **Skipped** if the token or repo URL is missing

The registration status is tracked and reported (created, exists, updated, error, skipped).

## Switching Projects

Use the **project dropdown** in the header to switch between projects. When you switch:

- The Kanban board updates to show only tickets for the selected project
- The terminal reconnects to the selected project's tmux session
- The PO Chat panel filters to the active project
- Status bar stats update (running, blocked, total, archived counts)

Your active project selection is saved to `localStorage` and restored on next visit. If no project is selected, the first available project is auto-selected.

## Updating a Project

Edit project settings via the project dropdown menu:

- **Name** — rename the project
- **Repository URL** — change the linked repository
- **GitHub Token** — update or remove the per-project token
- **Base Branch** — change the default branch

Changing the GitHub token triggers webhook cleanup (deletes the old webhook) and re-registration with the new token.

## Deleting a Project

Deleting a project:
1. Removes the project and all its configuration from Redis
2. Cleans up any registered GitHub webhooks
3. Does **not** delete tickets — they remain in Redis but are no longer associated with an active project

## Project Scope

Each project operates independently with its own:

| Resource | Scope |
|----------|-------|
| Kanban board | Separate ticket set per project |
| Terminal session | Dedicated tmux/kanban session |
| PO Agent | Per-project configuration and chat |
| Ticket sequence | Independent ticket numbering |
| Clone directory | Isolated git clone per ticket |
| Webhooks | Per-project GitHub webhook registration |
