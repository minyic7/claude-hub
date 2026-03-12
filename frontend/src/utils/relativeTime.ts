const UNITS: [string, number][] = [
  ['y', 31536000],
  ['mo', 2592000],
  ['d', 86400],
  ['h', 3600],
  ['min', 60],
  ['s', 1],
]

export function relativeTime(timestamp: string | number | Date): string {
  const seconds = Math.round((Date.now() - new Date(timestamp).getTime()) / 1000)
  if (seconds < 5) return 'just now'
  for (const [unit, value] of UNITS) {
    const count = Math.floor(seconds / value)
    if (count >= 1) return `${count} ${unit} ago`
  }
  return 'just now'
}

/** Format elapsed duration since a timestamp, e.g. "5m", "2h 15m", "3d 4h" */
export function formatElapsed(timestamp: string | number | Date): string {
  const totalSeconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000))
  if (totalSeconds < 60) return '<1m'
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`
  return `${minutes}m`
}
