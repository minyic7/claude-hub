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
