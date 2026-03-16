import { useEffect, useRef, useCallback, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { RefreshCw } from 'lucide-react'
import { api, getToken } from '../../lib/api'
import '@xterm/xterm/css/xterm.css'

interface QATerminalProps {
  projectId: string
  visible: boolean
}

export function QATerminal({ projectId, visible }: QATerminalProps) {
  const termRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const retriesRef = useRef(0)
  const [restarting, setRestarting] = useState(false)
  const [connecting, setConnecting] = useState(true)

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
    const wsUrl = `${proto}//${window.location.host}/ws/kanban/${projectId}/qa-terminal${qs}`

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
        terminal.write('\r\n\x1b[31mFailed to start QA Agent session.\x1b[0m\r\n')
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
    if (!visible || !termRef.current) return

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
    requestAnimationFrame(() => fitAddon.fit())

    terminalRef.current = terminal
    fitAddonRef.current = fitAddon

    // Keyboard handlers
    terminal.attachCustomKeyEventHandler((e) => {
      if (e.type === 'keydown' && e.key === 'Enter' && e.shiftKey) {
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(new TextEncoder().encode('\x1b[13;2u'))
        }
        return false
      }
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
  }, [visible, projectId, sendResize, connectWs])

  const handleRestart = async () => {
    setRestarting(true)
    try {
      await api.qa.restart(projectId)
      wsRef.current?.close()
      const terminal = terminalRef.current
      if (terminal) {
        terminal.clear()
        terminal.write('\x1b[33mRestarting QA Agent...\x1b[0m\r\n')
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
    <div className="flex h-full flex-col bg-[#1a1b26]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-1.5 shrink-0">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${connecting ? 'bg-[var(--color-text-muted)] animate-pulse' : 'bg-emerald-400'}`} />
          <span className="text-xs font-medium text-[var(--color-text-muted)]">QA Agent</span>
          <span className="text-[10px] text-[var(--color-text-muted)]/50">read-only reviewer</span>
        </div>
        <button
          onClick={handleRestart}
          disabled={restarting}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors disabled:opacity-50"
          title="Restart QA Agent session"
        >
          <RefreshCw size={10} className={restarting ? 'animate-spin' : ''} />
          {restarting ? 'Restarting...' : 'Restart'}
        </button>
      </div>
      {/* Terminal */}
      <div ref={termRef} className="flex-1 p-1 min-h-0" />
    </div>
  )
}
