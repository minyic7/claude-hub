import { useEffect, useRef, useState } from 'react'

/**
 * Tracks the width of a container element using ResizeObserver.
 * Callback is debounced at ~16ms to prevent per-frame recalc during drag resize.
 */
export function useContainerWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    let rafId: number | null = null
    let pending = false

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const newWidth = entry.contentRect.width

      if (!pending) {
        pending = true
        rafId = requestAnimationFrame(() => {
          setWidth(newWidth)
          pending = false
        })
      }
    })

    // Set initial width
    setWidth(el.getBoundingClientRect().width)
    observer.observe(el)

    return () => {
      observer.disconnect()
      if (rafId !== null) cancelAnimationFrame(rafId)
    }
  }, [])

  return [ref, width]
}
