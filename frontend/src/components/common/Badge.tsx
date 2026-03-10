import type { ReactNode } from 'react'

interface BadgeProps {
  color?: 'blue' | 'green' | 'red' | 'yellow' | 'gray'
  children: ReactNode
}

const colorMap = {
  blue: 'bg-[var(--color-accent-blue)]/15 text-[var(--color-accent-blue)]',
  green: 'bg-[var(--color-accent-green)]/15 text-[var(--color-accent-green)]',
  red: 'bg-[var(--color-accent-red)]/15 text-[var(--color-accent-red)]',
  yellow: 'bg-[var(--color-accent-yellow)]/15 text-[var(--color-accent-yellow)]',
  gray: 'bg-[var(--color-text-muted)]/15 text-[var(--color-text-muted)]',
}

export function Badge({ color = 'gray', children }: BadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colorMap[color]}`}>
      {children}
    </span>
  )
}
