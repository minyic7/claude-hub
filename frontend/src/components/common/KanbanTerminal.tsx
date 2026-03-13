import { useEffect, useRef, useCallback, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { TerminalSquare, RefreshCw, PanelRightClose } from 'lucide-react'
import { api, getToken } from '../../lib/api'
import '@xterm/xterm/css/xterm.css'

const MIN_WIDTH = 300
const MAX_WIDTH_VW = 70
const DEFAULT_WIDTH = 600

interface KanbanTerminalProps {
  projectId: string
  projectName?: string
  visible: boolean
  onClose: () => void
}

export function KanbanTerminal({ projectId, projectName, visible, onClose }: KanbanTerminalProps) {
  const termRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const retriesRef = useRef(0)
  const [restarting, setRestarting] = useState(false)
  const [connecting, setConnecting] = useState(true)
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const draggingRef = useRef(false)

  const sendResize = useCallback((cols: number, rows: number) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
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

    if (wsRef.current) {
      wsRef.current.close()
    }

    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      retriesRef.current = 0
      setConnecting(false)
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
      if (wsRef.current !== ws) return
      if (event.code === 4003) {
        terminal.write('\r\n\x1b[31mFailed to start session.\x1b[0m\r\n')
      } else if (event.code === 1006 && retriesRef.current < 5) {
        const delay = Math.min(200 * Math.pow(2, retriesRef.current), 3000)
        retriesRef.current++
        setConnecting(true)
        setTimeout(() => connectWs(terminal), delay)
      } else if (event.code !== 1000 && event.code !== 1005) {
        terminal.write(`\r\n\x1b[31mConnection closed (${event.code}).\x1b[0m\r\n`)
      }
    }

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

    requestAnimationFrame(() => {
      fitAddon.fit()
    })

    terminalRef.current = terminal
    fitAddonRef.current = fitAddon

    terminal.attachCustomKeyEventHandler((e) => {
      if (e.type === 'keydown' && (e.ctrlKey || e.metaKey)) {
        if (e.key === 'v') {
          navigator.clipboard.readText().then((text) => {
            const ws = wsRef.current
            if (text && ws && ws.readyState === WebSocket.OPEN) {
              ws.send(new TextEncoder().encode(text))
            }
          }).catch(() => {})
          return false
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

    connectWs(terminal)

    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit()
      sendResize(terminal.cols, terminal.rows)
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

  // Re-fit when becoming visible or width changes
  useEffect(() => {
    if (visible && fitAddonRef.current && terminalRef.current) {
      requestAnimationFrame(() => {
        fitAddonRef.current?.fit()
        const t = terminalRef.current
        if (t) sendResize(t.cols, t.rows)
      })
    }
  }, [visible, width, sendResize])

  // Escape key to hide (only when visible)
  useEffect(() => {
    if (!visible) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && e.shiftKey) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [visible, onClose])

  // Drag resize handler
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    draggingRef.current = true

    const startX = e.clientX
    const startWidth = width
    const maxWidth = window.innerWidth * MAX_WIDTH_VW / 100

    const onMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return
      const delta = startX - ev.clientX
      const newWidth = Math.min(Math.max(startWidth + delta, MIN_WIDTH), maxWidth)
      setWidth(newWidth)
    }

    const onUp = () => {
      draggingRef.current = false
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [width])

  const handleRestart = async () => {
    setRestarting(true)
    try {
      await api.kanban.restart(projectId)
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
    <div
      className={`fixed top-0 right-0 bottom-0 z-50 flex transition-transform duration-200 ${visible ? 'translate-x-0' : 'translate-x-full'}`}
      style={{ width }}
    >
      {/* Drag handle */}
      <div
        onMouseDown={handleDragStart}
        className="w-1 cursor-col-resize bg-[var(--color-border)] hover:bg-[var(--color-accent-blue)] transition-colors shrink-0"
      />

      {/* Panel */}
      <div className="flex flex-1 flex-col bg-[#1a1b26] border-l border-[var(--color-border)] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <TerminalSquare size={14} className={connecting ? 'text-[var(--color-text-muted)] animate-pulse' : 'text-[var(--color-accent-blue)]'} />
            <span className="text-xs font-semibold text-[var(--color-text-muted)] truncate">
              {projectName || 'Kanban Claude Code'}
            </span>
            <span className="font-mono text-[10px] text-[var(--color-text-muted)]/40 select-all shrink-0" title={projectId}>
              {projectId.slice(0, 8)}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleRestart}
              disabled={restarting}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors disabled:opacity-50"
              title="Restart Claude Code session"
            >
              <RefreshCw size={10} className={restarting ? 'animate-spin' : ''} />
              {restarting ? 'Restarting...' : 'Restart'}
            </button>
            <button
              onClick={onClose}
              className="rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
              title="Hide terminal (Shift+Esc)"
            >
              <PanelRightClose size={14} />
            </button>
          </div>
        </div>
        {/* Terminal */}
        <div ref={termRef} className="flex-1 p-1 min-h-0" />
      </div>
    </div>
  )
}
