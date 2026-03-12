import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

const NORMAL_INTERVAL = 30_000 // 30s
const FAST_INTERVAL = 5_000 // 5s
const FAST_TIMEOUT = 5 * 60_000 // 5 min

interface UseVersionPollingReturn {
  /** Signal that a deploy was triggered — switch to fast polling */
  startFastPolling: () => void
  /** True when a new version has been detected but user hasn't refreshed yet */
  newVersionAvailable: boolean
}

export function useVersionPolling(
  onNewVersion?: () => void,
): UseVersionPollingReturn {
  const initialShaRef = useRef<string | null>(null)
  const [newVersionAvailable, setNewVersionAvailable] = useState(false)
  const [fast, setFast] = useState(false)
  const fastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const checkVersion = useCallback(async () => {
    try {
      const { sha } = await api.version()
      if (initialShaRef.current === null) {
        // First fetch — record the baseline
        initialShaRef.current = sha
        return
      }
      if (sha !== initialShaRef.current) {
        setNewVersionAvailable(true)
        // Stop fast polling — deploy is done
        setFast(false)
        if (fastTimerRef.current) {
          clearTimeout(fastTimerRef.current)
          fastTimerRef.current = null
        }
        onNewVersion?.()
      }
    } catch {
      // Silently ignore — server might be restarting during deploy
    }
  }, [onNewVersion])

  const startFastPolling = useCallback(() => {
    setFast(true)
    // Safety timeout: revert to normal after 5 min
    if (fastTimerRef.current) clearTimeout(fastTimerRef.current)
    fastTimerRef.current = setTimeout(() => {
      setFast(false)
    }, FAST_TIMEOUT)
  }, [])

  useEffect(() => {
    // Initial fetch
    checkVersion()

    const interval = fast ? FAST_INTERVAL : NORMAL_INTERVAL
    pollTimerRef.current = setInterval(checkVersion, interval)

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [fast, checkVersion])

  // Cleanup fast timer on unmount
  useEffect(() => {
    return () => {
      if (fastTimerRef.current) clearTimeout(fastTimerRef.current)
    }
  }, [])

  return { startFastPolling, newVersionAvailable }
}
