import { useEffect, useRef, useCallback, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { X, TerminalSquare, RefreshCw } from 'lucide-react'
import { api, getToken } from '../../lib/api'
import '@xterm/xterm/css/xterm.css'

interface KanbanTerminalProps {
  projectId: string
  onClose: () => void
}

export function KanbanTerminal({ projectId, onClose }: KanbanTerminalProps) {
  const termRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const [restarting, setRestarting] = useState(false)

  const sendResize = useCallback((cols: number, rows: number) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      // Resize protocol: 0x01 byte + JSON
      const json = JSON.stringify({ cols, rows })
      const payload = new Uint8Array(1 + json.length)
      payload[0] = 0x01
      for (let i = 0; i < json.length; i++) {
        payload[i + 1] = json.charCodeAt(i)
      }
      ws.send(payload.buffer)
    }
  }, [])

  const connectWs = useCallback((terminal: Terminal) => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const token = getToken()
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    const wsUrl = `${proto}//${window.location.host}/ws/kanban/${projectId}/terminal${qs}`

    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      sendResize(terminal.cols, terminal.rows)
    }

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        terminal.write(new Uint8Array(event.data))
      } else {
        terminal.write(event.data)
      }
    }

    ws.onclose = (event) => {
      if (event.code === 4003) {
        terminal.write('\r\n\x1b[31mFailed to start session.\x1b[0m\r\n')
      } else {
        terminal.write('\r\n\x1b[31mConnection closed.\x1b[0m\r\n')
      }
    }

    // Terminal input → WebSocket
    terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data))
      }
    })

    return ws
  }, [projectId, sendResize])

  useEffect(() => {
    if (!termRef.current) return

    const terminal = new Terminal({
      cursorBlink: true,
      scrollback: 10000,
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: '#1a1b26',
        foreground: '#a9b1d6',
        cursor: '#c0caf5',
        selectionBackground: '#33467c',
        black: '#15161e',
        red: '#f7768e',
        green: '#9ece6a',
        yellow: '#e0af68',
        blue: '#7aa2f7',
        magenta: '#bb9af7',
        cyan: '#7dcfff',
        white: '#a9b1d6',
      },
    })

    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(termRef.current)

    // Fit after a frame to ensure container has dimensions
    requestAnimationFrame(() => {
      fitAddon.fit()
    })

    terminalRef.current = terminal
    fitAddonRef.current = fitAddon

    // Clipboard paste (Ctrl+V / Cmd+V) → send to terminal
    terminal.attachCustomKeyEventHandler((e) => {
      if (e.type === 'keydown' && (e.ctrlKey || e.metaKey)) {
        if (e.key === 'v') {
          navigator.clipboard.readText().then((text) => {
            const ws = wsRef.current
            if (text && ws && ws.readyState === WebSocket.OPEN) {
              ws.send(new TextEncoder().encode(text))
            }
          }).catch(() => {})
          return false // prevent default
        }
        if (e.key === 'c') {
          const sel = terminal.getSelection()
          if (sel) {
            navigator.clipboard.writeText(sel).catch(() => {})
            return false
          }
        }
      }
      return true
    })

    // Connect WebSocket (auto-starts session if needed)
    connectWs(terminal)

    // Handle window resize
    const handleResize = () => {
      fitAddon.fit()
      sendResize(terminal.cols, terminal.rows)
    }

    const resizeObserver = new ResizeObserver(() => {
      handleResize()
    })
    resizeObserver.observe(termRef.current)

    return () => {
      resizeObserver.disconnect()
      wsRef.current?.close()
      terminal.dispose()
      terminalRef.current = null
      wsRef.current = null
      fitAddonRef.current = null
    }
  }, [projectId, sendResize, connectWs])

  // Escape key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && e.shiftKey) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const handleRestart = async () => {
    setRestarting(true)
    try {
      await api.kanban.restart(projectId)
      // Close and reconnect
      wsRef.current?.close()
      const terminal = terminalRef.current
      if (terminal) {
        terminal.clear()
        terminal.write('\x1b[33mRestarting Claude Code...\x1b[0m\r\n')
        await new Promise(r => setTimeout(r, 2000))
        connectWs(terminal)
      }
    } catch {
      // handled by global
    } finally {
      setRestarting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="relative flex h-[80vh] w-[90vw] max-w-5xl flex-col rounded-lg border border-[var(--color-border)] bg-[#1a1b26] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
          <div className="flex items-center gap-2">
            <TerminalSquare size={14} className="text-[var(--color-accent-blue)]" />
            <span className="text-xs font-semibold text-[var(--color-text-muted)]">
              Kanban Claude Code
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRestart}
              disabled={restarting}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors disabled:opacity-50"
              title="Restart Claude Code session"
            >
              <RefreshCw size={10} className={restarting ? 'animate-spin' : ''} />
              {restarting ? 'Restarting...' : 'Restart'}
            </button>
            <span className="text-[10px] text-[var(--color-text-muted)] whitespace-nowrap">Scroll: Ctrl+B [ ↑/PgUp, q exit · Shift+Esc close</span>
            <button
              onClick={onClose}
              className="rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>
        {/* Terminal */}
        <div ref={termRef} className="flex-1 p-1" />
      </div>
    </div>
  )
}
