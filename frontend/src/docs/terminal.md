# Terminal

The integrated terminal panel provides direct access to Claude Code CLI sessions running inside tmux.

## Opening the Terminal

- Click the **panel toggle** button in the header (right side)
- The terminal appears as a resizable right panel
- Switch between **Terminal** and **PO Chat** tabs

## Terminal Features

### Live Output
The terminal streams real-time output from Claude Code sessions. You can watch as Claude:
- Reads and analyzes code
- Makes edits to files
- Runs commands
- Responds to TicketAgent feedback

### Scroll Mode
Toggle **scroll mode** in the terminal header to scroll through output history:
- When enabled, mouse wheel scrolls through the tmux scrollback buffer
- When disabled, mouse wheel behaves normally (passed to the terminal)

### Session Management
- Each project has its own terminal session
- Sessions persist in tmux even if you navigate away
- The terminal reconnects automatically when you return

## How It Works

Under the hood:
1. Claude Code runs inside a tmux session per project
2. The backend captures terminal output via WebSocket
3. The frontend renders it using xterm.js
4. Input is sent back through the WebSocket to tmux

## Keyboard Shortcuts

Standard terminal shortcuts work as expected:
- `Ctrl+C` — interrupt running command
- `Ctrl+L` — clear screen
- Arrow keys — navigate command history
