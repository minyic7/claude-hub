# Terminal

The integrated terminal panel provides direct access to Claude Code CLI sessions running inside tmux. It uses xterm.js for rendering and communicates with the backend over WebSocket.

## Opening the Terminal

- Click the **terminal toggle** button in the header (right side)
- The terminal appears as a resizable right panel alongside the Kanban board
- Switch between the **Terminal** tab and the **PO Chat** tab at the top of the panel

Each project has its own dedicated terminal session. When you switch projects, the terminal reconnects to the new project's session.

## Terminal Display

The terminal renders with:

- **Font size** — 13px monospace
- **Scrollback** — 10,000 lines of history
- **Theme** — Tokyonight-inspired color scheme (dark background, light text)
- **Cursor** — blinking block cursor
- **Selection** — click and drag to select text

The terminal automatically fits to its container and re-fits when the window or panel is resized.

## Scroll Mode

Scroll mode lets you navigate through the tmux scrollback buffer using your mouse wheel.

### How It Works

- **Enable** — click the scroll mode toggle button in the terminal header, or press **Shift+Escape**
- When active, the terminal enters tmux copy-mode
- **Mouse wheel up/down** sends arrow key presses to scroll through history (25px of wheel movement = 1 line)
- **Disable** — click the toggle again or press **Shift+Escape** to exit copy-mode

Without scroll mode, wheel events are passed directly to the terminal (xterm.js default behavior). Scroll mode uses the capture phase to intercept wheel events before xterm.js processes them.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Shift+Escape** | Toggle scroll mode on/off |
| **Ctrl+C** / **Cmd+C** | Copy selected text to clipboard (when text is selected) |
| **Ctrl+V** / **Cmd+V** | Paste from clipboard into the terminal |
| **Shift+Enter** | Send a newline (CSI u encoded) |

Standard terminal shortcuts (Ctrl+C to interrupt, Ctrl+L to clear, arrow keys for history) work as expected when no text is selected.

## Drag-Resize

The terminal panel width is adjustable:

- **Drag handle** — a vertical divider on the left edge of the terminal panel
- **Hover** — shows a `col-resize` cursor
- **Drag** — resize the panel between a minimum of 300px and a maximum of 70% of the viewport width
- **Persistence** — your preferred width is saved to `localStorage` and restored on next visit

## Restarting the Session

Click the **Restart** button in the terminal header to kill and recreate the kanban session:

1. The current tmux session is terminated
2. A "Restarting Claude Code..." message is displayed
3. After a brief delay, a new session is created and connected
4. The terminal reconnects automatically

This is useful if the session gets into a bad state or you need a fresh environment.

## Connection & Reconnection

### WebSocket Connection

The terminal connects via WebSocket at `/ws/kanban/{project_id}/terminal?token=...` using binary mode (`arraybuffer`) for efficient data transfer.

### Auto-Reconnection

If the connection drops (e.g., network interruption), the terminal automatically reconnects:

- **Backoff strategy** — exponential backoff starting at 200ms, increasing to a maximum of 3 seconds
- **Retry limit** — up to 5 reconnection attempts
- **On success** — the terminal resumes streaming from the tmux session

### Connection Status

The terminal header shows a connection indicator:
- **Blue dot (pulsing)** — connected and receiving data
- **Gray dot** — disconnected

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Session start failure (code 4003) | Shows "Failed to start session" error |
| Network error (code 1006) | Auto-reconnects with exponential backoff |
| Normal close (codes 1000, 1005) | Silent close, no reconnection |
| Max retries exceeded | Shows error message, manual reconnect required |

## Resize Synchronization

When the terminal or browser window is resized, the frontend sends the new column and row dimensions to the backend via a custom binary protocol. The backend relays this to tmux so the session adjusts its output to match the new terminal size.

## How It Works

Under the hood:

1. Each project has a persistent **tmux session** for its kanban terminal
2. The backend bridges the tmux PTY to a **WebSocket** connection
3. The frontend renders the PTY output using **xterm.js**
4. User input is sent back through the WebSocket to the tmux session
5. Sessions persist even if you navigate away — the terminal reconnects when you return
