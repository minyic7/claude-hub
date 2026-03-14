import { useEffect, useState } from 'react'

/**
 * Tracks the visual viewport height to handle mobile keyboard popup.
 * Returns the offset (in px) that the keyboard is consuming from the bottom.
 * When no keyboard is open, returns 0.
 */
export function useVisualViewport(enabled: boolean): number {
  const [keyboardOffset, setKeyboardOffset] = useState(0)

  useEffect(() => {
    if (!enabled || !window.visualViewport) return

    const vv = window.visualViewport

    const update = () => {
      // The difference between the layout viewport and the visual viewport
      // tells us how much space the keyboard is consuming
      const offset = window.innerHeight - vv.height
      setKeyboardOffset(offset > 0 ? offset : 0)
    }

    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    update()

    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
      setKeyboardOffset(0)
    }
  }, [enabled])

  return keyboardOffset
}
