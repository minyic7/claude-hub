# Notifications & Deploy

## Notification Bell

The bell icon in the header is the central hub for all application events. A badge displays the unread count (shows "99+" when exceeding 99).

### Notification Types

| Type | Color | Examples |
|------|-------|----------|
| **Info** | Blue | Session started, status changed, PR created |
| **Success** | Green | PR merged, deploy succeeded, review passed |
| **Warning** | Yellow | Agent escalation, review requested changes |
| **Error** | Red | Session failed, CI failure, API error |

### Notification Sources

Notifications are generated from multiple systems:

**Ticket lifecycle:**
- Status transitions (started, blocked, ready for review, merged, failed)
- Failed tickets include the failure reason in the notification

**TicketAgent activity:**
- Review decisions: "review pass" (success) or "changes requested" (warning)
- Session completion events

**Escalations:**
- When the TicketAgent calls its `escalate` tool, a warning notification appears
- The escalation question is displayed in the ticket detail panel with answer buttons

**PR events:**
- Notification when a PR is created for a ticket, with a link to the PR

**API errors:**
- Any failed API call automatically generates an error notification with the error detail

### Managing Notifications

- Click the **bell icon** to open the dropdown panel
- Notifications are listed with the most recent first
- Each notification shows a color-coded dot, message text, and timestamp
- Some notifications include an **action button** (e.g., "Configure Settings") that navigates to the relevant area
- **Mark all read** — clears the unread badge without removing notifications
- **Clear all** — removes all notifications from the panel
- The panel keeps the last **50 notifications**

### Toast Banners

New notifications also appear as floating toasts in the bottom-right corner. Each toast auto-hides after **6 seconds** or can be dismissed with the X button.

## Deploy Status Widget

The deploy status widget in the header monitors GitHub Actions workflow runs for the active project.

### Status Indicators

| State | Icon | Description |
|-------|------|-------------|
| **Deploying** | Blue spinner | A workflow run is in progress or queued |
| **Success** | Green checkmark | The latest run completed successfully |
| **Failure** | Red X | The latest run failed |
| **Idle** | Muted checkmark | No recent runs, or runs exist but none are active |

### Workflow Run Details

Click the widget to open a dropdown showing the **5 most recent** workflow runs. Each entry displays:

- Status icon (in progress, success, failure)
- Workflow name
- Branch name
- Timestamp
- Link to view the run on GitHub

### Polling Behavior

The widget polls the GitHub Actions API at different intervals:

- **Normal:** every 120 seconds
- **Deploying:** every 15 seconds (while any run is in progress)

## Version Update Banner

When a new version of the application is deployed, a blue banner appears at the top of the page:

> A new version is available. Click to refresh.

Clicking the banner reloads the page to pick up the new build.

### How It Works

1. On load, the frontend records the current build SHA from `/api/version`
2. It polls this endpoint every **30 seconds**
3. When the SHA changes, the banner appears
4. After a merge is initiated, polling speeds up to every **5 seconds** for up to 5 minutes to catch the deploy faster

## Deploy Queue Lock

The deploy queue lock prevents overlapping merges that could cause deployment conflicts.

### When the Lock Activates

The merge button on ticket detail panels is disabled when:

- A merge was just initiated (waiting for the deploy to complete)
- A GitHub Actions workflow is currently in progress

### Visual Indicators

- The merge button is grayed out and unclickable
- A yellow warning banner appears: **"Deploy in progress -- merge is queued"**

### Lock Lifecycle

1. User clicks **Merge** on a ticket -- lock activates, fast version polling begins
2. Deploy completes (detected via version SHA change or GitHub Actions status)
3. Lock releases, merge button re-enables
4. A success or failure notification is generated

A **5-minute safety timeout** ensures the lock always releases even if deploy detection fails.

### Deploy Completion Notifications

When a deploy completes while the lock is active:

- **Success:** an info notification confirms the deploy completed
- **Failure:** an error notification alerts that the deploy failed
